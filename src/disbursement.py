"""Disbursement webhook handling and timeout escalation."""

from datetime import datetime, timezone

import sqlite3

from .config import get_disbursement_timeout_seconds
from .db import (
    get_connection,
    get_application,
    get_webhook_by_transaction_id,
    insert_webhook_event,
    update_application_status,
    list_disbursement_queued_stale,
    init_db,
)
from .errors import InvalidStateTransitionError
from .state_machine import ApplicationStatus, validate_transition


def handle_disbursement_webhook(
    application_id: str,
    status: str,
    transaction_id: str,
    timestamp: str | None,
) -> dict:
    """
    Process POST /webhook/disbursement payload.
    Idempotent: same transaction_id twice → no state change, return 200 with already_processed.
    Returns dict with keys: processed (bool), application_id, new_status (if processed).
    """
    if status not in ("success", "failed"):
        raise ValueError(f"Invalid status: {status}")

    with get_connection() as conn:
        init_db(conn)
        existing = get_webhook_by_transaction_id(conn, transaction_id)
        if existing:
            return {
                "processed": False,
                "already_processed": True,
                "application_id": existing["application_id"],
                "transaction_id": transaction_id,
            }

        app = get_application(conn, application_id)
        if not app:
            raise ValueError(f"Application not found: {application_id}")

        current = ApplicationStatus(app["status"])
        target = ApplicationStatus.DISBURSED if status == "success" else ApplicationStatus.DISBURSEMENT_FAILED
        validate_transition(current, target)

        insert_webhook_event(conn, transaction_id, application_id, status, timestamp)
        update_application_status(conn, application_id, target.value)

    return {
        "processed": True,
        "already_processed": False,
        "application_id": application_id,
        "new_status": target.value,
        "transaction_id": transaction_id,
    }


def check_disbursement_timeouts() -> list[dict]:
    """
    Find applications in disbursement_queued past the configurable timeout,
    transition them to flagged_for_review. Returns list of {application_id, transitioned_at}.
    """
    timeout_sec = get_disbursement_timeout_seconds()
    cutoff = datetime.now(timezone.utc).timestamp() - timeout_sec
    cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()

    result = []
    with get_connection() as conn:
        init_db(conn)
        stale = list_disbursement_queued_stale(conn, cutoff_iso)
        for app in stale:
            try:
                validate_transition(
                    ApplicationStatus(app["status"]),
                    ApplicationStatus.FLAGGED_FOR_REVIEW,
                )
                update_application_status(conn, app["id"], ApplicationStatus.FLAGGED_FOR_REVIEW.value)
                result.append({"application_id": app["id"], "transitioned_at": cutoff_iso})
            except InvalidStateTransitionError:
                continue
    return result
