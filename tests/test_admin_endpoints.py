"""Admin endpoints: list+filter, full detail with score breakdown, review (approve/deny/partially_approve)."""

import os
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient

_test_db_dir = tempfile.mkdtemp(prefix="loanapp_admin_test_")
_test_db_path = os.path.join(_test_db_dir, "loanapp.db")
os.environ["LOANAPP_DB_PATH"] = _test_db_path

from src.app import app

client = TestClient(app)
auth = ("admin", "admin")  # config/app.yaml defaults


# Scenario 4: Jane Doe, larger loan → flag_for_review
FLAGGED_PAYLOAD = {
    "applicant_name": "Jane Doe",
    "email": "jane.admin.test@example.com",
    "loan_amount": 4500,
    "stated_monthly_income": 5000,
    "employment_status": "employed",
    "documented_monthly_income": 4800,
    "bank_ending_balance": 3200,
    "bank_has_overdrafts": False,
    "bank_has_consistent_deposits": True,
    "monthly_withdrawals": 1200,
    "monthly_deposits": 4800,
}


def test_admin_list_without_auth_returns_401():
    r = client.get("/admin/applications")
    assert r.status_code == 401


def test_admin_list_filtered_by_status():
    r_submit = client.post("/applications", json=FLAGGED_PAYLOAD)
    assert r_submit.status_code == 200
    assert r_submit.json()["status"] == "flagged_for_review"

    r = client.get("/admin/applications?status=flagged_for_review", auth=auth)
    assert r.status_code == 200
    data = r.json()
    assert "applications" in data
    assert data["count"] >= 1
    assert any(a["email"] == FLAGGED_PAYLOAD["email"] for a in data["applications"])


def test_admin_get_application_full_detail_with_score_breakdown():
    payload = {**FLAGGED_PAYLOAD, "email": "admin.detail.test@example.com"}
    r_submit = client.post("/applications", json=payload)
    assert r_submit.status_code == 200
    app_id = r_submit.json()["id"]

    r = client.get(f"/admin/applications/{app_id}", auth=auth)
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == app_id
    assert "score_breakdown" in data
    assert isinstance(data["score_breakdown"], list)
    assert len(data["score_breakdown"]) > 0
    assert "factor_name" in data["score_breakdown"][0]
    assert "weighted_score" in data["score_breakdown"][0]


def test_admin_review_deny():
    payload = {**FLAGGED_PAYLOAD, "email": "admin.deny.test@example.com"}
    r_submit = client.post("/applications", json=payload)
    assert r_submit.status_code == 200
    app_id = r_submit.json()["id"]

    r = client.post(
        f"/admin/applications/{app_id}/review",
        auth=auth,
        json={"action": "deny", "note": "Not sufficient income."},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "denied"
    assert r.json()["action"] == "deny"

    r_get = client.get(f"/admin/applications/{app_id}", auth=auth)
    assert r_get.json()["status"] == "denied"


def test_admin_review_partially_approve():
    payload = {**FLAGGED_PAYLOAD, "email": "admin.partial.test@example.com"}
    r_submit = client.post("/applications", json=payload)
    assert r_submit.status_code == 200
    app_id = r_submit.json()["id"]

    r = client.post(
        f"/admin/applications/{app_id}/review",
        auth=auth,
        json={
            "action": "partially_approve",
            "approved_loan_amount": 2000,
            "note": "Approved reduced amount.",
        },
    )
    assert r.status_code == 200
    assert r.json()["status"] == "partially_approved"
    assert r.json()["approved_loan_amount"] == 2000

    r_get = client.get(f"/admin/applications/{app_id}", auth=auth)
    assert r_get.json()["status"] == "partially_approved"


def test_admin_review_approve_moves_to_disbursement_queued():
    payload = {**FLAGGED_PAYLOAD, "email": "admin.approve.test@example.com"}
    r_submit = client.post("/applications", json=payload)
    assert r_submit.status_code == 200
    app_id = r_submit.json()["id"]

    r = client.post(
        f"/admin/applications/{app_id}/review",
        auth=auth,
        json={"action": "approve", "note": "Approved after review."},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "disbursement_queued"

    r_get = client.get(f"/admin/applications/{app_id}", auth=auth)
    assert r_get.json()["status"] == "disbursement_queued"
