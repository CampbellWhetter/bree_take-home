"""Typed errors for the loan application backend (no string throws)."""


class InvalidStateTransitionError(Exception):
    """Raised when an application transition is not allowed by the state machine."""

    def __init__(self, current_state: str, requested_state: str, allowed_next_states: list[str]):
        self.current_state = current_state
        self.requested_state = requested_state
        self.allowed_next_states = allowed_next_states
        super().__init__(
            f"Invalid transition from {current_state!r} to {requested_state!r}. "
            f"Allowed: {allowed_next_states}"
        )


class DuplicateApplicationError(Exception):
    """Raised when the same email + loan amount was submitted within the duplicate window."""

    def __init__(self, original_application_id: str, message: str | None = None):
        self.original_application_id = original_application_id
        super().__init__(message or f"Duplicate application; see original id: {original_application_id}")


class WebhookReplayError(Exception):
    """Raised when webhook handling detects an unexpected replay (optional; idempotent flow may not raise)."""

    def __init__(self, transaction_id: str, message: str | None = None):
        self.transaction_id = transaction_id
        super().__init__(message or f"Webhook replay: transaction_id={transaction_id!r}")


class ApplicationNotFoundError(Exception):
    """Raised when an application id does not exist."""

    def __init__(self, application_id: str, message: str | None = None):
        self.application_id = application_id
        super().__init__(message or f"Application not found: {application_id!r}")


class InvalidDisbursementStatusError(Exception):
    """Raised when webhook disbursement status is not 'success' or 'failed'."""

    def __init__(self, status: str, message: str | None = None):
        self.status = status
        super().__init__(message or f"Invalid disbursement status: {status!r}")


class InvalidReviewActionError(Exception):
    """Raised when admin review action is not approve, deny, or partially_approve."""

    def __init__(self, action: str, message: str | None = None):
        self.action = action
        super().__init__(message or f"Invalid review action: {action!r}")


class MissingApprovedLoanAmountError(Exception):
    """Raised when partially_approve is used without approved_loan_amount > 0."""

    def __init__(self, message: str | None = None):
        super().__init__(message or "partially_approve requires approved_loan_amount > 0")


class InvalidApplicationStateError(Exception):
    """Raised when an application has invalid or missing status (e.g. not a valid ApplicationStatus enum)."""

    def __init__(self, application_id: str, reason: str | None = None):
        self.application_id = application_id
        self.reason = reason
        super().__init__(reason or f"Application {application_id!r} has invalid or missing status")
