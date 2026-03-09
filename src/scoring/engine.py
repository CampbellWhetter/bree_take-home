"""Scoring engine: computes weighted score and decision from config and application data."""

from pathlib import Path

import yaml

from .models import (
    Decision,
    LoanApplication,
    ScoreBreakdown,
    ScoreResult,
)


def _load_config(config_path: Path | None = None) -> dict:
    if config_path is None:
        config_path = Path(__file__).resolve().parents[2] / "config" / "scoring.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def _income_verification_score(app: LoanApplication, factor_cfg: dict) -> ScoreBreakdown:
    """Documented income must match stated income within tolerance (e.g. ±10%)."""
    weight = factor_cfg["weight"]
    tolerance = factor_cfg["income_tolerance"]
    if app.documented_monthly_income is None:
        return ScoreBreakdown("income_verification", 0.0, weight, 0.0)
    stated = app.stated_monthly_income
    doc = app.documented_monthly_income
    if stated <= 0:
        return ScoreBreakdown("income_verification", 0.0, weight, 0.0)
    ratio = doc / stated
    # Within [1 - tolerance, 1 + tolerance] → 100
    if (1 - tolerance) <= ratio <= (1 + tolerance):
        raw = 100.0
    else:
        raw = 0.0
    return ScoreBreakdown("income_verification", raw, weight, raw * weight)


def _income_level_score(app: LoanApplication, factor_cfg: dict) -> ScoreBreakdown:
    """Monthly income >= multiple * loan amount. Use documented if available, else stated."""
    weight = factor_cfg["weight"]
    multiple = factor_cfg["income_to_loan_multiple"]
    income = app.documented_monthly_income if app.documented_monthly_income is not None else app.stated_monthly_income
    if income is None or app.loan_amount <= 0:
        return ScoreBreakdown("income_level", 0.0, weight, 0.0)
    if income >= multiple * app.loan_amount:
        raw = 100.0
    else:
        raw = 0.0
    return ScoreBreakdown("income_level", raw, weight, raw * weight)


def _account_stability_score(app: LoanApplication, factor_cfg: dict) -> ScoreBreakdown:
    """Positive ending balance, no overdrafts, consistent deposits. Null = fail that criterion."""
    weight = factor_cfg["weight"]
    balance_ok = app.bank_ending_balance is not None and app.bank_ending_balance > 0
    no_overdrafts = app.bank_has_overdrafts is not None and app.bank_has_overdrafts is False
    consistent = app.bank_has_consistent_deposits is not None and app.bank_has_consistent_deposits is True
    n = 3
    raw = 100.0 * (balance_ok + no_overdrafts + consistent) / n
    return ScoreBreakdown("account_stability", raw, weight, raw * weight)


def _employment_status_score(app: LoanApplication, factor_cfg: dict) -> ScoreBreakdown:
    """Employed > self-employed > unemployed."""
    weight = factor_cfg["weight"]
    scores = factor_cfg["scores"]
    key = app.employment_status.lower().replace("-", "_")
    raw = float(scores.get(key, scores.get("unemployed", 0)))
    return ScoreBreakdown("employment_status", raw, weight, raw * weight)


def _debt_to_income_score(app: LoanApplication, factor_cfg: dict) -> ScoreBreakdown:
    """Ratio of withdrawals to deposits; lower is better. Score 100 when ratio 0, 0 when ratio >= 1."""
    weight = factor_cfg["weight"]
    w = app.monthly_withdrawals
    d = app.monthly_deposits
    if d is None or d <= 0 or w is None:
        return ScoreBreakdown("debt_to_income", 0.0, weight, 0.0)
    ratio = min(w / d, 1.0)
    raw = 100.0 * (1.0 - ratio)
    return ScoreBreakdown("debt_to_income", raw, weight, raw * weight)


def score_application(
    application: LoanApplication | dict,
    config_path: Path | None = None,
) -> ScoreResult:
    """
    Score a loan application using the configured rubric and return total score,
    decision, and per-factor breakdown.
    """
    if isinstance(application, dict):
        application = LoanApplication.from_dict(application)
    config = _load_config(config_path)
    factors_cfg = config["scoring"]["factors"]
    thresholds = config["decision_thresholds"]

    breakdowns = [
        _income_verification_score(application, factors_cfg["income_verification"]),
        _income_level_score(application, factors_cfg["income_level"]),
        _account_stability_score(application, factors_cfg["account_stability"]),
        _employment_status_score(application, factors_cfg["employment_status"]),
        _debt_to_income_score(application, factors_cfg["debt_to_income"]),
    ]

    total = sum(b.weighted_score for b in breakdowns)
    auto_approve_min = thresholds["auto_approve_min"]
    manual_review_min = thresholds["manual_review_min"]

    if total >= auto_approve_min:
        decision = Decision.AUTO_APPROVE
    elif total >= manual_review_min:
        decision = Decision.FLAG_FOR_REVIEW
    else:
        decision = Decision.AUTO_DENY

    # No documentation → flag for review instead of auto-deny (spec scenario 5)
    if application.documented_monthly_income is None and decision == Decision.AUTO_DENY:
        decision = Decision.FLAG_FOR_REVIEW

    return ScoreResult(total_score=total, decision=decision, breakdown=breakdowns)
