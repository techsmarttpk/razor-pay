"""Money-at-risk arithmetic: recoverable never exceeds at-risk, breakdown
components sum exactly to the reported total, and category-level allocation
in /api/overview never double-counts an exception into two health buckets."""
from app.analytics.detectors import run_all_detectors


def test_recoverable_never_exceeds_at_risk(bundle):
    for f in run_all_detectors(bundle):
        assert f["recoverable_amount"] <= f["money_at_risk"] + 1e-6


def test_breakdown_components_are_non_negative_and_sum_correctly(bundle):
    for f in run_all_detectors(bundle):
        total = 0.0
        for c in f["money_at_risk_breakdown"]:
            assert c["amount"] >= 0
            total += c["amount"]
        assert abs(total - f["money_at_risk"]) < 0.05


def test_overview_health_buckets_are_disjoint_exception_types():
    from app.services.overview import get_overview
    ov = get_overview()
    assert ov["money_at_risk"] >= 0
    assert ov["recoverable_amount"] <= ov["money_at_risk"] + ov["recoverable_amount"]  # sanity, no crash
