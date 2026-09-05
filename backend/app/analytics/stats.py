"""Explainable statistical primitives used by the detection engines.

Deliberately simple and auditable — robust z-scores, EWMA baselines and a
thin isolation-forest wrapper. No black-box scoring is used without the
underlying numbers being retrievable for the evidence panel.
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


def isolation_forest_scores(df: pd.DataFrame, feature_cols, contamination: float = 0.06,
                             random_state: int = 42) -> pd.Series:
    from sklearn.ensemble import IsolationForest

    X = df[feature_cols].fillna(0.0).to_numpy()
    if len(X) < 10:
        return pd.Series(np.zeros(len(df)), index=df.index)
    model = IsolationForest(contamination=contamination, random_state=random_state, n_estimators=200)
    model.fit(X)
    # decision_function: higher = more normal. Flip sign so higher = more anomalous.
    raw = -model.decision_function(X)
    return pd.Series(raw, index=df.index)
