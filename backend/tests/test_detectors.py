"""Detector behaviour on the real seeded dataset (seed=42, deterministic).
Verifies each detector produces well-formed findings and that at least some
of the deliberately injected scenarios are actually caught."""
from app.analytics.detectors import run_all_detectors, ALL_DETECTORS


def test_all_detectors_produce_well_formed_findings(bundle):
    findings = run_all_detectors(bundle)
    assert len(findings) > 50, "expected a substantial number of findings on the seeded dataset"
    for f in findings:
        assert f["money_at_risk"] >= 0
        assert f["recoverable_amount"] >= 0
        assert f["recoverable_amount"] <= f["money_at_risk"] + 1e-6
        assert 0.0 <= f["confidence"] <= 1.0
        assert f["severity"] in ("low", "medium", "high", "critical")
        assert isinstance(f["evidence"], list) and len(f["evidence"]) > 0
        assert isinstance(f["money_at_risk_breakdown"], list) and len(f["money_at_risk_breakdown"]) > 0
        breakdown_sum = sum(c["amount"] for c in f["money_at_risk_breakdown"])
        assert abs(breakdown_sum - f["money_at_risk"]) < 0.05, "breakdown must sum to money_at_risk exactly"


def test_detects_fee_anomalies(bundle):
    from app.analytics.detectors import detect_fee_anomalies
    findings = detect_fee_anomalies(bundle)
    types = {f["exception_type"] for f in findings}
    assert "fee_anomaly" in types
    assert any(f["exception_type"] == "fee_anomaly" and f["money_at_risk"] > 0 for f in findings)


def test_detects_duplicate_transactions_same_order_only(bundle):
    from app.analytics.detectors import detect_duplicate_transactions
    findings = detect_duplicate_transactions(bundle)
    assert len(findings) > 0
    for f in findings:
        assert f["evidence"][0]["fields"]["gap_minutes"] <= 10


def test_detects_delayed_settlements(bundle):
    from app.analytics.detectors import detect_delayed_settlements
    findings = detect_delayed_settlements(bundle)
    assert len(findings) > 0
    for f in findings:
        assert f["evidence"][0]["fields"]["delay_days"] >= 4


def test_detects_missing_settlement_items(bundle):
    from app.analytics.detectors import detect_missing_settlement_items
    findings = detect_missing_settlement_items(bundle)
    assert len(findings) > 0


def test_detects_chargeback_reserve(bundle):
    from app.analytics.detectors import detect_chargeback_reserve
    findings = detect_chargeback_reserve(bundle)
    assert len(findings) > 0
    for f in findings:
        assert f["money_at_risk"] > 0


def test_no_detector_raises(bundle):
    for fn in ALL_DETECTORS:
        result = fn(bundle)
        assert isinstance(result, list)
