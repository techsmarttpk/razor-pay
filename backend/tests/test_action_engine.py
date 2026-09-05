import pytest

from app.agents.action_engine import categorize, recommend_action, build_action_payload, ALLOWED_ACTIONS


def _finding(amount, exception_type="fee_anomaly"):
    return {"exception_type": exception_type, "money_at_risk": amount, "recoverable_amount": amount,
            "entity_id": "pay_x", "entity_type": "payment", "merchant_id": "mer_x"}


def _diag(confidence, classification="fee_anomaly"):
    return {"confidence": confidence, "final_classification": classification,
            "calculations": {"excess_fee_charged": 100}}


def test_high_confidence_low_amount_is_safe_auto():
    finding = _finding(500)
    diag = _diag(0.95)
    assert categorize(finding, diag) == "SAFE_AUTO_ACTION"


def test_large_amount_always_escalates_regardless_of_confidence():
    finding = _finding(200000)
    diag = _diag(0.99)
    assert categorize(finding, diag) == "ESCALATE"


def test_low_confidence_escalates():
    finding = _finding(1000)
    diag = _diag(0.4)
    assert categorize(finding, diag) == "ESCALATE"


def test_unresolved_classification_always_escalates_even_if_cheap_and_confident():
    finding = _finding(10)
    diag = _diag(0.99, classification="unresolved_exception")
    assert categorize(finding, diag) == "ESCALATE"


def test_mid_range_is_review_required():
    finding = _finding(20000)
    diag = _diag(0.75)
    assert categorize(finding, diag) == "REVIEW_REQUIRED"


def test_recommended_action_is_always_in_allowlist():
    for etype in ("fee_anomaly", "delayed_settlement", "duplicate_transaction",
                  "missing_settlement_item", "chargeback_reserve", "unresolved_exception",
                  "totally_unknown_type"):
        finding = _finding(100, exception_type=etype)
        diag = _diag(0.8, classification=etype)
        action = recommend_action(finding, diag)
        assert action in ALLOWED_ACTIONS


def test_action_payload_never_invents_amounts():
    finding = _finding(1234.56, exception_type="fee_anomaly")
    diag = _diag(0.9)
    payload = build_action_payload("create_recovery_case", finding, diag)
    assert "1234" in payload["case_summary"] or "1,234" in payload["case_summary"]
    assert payload["money_at_risk"] == finding["money_at_risk"]
