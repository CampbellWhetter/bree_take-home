# Loan Application Processor — Backend

Backend for the AI-powered loan application processor: scoring engine, state machine, and disbursement flow.

## Setup

```bash
pip install -r requirements.txt
```

## Step 1: Scoring Engine

Score a loan application from JSON (stdin or file):

```bash
echo '{"applicant_name": "Jane Doe", "email": "jane@example.com", "loan_amount": 1500, "stated_monthly_income": 5000, "employment_status": "employed", "documented_monthly_income": 4800, "bank_ending_balance": 3200, "bank_has_overdrafts": false, "bank_has_consistent_deposits": true, "monthly_withdrawals": 1200, "monthly_deposits": 4800}' | python run_scoring.py
```

Or with the test data file:

```bash
python run_scoring.py tests/sample_application.json
```

### Configuration

Weights and decision thresholds are in **`config/scoring.yaml`** (not hardcoded):

- Factor weights: income verification 30%, income level 25%, account stability 20%, employment 15%, debt-to-income 10%.
- Decision thresholds: score ≥ 75 → auto-approve; 50–74 → flag for review; &lt; 50 → auto-deny.
- **Income verification tolerance**: `income_tolerance: 0.10` — see below.

### Income verification tolerance (10%)

The spec says income verification uses a “10% tolerance” but does not say whether that is above stated income, below, or either direction.

**Interpretation used here:** **±10% in either direction.**  
Documented monthly income is accepted if it is within 10% of stated income (i.e. ratio `documented / stated` in `[0.9, 1.1]`). So for stated $5,000, documented between $4,500 and $5,500 passes.

- **Why ±10%:** Common in lending for rounding, pay stub vs. annual salary, and minor timing differences. One-sided tolerance (e.g. only “documented ≥ 90% of stated”) would allow overstated income with no doc check; the other way would be overly strict for small under-statements.
- Documented in config as `income_tolerance: 0.10`; implementation treats it as symmetric.

### Test scenarios

Run the spec’s scoring scenarios (1–6):

```bash
python tests/test_scoring_engine.py
```

| # | Applicant   | Expected        |
|---|-------------|-----------------|
| 1 | Jane Doe    | Auto-approve    |
| 2 | Bob Smith   | Auto-deny       |
| 3 | Bob Smith   | Flag for review |
| 4 | Jane Doe    | Flag for review |
| 5 | Carol Tester (no docs) | Flag for review |
| 6 | Dave Liar   | Auto-deny       |

Scenarios 7 (duplicate submission) and 8 (webhook replay) are covered by the application/orchestration layer (Step 2+).

## Step 2: Application State Machine

The lifecycle is enforced by an explicit transition table; every transition is validated before persistence.

### States

- `submitted` → `processing` → `approved` | `denied` | `flagged_for_review`
- `approved` / `partially_approved` → `disbursement_queued` → `disbursed` | `disbursement_failed`
- `disbursement_failed` → `disbursement_queued` (retry)
- `flagged_for_review` → `approved` | `denied` | `partially_approved` (manual review)

Terminal states: `denied`, `disbursed`.

### Usage

All state changes go through `validate_transition(current, target)`. Invalid transitions raise `InvalidStateTransitionError` with `current_state`, `requested_state`, and `allowed_next_states` (for structured API responses).

```python
from src.state_machine import ApplicationStatus, validate_transition, get_allowed_transitions
from src.errors import InvalidStateTransitionError

validate_transition(ApplicationStatus.SUBMITTED, ApplicationStatus.PROCESSING)  # ok
validate_transition(ApplicationStatus.DENIED, ApplicationStatus.PROCESSING)    # raises InvalidStateTransitionError
```

### Migration: `partially_approved`

The table includes `partially_approved`: an admin can approve a reduced loan amount from `flagged_for_review`. Transition table lives in `src/state_machine/transitions.py`; adding the state and edges required no change to existing applications.

### Tests

```bash
python -m pytest tests/test_state_machine.py -v
```

---

*Webhook flow and admin endpoints to be added in subsequent steps.*
