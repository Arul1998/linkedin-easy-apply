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
    ensure_easy_apply_url,
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


def _scroll_job_list(driver):
    try:
        driver.execute_script(
            "var el = document.querySelector('.jobs-search-results-list') || document.querySelector('.scaffold-layout__list-container'); if(el) el.scrollBy(0, 220);"
        )
    except Exception:
        pass


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
            cfg.get("work_type", ""),
            cfg.get("job_type", ""),
            cfg.get("date_posted", ""),
            cfg.get("experience_level", ""),
            cfg.get("few_applicants", False),
            cfg.get("geo_id", ""),
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
        max_applications = cfg.get("max_applications") or 0
        last_processed_url = None

        while True:
            if max_applications > 0 and applied_count >= max_applications:
                print(f"Reached limit of {max_applications} applications.")
                break
            ensure_easy_apply_url(driver)
            cards = get_job_cards(driver)
            if not cards:
                time.sleep(3)
                cards = get_job_cards(driver)
            if not cards:
                time.sleep(2)
                cards = get_job_cards(driver)
            easy_apply_cards = [c for c in cards if job_has_easy_apply(c)]
            if not easy_apply_cards:
                easy_apply_cards = cards
            if not cards:
                print("No job cards found. Page may still be loading, or LinkedIn's layout changed.")
                break

            card = None
            job_url = None
            for c in cards:
                url = get_job_url_from_card(c)
                if not url:
                    continue
                if url == last_processed_url:
                    continue
                if already_applied(tracking_file, tracking_fmt, url):
                    skipped_count += 1
                    last_processed_url = url
                    break
                card = c
                job_url = url
                break
            if card is None:
                _scroll_job_list(driver)
                _scroll_job_list(driver)
                rate_limit_actions(cfg)
                continue

            try:
                last_processed_url = job_url
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
                    if status != "skipped":
                        print(f"Skipped: {title} @ {company} ({status})")
            except Exception as e:
                print(f"Error: {e}")
                rate_limit_actions(cfg)

            _scroll_job_list(driver)
            rate_limit_actions(cfg)

        print(f"Done. Applied: {applied_count}, Skipped: {skipped_count}. Tracking: {tracking_file}")
    finally:
        driver.quit()


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv
    main(dry_run=dry_run)
