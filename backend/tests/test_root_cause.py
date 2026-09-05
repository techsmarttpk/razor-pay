from app.analytics.detectors import detect_settlement_variance, run_all_detectors
from app.agents.root_cause import diagnose


def test_settlement_variance_diagnosis_shape(bundle):
    findings = detect_settlement_variance(bundle)
    assert len(findings) > 0
    for f in findings[:10]:
        diag = diagnose(f, bundle)
        assert "hypotheses" in diag
        assert "contradicted_hypotheses" in diag
        assert "calculations" in diag
        assert 0.0 <= diag["confidence"] <= 1.0
        assert diag["final_classification"] in (
            "refund_timing", "fee_anomaly", "chargeback_reserve", "delayed_settlement",
            "unknown", "unresolved_exception",
        )
        # explained + residual must reconcile to the total variance
        calc = diag["calculations"]
        explained = (calc["refund_timing"] + calc["fee_anomaly"]
                     + calc["chargeback_reserve"] + calc["delayed_settlement"])
        assert abs(explained + calc["residual_unexplained"] - calc["total_variance"]) < 0.05


def test_unambiguous_exception_types_confirm_detector_classification(bundle):
    findings = run_all_detectors(bundle)
    fee_findings = [f for f in findings if f["exception_type"] == "fee_anomaly"]
    assert fee_findings
    diag = diagnose(fee_findings[0], bundle)
    assert diag["final_classification"] == "fee_anomaly"
    assert diag["confidence"] == fee_findings[0]["confidence"]
