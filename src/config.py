"""Load app config from config/app.yaml."""

import os
from pathlib import Path

import yaml


def _config_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "app.yaml"


def load_app_config() -> dict:
    with open(_config_path()) as f:
        return yaml.safe_load(f)


def get_disbursement_timeout_seconds() -> int:
    cfg = load_app_config()
    return int(cfg.get("disbursement", {}).get("timeout_seconds", 86400))


def get_duplicate_window_minutes() -> int:
    cfg = load_app_config()
    return int(cfg.get("duplicate_prevention", {}).get("window_minutes", 5))


def get_admin_username() -> str:
    cfg = load_app_config()
    return str(cfg.get("admin", {}).get("username", "admin"))


def get_admin_password() -> str:
    """Env LOANAPP_ADMIN_PASSWORD overrides config."""
    if os.environ.get("LOANAPP_ADMIN_PASSWORD"):
        return os.environ["LOANAPP_ADMIN_PASSWORD"]
    cfg = load_app_config()
    return str(cfg.get("admin", {}).get("password", "admin"))
