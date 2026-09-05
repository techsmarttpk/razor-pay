"""Bounded action engine.

Hard allowlist of action types. No action moves real money. Every action is
either instantly reversible (status flips) or purely communicative (drafts,
alerts, journal *suggestions*). Category assignment (SAFE_AUTO_ACTION /
REVIEW_REQUIRED / ESCALATE) is a deterministic function of confidence,
amount and whether the root-cause engine actually resolved the case —
never an LLM judgment call.
"""
from app.rules import thresholds as T

ALLOWED_ACTIONS = {
    "mark_resolved",
    "create_recovery_case",
    "create_reconciliation_task",
    "generate_merchant_alert",
    "generate_recovery_communication_draft",
    "generate_journal_suggestion",
    "group_related_exceptions",
    "close_duplicate_exception",
}

UNRESOLVED_CLASSIFICATIONS = {"unknown", "unresolved_exception"}

ACTION_BY_TYPE = {
    "fee_anomaly": "create_recovery_case",
    "repeated_cohort_anomaly": "generate_merchant_alert",
    "delayed_settlement": "generate_merchant_alert",
    "refund_timing_mismatch": "create_reconciliation_task",
    "duplicate_transaction": "create_recovery_case",
    "missing_settlement_item": "create_recovery_case",
    "partial_settlement": "create_recovery_case",
    "settlement_variance": "create_reconciliation_task",
    "chargeback_reserve": "generate_merchant_alert",
    "refund_rate_spike": "generate_merchant_alert",
    "settlement_degradation": "create_reconciliation_task",
    "merchant_level_anomaly": "generate_merchant_alert",
    "unresolved_exception": "create_reconciliation_task",
}


def categorize(finding: dict, diagnosis: dict) -> str:
    amount = finding["money_at_risk"]
    confidence = diagnosis["confidence"]
    classification = diagnosis["final_classification"]

    if classification in UNRESOLVED_CLASSIFICATIONS:
        return "ESCALATE"
    if amount >= T.ESCALATE_MIN_AMOUNT or confidence <= T.ESCALATE_MAX_CONFIDENCE:
        return "ESCALATE"
    if amount <= T.SAFE_AUTO_MAX_AMOUNT and confidence >= T.SAFE_AUTO_MIN_CONFIDENCE:
        return "SAFE_AUTO_ACTION"
    return "REVIEW_REQUIRED"


def recommend_action(finding: dict, diagnosis: dict) -> str:
    classification = diagnosis["final_classification"]
    action = ACTION_BY_TYPE.get(classification) or ACTION_BY_TYPE.get(finding["exception_type"])
    if action is None:
        action = "create_reconciliation_task"
    assert action in ALLOWED_ACTIONS, f"action {action} not in allowlist"
    return action


def build_action_payload(action_type: str, finding: dict, diagnosis: dict) -> dict:
    base = {
        "exception_type": finding["exception_type"],
        "merchant_id": finding["merchant_id"],
        "money_at_risk": finding["money_at_risk"],
        "recoverable_amount": finding["recoverable_amount"],
    }
    if action_type == "create_recovery_case":
        base["case_summary"] = (
            f"Recovery case for {finding['exception_type']} — "
            f"₹{finding['recoverable_amount']:.2f} recoverable"
        )
    elif action_type == "generate_merchant_alert":
        base["alert_text"] = (
            f"Heads up: {finding['exception_type'].replace('_', ' ')} detected, "
            f"₹{finding['money_at_risk']:.2f} at risk. See the exception detail for evidence."
        )
    elif action_type == "generate_recovery_communication_draft":
        base["draft"] = (
            f"Draft note to settlement ops: please investigate {finding['exception_type']} "
            f"on entity {finding['entity_id']} (₹{finding['money_at_risk']:.2f})."
        )
    elif action_type == "generate_journal_suggestion":
        base["journal_lines"] = [
            {"account": "recoverable_receivable", "debit": finding["recoverable_amount"], "credit": 0},
            {"account": "settlement_variance_clearing", "debit": 0, "credit": finding["recoverable_amount"]},
        ]
    elif action_type == "create_reconciliation_task":
        base["task"] = f"Reconcile {finding['exception_type']} on {finding['entity_type']} {finding['entity_id']}"
    elif action_type == "mark_resolved":
        base["reason"] = "Auto-resolved: high confidence, fully explained, below auto-action ceiling"
    elif action_type == "close_duplicate_exception":
        base["reason"] = "Duplicate of an existing open exception on the same entity"
    elif action_type == "group_related_exceptions":
        base["reason"] = "Grouped with sibling exceptions sharing the same settlement/merchant window"
    return base
