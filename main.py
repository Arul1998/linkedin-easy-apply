#!/usr/bin/env python3
"""
LinkedIn Easy Apply – standalone automation.
Run: set env vars (or .env), optionally copy config.example.json to config.json, then:
  python main.py
"""
import argparse
import logging
import sys
import time
from collections import Counter
from typing import Optional

from dataclasses import asdict

from config import AppConfig, get_config
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
from tracker import record_application, load_existing_tracking


logger = logging.getLogger("linkedin_easy_apply")


def _configure_logging() -> None:
    """Configure root logging for the CLI run."""
    if logging.getLogger().handlers:
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )


def rate_limit_actions(cfg: AppConfig) -> None:
    """Delay between general actions (clicks, page loads)."""
    time.sleep(cfg.delay_between_actions_sec)


def rate_limit_after_application(cfg: AppConfig) -> None:
    """Delay after submitting an application."""
    time.sleep(cfg.delay_between_applications_sec)


def _scroll_job_list(driver) -> None:
    try:
        driver.execute_script(
            "var el = document.querySelector('.jobs-search-results-list') || "
            "document.querySelector('.scaffold-layout__list-container'); "
            "if(el) el.scrollBy(0, 220);"
        )
    except Exception:
        logger.debug("Failed to scroll job list.", exc_info=True)


def main(dry_run: bool = False, cfg: Optional[AppConfig] = None) -> None:
    _configure_logging()
    if cfg is None:
        cfg = get_config()

    if not cfg.email or not cfg.password:
        logger.error("Set LINKEDIN_EMAIL and LINKEDIN_PASSWORD in .env or environment.")
        sys.exit(1)

    tracking_file = cfg.tracking_file
    tracking_fmt = cfg.tracking_format if cfg.tracking_format in ("json", "csv") else "json"

    logger.info(
        "Starting LinkedIn Easy Apply (dry_run=%s, max_applications=%s, tracking_file=%s, format=%s)",
        dry_run,
        cfg.max_applications or 0,
        tracking_file,
        tracking_fmt,
    )
    logger.info(
        "Search filters: keywords=%r, location=%r, work_type=%r, job_type=%r, date_posted=%r, "
        "experience_level=%r, few_applicants=%r, geo_id=%r",
        cfg.keywords,
        cfg.location,
        cfg.work_type,
        cfg.job_type,
        cfg.date_posted,
        cfg.experience_level,
        cfg.few_applicants,
        cfg.geo_id,
    )

    driver = get_driver(headless=False)
    try:
        if not login(driver, cfg.email, cfg.password):
            logger.error("Login failed. Check credentials and try again.")
            sys.exit(1)
        rate_limit_actions(cfg)

        if not navigate_to_search(
            driver,
            cfg.keywords,
            cfg.location,
            cfg.work_type,
            cfg.job_type,
            cfg.date_posted,
            cfg.experience_level,
            cfg.few_applicants,
            cfg.geo_id,
        ):
            logger.error("Job search navigation failed.")
            sys.exit(1)
        rate_limit_actions(cfg)

        cards = get_job_cards(driver)
        easy_apply_cards = [c for c in cards if job_has_easy_apply(c)]

        if dry_run:
            logger.info(
                "Dry run: found %d job cards, %d with Easy Apply.",
                len(cards),
                len(easy_apply_cards),
            )
            logger.info("Login and search OK. Run without --dry-run to apply.")
            return

        existing = load_existing_tracking(tracking_file, tracking_fmt)
        applied_urls: set[str] = {r.get("job_url", "") for r in existing}
        applied_count = 0
        skipped_count = 0
        skip_reasons: Counter[str] = Counter()
        max_applications = cfg.max_applications or 0
        last_processed_url: Optional[str] = None
        scroll_attempts = 0
        MAX_SCROLL_ATTEMPTS = 10

        while True:
            if max_applications > 0 and applied_count >= max_applications:
                logger.info("Reached limit of %d applications.", max_applications)
                break

            ensure_easy_apply_url(driver)
            cards = get_job_cards(driver)
            if not cards:
                time.sleep(3)
                cards = get_job_cards(driver)
            if not cards:
                time.sleep(2)
                cards = get_job_cards(driver)

            if not cards:
                logger.warning(
                    "No job cards found. Page may still be loading, or LinkedIn's layout changed."
                )
                break

            card = None
            job_url = None
            for c in cards:
                url = get_job_url_from_card(c)
                if not url:
                    continue
                if url == last_processed_url:
                    continue
                if url in applied_urls:
                    skipped_count += 1
                    skip_reasons["already_applied"] += 1
                    last_processed_url = url
                    logger.debug("Skipping already applied job: %s", url)
                    break
                card = c
                job_url = url
                break

            if card is None:
                scroll_attempts += 1
                if scroll_attempts >= MAX_SCROLL_ATTEMPTS:
                    logger.info("No new unprocessed job cards after %d scroll attempts. Stopping.", MAX_SCROLL_ATTEMPTS)
                    break
                _scroll_job_list(driver)
                _scroll_job_list(driver)
                rate_limit_actions(cfg)
                continue

            scroll_attempts = 0

            try:
                last_processed_url = job_url
                rate_limit_actions(cfg)
                title, company, url, status = apply_to_job(
                    driver,
                    card,
                    asdict(cfg.saved_answers),
                    cfg.resume_path,
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
                    applied_urls.add(url)
                    applied_count += 1
                    logger.info("Applied: %s @ %s", title, company)
                    rate_limit_after_application(cfg)
                else:
                    skipped_count += 1
                    key = status or "skipped"
                    skip_reasons[key] += 1
                    logger.info("Skipped: %s @ %s (%s)", title, company, status)
            except Exception:
                skipped_count += 1
                skip_reasons["exception"] += 1
                logger.exception("Unexpected error while processing job: %s", job_url)
                rate_limit_actions(cfg)

            _scroll_job_list(driver)
            rate_limit_actions(cfg)

        logger.info(
            "Run complete. Applied: %d, Skipped: %d. Tracking file: %s",
            applied_count,
            skipped_count,
            tracking_file,
        )
        if skip_reasons:
            logger.info("Skip reasons breakdown:")
            for reason, count in skip_reasons.most_common():
                logger.info("  %s: %d", reason, count)
    finally:
        driver.quit()


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Automate LinkedIn Easy Apply for configured job searches."
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Login and open the job search, but do not submit any applications.",
    )
    parser.add_argument(
        "--keywords",
        help="Override configured keywords / role for this run (e.g. 'software engineer').",
    )
    parser.add_argument(
        "--location",
        help="Override configured location for this run (e.g. 'United Kingdom').",
    )
    parser.add_argument(
        "--max-applications",
        type=int,
        help="Override configured max applications for this run (0 = no limit).",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Show a one-time summary of filters and limits and ask for confirmation before applying.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    dry_run_flag = bool(args.dry_run)

    # Load config once so we can apply user-friendly overrides before running.
    _configure_logging()
    cfg = get_config()

    if args.keywords:
        cfg.keywords = args.keywords
    if args.location:
        cfg.location = args.location
    if args.max_applications is not None:
        cfg.max_applications = max(args.max_applications, 0)

    logging.getLogger("linkedin_easy_apply").info(
        "Using configuration for this run: dry_run=%s, keywords=%r, location=%r, "
        "max_applications=%s, delay_between_actions_sec=%.1f, "
        "delay_between_applications_sec=%.1f",
        dry_run_flag,
        cfg.keywords,
        cfg.location,
        cfg.max_applications or 0,
        cfg.delay_between_actions_sec,
        cfg.delay_between_applications_sec,
    )

    if args.confirm and not dry_run_flag:
        print(
            "\nAbout to start a live Easy Apply run with the above configuration.\n"
            "This will submit real applications on LinkedIn.\n"
        )
        proceed = input("Proceed? [y/N]: ").strip().lower()
        if proceed not in ("y", "yes"):
            print("Aborted by user.")
            sys.exit(0)

    main(dry_run=dry_run_flag, cfg=cfg)
