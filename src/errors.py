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
