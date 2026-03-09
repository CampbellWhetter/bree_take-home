"""SQLite persistence: applications and webhook events (idempotency + audit)."""

import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .state_machine.states import ApplicationStatus


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def get_db_path() -> Path:
    return _project_root() / "data" / "loanapp.db"


@contextmanager
def get_connection():
    path = get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS applications (
            id TEXT PRIMARY KEY,
            applicant_name TEXT NOT NULL,
            email TEXT NOT NULL,
            loan_amount REAL NOT NULL,
            stated_monthly_income REAL NOT NULL,
            employment_status TEXT NOT NULL,
            documented_monthly_income REAL,
            bank_ending_balance REAL,
            bank_has_overdrafts INTEGER,
            bank_has_consistent_deposits INTEGER,
            monthly_withdrawals REAL,
            monthly_deposits REAL,
            status TEXT NOT NULL,
            score REAL,
            decision TEXT,
            score_breakdown_json TEXT,
            disbursement_queued_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS webhook_events (
            transaction_id TEXT PRIMARY KEY,
            application_id TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_timestamp TEXT,
            received_at TEXT NOT NULL,
            FOREIGN KEY (application_id) REFERENCES applications(id)
        );

        CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);
        CREATE INDEX IF NOT EXISTS idx_applications_email_loan_created ON applications(email, loan_amount, created_at);
        CREATE INDEX IF NOT EXISTS idx_applications_disbursement_queued ON applications(disbursement_queued_at)
            WHERE status = 'disbursement_queued';
    """)


# --- Applications ---

def create_application(
    conn: sqlite3.Connection,
    *,
    applicant_name: str,
    email: str,
    loan_amount: float,
    stated_monthly_income: float,
    employment_status: str,
    documented_monthly_income: float | None,
    bank_ending_balance: float | None,
    bank_has_overdrafts: bool | None,
    bank_has_consistent_deposits: bool | None,
    monthly_withdrawals: float | None,
    monthly_deposits: float | None,
    status: str,
    score: float | None,
    decision: str | None,
    score_breakdown_json: str | None,
    disbursement_queued_at: str | None,
) -> str:
    app_id = str(uuid.uuid4())
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO applications (
            id, applicant_name, email, loan_amount, stated_monthly_income,
            employment_status, documented_monthly_income, bank_ending_balance,
            bank_has_overdrafts, bank_has_consistent_deposits, monthly_withdrawals,
            monthly_deposits, status, score, decision, score_breakdown_json,
            disbursement_queued_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            app_id, applicant_name, email, loan_amount, stated_monthly_income,
            employment_status, documented_monthly_income, bank_ending_balance,
            1 if bank_has_overdrafts else 0 if bank_has_overdrafts is False else None,
            1 if bank_has_consistent_deposits else 0 if bank_has_consistent_deposits is False else None,
            monthly_withdrawals, monthly_deposits,
            status, score, decision, score_breakdown_json,
            disbursement_queued_at, now, now,
        ),
    )
    return app_id


def get_application(conn: sqlite3.Connection, application_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
    if row is None:
        return None
    return _row_to_application(row)


def find_duplicate(
    conn: sqlite3.Connection,
    email: str,
    loan_amount: float,
    within_minutes: int,
) -> str | None:
    """Return application_id of a recent application with same email+loan_amount, or None."""
    row = conn.execute(
        """SELECT id FROM applications
           WHERE email = ? AND loan_amount = ?
             AND datetime(created_at) >= datetime('now', ?)
           ORDER BY created_at DESC LIMIT 1""",
        (email, loan_amount, f"-{within_minutes} minutes"),
    ).fetchone()
    return row["id"] if row else None


def update_application_status(
    conn: sqlite3.Connection,
    application_id: str,
    new_status: str,
    *,
    disbursement_queued_at: str | None = None,
) -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    if disbursement_queued_at is not None:
        conn.execute(
            "UPDATE applications SET status = ?, disbursement_queued_at = ?, updated_at = ? WHERE id = ?",
            (new_status, disbursement_queued_at, now, application_id),
        )
    else:
        conn.execute(
            "UPDATE applications SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, now, application_id),
        )


def list_applications_by_status(conn: sqlite3.Connection, status: str) -> list[dict]:
    rows = conn.execute("SELECT * FROM applications WHERE status = ? ORDER BY created_at DESC", (status,)).fetchall()
    return [_row_to_application(r) for r in rows]


def list_disbursement_queued_stale(conn: sqlite3.Connection, before_iso: str) -> list[dict]:
    """Applications in disbursement_queued with disbursement_queued_at < before_iso."""
    rows = conn.execute(
        """SELECT * FROM applications
           WHERE status = ? AND disbursement_queued_at IS NOT NULL AND disbursement_queued_at < ?""",
        (ApplicationStatus.DISBURSEMENT_QUEUED.value, before_iso),
    ).fetchall()
    return [_row_to_application(r) for r in rows]


def _row_to_application(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["bank_has_overdrafts"] = None if d["bank_has_overdrafts"] is None else bool(d["bank_has_overdrafts"])
    d["bank_has_consistent_deposits"] = None if d["bank_has_consistent_deposits"] is None else bool(d["bank_has_consistent_deposits"])
    return d


# --- Webhook events (idempotency) ---

def get_webhook_by_transaction_id(conn: sqlite3.Connection, transaction_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM webhook_events WHERE transaction_id = ?", (transaction_id,)).fetchone()
    if row is None:
        return None
    return dict(row)


def insert_webhook_event(
    conn: sqlite3.Connection,
    transaction_id: str,
    application_id: str,
    status: str,
    payload_timestamp: str | None,
) -> None:
    from datetime import datetime, timezone
    received_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO webhook_events (transaction_id, application_id, status, payload_timestamp, received_at)
           VALUES (?, ?, ?, ?, ?)""",
        (transaction_id, application_id, status, payload_timestamp, received_at),
    )
