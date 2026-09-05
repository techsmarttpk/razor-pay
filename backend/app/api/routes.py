import json
import os
from datetime import datetime
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_db, engine, DATA_DIR
from app.models import orm
from app.api.serializers import row_to_dict
from app.services.overview import get_overview
from app.agents.action_engine import ALLOWED_ACTIONS, build_action_payload
from app.agents.llm import get_llm_provider

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Merchants
# ---------------------------------------------------------------------------
@router.get("/merchants")
def list_merchants(db: Session = Depends(get_db)):
    merchants = db.query(orm.Merchant).all()
    out = []
    for m in merchants:
        d = row_to_dict(m)
        n_exc = db.query(orm.Exception_).filter(orm.Exception_.merchant_id == m.id).count()
        d["exception_count"] = n_exc
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------
@router.get("/overview")
def overview(merchant_id: Optional[str] = None):
    return get_overview(merchant_id)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
@router.get("/exceptions")
def list_exceptions(status: Optional[str] = None, severity: Optional[str] = None,
                     exception_type: Optional[str] = None, merchant_id: Optional[str] = None,
                     limit: int = 200, db: Session = Depends(get_db)):
    q = db.query(orm.Exception_)
    if status:
        q = q.filter(orm.Exception_.status == status)
    if severity:
        q = q.filter(orm.Exception_.severity == severity)
    if exception_type:
        q = q.filter(orm.Exception_.exception_type == exception_type)
    if merchant_id:
        q = q.filter(orm.Exception_.merchant_id == merchant_id)
    q = q.order_by(orm.Exception_.money_at_risk.desc()).limit(limit)
    rows = [row_to_dict(r) for r in q.all()]
    merchant_ids = {r["merchant_id"] for r in rows}
    if merchant_ids:
        merchants = db.query(orm.Merchant).filter(orm.Merchant.id.in_(merchant_ids)).all()
        name_map = {m.id: m.name for m in merchants}
        for r in rows:
            r["merchant_name"] = name_map.get(r["merchant_id"])
    return rows


@router.get("/exceptions/{exception_id}")
def get_exception(exception_id: str, db: Session = Depends(get_db)):
    exc = db.query(orm.Exception_).filter(orm.Exception_.id == exception_id).first()
    if not exc:
        raise HTTPException(404, "exception not found")
    d = row_to_dict(exc)
    merchant = db.query(orm.Merchant).filter(orm.Merchant.id == exc.merchant_id).first()
    d["merchant_name"] = merchant.name if merchant else None
    actions = db.query(orm.Action).filter(orm.Action.exception_id == exception_id).all()
    d["actions"] = [row_to_dict(a) for a in actions]
    audit = db.query(orm.AuditEvent).filter(orm.AuditEvent.entity_id == exception_id) \
        .order_by(orm.AuditEvent.timestamp.asc()).all()
    d["audit_trail"] = [row_to_dict(a) for a in audit]
    return d


@router.post("/exceptions/{exception_id}/actions/{action_type}")
def execute_action(exception_id: str, action_type: str, db: Session = Depends(get_db)):
    if action_type not in ALLOWED_ACTIONS:
        raise HTTPException(400, f"action '{action_type}' is not in the allowlist")
    exc = db.query(orm.Exception_).filter(orm.Exception_.id == exception_id).first()
    if not exc:
        raise HTTPException(404, "exception not found")

    idem_key = f"{exception_id}:{action_type}"
    existing = db.query(orm.Action).filter_by(idempotency_key=idem_key).first()
    if existing:
        return row_to_dict(existing)

    finding = {
        "exception_type": exc.exception_type, "merchant_id": exc.merchant_id,
        "money_at_risk": exc.money_at_risk, "recoverable_amount": exc.recoverable_amount,
        "entity_id": exc.entity_id, "entity_type": exc.entity_type,
    }
    payload = build_action_payload(action_type, finding, {"final_classification": exc.root_cause_label})

    action = orm.Action(
        exception_id=exception_id, action_type=action_type, category=exc.action_category or "REVIEW_REQUIRED",
        status="executed", payload=payload, result={"outcome": "applied_manually", **payload},
        idempotency_key=idem_key, executed_at=datetime.utcnow(),
    )
    db.add(action)

    if action_type in ("mark_resolved", "close_duplicate_exception"):
        exc.status = "resolved"
    elif action_type == "group_related_exceptions":
        exc.case_id = exc.case_id or f"case_{exception_id}"

    audit = orm.AuditEvent(
        entity_type="exception", entity_id=exception_id, trigger="manual_operator_action",
        evidence_consulted=exc.evidence, calculations=exc.root_cause.get("calculations") if exc.root_cause else {},
        model_or_rule="manual", decision=f"MANUAL: {action_type}", confidence=exc.confidence,
        action=action_type, execution_outcome="executed", human_review_required=False,
    )
    db.add(audit)
    db.commit()
    db.refresh(action)
    return row_to_dict(action)


@router.get("/actions")
def list_actions(status: Optional[str] = None, category: Optional[str] = None,
                  limit: int = 300, db: Session = Depends(get_db)):
    q = db.query(orm.Action)
    if status:
        q = q.filter(orm.Action.status == status)
    if category:
        q = q.filter(orm.Action.category == category)
    q = q.order_by(orm.Action.created_at.desc()).limit(limit)
    rows = [row_to_dict(a) for a in q.all()]
    exc_ids = {r["exception_id"] for r in rows}
    if exc_ids:
        excs = db.query(orm.Exception_).filter(orm.Exception_.id.in_(exc_ids)).all()
        exc_map = {e.id: e for e in excs}
        for r in rows:
            e = exc_map.get(r["exception_id"])
            if e:
                r["exception_type"] = e.exception_type
                r["merchant_id"] = e.merchant_id
                r["money_at_risk"] = e.money_at_risk
    return rows


# ---------------------------------------------------------------------------
# Financial events feed
# ---------------------------------------------------------------------------
@router.get("/events")
def list_events(merchant_id: Optional[str] = None, entity_type: Optional[str] = None, limit: int = 200):
    frames = []
    with engine.connect() as conn:
        pay = pd.read_sql(text("SELECT * FROM payments" + (" WHERE merchant_id=:m" if merchant_id else "")),
                           conn, params={"m": merchant_id} if merchant_id else {})
        rfnd = pd.read_sql(text("SELECT * FROM refunds" + (" WHERE merchant_id=:m" if merchant_id else "")),
                            conn, params={"m": merchant_id} if merchant_id else {})
        stl = pd.read_sql(text("SELECT * FROM settlements" + (" WHERE merchant_id=:m" if merchant_id else "")),
                           conn, params={"m": merchant_id} if merchant_id else {})
        disp = pd.read_sql(text("SELECT * FROM disputes" + (" WHERE merchant_id=:m" if merchant_id else "")),
                            conn, params={"m": merchant_id} if merchant_id else {})

    if (entity_type in (None, "payment")) and not pay.empty:
        for _, r in pay.iterrows():
            frames.append({"event_type": "payment", "id": r["id"], "merchant_id": r["merchant_id"],
                            "amount": r["amount"], "timestamp": r["created_at"], "status": r["status"],
                            "detail": f"{r['method']} payment"})
    if (entity_type in (None, "refund")) and not rfnd.empty:
        for _, r in rfnd.iterrows():
            frames.append({"event_type": "refund", "id": r["id"], "merchant_id": r["merchant_id"],
                            "amount": -r["amount"], "timestamp": r["created_at"], "status": r["status"],
                            "detail": f"refund: {r['reason']}"})
    if (entity_type in (None, "settlement")) and not stl.empty:
        for _, r in stl.iterrows():
            frames.append({"event_type": "settlement", "id": r["id"], "merchant_id": r["merchant_id"],
                            "amount": r["amount"], "timestamp": r["settled_at"], "status": r["status"],
                            "detail": f"UTR {r['utr']}"})
    if (entity_type in (None, "dispute")) and not disp.empty:
        for _, r in disp.iterrows():
            frames.append({"event_type": "dispute", "id": r["id"], "merchant_id": r["merchant_id"],
                            "amount": r["amount"], "timestamp": r["created_at"], "status": r["status"],
                            "detail": f"dispute: {r['reason']}"})

    frames.sort(key=lambda x: str(x["timestamp"]), reverse=True)
    return frames[:limit]


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------
@router.get("/audit")
def list_audit(entity_id: Optional[str] = None, limit: int = 300, db: Session = Depends(get_db)):
    q = db.query(orm.AuditEvent)
    if entity_id:
        q = q.filter(orm.AuditEvent.entity_id == entity_id)
    q = q.order_by(orm.AuditEvent.timestamp.desc()).limit(limit)
    return [row_to_dict(r) for r in q.all()]


# ---------------------------------------------------------------------------
# Model performance / evaluation metrics
# ---------------------------------------------------------------------------
@router.get("/metrics")
def metrics():
    path = os.path.join(DATA_DIR, "benchmarks", "results.json")
    if not os.path.exists(path):
        raise HTTPException(404, "no benchmark results yet — run the pipeline")
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Pipeline control (demo convenience)
# ---------------------------------------------------------------------------
@router.post("/pipeline/rerun")
def rerun_pipeline():
    from app.services.pipeline import run_full_pipeline
    run_full_pipeline()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Agent chat (secondary interaction — product works fully without this)
# ---------------------------------------------------------------------------
@router.post("/agent/ask")
def agent_ask(payload: dict):
    question = payload.get("question", "")
    ov = get_overview(payload.get("merchant_id"))
    facts = {
        "total_money_at_risk": ov["money_at_risk"],
        "open_exceptions": ov["active_exceptions"],
        "top_exceptions": ov["top_exceptions"],
    }
    answer = get_llm_provider().answer(question, facts)
    return {"answer": answer, "facts": facts}
