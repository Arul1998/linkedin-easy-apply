"""Persist LinkedIn session cookies between runs."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("linkedin_easy_apply.session")

SESSION_DIR = Path(__file__).parent / ".linkedin_session"
COOKIES_FILE = SESSION_DIR / "cookies.json"


def _ensure_session_dir() -> None:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)


def save_cookies(driver) -> None:
    """Save browser cookies after a successful login."""
    try:
        _ensure_session_dir()
        cookies = driver.get_cookies()
        with open(COOKIES_FILE, "w", encoding="utf-8") as f:
            json.dump(cookies, f, indent=2)
        logger.info("Saved LinkedIn session to %s", COOKIES_FILE)
    except Exception:
        logger.warning("Could not save session cookies.", exc_info=True)


def clear_session() -> None:
    """Remove saved session cookies."""
    if COOKIES_FILE.exists():
        COOKIES_FILE.unlink()
        logger.info("Cleared saved LinkedIn session.")


def load_cookies(driver) -> bool:
    """
    Load saved cookies and verify the session is still valid.
    Returns True if the user appears logged in.
    """
    if not COOKIES_FILE.exists():
        return False
    try:
        with open(COOKIES_FILE, "r", encoding="utf-8") as f:
            cookies: list[dict[str, Any]] = json.load(f)
        if not cookies:
            return False

        driver.get("https://www.linkedin.com/")
        for cookie in cookies:
            cookie = dict(cookie)
            cookie.pop("sameSite", None)
            if cookie.get("domain", "").startswith("."):
                cookie["domain"] = cookie["domain"].lstrip(".")
            try:
                driver.add_cookie(cookie)
            except Exception:
                logger.debug("Skipped cookie: %s", cookie.get("name"), exc_info=True)

        driver.get("https://www.linkedin.com/feed/")
        current = driver.current_url.lower()
        if "login" in current or "checkpoint" in current or "challenge" in current:
            logger.info("Saved session is no longer valid.")
            return False
        logger.info("Reused saved LinkedIn session.")
        return True
    except Exception:
        logger.warning("Could not restore session cookies.", exc_info=True)
        return False
