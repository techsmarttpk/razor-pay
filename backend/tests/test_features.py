"""Feature engineering (app/analytics/features.py) — shape, bounds, and the
merchant-relative baseline math, on the real seeded dataset."""
import numpy as np

from app.analytics.features import build_merchant_day_features, FEATURE_COLUMNS, FEATURE_RATIONALE


def test_every_feature_column_is_documented():
    for col in FEATURE_COLUMNS:
        assert col in FEATURE_RATIONALE and FEATURE_RATIONALE[col], f"{col} has no documented rationale"


def test_feature_matrix_well_formed(bundle):
    df = build_merchant_day_features(bundle)
    assert len(df) > 1000, "expected one row per merchant-day across the seeded window"
    assert {"merchant_id", "day"} <= set(df.columns)
    for col in FEATURE_COLUMNS:
        assert col in df.columns
        assert df[col].notna().all(), f"{col} must never be NaN in the final feature matrix"
        assert np.isfinite(df[col]).all(), f"{col} must never be inf"


def test_rates_and_ratios_are_bounded(bundle):
    df = build_merchant_day_features(bundle)
    # refund_rate/dispute_rate are refund(or dispute)-count / same-day payment-count —
    # legitimately > 1 when refunds for earlier payments land on a low-volume day, so
    # only non-negativity is guaranteed, not an upper bound of 1.
    assert (df["refund_rate"] >= 0).all()
    assert (df["dispute_rate"] >= 0).all()
    assert (df["n_pay"] >= 1).all(), "grouped rows only exist for days with at least one payment"


def test_no_label_or_scenario_columns_present(bundle):
    df = build_merchant_day_features(bundle)
    forbidden = {"scenario_type", "is_true_anomaly", "expected_amount", "split", "ground_truth_label_id"}
    assert forbidden.isdisjoint(df.columns)


def test_merchant_baseline_features_only_use_past_days(bundle):
    """Truncating the dataset to end at day d must not change day d's own
    baseline features (avg_ticket_z30 / refund_rate_z30 / volume_ratio_7d) —
    if it did, those features would be using information from days after d,
    i.e. leaking the future into "today"."""
    import copy

    full = build_merchant_day_features(bundle)
    merchant_id = full["merchant_id"].iloc[0]
    merchant_days = full[full["merchant_id"] == merchant_id].sort_values("day")
    assert len(merchant_days) > 20
    cutoff_day = merchant_days["day"].iloc[15]

    truncated_bundle = copy.copy(bundle)
    truncated_bundle.payments = bundle.payments[
        bundle.payments["created_at"] <= cutoff_day + __import__("pandas").Timedelta(days=1)
    ]
    truncated_bundle.refunds = bundle.refunds[
        bundle.refunds["created_at"] <= cutoff_day + __import__("pandas").Timedelta(days=1)
    ]
    truncated_bundle.disputes = bundle.disputes[
        bundle.disputes["created_at"] <= cutoff_day + __import__("pandas").Timedelta(days=1)
    ]
    truncated_bundle.settlements = bundle.settlements[
        bundle.settlements["created_at"] <= cutoff_day + __import__("pandas").Timedelta(days=1)
    ]

    truncated = build_merchant_day_features(truncated_bundle)
    row_full = full[(full["merchant_id"] == merchant_id) & (full["day"] == cutoff_day)].iloc[0]
    row_trunc = truncated[(truncated["merchant_id"] == merchant_id) & (truncated["day"] == cutoff_day)].iloc[0]

    for col in ("avg_ticket_z30", "refund_rate_z30", "volume_ratio_7d", "avg_ticket", "refund_rate", "n_pay"):
        assert abs(row_full[col] - row_trunc[col]) < 1e-6, (
            f"{col} for day {cutoff_day} changed when future days were removed — "
            "this feature is leaking future information"
        )
