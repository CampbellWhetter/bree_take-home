"""FastAPI app: submit, webhook disbursement, application lookup, and admin."""

import json
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Path, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field

# UUID pattern so GET /admin/applications (list) is not matched by /admin/applications/{application_id}
UUID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"

from .config import get_admin_password, get_admin_username, get_duplicate_window_minutes
from .db import (
    get_connection,
    init_db,
    create_application,
    get_application,
    find_duplicate,
    list_applications,
    update_application_status,
    update_application_review,
)
from .disbursement import handle_disbursement_webhook, check_disbursement_timeouts
from .errors import (
    ApplicationNotFoundError,
    DuplicateApplicationError,
    InvalidApplicationStateError,
    InvalidDisbursementStatusError,
    InvalidReviewActionError,
    InvalidStateTransitionError,
    MissingApprovedLoanAmountError,
    WebhookReplayError,
)
from .scoring import score_application
from .scoring.models import Decision
from .state_machine import ApplicationStatus, validate_transition


app = FastAPI(title="Loan Application API", version="0.1.0")


# --- Typed error → HTTP (spec: no string throws) ---

@app.exception_handler(InvalidStateTransitionError)
def handle_invalid_state_transition(request, exc: InvalidStateTransitionError):
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "detail": {
                "error": "InvalidStateTransitionError",
                "current_state": exc.current_state,
                "requested_state": exc.requested_state,
                "allowed_next_states": exc.allowed_next_states,
            }
        },
    )


@app.exception_handler(DuplicateApplicationError)
def handle_duplicate_application(request, exc: DuplicateApplicationError):
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "detail": {
                "error": "DuplicateApplicationError",
                "message": str(exc),
                "original_application_id": exc.original_application_id,
            }
        },
    )


@app.exception_handler(WebhookReplayError)
def handle_webhook_replay(request, exc: WebhookReplayError):
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "detail": {
                "error": "WebhookReplayError",
                "message": str(exc),
                "transaction_id": exc.transaction_id,
            }
        },
    )


@app.exception_handler(ApplicationNotFoundError)
def handle_application_not_found(request, exc: ApplicationNotFoundError):
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "detail": {
                "error": "ApplicationNotFoundError",
                "message": str(exc),
                "application_id": exc.application_id,
            }
        },
    )


@app.exception_handler(InvalidDisbursementStatusError)
def handle_invalid_disbursement_status(request, exc: InvalidDisbursementStatusError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "detail": {
                "error": "InvalidDisbursementStatusError",
                "message": str(exc),
                "status": exc.status,
            }
        },
    )


@app.exception_handler(InvalidReviewActionError)
def handle_invalid_review_action(request, exc: InvalidReviewActionError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "detail": {
                "error": "InvalidReviewActionError",
                "message": str(exc),
                "action": exc.action,
            }
        },
    )


@app.exception_handler(MissingApprovedLoanAmountError)
def handle_missing_approved_loan_amount(request, exc: MissingApprovedLoanAmountError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "detail": {
                "error": "MissingApprovedLoanAmountError",
                "message": str(exc),
            }
        },
    )


@app.exception_handler(InvalidApplicationStateError)
def handle_invalid_application_state(request, exc: InvalidApplicationStateError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "detail": {
                "error": "InvalidApplicationStateError",
                "message": str(exc),
                "application_id": exc.application_id,
                "reason": exc.reason,
            }
        },
    )


def _application_for_response(app: dict) -> dict:
    """Replace score_breakdown_json string with parsed score_breakdown; do not include the raw string in response."""
    out = {k: v for k, v in app.items() if k != "score_breakdown_json"}
    if app.get("score_breakdown_json"):
        out["score_breakdown"] = json.loads(app["score_breakdown_json"])
    return out


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


class ReviewBody(BaseModel):
    action: str = Field(..., description="approve | deny | partially_approve")
    note: str | None = Field(None, description="Reviewer note")
    approved_loan_amount: float | None = Field(None, description="Required for partially_approve")


security = HTTPBasic()


def verify_admin(credentials: HTTPBasicCredentials = Depends(security)) -> None:
    if credentials.username != get_admin_username() or credentials.password != get_admin_password():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


# --- Submit: create + score + transition to approved/denied/flagged, then approved → disbursement_queued ---

@app.post("/applications")
def submit_application(body: SubmitApplicationBody):
    with get_connection() as conn:
        init_db(conn)
        window = get_duplicate_window_minutes()
        dup_id = find_duplicate(conn, body.email, body.loan_amount, window)
        if dup_id:
            raise DuplicateApplicationError(dup_id)

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
    return json.dumps([
        {"factor_name": b.factor_name, "raw_score": b.raw_score, "weight": b.weight, "weighted_score": b.weighted_score}
        for b in score_result.breakdown
    ])


# --- Webhook: idempotent by transaction_id ---

@app.post("/webhook/disbursement")
def webhook_disbursement(body: WebhookDisbursementBody):
    return handle_disbursement_webhook(
        application_id=body.application_id,
        status=body.status,
        transaction_id=body.transaction_id,
        timestamp=body.timestamp,
    )


# --- Get application ---

@app.get("/applications/{application_id}")
def get_app(application_id: str):
    with get_connection() as conn:
        init_db(conn)
        app = get_application(conn, application_id)
    if not app:
        raise ApplicationNotFoundError(application_id)
    return _application_for_response(app)


# --- Timeout escalation (call from cron or manually) ---

@app.post("/internal/check-disbursement-timeouts")
def run_disbursement_timeout_check():
    result = check_disbursement_timeouts()
    return {"transitioned": result}


# --- Admin (Basic auth) ---

@app.get("/admin/applications")
def admin_list_applications(
    status: str | None = None,
    _: None = Depends(verify_admin),
):
    """List applications with optional filter by status (e.g. status=flagged_for_review)."""
    with get_connection() as conn:
        init_db(conn)
        apps = list_applications(conn, status=status)
    return {"applications": [_application_for_response(a) for a in apps], "count": len(apps)}


@app.get("/admin/applications/{application_id}")
def admin_get_application(
    application_id: str = Path(..., pattern=UUID_PATTERN),
    _: None = Depends(verify_admin),
):
    """Full detail including score breakdown."""
    with get_connection() as conn:
        init_db(conn)
        app = get_application(conn, application_id)
    if not app:
        raise ApplicationNotFoundError(application_id)
    return _application_for_response(app)


@app.post("/admin/applications/{application_id}/review")
def admin_review_application(
    application_id: str = Path(..., pattern=UUID_PATTERN),
    body: ReviewBody = ...,
    _: None = Depends(verify_admin),
):
    """Approve, deny, or partially_approve (with approved_loan_amount) a flagged application. Optional note."""
    if body.action not in ("approve", "deny", "partially_approve"):
        raise InvalidReviewActionError(body.action)
    if body.action == "partially_approve" and (body.approved_loan_amount is None or body.approved_loan_amount <= 0):
        raise MissingApprovedLoanAmountError()

    try:
        with get_connection() as conn:
            init_db(conn)
            app = get_application(conn, application_id)
            if not app:
                raise ApplicationNotFoundError(application_id)

            try:
                current = ApplicationStatus(app["status"])
            except (ValueError, KeyError) as e:
                raise InvalidApplicationStateError(application_id, reason=str(e))

            if body.action == "approve":
                target = ApplicationStatus.APPROVED
            elif body.action == "deny":
                target = ApplicationStatus.DENIED
            else:
                target = ApplicationStatus.PARTIALLY_APPROVED

            validate_transition(current, target)

            if target == ApplicationStatus.PARTIALLY_APPROVED:
                update_application_review(
                    conn,
                    application_id,
                    target.value,
                    approved_loan_amount=body.approved_loan_amount,
                    review_note=body.note,
                )
            else:
                update_application_review(
                    conn,
                    application_id,
                    target.value,
                    review_note=body.note,
                )

            if target == ApplicationStatus.APPROVED:
                validate_transition(ApplicationStatus.APPROVED, ApplicationStatus.DISBURSEMENT_QUEUED)
                now = datetime.now(timezone.utc).isoformat()
                update_application_status(
                    conn,
                    application_id,
                    ApplicationStatus.DISBURSEMENT_QUEUED.value,
                    disbursement_queued_at=now,
                )

        out = {
            "id": application_id,
            "status": ApplicationStatus.DISBURSEMENT_QUEUED.value if target == ApplicationStatus.APPROVED else target.value,
            "action": body.action,
            "note": body.note,
        }
        if body.action == "partially_approve":
            out["approved_loan_amount"] = body.approved_loan_amount
        return out
    except HTTPException:
        raise
    except (ApplicationNotFoundError, InvalidApplicationStateError, InvalidStateTransitionError):
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": type(e).__name__, "message": str(e)},
        )
