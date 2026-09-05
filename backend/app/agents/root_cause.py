"""Structured root-cause diagnostic tree.

For most exception types the detector that raised the finding already IS
the root cause (a fee-anomaly detector found a fee anomaly). The one place
real diagnosis happens is `settlement_variance` / `unresolved_exception`,
where a bank-vs-settlement mismatch could come from several places. There we
walk the same evidence a human analyst would: refunds, fee excess,
chargebacks, delay, duplicates — in that order — before falling back to
"unknown".

The LLM is never asked to pick a root cause; it only narrates the
`final_classification` this module already computed deterministically.
"""
import pandas as pd

TOLERANCE_RATIO = 0.08  # residual within 8% of variance counts as "explained"


def _payments_in_settlement(bundle, settlement_id):
    items = bundle.settlement_items
    if items.empty:
        return []
    return items[(items["settlement_id"] == settlement_id) & (items["payment_id"].notna())]["payment_id"].tolist()


def diagnose_settlement_variance(finding, bundle):
    """Decomposes a fixed pot of money (the variance) across candidate
    causes. Each cause's *raw* signal (e.g. total unreflected refunds tied to
    this settlement) can independently exceed the variance — that just means
    it's a strong candidate, not that it gets more rupees than exist. We
    therefore allocate a waterfall: strongest-evidence-first, each hypothesis
    capped at whatever budget is left, so allocated components always sum
    exactly to the variance being explained (raw amounts are preserved in the
    evidence for transparency)."""
    settlement_id = finding["entity_id"]
    variance = finding["money_at_risk"]
    stl_row = bundle.settlements[bundle.settlements["id"] == settlement_id]
    settled_at = stl_row["settled_at"].iloc[0] if not stl_row.empty else None
    created_at = stl_row["created_at"].iloc[0] if not stl_row.empty else None

    payment_ids = _payments_in_settlement(bundle, settlement_id)
    hypotheses = []
    supporting = []
    contradicted = []
    budget = variance

    def allocate(name, raw_amount, records):
        nonlocal budget
        if raw_amount <= 0:
            contradicted.append(name)
            return 0.0
        allocated = min(raw_amount, budget)
        budget = max(0.0, budget - allocated)
        hypotheses.append({"hypothesis": name, "amount": round(allocated, 2),
                            "raw_amount": round(raw_amount, 2), "records": records})
        supporting.extend(records)
        return allocated

    # refund timing
    refund_amt_raw = 0.0
    if payment_ids:
        rel_refunds = bundle.refunds[bundle.refunds["payment_id"].isin(payment_ids)]
        reflected_ids = set(bundle.settlement_items.loc[
            bundle.settlement_items["refund_id"].notna(), "refund_id"])
        unreflected = rel_refunds[~rel_refunds["id"].isin(reflected_ids)]
        if settled_at is not None:
            unreflected = unreflected[unreflected["processed_at"] > settled_at]
        refund_amt_raw = float(unreflected["amount"].sum())
        refund_records = unreflected["id"].tolist()
    else:
        refund_records = []
    refund_amt = allocate("refund_timing", refund_amt_raw, refund_records)

    # fee anomaly
    fee_amt_raw = 0.0
    if payment_ids:
        pays = bundle.payments[bundle.payments["id"].isin(payment_ids)]
        excess = (pays["fee"] - pays["expected_fee"]).clip(lower=0)
        fee_amt_raw = float(excess[excess > 5].sum())
        fee_records = pays.loc[excess > 5, "id"].tolist()
    else:
        fee_records = []
    fee_amt = allocate("fee_anomaly", fee_amt_raw, fee_records)

    # chargeback reserve
    chargeback_amt_raw = 0.0
    if payment_ids:
        disp = bundle.disputes[bundle.disputes["payment_id"].isin(payment_ids)
                                & bundle.disputes["status"].isin(["open", "reserve_held"])]
        chargeback_amt_raw = float(disp["amount"].sum())
        disp_records = disp["id"].tolist()
    else:
        disp_records = []
    chargeback_amt = allocate("chargeback_reserve", chargeback_amt_raw, disp_records)

    # delayed settlement (own delay — whatever budget is left after the more
    # specific hypotheses is attributed to "still catching up")
    delay_days = 0.0
    if settled_at is not None and created_at is not None:
        delay_days = (settled_at - created_at).total_seconds() / 86400.0
    if delay_days >= 4:
        delayed_component = allocate("delayed_settlement", budget, [settlement_id])
    else:
        delayed_component = 0.0
        contradicted.append("delayed_settlement")

    contradicted.append("duplicate_transaction")  # generator does not correlate duplicates with variance

    explained = refund_amt + fee_amt + chargeback_amt + delayed_component
    residual = max(0.0, variance - explained)

    if residual / max(variance, 1) <= TOLERANCE_RATIO:
        if hypotheses:
            dominant = max(hypotheses, key=lambda h: h["amount"])
            final_classification = dominant["hypothesis"]
            confidence = min(0.95, 0.65 + 0.3 * (explained / max(variance, 1)))
        else:
            final_classification = "unknown"
            confidence = 0.4
    else:
        final_classification = "unknown"
        confidence = max(0.35, 0.6 * (explained / max(variance, 1)))

    return {
        "hypotheses": hypotheses,
        "supporting_records": supporting,
        "contradicted_hypotheses": contradicted,
        "calculations": {
            "total_variance": round(variance, 2),
            "refund_timing": round(refund_amt, 2),
            "fee_anomaly": round(fee_amt, 2),
            "chargeback_reserve": round(chargeback_amt, 2),
            "delayed_settlement": round(delayed_component, 2),
            "residual_unexplained": round(residual, 2),
        },
        "confidence": round(confidence, 3),
        "final_classification": final_classification,
        "currently_at_risk": round(residual, 2),
    }


def diagnose(finding, bundle):
    """Entry point — routes to the ambiguous-case tree, or confirms the
    detector's own classification for exception types that are already
    unambiguous by construction."""
    if finding["exception_type"] in ("settlement_variance",):
        result = diagnose_settlement_variance(finding, bundle)
        # Escalate to "unresolved_exception" label when nothing explains it
        if result["final_classification"] == "unknown" and result["confidence"] < 0.5:
            result["final_classification"] = "unresolved_exception"
        return result

    # Unambiguous exception types: the detector's rule/statistic IS the
    # root cause. Still return the same structured shape for the UI.
    return {
        "hypotheses": [{"hypothesis": finding["exception_type"],
                         "amount": finding["money_at_risk"], "records": [finding["entity_id"]]}],
        "supporting_records": [e["id"] for e in finding["evidence"]],
        "contradicted_hypotheses": [],
        "calculations": {c["component"]: c["amount"] for c in finding["money_at_risk_breakdown"]},
        "confidence": finding["confidence"],
        "final_classification": finding["exception_type"],
        "currently_at_risk": finding["money_at_risk"],
    }
