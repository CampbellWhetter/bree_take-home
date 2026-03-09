"""Data models for loan application scoring."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Decision(str, Enum):
    """Decision outcome from scoring."""

    AUTO_APPROVE = "auto_approve"
    FLAG_FOR_REVIEW = "flag_for_review"
    AUTO_DENY = "auto_deny"


@dataclass
class LoanApplication:
    """Structured application input for scoring."""

    applicant_name: str
    email: str
    loan_amount: float
    stated_monthly_income: float
    employment_status: str
    documented_monthly_income: Optional[float]
    bank_ending_balance: Optional[float]
    bank_has_overdrafts: Optional[bool]
    bank_has_consistent_deposits: Optional[bool]
    monthly_withdrawals: Optional[float]
    monthly_deposits: Optional[float]

    @classmethod
    def from_dict(cls, data: dict) -> "LoanApplication":
        return cls(
            applicant_name=str(data["applicant_name"]),
            email=str(data["email"]),
            loan_amount=float(data["loan_amount"]),
            stated_monthly_income=float(data["stated_monthly_income"]),
            employment_status=str(data["employment_status"]).strip().lower().replace("-", "_"),
            documented_monthly_income=_optional_float(data.get("documented_monthly_income")),
            bank_ending_balance=_optional_float(data.get("bank_ending_balance")),
            bank_has_overdrafts=_optional_bool(data.get("bank_has_overdrafts")),
            bank_has_consistent_deposits=_optional_bool(data.get("bank_has_consistent_deposits")),
            monthly_withdrawals=_optional_float(data.get("monthly_withdrawals")),
            monthly_deposits=_optional_float(data.get("monthly_deposits")),
        )


def _optional_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _optional_bool(v) -> Optional[bool]:
    if v is None:
        return None
    return bool(v)


@dataclass
class ScoreBreakdown:
    """Per-factor score contribution (0–100 raw, weighted contribution)."""

    factor_name: str
    raw_score: float  # 0–100
    weight: float
    weighted_score: float


@dataclass
class ScoreResult:
    """Full scoring result with decision and breakdown."""

    total_score: float
    decision: Decision
    breakdown: list[ScoreBreakdown]
