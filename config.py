"""
Load configuration from environment variables and optional config file.
No passwords or secrets in config files; credentials come from env only.
"""
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv

load_dotenv()

# Defaults
DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.json"
DEFAULT_DELAY_ACTIONS = 2
DEFAULT_DELAY_APPLICATIONS = 30
DEFAULT_TRACKING_FILE = "applications.json"
DEFAULT_TRACKING_FORMAT = "json"


@dataclass(slots=True)
class SavedAnswers:
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    phone_country_code: str = ""
    city: str = ""
    cover_letter: str = ""
    salary: str = ""
    sponsorship: str = "No"
    start_date: str = "Immediately"


@dataclass(slots=True)
class AppConfig:
    email: str
    password: str
    keywords: str
    location: str
    work_type: str
    job_type: str
    date_posted: str
    experience_level: str
    few_applicants: bool
    geo_id: str
    delay_between_actions_sec: float
    delay_between_applications_sec: float
    resume_path: str
    tracking_file: str
    tracking_format: str
    max_applications: int
    saved_answers: SavedAnswers = field(default_factory=SavedAnswers)


def _load_json_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _bool_env(name: str, default: bool) -> bool:
    val = os.environ.get(name, "").strip().lower()
    if not val:
        return bool(default)
    return val in ("1", "true", "yes", "on")


def _int_env(name: str, default: int) -> int:
    val = os.environ.get(name, "").strip()
    if not val:
        return int(default) if default is not None else 0
    try:
        return int(val)
    except ValueError:
        return int(default) if default is not None else 0


def get_config() -> AppConfig:
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
    saved_cfg = file_cfg.get("saved_answers", {})

    saved = SavedAnswers(
        first_name=saved_cfg.get("first_name", ""),
        last_name=saved_cfg.get("last_name", ""),
        email=saved_cfg.get("email", ""),
        phone=saved_cfg.get("phone", ""),
        phone_country_code=saved_cfg.get("phone_country_code", ""),
        city=saved_cfg.get("city", ""),
        cover_letter=saved_cfg.get("cover_letter", ""),
        salary=saved_cfg.get("salary", ""),
        sponsorship=saved_cfg.get("sponsorship", "No"),
        start_date=saved_cfg.get("start_date", "Immediately"),
    )

    return AppConfig(
        email=email,
        password=password,
        keywords=os.environ.get("LINKEDIN_KEYWORDS", search.get("keywords", "frontend developer")),
        location=os.environ.get("LINKEDIN_LOCATION", search.get("location", "United Kingdom")),
        work_type=os.environ.get("LINKEDIN_WORK_TYPE", search.get("work_type", search.get("remote", ""))),
        job_type=os.environ.get("LINKEDIN_JOB_TYPE", search.get("job_type", "")),
        date_posted=os.environ.get("LINKEDIN_DATE_POSTED", search.get("date_posted", "")),
        experience_level=os.environ.get("LINKEDIN_EXPERIENCE_LEVEL", search.get("experience_level", "")),
        few_applicants=_bool_env("LINKEDIN_FEW_APPLICANTS", search.get("few_applicants", False)),
        geo_id=os.environ.get("LINKEDIN_GEO_ID", search.get("geo_id", "")),
        delay_between_actions_sec=float(
            os.environ.get("DELAY_ACTIONS_SEC", rate.get("delay_between_actions_sec", DEFAULT_DELAY_ACTIONS))
        ),
        delay_between_applications_sec=float(
            os.environ.get("DELAY_APPLICATIONS_SEC", rate.get("delay_between_applications_sec", DEFAULT_DELAY_APPLICATIONS))
        ),
        resume_path=os.environ.get("RESUME_PATH", file_cfg.get("resume_path", "")),
        tracking_file=os.environ.get("TRACKING_FILE", tracking.get("output_file", DEFAULT_TRACKING_FILE)),
        tracking_format=os.environ.get("TRACKING_FORMAT", tracking.get("format", DEFAULT_TRACKING_FORMAT)).lower(),
        max_applications=_int_env("MAX_APPLICATIONS", file_cfg.get("max_applications", 0)),
        saved_answers=saved,
    )
