# EMA 9/18 + take profit parziale su z-score — BTC 1h (Hyperliquid)

## Regole (valutate alla chiusura di ogni barra 1h)
- Incrocio rialzista EMA9/EMA18 -> LONG a mercato; incrocio ribassista -> SHORT (stop-and-reverse).
- Z-score = (close - SMA20) / stdev20 (deviazione standard di popolazione, come `ta.stdev` di Pine).
- Take profit parziale (default 50%) quando z >= +2 (long) / z <= -2 (short), una sola volta per trade,
  valutato dalla barra successiva all'ingresso.
- Il resto resta aperto fino all'incrocio opposto, dove la posizione viene invertita.

## Backtest
    python backtest.py                         # ultime ~5000 barre 1h da Hyperliquid (~208 giorni)
    python backtest.py --csv BTC_1h.csv        # storico lungo (export TradingView, BTC 1h)
    python backtest.py --compare               # TP 0/25/50/75/100% a parita' di segnali
    python backtest.py --compound --capital 2000 --tp-z 2 --tp-fraction 0.5
Include fee (0.045%/lato) e slippage (0.02%/lato). Esecuzione al close della barra del segnale.

## Live
1. Crea un SUB-ACCOUNT dedicato (una sola posizione BTC per account: non mescolare con la strategia 1349).
2. `python3 -m venv venv && venv/bin/pip install -r requirements.txt`, copia `.env.example` in `.env` e compilalo
   (HL_VAULT_ADDRESS = indirizzo del sub-account, STRAT_CAPITAL_USD = capitale assegnato).
3. Prova con DRY_RUN=true: `venv/bin/python main.py`. Poi DRY_RUN=false.
4. Cron (minuto 2 di ogni ora):  `2 * * * * cd /root/ema_cross_btc && /root/ema_cross_btc/venv/bin/python main.py >> run.log 2>&1`
- Stateless: lo stato (pieno / ridotto dopo TP) si deduce dalla posizione reale.
- WAIT_FOR_FLIP=true: se sei flat non entri nel trade in corso, aspetti il prossimo incrocio.
- Email solo se vengono eseguiti ordini o ci sono errori (notify.py, stesse variabili SMTP degli altri sistemi).
