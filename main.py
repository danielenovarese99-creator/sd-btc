"""
Run orario (cron al minuto 2 di ogni ora): scarica le candele 1h CHIUSE di BTC, calcola il segnale
(incrocio EMA 9/18 + take profit parziale su z-score) e allinea la posizione su Hyperliquid.
"""
import sys
from datetime import datetime, timedelta, timezone

import config as cfg
import data as data_mod
import strategy as strat


def main() -> int:
    now = datetime.now(timezone.utc)
    print(f"\n===== EMA{cfg.EMA_FAST}/{cfg.EMA_SLOW} z-TP {now:%Y-%m-%d %H:%M:%S} UTC | DRY_RUN={cfg.DRY_RUN} | "
          f"{'TESTNET' if cfg.USE_TESTNET else 'MAINNET'} =====")
    df = data_mod.fetch_hyperliquid()
    last = df["time"].iloc[-1]
    expected = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    print(f"Ultima barra chiusa: {last:%Y-%m-%d %H:%M} close={df['close'].iloc[-1]:.2f} ({len(df)} barre)")
    if last < expected:
        print(f"[ERRORE] dati non aggiornati: ultima {last:%H:%M}, attesa {expected:%H:%M}. Esco senza operare.")
        return 1

    sig = strat.compute_signals(df)
    st = strat.run_state_machine(sig)
    r, s = sig.iloc[-1], st.iloc[-1]
    print(f"EMA{cfg.EMA_FAST}={r['ema_fast']:.2f} EMA{cfg.EMA_SLOW}={r['ema_slow']:.2f} z={r['z']:.2f} | "
          f"dir={int(s['pos']):+d} cross_ora={bool(s['flip'])} tp_evento_ora={bool(s['tp_event'])} "
          f"tp_done={bool(s['tp_done'])}")

    if not cfg.DRY_RUN and (not cfg.ACCOUNT_ADDRESS or not cfg.AGENT_PRIVATE_KEY):
        print("[ERRORE] credenziali mancanti in .env")
        return 1

    from executor import get_exchange, get_info, sync_position
    info = get_info()
    exchange = get_exchange() if not cfg.DRY_RUN else None
    ok = sync_position(info, exchange, cfg.COIN, int(s["pos"]), bool(s["flip"]), bool(s["tp_done"]))
    print("Run completata.\n" if ok else "Run terminata CON ERRORI.\n")
    return 0 if ok else 1


if __name__ == "__main__":
    import traceback
    import notify
    _buf = notify.start_capture()
    try:
        _code = main()
    except Exception:
        print("[FATAL] Errore non gestito durante la run:", file=sys.stderr)
        traceback.print_exc()
        _code = 1
    notify.finish("EMA9/18 z-TP", _buf, _code)
    sys.exit(_code)
