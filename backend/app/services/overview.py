"""Overview KPI computation — pure aggregation over already-persisted
exceptions and raw financial entities. No detection logic lives here."""
import pandas as pd
from sqlalchemy import text

from app.core.db import engine


def _read(table, merchant_id=None):
    q = f"SELECT * FROM {table}"
    if merchant_id:
        q += f" WHERE merchant_id = :mid"
    with engine.connect() as conn:
        if merchant_id:
            return pd.read_sql(text(q), conn, params={"mid": merchant_id})
        return pd.read_sql(text(q), conn)


def get_overview(merchant_id: str | None = None) -> dict:
    exceptions = _read("exceptions", merchant_id)
    payments = _read("payments", merchant_id)
    settlements = _read("settlements", merchant_id)
    refunds = _read("refunds", merchant_id)
    merchants = _read("merchants")

    total_settled = float(settlements["amount"].sum()) if not settlements.empty else 0.0
    total_paid = float(payments["amount"].sum()) if not payments.empty else 0.0

    open_mask = exceptions["status"].isin(["open", "review_required", "escalated"]) if not exceptions.empty else None
    money_at_risk = float(exceptions.loc[open_mask, "money_at_risk"].sum()) if not exceptions.empty else 0.0
    recoverable = float(exceptions.loc[open_mask, "recoverable_amount"].sum()) if not exceptions.empty else 0.0
    active_exceptions = int(open_mask.sum()) if not exceptions.empty else 0
    auto_resolved = int((exceptions["status"] == "auto_resolved").sum()) if not exceptions.empty else 0
    pending_review = int((exceptions["status"] == "review_required").sum()) if not exceptions.empty else 0
    escalated = int((exceptions["status"] == "escalated").sum()) if not exceptions.empty else 0

    settlement_risk = float(exceptions.loc[
        exceptions["exception_type"].isin(["delayed_settlement", "settlement_variance", "settlement_degradation"])
        & open_mask, "money_at_risk"].sum()) if not exceptions.empty else 0.0
    refund_risk = float(exceptions.loc[
        exceptions["exception_type"].isin(["refund_timing_mismatch", "refund_rate_spike"])
        & open_mask, "money_at_risk"].sum()) if not exceptions.empty else 0.0
    reconciliation_risk = float(exceptions.loc[
        exceptions["exception_type"].isin(["missing_settlement_item", "partial_settlement", "duplicate_transaction"])
        & open_mask, "money_at_risk"].sum()) if not exceptions.empty else 0.0

    def health(risk, base):
        if base <= 0:
            return 100.0
        return round(max(0.0, min(100.0, 100.0 * (1 - risk / base))), 1)

    settlement_health = health(settlement_risk, max(total_settled, 1))
    refund_health = health(refund_risk, max(float(refunds["amount"].sum()) if not refunds.empty else 0, 1))
    reconciliation_health = health(reconciliation_risk, max(total_paid, 1))

    top = exceptions.loc[open_mask].sort_values("money_at_risk", ascending=False).head(5) if not exceptions.empty else exceptions
    merchant_name_map = dict(zip(merchants["id"], merchants["name"]))
    top_list = []
    for _, row in top.iterrows():
        top_list.append({
            "id": row["id"],
            "exception_type": row["exception_type"],
            "merchant_id": row["merchant_id"],
            "merchant_name": merchant_name_map.get(row["merchant_id"], row["merchant_id"]),
            "money_at_risk": row["money_at_risk"],
            "recoverable_amount": row["recoverable_amount"],
            "confidence": row["confidence"],
            "severity": row["severity"],
            "status": row["status"],
            "explanation": row["explanation"],
        })

    return {
        "money_at_risk": round(money_at_risk, 2),
        "recoverable_amount": round(recoverable, 2),
        "active_exceptions": active_exceptions,
        "auto_resolved": auto_resolved,
        "pending_review": pending_review,
        "escalated": escalated,
        "settlement_health": settlement_health,
        "refund_health": refund_health,
        "reconciliation_health": reconciliation_health,
        "total_settled": round(total_settled, 2),
        "total_paid": round(total_paid, 2),
        "top_exceptions": top_list,
    }
