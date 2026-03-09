"""Step 4: Duplicate prevention (same email + loan within 5 min) and webhook replay idempotency."""

import os
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient

# Set test DB before importing app so first request uses it
_test_db_dir = tempfile.mkdtemp(prefix="loanapp_test_")
_test_db_path = os.path.join(_test_db_dir, "loanapp.db")
os.environ["LOANAPP_DB_PATH"] = _test_db_path

from src.app import app

client = TestClient(app)


# Same payload as spec scenario 1 (auto-approve → disbursement_queued)
APPLICATION_PAYLOAD = {
    "applicant_name": "Jane Doe",
    "email": "jane.doe@example.com",
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


def test_duplicate_prevention_same_email_and_loan_within_window():
    """Same email + loan amount within 5 minutes → 409 and original_application_id."""
    r1 = client.post("/applications", json=APPLICATION_PAYLOAD)
    assert r1.status_code == 200
    original_id = r1.json()["id"]

    r2 = client.post("/applications", json=APPLICATION_PAYLOAD)
    assert r2.status_code == 409
    body = r2.json()
    assert "detail" in body
    assert body["detail"]["error"] == "DuplicateApplicationError"
    assert body["detail"]["original_application_id"] == original_id


def test_webhook_replay_idempotent():
    """Same transaction_id sent twice: first processes, second returns 200 with already_processed, no state change."""
    payload_submit = {**APPLICATION_PAYLOAD, "email": "idempotency.test@example.com"}
    r_submit = client.post("/applications", json=payload_submit)
    assert r_submit.status_code == 200
    app_id = r_submit.json()["id"]
    assert r_submit.json()["status"] == "disbursement_queued"

    payload = {
        "application_id": app_id,
        "status": "success",
        "transaction_id": "txn_idempotency_test_001",
        "timestamp": "2026-01-15T10:30:00Z",
    }

    r1 = client.post("/webhook/disbursement", json=payload)
    assert r1.status_code == 200
    assert r1.json()["processed"] is True
    assert r1.json()["already_processed"] is False
    assert r1.json()["new_status"] == "disbursed"

    r2 = client.post("/webhook/disbursement", json=payload)
    assert r2.status_code == 200
    assert r2.json()["processed"] is False
    assert r2.json()["already_processed"] is True
    assert "new_status" not in r2.json() or r2.json().get("new_status") is None

    r_get = client.get(f"/applications/{app_id}")
    assert r_get.status_code == 200
    assert r_get.json()["status"] == "disbursed"
