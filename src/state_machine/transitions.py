"""Explicit transition table and validation. All allowed (from, to) pairs in one place."""

from .states import ApplicationStatus
from ..errors import InvalidStateTransitionError

# Graph: from_state -> set of allowed to_states.
# Adding partially_approved: new state + new edges; existing apps unchanged.
TRANSITIONS: dict[ApplicationStatus, set[ApplicationStatus]] = {
    ApplicationStatus.SUBMITTED: {ApplicationStatus.PROCESSING},
    ApplicationStatus.PROCESSING: {
        ApplicationStatus.APPROVED,
        ApplicationStatus.DENIED,
        ApplicationStatus.FLAGGED_FOR_REVIEW,
    },
    ApplicationStatus.APPROVED: {ApplicationStatus.DISBURSEMENT_QUEUED},
    ApplicationStatus.DENIED: set(),  # terminal
    ApplicationStatus.FLAGGED_FOR_REVIEW: {
        ApplicationStatus.APPROVED,
        ApplicationStatus.DENIED,
        ApplicationStatus.PARTIALLY_APPROVED,
    },
    ApplicationStatus.PARTIALLY_APPROVED: {ApplicationStatus.DISBURSEMENT_QUEUED},
    ApplicationStatus.DISBURSEMENT_QUEUED: {
        ApplicationStatus.DISBURSED,
        ApplicationStatus.DISBURSEMENT_FAILED,
    },
    ApplicationStatus.DISBURSED: set(),  # terminal
    ApplicationStatus.DISBURSEMENT_FAILED: {ApplicationStatus.DISBURSEMENT_QUEUED},
}


def get_allowed_transitions(current: ApplicationStatus) -> list[ApplicationStatus]:
    """Return the list of states that are valid next states from current."""
    return sorted(TRANSITIONS.get(current, set()), key=lambda s: s.value)


def validate_transition(
    current: ApplicationStatus,
    target: ApplicationStatus,
) -> None:
    """
    Validate that transitioning from current to target is allowed.
    Raises InvalidStateTransitionError if not.
    Business guards (e.g. partially_approved requires approved_loan_amount) belong in the API layer.
    """
    allowed = TRANSITIONS.get(current, set())
    if target not in allowed:
        allowed_list = [s.value for s in get_allowed_transitions(current)]
        raise InvalidStateTransitionError(
            current_state=current.value,
            requested_state=target.value,
            allowed_next_states=allowed_list,
        )
