"""
Load configuration from environment variables and optional config file.
No passwords or secrets in config files; credentials come from env only.
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Defaults
DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.json"
DEFAULT_DELAY_ACTIONS = 2
DEFAULT_DELAY_APPLICATIONS = 30
DEFAULT_TRACKING_FILE = "applications.json"
DEFAULT_TRACKING_FORMAT = "json"


def _load_json_config(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_config():
    """Build config from env and optional config file. Env overrides file."""
    config_file = os.environ.get("CONFIG_FILE", "").strip()
    config_path = Path(config_file).expanduser() if config_file else DEFAULT_CONFIG_PATH
    file_cfg = _load_json_config(config_path)

    # Credentials only from env
    email = os.environ.get("LINKEDIN_EMAIL", "").strip()
    password = os.environ.get("LINKEDIN_PASSWORD", "").strip()

    search = file_cfg.get("search", {})
    rate = file_cfg.get("rate_limiting", {})
    tracking = file_cfg.get("tracking", {})
    saved = file_cfg.get("saved_answers", {})

    return {
        "email": email,
        "password": password,
        "keywords": os.environ.get("LINKEDIN_KEYWORDS", search.get("keywords", "software engineer")),
        "location": os.environ.get("LINKEDIN_LOCATION", search.get("location", "United Kingdom")),
        "remote": os.environ.get("LINKEDIN_REMOTE", search.get("remote", "Remote")),
        "delay_between_actions_sec": float(
            os.environ.get("DELAY_ACTIONS_SEC", rate.get("delay_between_actions_sec", DEFAULT_DELAY_ACTIONS))
        ),
        "delay_between_applications_sec": float(
            os.environ.get("DELAY_APPLICATIONS_SEC", rate.get("delay_between_applications_sec", DEFAULT_DELAY_APPLICATIONS))
        ),
        "resume_path": os.environ.get("RESUME_PATH", file_cfg.get("resume_path", "")),
        "tracking_file": os.environ.get("TRACKING_FILE", tracking.get("output_file", DEFAULT_TRACKING_FILE)),
        "tracking_format": os.environ.get("TRACKING_FORMAT", tracking.get("format", DEFAULT_TRACKING_FORMAT)).lower(),
        "saved_answers": saved,
    }
