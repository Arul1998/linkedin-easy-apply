#!/usr/bin/env python3
"""
LinkedIn Easy Apply – standalone automation.
Run: set env vars (or .env), optionally copy config.example.json to config.json, then:
  python main.py
"""
import sys
import time

from config import get_config
from linkedin_automation import (
    get_driver,
    login,
    navigate_to_search,
    get_job_cards,
    job_has_easy_apply,
    get_job_url_from_card,
    apply_to_job,
)
from tracker import record_application, already_applied, load_existing_tracking


def rate_limit_actions(cfg):
    """Delay between general actions (clicks, page loads)."""
    time.sleep(cfg["delay_between_actions_sec"])


def rate_limit_after_application(cfg):
    """Delay after submitting an application."""
    time.sleep(cfg["delay_between_applications_sec"])


def main(dry_run: bool = False):
    cfg = get_config()
    if not cfg["email"] or not cfg["password"]:
        print("Set LINKEDIN_EMAIL and LINKEDIN_PASSWORD in .env or environment.")
        sys.exit(1)

    tracking_file = cfg["tracking_file"]
    tracking_fmt = cfg["tracking_format"]
    if tracking_fmt not in ("json", "csv"):
        tracking_fmt = "json"

    driver = get_driver(headless=False)
    try:
        if not login(driver, cfg["email"], cfg["password"]):
            print("Login failed. Check credentials and try again.")
            sys.exit(1)
        rate_limit_actions(cfg)

        if not navigate_to_search(
            driver,
            cfg["keywords"],
            cfg["location"],
            cfg.get("remote", ""),
        ):
            print("Job search navigation failed.")
            sys.exit(1)
        rate_limit_actions(cfg)

        if dry_run:
            cards = get_job_cards(driver)
            easy_apply_cards = [c for c in cards if job_has_easy_apply(c)]
            print(f"Dry run: found {len(cards)} job cards, {len(easy_apply_cards)} with Easy Apply.")
            print("Login and search OK. Run without --dry-run to apply.")
            return

        existing = load_existing_tracking(tracking_file, tracking_fmt)
        applied_count = 0
        skipped_count = 0

        while True:
            cards = get_job_cards(driver)
            easy_apply_cards = [c for c in cards if job_has_easy_apply(c)]
            if not easy_apply_cards:
                print("No more Easy Apply jobs in view. Scroll the list or run again later.")
                break

            for card in easy_apply_cards:
                try:
                    job_url = None
                    job_url = get_job_url_from_card(card)
                    if not job_url:
                        continue
                    if already_applied(tracking_file, tracking_fmt, job_url):
                        skipped_count += 1
                        continue

                    rate_limit_actions(cfg)
                    title, company, url, status = apply_to_job(
                        driver,
                        card,
                        cfg["saved_answers"],
                        cfg.get("resume_path", ""),
                    )
                    if status == "applied":
                        record_application(
                            tracking_file,
                            tracking_fmt,
                            title,
                            company,
                            url,
                            existing=existing if tracking_fmt == "json" else None,
                        )
                        applied_count += 1
                        print(f"Applied: {title} @ {company}")
                        rate_limit_after_application(cfg)
                    else:
                        skipped_count += 1
                except Exception as e:
                    print(f"Error processing job: {e}")
                    rate_limit_actions(cfg)

            # Scroll job list to load more (optional: break after first page to avoid infinite loop)
            try:
                driver.execute_script(
                    "document.querySelector('.jobs-search-results-list')?.scrollBy(0, 400);"
                )
                rate_limit_actions(cfg)
            except Exception:
                break

        print(f"Done. Applied: {applied_count}, Skipped: {skipped_count}. Tracking: {tracking_file}")
    finally:
        driver.quit()


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv
    main(dry_run=dry_run)
