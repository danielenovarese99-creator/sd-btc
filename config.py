"""
Configurazione del sistema "EMA cross + take profit sulla z-score" su BTC, timeframe 1h.

Logica (valutata alla chiusura di ogni barra 1h):
  - incrocio rialzista EMA 9 / EMA 18  -> LONG (chiude l'eventuale short e apre il long)
  - incrocio ribassista                -> SHORT (chiude l'eventuale long e apre lo short)
  - take profit PARZIALE: z-score(close, 20) >= +2 (long) oppure <= -2 (short); una sola volta per trade
  - il resto della posizione resta aperto fino al prossimo incrocio (stop-and-reverse)
I valori letti da .env si cambiano senza toccare il codice.
"""
import os

from dotenv import load_dotenv

load_dotenv()


def _f(name, default):
    return float(os.environ.get(name, default))


def _i(name, default):
    return int(os.environ.get(name, default))


# ---------------------------------------------------------------------------
# Parametri strategia
# ---------------------------------------------------------------------------
EMA_FAST = _i("EMA_FAST", 9)
EMA_SLOW = _i("EMA_SLOW", 18)
Z_LEN = _i("Z_LEN", 20)            # lunghezza di SMA e deviazione standard dello z-score (Pine: length = 20)
TP_Z = _f("TP_Z", 2.0)             # soglia dello z-score per il take profit parziale
TP_FRACTION = _f("TP_FRACTION", 0.5)   # quota della posizione chiusa al take profit (0 = TP disattivato, 1 = chiude tutto)

# Filtro di regime: long solo se close > EMA(REGIME_EMA), short solo se close < EMA(REGIME_EMA). 0 = disattivato
REGIME_EMA = _i("REGIME_EMA", 0)
# true = chiudi anche la posizione aperta quando il prezzo rompe la EMA di regime (oltre all'incrocio opposto)
REGIME_EXIT = os.environ.get("REGIME_EXIT", "false").lower() == "true"

COIN = "BTC"
CANDLE_INTERVAL = "1h"
WARMUP_BARS = 100                  # barre iniziali ignorate: le EMA devono convergere

# ---------------------------------------------------------------------------
# Live (letti da .env)
# ---------------------------------------------------------------------------
ACCOUNT_ADDRESS = os.environ.get("HL_ACCOUNT_ADDRESS", "")
AGENT_PRIVATE_KEY = os.environ.get("HL_AGENT_PRIVATE_KEY", "")
USE_TESTNET = os.environ.get("HL_ENV", "mainnet").lower() == "testnet"

# Sub-account su cui opera il sistema (OBBLIGATORIO in pratica se usi anche altre strategie su BTC: vedi README)
VAULT_ADDRESS = os.environ.get("HL_VAULT_ADDRESS", "").strip() or None

DRY_RUN = os.environ.get("DRY_RUN", "true").lower() == "true"

# notional target = STRAT_CAPITAL_USD * LEVERAGE_FACTOR (quantita' fissa all'ingresso, non ribilanciata)
STRAT_CAPITAL_USD = _f("STRAT_CAPITAL_USD", 0) if os.environ.get("STRAT_CAPITAL_USD") else 0.0
LEVERAGE_FACTOR = _f("LEVERAGE_FACTOR", 1.0)

# true = quando sei flat su Hyperliquid NON entri nel trade in corso: aspetti il prossimo incrocio
WAIT_FOR_FLIP = os.environ.get("WAIT_FOR_FLIP", "true").lower() == "true"

MIN_NOTIONAL_USD = 10.0
IOC_SLIPPAGE_BUFFER = 0.003        # 0.3% di buffer sul limit price degli ordini IOC
