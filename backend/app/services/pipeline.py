"""Orchestrates: load data -> detect -> diagnose -> categorize -> act -> audit
-> evaluate. This is the one function the seed command and the `/api/pipeline/rerun`
endpoint both call.
"""
import time
import uuid
from datetime import datetime

from app.core.db import SessionLocal
from app.models import orm
from app.repositories.data_repo import load_bundle
from app.analytics.detectors import run_all_detectors
from app.agents.root_cause import diagnose
from app.agents.action_engine import categorize, recommend_action, build_action_payload


def _new_audit_event(db, entity_type, entity_id, trigger, evidence, calculations,
                      model_or_rule, decision, confidence, action, outcome, review_required):
    ev = orm.AuditEvent(
        entity_type=entity_type, entity_id=entity_id, trigger=trigger,
        evidence_consulted=evidence, calculations=calculations, model_or_rule=model_or_rule,
        decision=decision, confidence=confidence, action=action,
        execution_outcome=outcome, human_review_required=review_required,
    )
    db.add(ev)
    return ev


def _execute_action(db, exception_row, action_type, category, finding, diagnosis):
    idem_key = f"{exception_row.id}:{action_type}"
    existing = db.query(orm.Action).filter_by(idempotency_key=idem_key).first()
    if existing:
        return existing

    payload = build_action_payload(action_type, finding, diagnosis)
    action = orm.Action(
        exception_id=exception_row.id, action_type=action_type, category=category,
        payload=payload, idempotency_key=idem_key,
    )

    if category == "SAFE_AUTO_ACTION":
        action.status = "executed"
        action.executed_at = datetime.utcnow()
        action.result = {"outcome": "applied", **payload}
        if action_type == "mark_resolved":
            exception_row.status = "auto_resolved"
        else:
            exception_row.status = "auto_resolved"
        outcome = "executed"
        review_required = False
    else:
        action.status = "pending"
        action.result = {"outcome": "pending_review", **payload}
        exception_row.status = "review_required" if category == "REVIEW_REQUIRED" else "escalated"
        outcome = "pending_review"
        review_required = True

    db.add(action)
    _new_audit_event(
        db, "exception", exception_row.id, trigger="pipeline_run",
        evidence=finding["evidence"], calculations=diagnosis["calculations"],
        model_or_rule=finding["detector"], decision=f"{category}: {action_type}",
        confidence=diagnosis["confidence"], action=action_type,
        outcome=outcome, review_required=review_required,
    )
    return action


def run_full_pipeline():
    t0 = time.time()
    bundle = load_bundle()
    db = SessionLocal()
    try:
        # idempotent re-run: clear previously derived exceptions/actions/audit
        # (raw financial data is never touched)
        db.query(orm.AuditEvent).delete()
        db.query(orm.Action).delete()
        db.query(orm.Exception_).delete()
        db.commit()

        findings = run_all_detectors(bundle)
        print(f"[pipeline] {len(findings)} raw findings from {len(bundle.payments)} payments")

        merchant_names = dict(zip(bundle.merchants["id"], bundle.merchants["name"]))

        for finding in findings:
            diagnosis = diagnose(finding, bundle)
            category = categorize(finding, diagnosis)
            action_type = recommend_action(finding, diagnosis)

            exc = orm.Exception_(
                merchant_id=finding["merchant_id"],
                exception_type=finding["exception_type"],
                entity_type=finding["entity_type"],
                entity_id=finding["entity_id"],
                severity=finding["severity"],
                status="open",
                window_start=finding["window_start"],
                window_end=finding["window_end"],
                money_at_risk=finding["money_at_risk"],
                recoverable_amount=finding["recoverable_amount"],
                money_at_risk_breakdown=finding["money_at_risk_breakdown"],
                detector=finding["detector"],
                confidence=diagnosis["confidence"],
                evidence=finding["evidence"],
                root_cause=diagnosis,
                root_cause_label=diagnosis["final_classification"],
                recommended_action=action_type,
                action_category=category,
                explanation=None,
            )
            db.add(exc)
            db.flush()  # get exc.id

            from app.agents.llm import get_llm_provider
            facts = {
                "exception_type": finding["exception_type"],
                "money_at_risk": finding["money_at_risk"],
                "recoverable_amount": finding["recoverable_amount"],
                "final_classification": diagnosis["final_classification"],
                "confidence": diagnosis["confidence"],
                "calculations": diagnosis["calculations"],
                "recommended_action": action_type,
            }
            exc.explanation = get_llm_provider().explain(facts)

            _execute_action(db, exc, action_type, category, finding, diagnosis)

        db.commit()
        print(f"[pipeline] {len(findings)} exceptions persisted in {time.time()-t0:.1f}s")
    finally:
        db.close()

    from app.services.evaluation import run_evaluation
    run_evaluation()


if __name__ == "__main__":
    run_full_pipeline()
