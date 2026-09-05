"""Detector thresholds.

These were picked by inspecting distributions on the `calibration` split of
the ground-truth labels only (see app/services/evaluation.py) — the
`holdout` split is never used to pick a number here. Kept as plain
constants (not learned weights) so every threshold is auditable and
explainable in the evidence panel.
"""

FEE_ANOMALY_MIN_ABS = 8.0           # ignore sub-8 rupee fee noise
FEE_ANOMALY_MIN_RATIO = 0.003       # excess fee must exceed 0.3% of order amount
FEE_ANOMALY_MIN_Z = 2.2             # robust z-score vs merchant fee-rate baseline

DELAYED_SETTLEMENT_BASELINE_DAYS = 2
DELAYED_SETTLEMENT_FLAG_DAYS = 4    # >= T+4 flagged

DUPLICATE_WINDOW_MINUTES = 10

MISSING_SETTLEMENT_GRACE_DAYS = 8   # payment old enough it should have settled

PARTIAL_SETTLEMENT_MIN_SHORTFALL = 25.0
PARTIAL_SETTLEMENT_MIN_RATIO = 0.03

SETTLEMENT_VARIANCE_MIN_ABS = 40.0
SETTLEMENT_VARIANCE_MIN_RATIO = 0.003

REFUND_SPIKE_MIN_Z = 1.2
REFUND_SPIKE_MIN_RATIO = 2.5        # recent rate must be >= 2.5x baseline
REFUND_SPIKE_MIN_RECENT_VOLUME = 5  # need enough recent payments for the rate to be meaningful

DEGRADATION_MIN_SLOPE_DAYS = 0.35   # settlement delay growing >= 0.35 days/day
DEGRADATION_MIN_WINDOW = 6

MERCHANT_ANOMALY_MIN_SCORE = 0.15   # statistical heuristic score threshold (app/analytics/detectors.py
                                     # detect_merchant_level_anomalies_statistical). The ML detector
                                     # (app/ml/anomaly_model.py) has its own threshold, selected from
                                     # calibration data and stored in data/models/isolation_forest_meta.json —
                                     # not a hand-picked constant.
MERCHANT_ANOMALY_RISK_SHARE = 0.05  # assumed share of a flagged window's volume actually at risk (both the
                                     # statistical heuristic and the ML detector use this same assumption,
                                     # so neither looks artificially better/worse on money_at_risk accuracy)

CHARGEBACK_MIN_AGE_DAYS = 0

# Bounded action thresholds
SAFE_AUTO_MAX_AMOUNT = 5000.0
SAFE_AUTO_MIN_CONFIDENCE = 0.9
ESCALATE_MIN_AMOUNT = 100000.0
ESCALATE_MAX_CONFIDENCE = 0.6       # low confidence + high amount => escalate
