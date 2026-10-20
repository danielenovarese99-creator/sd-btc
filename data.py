"""Candele 1h BTC (solo barre CHIUSE), da CSV (es. export TradingView) o da Hyperliquid."""
from datetime import datetime, timezone

import pandas as pd

import config as cfg


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("time").drop_duplicates("time").reset_index(drop=True)
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float)
    if "volume" not in df:
        df["volume"] = 0.0
    return df[["time", "open", "high", "low", "close", "volume"]]


def load_csv(path: str) -> pd.DataFrame:
    """CSV con colonne time,open,high,low,close[,volume]; 'time' unix (s o ms) oppure data ISO.
    L'export "Esporta dati del grafico" di TradingView (BTC, 1h) va bene cosi' com'e'.
    Se l'ultima barra e' ancora in formazione, va esclusa a mano."""
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    t = df["time"]
    if pd.api.types.is_numeric_dtype(t):
        df["time"] = pd.to_datetime(t, unit="ms" if t.iloc[0] > 1e11 else "s", utc=True)
    else:
        df["time"] = pd.to_datetime(t, utc=True)
    return _clean(df)


def fetch_hyperliquid(coin: str = None, max_bars: int = 5000) -> pd.DataFrame:
    """Candele 1h da Hyperliquid (l'API restituisce al massimo le ultime 5000, circa 208 giorni),
    scartando la barra in corso."""
    from hyperliquid.info import Info
    from hyperliquid.utils import constants

    coin = coin or cfg.COIN
    base_url = constants.TESTNET_API_URL if cfg.USE_TESTNET else constants.MAINNET_API_URL
    info = Info(base_url, skip_ws=True)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = now_ms - (max_bars + 50) * 3600 * 1000
    raw = info.candles_snapshot(coin, cfg.CANDLE_INTERVAL, start_ms, now_ms)
    if not raw:
        raise RuntimeError(f"Nessuna candela ricevuta per {coin}")
    df = pd.DataFrame(raw).rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    df = df[df["T"].astype("int64") < now_ms].copy()          # T = istante di chiusura della candela
    df["time"] = pd.to_datetime(df["t"].astype("int64"), unit="ms", utc=True)   # t = apertura
    return _clean(df)
