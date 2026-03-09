"""Application lifecycle states. All states and terminal states in one place."""

from enum import Enum


class ApplicationStatus(str, Enum):
    """State of a loan application in the lifecycle."""

    SUBMITTED = "submitted"
    PROCESSING = "processing"
    APPROVED = "approved"
    DENIED = "denied"
    FLAGGED_FOR_REVIEW = "flagged_for_review"
    # Mid-spec migration: reduced loan amount approved by admin
    PARTIALLY_APPROVED = "partially_approved"
    DISBURSEMENT_QUEUED = "disbursement_queued"
    DISBURSED = "disbursed"
    DISBURSEMENT_FAILED = "disbursement_failed"
