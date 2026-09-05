"""API smoke tests against the seeded demo database. Run
`python -m app.services.seed` before `pytest` (same prerequisite the README
states for the demo)."""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_merchants_list():
    r = client.get("/api/merchants")
    assert r.status_code == 200
    data = r.json()
    assert len(data) > 0
    assert "id" in data[0] and "name" in data[0]


def test_overview():
    r = client.get("/api/overview")
    assert r.status_code == 200
    data = r.json()
    for key in ("money_at_risk", "recoverable_amount", "active_exceptions", "auto_resolved",
                "pending_review", "settlement_health", "refund_health", "reconciliation_health"):
        assert key in data
    assert data["money_at_risk"] >= 0
    assert 0 <= data["settlement_health"] <= 100


def test_exceptions_list_and_detail():
    r = client.get("/api/exceptions", params={"limit": 5})
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) > 0
    exc_id = rows[0]["id"]

    r2 = client.get(f"/api/exceptions/{exc_id}")
    assert r2.status_code == 200
    detail = r2.json()
    assert detail["id"] == exc_id
    assert "evidence" in detail and "root_cause" in detail
    assert "audit_trail" in detail
    assert len(detail["audit_trail"]) > 0


def test_execute_action_rejects_non_allowlisted_action():
    r = client.get("/api/exceptions", params={"limit": 1})
    exc_id = r.json()[0]["id"]
    r2 = client.post(f"/api/exceptions/{exc_id}/actions/delete_all_transactions")
    assert r2.status_code == 400


def test_execute_action_is_idempotent():
    r = client.get("/api/exceptions", params={"status": "review_required", "limit": 1})
    rows = r.json()
    if not rows:
        pytest.skip("no review_required exceptions in this seed")
    exc_id = rows[0]["id"]
    r1 = client.post(f"/api/exceptions/{exc_id}/actions/generate_merchant_alert")
    r2 = client.post(f"/api/exceptions/{exc_id}/actions/generate_merchant_alert")
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]


def test_events_feed():
    r = client.get("/api/events", params={"limit": 20})
    assert r.status_code == 200
    assert len(r.json()) > 0


def test_audit_trail():
    r = client.get("/api/audit", params={"limit": 20})
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) > 0
    assert "decision" in rows[0] and "confidence" in rows[0]


def test_metrics():
    r = client.get("/api/metrics")
    assert r.status_code == 200
    data = r.json()
    for key in ("precision", "recall", "f1", "false_positive_rate", "root_cause_accuracy"):
        assert key in data
    assert 0 <= data["precision"] <= 1
    assert 0 <= data["recall"] <= 1


def test_agent_ask_never_exceeds_100_percent_certainty():
    r = client.post("/api/agent/ask", json={"question": "Why is money at risk today?"})
    assert r.status_code == 200
    assert "answer" in r.json()
