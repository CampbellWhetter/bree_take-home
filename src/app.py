"""FastAPI app: submit, webhook disbursement, and application lookup."""

from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .config import get_duplicate_window_minutes
from .db import (
    get_connection,
    init_db,
    create_application,
    get_application,
    find_duplicate,
    update_application_status,
)
from .disbursement import handle_disbursement_webhook, check_disbursement_timeouts
from .errors import DuplicateApplicationError, InvalidStateTransitionError
from .scoring import score_application
from .scoring.models import Decision
from .state_machine import ApplicationStatus, validate_transition


app = FastAPI(title="Loan Application API", version="0.1.0")


# --- Request/response models ---

class SubmitApplicationBody(BaseModel):
    applicant_name: str
    email: str
    loan_amount: float
    stated_monthly_income: float
    employment_status: str
    documented_monthly_income: float | None = None
    bank_ending_balance: float | None = None
    bank_has_overdrafts: bool | None = None
    bank_has_consistent_deposits: bool | None = None
    monthly_withdrawals: float | None = None
    monthly_deposits: float | None = None


class WebhookDisbursementBody(BaseModel):
    application_id: str = Field(..., description="Application UUID")
    status: str = Field(..., description="'success' or 'failed'")
    transaction_id: str = Field(..., description="Idempotency key")
    timestamp: str = Field(..., description="ISO timestamp e.g. 2026-01-15T10:30:00Z")


# --- Submit: create + score + transition to approved/denied/flagged, then approved → disbursement_queued ---

@app.post("/applications")
def submit_application(body: SubmitApplicationBody):
    with get_connection() as conn:
        init_db(conn)
        window = get_duplicate_window_minutes()
        dup_id = find_duplicate(conn, body.email, body.loan_amount, window)
        if dup_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "DuplicateApplicationError",
                    "message": f"Duplicate application; same email and loan amount within {window} minutes",
                    "original_application_id": dup_id,
                },
            )

        payload = body.model_dump()
        score_result = score_application(payload)
        decision = score_result.decision

        # Map Decision -> ApplicationStatus
        if decision == Decision.AUTO_APPROVE:
            next_status = ApplicationStatus.APPROVED
        elif decision == Decision.FLAG_FOR_REVIEW:
            next_status = ApplicationStatus.FLAGGED_FOR_REVIEW
        else:
            next_status = ApplicationStatus.DENIED

        validate_transition(ApplicationStatus.SUBMITTED, ApplicationStatus.PROCESSING)
        validate_transition(ApplicationStatus.PROCESSING, next_status)
        if next_status == ApplicationStatus.APPROVED:
            validate_transition(ApplicationStatus.APPROVED, ApplicationStatus.DISBURSEMENT_QUEUED)

        now = datetime.now(timezone.utc).isoformat()
        final_status = (
            ApplicationStatus.DISBURSEMENT_QUEUED.value
            if next_status == ApplicationStatus.APPROVED
            else next_status.value
        )
        disbursement_queued_at = now if next_status == ApplicationStatus.APPROVED else None

        app_id = create_application(
            conn,
            applicant_name=body.applicant_name,
            email=body.email,
            loan_amount=body.loan_amount,
            stated_monthly_income=body.stated_monthly_income,
            employment_status=body.employment_status,
            documented_monthly_income=body.documented_monthly_income,
            bank_ending_balance=body.bank_ending_balance,
            bank_has_overdrafts=body.bank_has_overdrafts,
            bank_has_consistent_deposits=body.bank_has_consistent_deposits,
            monthly_withdrawals=body.monthly_withdrawals,
            monthly_deposits=body.monthly_deposits,
            status=final_status,
            score=score_result.total_score,
            decision=decision.value,
            score_breakdown_json=__breakdown_to_json(score_result),
            disbursement_queued_at=disbursement_queued_at,
        )

    return {
        "id": app_id,
        "status": final_status,
        "score": score_result.total_score,
        "decision": decision.value,
    }


def __breakdown_to_json(score_result):
    import json
    return json.dumps([
        {"factor_name": b.factor_name, "raw_score": b.raw_score, "weight": b.weight, "weighted_score": b.weighted_score}
        for b in score_result.breakdown
    ])


# --- Webhook: idempotent by transaction_id ---

@app.post("/webhook/disbursement")
def webhook_disbursement(body: WebhookDisbursementBody):
    try:
        result = handle_disbursement_webhook(
            application_id=body.application_id,
            status=body.status,
            transaction_id=body.transaction_id,
            timestamp=body.timestamp,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "ValueError", "message": str(e)})
    except InvalidStateTransitionError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "InvalidStateTransitionError",
                "current_state": e.current_state,
                "requested_state": e.requested_state,
                "allowed_next_states": e.allowed_next_states,
            },
        )


# --- Get application ---

@app.get("/applications/{application_id}")
def get_app(application_id: str):
    with get_connection() as conn:
        init_db(conn)
        app = get_application(conn, application_id)
    if not app:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return app


# --- Timeout escalation (call from cron or manually) ---

@app.post("/internal/check-disbursement-timeouts")
def run_disbursement_timeout_check():
    result = check_disbursement_timeouts()
    return {"transitioned": result}
