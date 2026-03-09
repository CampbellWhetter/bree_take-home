#!/usr/bin/env python3
"""
Webhook simulator: send success, failure, or replay to POST /webhook/disbursement.
Usage:
  python scripts/simulate_disbursement.py <base_url> <application_id> success
  python scripts/simulate_disbursement.py <base_url> <application_id> failure
  python scripts/simulate_disbursement.py <base_url> <application_id> replay [transaction_id]
For replay, if transaction_id is omitted we send a success first then replay the same payload.
"""

import json
import sys
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

def main():
    if len(sys.argv) < 4:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(1)
    base_url = sys.argv[1].rstrip("/")
    application_id = sys.argv[2]
    mode = sys.argv[3].lower()
    replay_txn = sys.argv[4] if len(sys.argv) > 4 else None

    url = f"{base_url}/webhook/disbursement"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if mode == "success":
        payload = {
            "application_id": application_id,
            "status": "success",
            "transaction_id": f"txn_demo_{application_id[:8]}_success",
            "timestamp": now,
        }
        send(url, payload)
    elif mode == "failure":
        payload = {
            "application_id": application_id,
            "status": "failed",
            "transaction_id": f"txn_demo_{application_id[:8]}_fail",
            "timestamp": now,
        }
        send(url, payload)
    elif mode == "replay":
        if replay_txn:
            payload = {
                "application_id": application_id,
                "status": "success",
                "transaction_id": replay_txn,
                "timestamp": now,
            }
            send(url, payload)
        else:
            txn = f"txn_demo_{application_id[:8]}_replay"
            payload = {
                "application_id": application_id,
                "status": "success",
                "transaction_id": txn,
                "timestamp": now,
            }
            print("First request (process):", file=sys.stderr)
            send(url, payload)
            print("\nReplay (same transaction_id, expect 200 and no state change):", file=sys.stderr)
            send(url, payload)
    else:
        print(f"Unknown mode: {mode}. Use success, failure, or replay.", file=sys.stderr)
        sys.exit(1)


def send(url: str, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=10) as resp:
            body = resp.read().decode()
            print(f"HTTP {resp.status}")
            try:
                print(json.dumps(json.loads(body), indent=2))
            except Exception:
                print(body)
    except HTTPError as e:
        print(e.code, e.reason, file=sys.stderr)
        print(e.read().decode(), file=sys.stderr)
        sys.exit(1)
    except URLError as e:
        print("Request failed:", e.reason, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
