"""State machine: valid transitions succeed, invalid raise InvalidStateTransitionError."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from src.state_machine import ApplicationStatus, validate_transition, get_allowed_transitions
from src.errors import InvalidStateTransitionError


# Valid transitions from the spec
@pytest.mark.parametrize(
    "current,target",
    [
        (ApplicationStatus.SUBMITTED, ApplicationStatus.PROCESSING),
        (ApplicationStatus.PROCESSING, ApplicationStatus.APPROVED),
        (ApplicationStatus.PROCESSING, ApplicationStatus.DENIED),
        (ApplicationStatus.PROCESSING, ApplicationStatus.FLAGGED_FOR_REVIEW),
        (ApplicationStatus.APPROVED, ApplicationStatus.DISBURSEMENT_QUEUED),
        (ApplicationStatus.DISBURSEMENT_QUEUED, ApplicationStatus.DISBURSED),
        (ApplicationStatus.DISBURSEMENT_QUEUED, ApplicationStatus.DISBURSEMENT_FAILED),
        (ApplicationStatus.DISBURSEMENT_FAILED, ApplicationStatus.DISBURSEMENT_QUEUED),
        (ApplicationStatus.DISBURSEMENT_QUEUED, ApplicationStatus.FLAGGED_FOR_REVIEW),  # timeout escalation
        (ApplicationStatus.FLAGGED_FOR_REVIEW, ApplicationStatus.APPROVED),
        (ApplicationStatus.FLAGGED_FOR_REVIEW, ApplicationStatus.DENIED),
        (ApplicationStatus.FLAGGED_FOR_REVIEW, ApplicationStatus.PARTIALLY_APPROVED),
        (ApplicationStatus.PARTIALLY_APPROVED, ApplicationStatus.DISBURSEMENT_QUEUED),
    ],
)
def test_valid_transitions(current: ApplicationStatus, target: ApplicationStatus) -> None:
    validate_transition(current, target)


# Invalid: denied -> processing (spec says show this in Loom)
@pytest.mark.parametrize(
    "current,target",
    [
        (ApplicationStatus.DENIED, ApplicationStatus.PROCESSING),
        (ApplicationStatus.DENIED, ApplicationStatus.APPROVED),
        (ApplicationStatus.APPROVED, ApplicationStatus.DENIED),
        (ApplicationStatus.SUBMITTED, ApplicationStatus.APPROVED),
        (ApplicationStatus.PROCESSING, ApplicationStatus.SUBMITTED),
        (ApplicationStatus.DISBURSED, ApplicationStatus.DISBURSEMENT_QUEUED),
    ],
)
def test_invalid_transitions_raise(current: ApplicationStatus, target: ApplicationStatus) -> None:
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        validate_transition(current, target)
    err = exc_info.value
    assert err.current_state == current.value
    assert err.requested_state == target.value
    assert err.allowed_next_states == [s.value for s in get_allowed_transitions(current)]


def test_denied_has_no_allowed_transitions() -> None:
    allowed = get_allowed_transitions(ApplicationStatus.DENIED)
    assert allowed == []


def test_partially_approved_to_disbursement_queued() -> None:
    """Mid-spec migration: partially_approved behaves like approved for disbursement."""
    validate_transition(ApplicationStatus.PARTIALLY_APPROVED, ApplicationStatus.DISBURSEMENT_QUEUED)
