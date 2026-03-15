"""
Track applied jobs to CSV or JSON file.
"""
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _ensure_file_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_existing_tracking(file_path: str, fmt: str) -> list[dict[str, Any]]:
    """Load existing applications so we don't duplicate and can append."""
    path = Path(file_path)
    if not path.exists():
        return []
    try:
        if fmt == "csv":
            with open(path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                return list(reader)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, csv.Error):
        return []


def record_application(
    file_path: str,
    fmt: str,
    job_title: str,
    company_name: str,
    job_url: str,
    existing: list[dict[str, Any]] | None = None,
) -> None:
    """Append one application to the tracking file."""
    path = Path(file_path)
    _ensure_file_dir(path)
    date_applied = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    row = {
        "job_title": job_title,
        "company_name": company_name,
        "job_url": job_url,
        "date_applied": date_applied,
    }

    if fmt == "csv":
        file_exists = path.exists()
        with open(path, "a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["job_title", "company_name", "job_url", "date_applied"])
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
        return

    # JSON
    records = existing if existing is not None else load_existing_tracking(file_path, "json")
    records.append(row)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)


def already_applied(file_path: str, fmt: str, job_url: str) -> bool:
    """Check if we already have this job URL in the tracking file."""
    records = load_existing_tracking(file_path, fmt)
    return any(r.get("job_url") == job_url for r in records)
