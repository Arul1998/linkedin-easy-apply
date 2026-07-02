"""Structured status codes and user-friendly messages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


SKIP_REASON_MESSAGES: dict[str, str] = {
    "already_applied": "Already in your tracking file — skipped to avoid duplicate application",
    "skipped (no job link)": "Could not read the job link from the listing",
    "skipped (Apply button not found)": "No Easy Apply button on this job page",
    "skipped (multi-step)": "Application form has too many steps or custom screens",
    "skipped (no submit)": "Could not find a Submit button on the application form",
    "error": "Unexpected error while processing this job",
    "exception": "Script error while processing this job",
}

LOGIN_FAILURE_MESSAGES: dict[str, str] = {
    "invalid_credentials": "LinkedIn rejected the email or password. Check your .env file.",
    "challenge_required": "LinkedIn wants verification (CAPTCHA or 2FA). Complete it in the browser, then press Enter.",
    "form_not_found": "Could not find the login form. LinkedIn may have changed their page layout.",
    "session_expired": "Saved session expired. Logging in again.",
    "unknown": "Login failed for an unknown reason. Run with --debug for details.",
}


def humanize_skip_reason(status: str) -> str:
    """Return a plain-English explanation for a skip/apply status."""
    if status in SKIP_REASON_MESSAGES:
        return SKIP_REASON_MESSAGES[status]
    if status.startswith("skipped"):
        return status.replace("skipped", "Skipped", 1).replace("(", " (").replace("_", " ")
    if status == "applied":
        return "Application submitted successfully"
    return status.replace("_", " ")


@dataclass(slots=True)
class LoginResult:
    success: bool
    reason: str = ""
    message: str = ""

    @classmethod
    def ok(cls) -> "LoginResult":
        return cls(success=True, reason="ok", message="Logged in successfully")

    @classmethod
    def fail(cls, reason: str, message: Optional[str] = None) -> "LoginResult":
        return cls(
            success=False,
            reason=reason,
            message=message or LOGIN_FAILURE_MESSAGES.get(reason, LOGIN_FAILURE_MESSAGES["unknown"]),
        )
