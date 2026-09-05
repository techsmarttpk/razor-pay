"""Merchant-day feature engineering for the ML anomaly detector.

Every feature here is a plain financial signal already meaningful to a
settlement-ops analyst — nothing is included "because a model needs a
number." Each is documented with why a shift in it matters (see
FEATURE_RATIONALE below). These are the same underlying signals the
rule-based detectors already look at one at a time (ticket size, refund
rate, fee excess, settlement delay); the point of the ML detector is to
judge them *jointly* per merchant-day, which a set of independent
threshold rules cannot do.

LEAKAGE RULES (enforced/verified in tests/test_leakage.py):
  - This module never reads `bundle.labels` (AnomalyLabel / scenario_type /
    ground truth) — it only ever sees the raw financial tables.
  - Every merchant-baseline feature is computed with `.shift(1)` BEFORE the
    rolling window, so a day's own value can never leak into its own
    baseline (the baseline for day d is a function of days < d only).
  - Nothing here aggregates or looks ahead past the row's own day.
"""
import numpy as np
import pandas as pd

FEATURE_COLUMNS = [
    "n_pay", "avg_ticket", "total_amount", "refund_rate", "refund_amount_ratio",
    "fee_excess_ratio", "dispute_rate", "avg_delay_days",
    "avg_ticket_z30", "refund_rate_z30", "volume_ratio_7d", "dow_sin", "dow_cos",
]

FEATURE_RATIONALE = {
    "n_pay": "Raw daily transaction volume — a sudden inflation/collapse can mark bot traffic, a testing burst, or an outage.",
    "avg_ticket": "Mean order size for the day — an unexplained jump can indicate ticket inflation, mispricing, or card-testing/fraud.",
    "total_amount": "Total rupee volume moved that day — the scale multiplier every other risk signal needs context from.",
    "refund_rate": "Refunds / payments for the day — a leading indicator of a product, fulfilment, or fraud problem.",
    "refund_amount_ratio": "Refunded rupees / captured rupees — catches large-value refund concentration that a pure count-rate misses.",
    "fee_excess_ratio": "(actual fee - expected MDR fee) / volume that day — an overcharge signal independent of ticket size.",
    "dispute_rate": "Disputes opened / payments that day — an early chargeback-risk signal.",
    "avg_delay_days": "Average settlement delay for settlements created that day — operational/liquidity risk.",
    "avg_ticket_z30": "Deviation of today's avg ticket from the merchant's own trailing 30-day baseline — normalizes for merchant size "
                       "so a ₹300 gaming merchant and a ₹6,500 travel merchant are judged against themselves, not each other.",
    "refund_rate_z30": "Same idea for refund rate — a merchant-relative spike rather than one absolute threshold for every merchant.",
    "volume_ratio_7d": "Today's volume vs. the merchant's trailing 7-day mean — a transaction-velocity change.",
    "dow_sin": "Day-of-week seasonality (sine component) — normal payment volume is not flat across the week.",
    "dow_cos": "Day-of-week seasonality (cosine component), paired with dow_sin for a continuous weekly cycle.",
}


def _safe_div(a: pd.Series, b: pd.Series) -> pd.Series:
    return a / b.replace(0, np.nan)


def build_merchant_day_features(bundle) -> pd.DataFrame:
    """Returns one row per (merchant_id, day) with raw aggregates + engineered
    FEATURE_COLUMNS. Never touches bundle.labels."""
    pay = bundle.payments.copy()
    if pay.empty:
        return pd.DataFrame(columns=["merchant_id", "day"] + FEATURE_COLUMNS)

    pay["day"] = pd.to_datetime(pay["created_at"]).dt.normalize()
    pay["fee_excess"] = pay["fee"] - pay["expected_fee"]

    daily = pay.groupby(["merchant_id", "day"]).agg(
        n_pay=("id", "count"),
        avg_ticket=("amount", "mean"),
        total_amount=("amount", "sum"),
        fee_excess_sum=("fee_excess", "sum"),
    ).reset_index()

    refunds = bundle.refunds.copy()
    if not refunds.empty:
        refunds["day"] = pd.to_datetime(refunds["created_at"]).dt.normalize()
        rdaily = refunds.groupby(["merchant_id", "day"]).agg(
            n_refund=("id", "count"), refund_amount=("amount", "sum"),
        ).reset_index()
        daily = daily.merge(rdaily, on=["merchant_id", "day"], how="left")
    else:
        daily["n_refund"] = 0.0
        daily["refund_amount"] = 0.0

    disp = bundle.disputes.copy()
    if not disp.empty:
        disp["day"] = pd.to_datetime(disp["created_at"]).dt.normalize()
        ddaily = disp.groupby(["merchant_id", "day"]).agg(n_dispute=("id", "count")).reset_index()
        daily = daily.merge(ddaily, on=["merchant_id", "day"], how="left")
    else:
        daily["n_dispute"] = 0.0

    stl = bundle.settlements.copy()
    if not stl.empty:
        stl = stl[stl["settled_at"].notna()].copy()
        stl["day"] = pd.to_datetime(stl["created_at"]).dt.normalize()
        stl["delay_days"] = (stl["settled_at"] - stl["created_at"]).dt.total_seconds() / 86400.0
        sdaily = stl.groupby(["merchant_id", "day"]).agg(avg_delay_days=("delay_days", "mean")).reset_index()
        daily = daily.merge(sdaily, on=["merchant_id", "day"], how="left")
    else:
        daily["avg_delay_days"] = np.nan

    for col in ("n_refund", "refund_amount", "n_dispute"):
        if col not in daily.columns:
            daily[col] = 0.0
    daily[["n_refund", "refund_amount", "n_dispute"]] = daily[["n_refund", "refund_amount", "n_dispute"]].fillna(0.0)

    daily["refund_rate"] = _safe_div(daily["n_refund"], daily["n_pay"]).fillna(0.0)
    daily["refund_amount_ratio"] = _safe_div(daily["refund_amount"], daily["total_amount"]).fillna(0.0)
    daily["fee_excess_ratio"] = _safe_div(daily["fee_excess_sum"], daily["total_amount"]).fillna(0.0)
    daily["dispute_rate"] = _safe_div(daily["n_dispute"], daily["n_pay"]).fillna(0.0)

    daily = daily.sort_values(["merchant_id", "day"]).reset_index(drop=True)

    # Merchant-relative baselines. `.shift(1)` moves the series forward by one
    # row before the rolling window even starts, so the window used for day
    # d's baseline covers strictly days < d — day d's own value cannot enter
    # its own baseline. Verified in tests/test_leakage.py.
    parts = []
    for _merchant_id, grp in daily.groupby("merchant_id", sort=False):
        grp = grp.copy()
        past_ticket = grp["avg_ticket"].shift(1)
        past_refund = grp["refund_rate"].shift(1)
        past_volume = grp["n_pay"].shift(1)

        roll_mean_ticket = past_ticket.rolling(30, min_periods=10).mean()
        roll_std_ticket = past_ticket.rolling(30, min_periods=10).std(ddof=0)
        grp["avg_ticket_z30"] = ((grp["avg_ticket"] - roll_mean_ticket) / roll_std_ticket.replace(0, np.nan)).fillna(0.0)

        roll_mean_refund = past_refund.rolling(30, min_periods=10).mean()
        roll_std_refund = past_refund.rolling(30, min_periods=10).std(ddof=0)
        grp["refund_rate_z30"] = ((grp["refund_rate"] - roll_mean_refund) / roll_std_refund.replace(0, np.nan)).fillna(0.0)

        roll_mean_volume = past_volume.rolling(7, min_periods=3).mean()
        grp["volume_ratio_7d"] = (grp["n_pay"] / roll_mean_volume.replace(0, np.nan)).fillna(1.0)

        parts.append(grp)
    daily = pd.concat(parts, ignore_index=True)

    fallback_delay = daily["avg_delay_days"].median()
    if pd.isna(fallback_delay):
        fallback_delay = 2.0
    daily["avg_delay_days"] = daily["avg_delay_days"].fillna(fallback_delay)

    dow = pd.to_datetime(daily["day"]).dt.weekday
    daily["dow_sin"] = np.sin(2 * np.pi * dow / 7)
    daily["dow_cos"] = np.cos(2 * np.pi * dow / 7)

    return daily
