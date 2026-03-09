"""
Test: After approval, queue disbursement. POST /webhook/disbursement with:
  application_id, status ("success" | "failed"), transaction_id, timestamp.

Shows: submit → auto-approve → disbursement_queued → webhook success → disbursed;
       webhook failed → disbursement_failed; same transaction_id replay → idempotent.
"""

import os
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

_test_db_dir = tempfile.mkdtemp(prefix="loanapp_webhook_test_")
os.environ["LOANAPP_DB_PATH"] = os.path.join(_test_db_dir, "loanapp.db")

from src.app import app

client = TestClient(app)

# Scenario 1 (Jane Doe): strong financials → auto-approve → disbursement_queued
AUTO_APPROVE_PAYLOAD = {
    "applicant_name": "Jane Doe",
    "email": "jane.webhook.test@example.com",
    "loan_amount": 1500,
    "stated_monthly_income": 5000,
    "employment_status": "employed",
    "documented_monthly_income": 4800,
    "bank_ending_balance": 3200,
    "bank_has_overdrafts": False,
    "bank_has_consistent_deposits": True,
    "monthly_withdrawals": 1200,
    "monthly_deposits": 4800,
}


def test_after_approval_webhook_success_disbursed():
    """After approval, app is in disbursement_queued; POST /webhook/disbursement (success) → disbursed."""
    r_submit = client.post("/applications", json=AUTO_APPROVE_PAYLOAD)
    assert r_submit.status_code == 200
    data = r_submit.json()
    application_id = data["id"]
    assert data["status"] == "disbursement_queued"

    webhook_payload = {
        "application_id": application_id,
        "status": "success",
        "transaction_id": "txn_456",
        "timestamp": "2026-01-15T10:30:00Z",
    }
    r_webhook = client.post("/webhook/disbursement", json=webhook_payload)
    assert r_webhook.status_code == 200
    body = r_webhook.json()
    assert body["processed"] is True
    assert body["already_processed"] is False
    assert body["application_id"] == application_id
    assert body["new_status"] == "disbursed"
    assert body["transaction_id"] == "txn_456"

    r_get = client.get(f"/applications/{application_id}")
    assert r_get.status_code == 200
    assert r_get.json()["status"] == "disbursed"


def test_webhook_failed_disbursement_failed():
    """POST /webhook/disbursement with status 'failed' → application moves to disbursement_failed."""
    payload = {**AUTO_APPROVE_PAYLOAD, "email": "jane.fail.test@example.com"}
    r_submit = client.post("/applications", json=payload)
    assert r_submit.status_code == 200
    application_id = r_submit.json()["id"]
    assert r_submit.json()["status"] == "disbursement_queued"

    webhook_payload = {
        "application_id": application_id,
        "status": "failed",
        "transaction_id": "txn_fail_789",
        "timestamp": "2026-01-15T10:30:00Z",
    }
    r_webhook = client.post("/webhook/disbursement", json=webhook_payload)
    assert r_webhook.status_code == 200
    assert r_webhook.json()["new_status"] == "disbursement_failed"

    r_get = client.get(f"/applications/{application_id}")
    assert r_get.status_code == 200
    assert r_get.json()["status"] == "disbursement_failed"


def test_webhook_same_transaction_id_replay_idempotent():
    """Same transaction_id sent twice: first processes, second returns 200 with already_processed, no state change."""
    payload = {**AUTO_APPROVE_PAYLOAD, "email": "jane.replay.test@example.com"}
    r_submit = client.post("/applications", json=payload)
    assert r_submit.status_code == 200
    application_id = r_submit.json()["id"]

    txn_id = "txn_replay_idempotent_001"
    webhook_payload = {
        "application_id": application_id,
        "status": "success",
        "transaction_id": txn_id,
        "timestamp": "2026-01-15T10:30:00Z",
    }
    r1 = client.post("/webhook/disbursement", json=webhook_payload)
    assert r1.status_code == 200
    assert r1.json()["processed"] is True
    assert r1.json()["new_status"] == "disbursed"

    r2 = client.post("/webhook/disbursement", json=webhook_payload)
    assert r2.status_code == 200
    assert r2.json()["processed"] is False
    assert r2.json()["already_processed"] is True
    assert r2.json()["application_id"] == application_id
    assert r2.json()["transaction_id"] == txn_id

    r_get = client.get(f"/applications/{application_id}")
    assert r_get.json()["status"] == "disbursed"
