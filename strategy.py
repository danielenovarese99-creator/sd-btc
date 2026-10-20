"""Segnali e macchina a stati: incrocio EMA 9/18 con take profit parziale sulla z-score."""
import numpy as np
import pandas as pd

import config as cfg
from indicators import ema, sma, stdev_pop


def compute_signals(df: pd.DataFrame, fast: int = None, slow: int = None, z_len: int = None,
                    regime_ema: int = None) -> pd.DataFrame:
    fast, slow, z_len = fast or cfg.EMA_FAST, slow or cfg.EMA_SLOW, z_len or cfg.Z_LEN
    sig = df.copy().reset_index(drop=True)
    c = sig["close"]
    sig["ema_fast"] = ema(c, fast)
    sig["ema_slow"] = ema(c, slow)
    sd = stdev_pop(c, z_len).replace(0, np.nan)
    sig["z"] = (c - sma(c, z_len)) / sd             # Pine: (source - sma) / stdev
    regime_ema = cfg.REGIME_EMA if regime_ema is None else regime_ema
    sig["ema_reg"] = ema(c, regime_ema) if regime_ema > 0 else np.nan
    pf, ps = sig["ema_fast"].shift(1), sig["ema_slow"].shift(1)
    sig["cross_up"] = (pf <= ps) & (sig["ema_fast"] > sig["ema_slow"])     # ta.crossover
    sig["cross_dn"] = (pf >= ps) & (sig["ema_fast"] < sig["ema_slow"])     # ta.crossunder
    return sig


def run_state_machine(sig: pd.DataFrame, tp_z: float = None, tp_fraction: float = None,
                      start_ts=None, regime_exit: bool = None) -> pd.DataFrame:
    """
    Per ogni barra (valutata alla chiusura):
      pos      +1 long / -1 short / 0 nessun trade ancora
      flip     True se su questa barra c'e' stato un incrocio (nuovo trade)
      tp_event True se su questa barra scatta il take profit parziale
      tp_done  True se il TP del trade corrente e' gia' stato preso
      level    posizione target in frazione della size piena (con segno): +-1, +-(1 - TP_FRACTION), 0
    Il TP si valuta solo dalla barra successiva a quella di ingresso e una volta per trade.
    """
    tp_z = cfg.TP_Z if tp_z is None else tp_z
    tp_fraction = cfg.TP_FRACTION if tp_fraction is None else tp_fraction
    regime_exit = cfg.REGIME_EXIT if regime_exit is None else regime_exit
    use_reg = sig["ema_reg"].notna().any()
    n = len(sig)
    close, reg = sig["close"].to_numpy(), sig["ema_reg"].to_numpy()
    up, dn, z = sig["cross_up"].to_numpy(), sig["cross_dn"].to_numpy(), sig["z"].to_numpy()
    ok = sig["ema_slow"].notna().to_numpy() & (np.arange(n) >= cfg.WARMUP_BARS)
    if use_reg:
        ok &= sig["ema_reg"].notna().to_numpy()
    if start_ts is not None:
        ok &= (sig["time"] >= start_ts).to_numpy()
    pos_a, flip_a, tp_a, done_a, lvl_a = (np.zeros(n, int), np.zeros(n, bool), np.zeros(n, bool),
                                          np.zeros(n, bool), np.zeros(n))
    pos, done, entry_i = 0, False, -1
    after_tp = 1.0 - tp_fraction
    for i in range(n):
        if ok[i]:
            long_ok = (not use_reg) or close[i] > reg[i]
            short_ok = (not use_reg) or close[i] < reg[i]
            if up[i] and pos <= 0:
                if long_ok:
                    pos, done, entry_i = 1, False, i
                    flip_a[i] = True
                else:
                    pos = 0                      # incrocio contro il regime: chiudi lo short e resta flat
            elif dn[i] and pos >= 0:
                if short_ok:
                    pos, done, entry_i = -1, False, i
                    flip_a[i] = True
                else:
                    pos = 0
            elif use_reg and regime_exit and ((pos > 0 and not long_ok) or (pos < 0 and not short_ok)):
                pos = 0                          # il prezzo ha rotto il regime: esci
            elif (pos != 0 and not done and tp_fraction > 0 and i > entry_i and not np.isnan(z[i])
                  and ((pos > 0 and z[i] >= tp_z) or (pos < 0 and z[i] <= -tp_z))):
                done = True
                tp_a[i] = True
        pos_a[i], done_a[i] = pos, done
        lvl_a[i] = pos * (after_tp if done else 1.0)
    return pd.DataFrame({"pos": pos_a, "flip": flip_a, "tp_event": tp_a, "tp_done": done_a, "level": lvl_a})
