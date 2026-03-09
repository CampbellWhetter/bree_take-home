#!/usr/bin/env python3
"""Run the Loan Application API. Usage: python run_server.py (or: python -m uvicorn src.app:app --host 0.0.0.0 --port 8000)"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("src.app:app", host="0.0.0.0", port=8000, reload=False)
