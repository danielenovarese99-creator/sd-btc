"""Indicatori fedeli a Pine v6: ta.ema (seed = SMA), ta.sma, ta.stdev (deviazione standard di POPOLAZIONE)."""
import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def stdev_pop(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).std(ddof=0)


def ema(s: pd.Series, n: int) -> pd.Series:
    x = s.to_numpy(float)
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return pd.Series(out, index=s.index)
    out[n - 1] = x[:n].mean()
    a = 2.0 / (n + 1)
    for i in range(n, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return pd.Series(out, index=s.index)
