#!/usr/bin/env python3
"""CLI to score a single loan application (JSON from stdin or file)."""

import json
import sys
from pathlib import Path

# Project root
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.scoring import score_application


def main():
    if len(sys.argv) > 1:
        with open(sys.argv[1]) as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)

    result = score_application(data)
    print(f"Score: {result.total_score:.1f}")
    print(f"Decision: {result.decision.value}")
    print("Breakdown:")
    for b in result.breakdown:
        print(f"  {b.factor_name}: raw={b.raw_score:.0f}, weighted={b.weighted_score:.1f}")


if __name__ == "__main__":
    main()
