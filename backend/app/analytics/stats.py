"""Explainable statistical primitives used by the deterministic/rule
detection engines (app/analytics/detectors.py).

Deliberately simple and auditable — robust z-scores and EWMA baselines,
each retrievable for the evidence panel. The one genuinely trained ML
model in this codebase (sklearn.ensemble.IsolationForest, fit on engineered
merchant-day features) lives in app/ml/anomaly_model.py, not here — see
that module's docstring for why it is scoped to exactly one detector.
"""
import numpy as np
import pandas as pd


def robust_z(series: pd.Series) -> pd.Series:
    """Median/MAD-based z-score — robust to the outliers it's trying to find."""
    median = series.median()
    mad = (series - median).abs().median()
    if mad == 0 or pd.isna(mad):
        std = series.std(ddof=0)
        if not std or pd.isna(std):
            return pd.Series(np.zeros(len(series)), index=series.index)
        return (series - series.mean()) / std
    return 0.6745 * (series - median) / mad


def ewma(series: pd.Series, span: int = 7) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def zscore(series: pd.Series) -> pd.Series:
    std = series.std(ddof=0)
    if not std or pd.isna(std):
        return pd.Series(np.zeros(len(series)), index=series.index)
    return (series - series.mean()) / std
