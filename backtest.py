"""
Backtest EMA cross + take profit parziale su z-score (BTC 1h).

  python backtest.py                       # ultime ~5000 barre da Hyperliquid (~208 giorni)
  python backtest.py --csv BTC_1h.csv      # storico lungo (export TradingView) -> molto piu' affidabile
  python backtest.py --compare             # confronta TP 0% / 25% / 50% / 75% / 100% a parita' di segnali
Esecuzione: segnale alla chiusura della barra i, ordine eseguito a quel close (come TradingView con
process_orders_on_close); il rendimento della posizione parte dalla barra i+1. Costi: fee + slippage per lato.
"""
import argparse

import numpy as np
import pandas as pd

import config as cfg
import data as data_mod
import strategy as strat

BARS_PER_YEAR = 24 * 365


def simulate(sig, st, fee, slip, capital, compound):
    close = sig["close"].to_numpy()
    lvl = st["level"].to_numpy()
    n = len(sig)
    ret = np.zeros(n)
    ret[1:] = close[1:] / close[:-1] - 1
    prev = np.concatenate([[0.0], lvl[:-1]])           # livello detenuto durante la barra i
    dlvl = np.abs(np.diff(np.concatenate([[0.0], lvl])))   # turnover generato alla chiusura di i
    cost = dlvl * cfg.LEVERAGE_FACTOR * (fee + slip)
    r = prev * ret * cfg.LEVERAGE_FACTOR - cost
    eq = capital * np.cumprod(1 + r) if compound else capital + capital * np.cumsum(r)
    return pd.Series(eq, index=sig["time"]), r, dlvl


def trades_table(sig, st):
    rows, cur, prev = [], None, 0
    close, pos = sig["close"].to_numpy(), st["pos"].to_numpy()
    for i in range(len(sig)):
        if pos[i] != prev:
            if cur:
                cur["exit_i"], cur["exit_px"] = i, close[i]
                rows.append(cur)
                cur = None
            if pos[i] != 0:
                cur = {"dir": int(pos[i]), "entry_i": i, "entry_px": close[i], "tp_i": None, "tp_px": None}
        elif st["tp_event"].iat[i] and cur:
            cur["tp_i"], cur["tp_px"] = i, close[i]
        prev = pos[i]
    if cur:
        cur["exit_i"], cur["exit_px"] = None, None
        rows.append(cur)
    return rows


def stats(eq, r):
    tot = eq.iloc[-1] / eq.iloc[0] - 1
    yrs = len(eq) / BARS_PER_YEAR
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 and eq.iloc[-1] > 0 else np.nan
    dd = (eq / eq.cummax() - 1).min()
    sh = r.mean() / r.std() * np.sqrt(BARS_PER_YEAR) if r.std() > 0 else np.nan
    return tot, cagr, dd, sh


def regime_sweep(df, a):
    lens = [0, 50, 100, 200, 400, 800]
    start = df["time"].iloc[max(lens) + cfg.WARMUP_BARS]          # stesso periodo per tutte le righe
    print(f"Sweep filtro di regime | EMA {a.ema_fast}/{a.ema_slow} | periodo comune da {start:%Y-%m-%d} a "
          f"{df['time'].iloc[-1]:%Y-%m-%d} | fee {a.fee:.3%} + slip {a.slippage:.3%} per lato")
    print(f"\n{'regime':>7} {'exit':>5} {'TP':>5} {'Rend.tot':>9} {'MaxDD':>8} {'Sharpe':>7} {'Trade':>6} {'Turnover':>9} {'%tempo in pos':>14}")
    for L in lens:
        sig = strat.compute_signals(df, a.ema_fast, a.ema_slow, a.z_len, L)
        for rexit in ([False] if L == 0 else [False, True]):
            for frac in [0.0, a.tp_fraction]:
                st = strat.run_state_machine(sig, a.tp_z, frac, start, rexit)
                eq, r, dl = simulate(sig, st, a.fee, a.slippage, a.capital, a.compound)
                m = (sig["time"] >= start).to_numpy()
                eq, r = eq[m], pd.Series(r[m])
                tot, cagr, dd, sh = stats(eq, r)
                ntr = len([1 for t in trades_table(sig[m].reset_index(drop=True), st[m].reset_index(drop=True))])
                inpos = (st["pos"][m] != 0).mean()
                print(f"{('off' if L == 0 else L):>7} {('si' if rexit else 'no'):>5} {frac:>5.0%} {tot:>9.1%} {dd:>8.1%} "
                      f"{sh:>7.2f} {ntr:>6} {dl[m].sum():>9.1f} {inpos:>14.0%}")
    print("\nexit = esce anche quando il prezzo rompe la EMA di regime. Le righe con TP 0% sono il segnale 'puro'.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    ap.add_argument("--capital", type=float, default=1000.0)
    ap.add_argument("--compound", action="store_true")
    ap.add_argument("--fee", type=float, default=0.00045, help="fee per lato (default 0.045%% taker HL)")
    ap.add_argument("--slippage", type=float, default=0.0002, help="slippage per lato (default 0.02%%)")
    ap.add_argument("--ema-fast", type=int, default=cfg.EMA_FAST)
    ap.add_argument("--ema-slow", type=int, default=cfg.EMA_SLOW)
    ap.add_argument("--z-len", type=int, default=cfg.Z_LEN)
    ap.add_argument("--tp-z", type=float, default=cfg.TP_Z)
    ap.add_argument("--tp-fraction", type=float, default=cfg.TP_FRACTION)
    ap.add_argument("--from", dest="start")
    ap.add_argument("--regime-ema", type=int, default=cfg.REGIME_EMA, help="filtro di regime: EMA su close (0 = off)")
    ap.add_argument("--regime-exit", action="store_true", default=cfg.REGIME_EXIT,
                    help="esci anche quando il prezzo rompe la EMA di regime")
    ap.add_argument("--regime-sweep", action="store_true", help="confronta varie lunghezze della EMA di regime")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--out", default=".")
    a = ap.parse_args()
    if a.ema_fast >= a.ema_slow:
        raise SystemExit("--ema-fast deve essere < --ema-slow")

    df = data_mod.load_csv(a.csv) if a.csv else data_mod.fetch_hyperliquid()
    if a.regime_sweep:
        return regime_sweep(df, a)
    sig = strat.compute_signals(df, a.ema_fast, a.ema_slow, a.z_len, a.regime_ema)
    start_ts = pd.Timestamp(a.start, tz="UTC") if a.start else None
    print(f"Dati: {sig['time'].iloc[0]:%Y-%m-%d %H:%M} -> {sig['time'].iloc[-1]:%Y-%m-%d %H:%M} "
          f"({len(sig)} barre, {len(sig)/24:.0f} giorni) | EMA {a.ema_fast}/{a.ema_slow} | z-len {a.z_len} | regime EMA {a.regime_ema or 'off'}{' (+exit)' if a.regime_exit and a.regime_ema else ''} | "
          f"fee {a.fee:.4%} + slip {a.slippage:.4%} per lato | {'compound' if a.compound else 'capitale fisso'}")

    def run(frac):
        st = strat.run_state_machine(sig, a.tp_z, frac, start_ts, a.regime_exit)
        eq, r, dl = simulate(sig, st, a.fee, a.slippage, a.capital, a.compound)
        first = st["pos"].ne(0).idxmax() if st["pos"].ne(0).any() else 0
        return st, eq.iloc[first:], pd.Series(r[first:]), dl

    if a.compare:
        print(f"\n{'TP quota':>9} {'Rend.tot':>10} {'CAGR':>8} {'MaxDD':>8} {'Sharpe':>7} {'Turnover':>9}")
        for f in [0, 0.25, 0.5, 0.75, 1.0]:
            st, eq, r, dl = run(f)
            tot, cagr, dd, sh = stats(eq, r)
            print(f"{f:>9.0%} {tot:>10.1%} {cagr:>8.1%} {dd:>8.1%} {sh:>7.2f} {dl.sum():>9.1f}")
        print("\n(TP 0% = puro stop-and-reverse sull'incrocio, senza take profit.)")
        return

    st, eq, r, dl = run(a.tp_fraction)
    tot, cagr, dd, sh = stats(eq, r)
    tr = trades_table(sig, st)
    done = [t for t in tr if t["exit_px"] is not None]
    pnl = [t["dir"] * (t["exit_px"] / t["entry_px"] - 1) for t in done]
    tp_n = sum(1 for t in tr if t["tp_i"] is not None)
    print(f"\nRendimento totale: {tot:.1%} | CAGR: {cagr:.1%} | Max DD: {dd:.1%} | Sharpe(h): {sh:.2f}")
    print(f"Equity finale: ${eq.iloc[-1]:,.2f} (da ${a.capital:,.0f})")
    print(f"Trade chiusi: {len(done)} (long {sum(t['dir']>0 for t in done)}, short {sum(t['dir']<0 for t in done)}) | "
          f"con TP preso: {tp_n}/{len(tr)} ({tp_n/max(len(tr),1):.0%})")
    if done:
        w = [p for p in pnl if p > 0]
        print(f"Win rate (trade interi, prezzo ingresso->uscita, senza costi): {len(w)/len(pnl):.0%} | "
              f"media {np.mean(pnl):.2%} | miglior {max(pnl):.2%} | peggior {min(pnl):.2%}")
    print(f"Turnover totale: {dl.sum():.1f}x il notional | costi stimati: ~{dl.sum()*cfg.LEVERAGE_FACTOR*(a.fee+a.slippage):.1%} del capitale")
    bh = df["close"].iloc[-1] / df["close"].iloc[0] - 1
    print(f"Buy&hold BTC sullo stesso periodo: {bh:.1%}")

    out = pd.DataFrame({"time": eq.index, "equity": eq.values})
    out.to_csv(f"{a.out}/equity_curve.csv", index=False)
    pd.DataFrame(tr).to_csv(f"{a.out}/trades.csv", index=False)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
        ax[0].plot(eq.index, eq.values)
        ax[0].set_title("Equity")
        ax[1].plot(eq.index, (eq / eq.cummax() - 1).values * 100, color="red")
        ax[1].set_title("Drawdown %")
        fig.tight_layout()
        fig.savefig(f"{a.out}/equity_curve.png", dpi=110)
    except Exception:
        pass
    print(f"Salvati: {a.out}/equity_curve.csv, trades.csv, equity_curve.png")


if __name__ == "__main__":
    main()
