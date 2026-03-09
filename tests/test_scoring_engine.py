"""Test scoring engine against the spec's test scenarios (1–6; 7–8 are duplicate/webhook)."""

import json
import sys
from pathlib import Path

# Allow importing from project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.scoring import score_application
from src.scoring.models import Decision


def load_scenarios():
    path = Path(__file__).parent / "test_data.json"
    with open(path) as f:
        return json.load(f)


def test_all_scenarios():
    scenarios = load_scenarios()
    for s in scenarios:
        result = score_application(s["input"])
        expected = Decision(s["expected_decision"])
        assert result.decision == expected, (
            f"Scenario {s['scenario']}: expected {expected.value}, got {result.decision.value} "
            f"(score={result.total_score:.1f})"
        )
        print(f"Scenario {s['scenario']}: {result.decision.value} (score={result.total_score:.1f}) ✓")


if __name__ == "__main__":
    test_all_scenarios()
    print("All scenario tests passed.")
