"""
LinkedIn automation: login, job search, Easy Apply flow.
Uses Selenium with Chrome; rate limiting applied by caller.
"""
import logging
import time
import urllib.parse
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager


logger = logging.getLogger("linkedin_easy_apply.automation")

# Timeout for page loads and element appearance
WAIT_TIMEOUT = 15
PAGE_LOAD_WAIT = 5

# Centralized DOM selectors to ease maintenance when LinkedIn changes layout.
JOB_LIST_SELECTORS = [
    "ul.scaffold-layout__list-container li",
    "li.jobs-search-results__list-item",
    "div.job-search-results-list ul li",
    "[data-occludable-job-id]",
]

JOB_LIST_XPATH_FALLBACKS = [
    "//ul[contains(@class,'scaffold-layout')]//li[.//a[contains(@href,'/jobs/')]]",
    "//li[.//a[contains(@href,'/jobs/view')]]",
]

EASY_APPLY_TEXT_XPATH = (
    ".//*[contains(translate(text(),'EASY APPLY','easy apply'),'easy apply') "
    "or contains(., 'In Apply')]"
)

EASY_APPLY_ARIA_SELECTORS = [
    "[aria-label*='Easy Apply']",
    "[aria-label*='easy apply']",
    "[aria-label*='In Apply']",
]


def get_driver(headless: bool = False):
    """Create Chrome WebDriver with sensible options."""
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.implicitly_wait(3)
    return driver


def _wait(driver, by, value, timeout=WAIT_TIMEOUT):
    return WebDriverWait(driver, timeout).until(EC.presence_of_element_located((by, value)))


def _wait_clickable(driver, by, value, timeout=WAIT_TIMEOUT):
    return WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((by, value)))


def login(driver, email: str, password: str) -> bool:
    """Log into LinkedIn. Returns True on success."""
    driver.get("https://www.linkedin.com/login")
    time.sleep(PAGE_LOAD_WAIT)

    try:
        email_el = _wait(driver, By.ID, "username")
        email_el.clear()
        email_el.send_keys(email)
        pass_el = driver.find_element(By.ID, "password")
        pass_el.clear()
        pass_el.send_keys(password)
        pass_el.send_keys(Keys.RETURN)
        time.sleep(PAGE_LOAD_WAIT)
        # Check we're not on login page (could add CAPTCHA check)
        if "login" in driver.current_url.lower():
            return False
        return True
    except Exception:
        return False


# Work type: 1=On-site, 2=Remote, 3=Hybrid (can pass "1"/"2"/"3" or "On-site"/"Remote"/"Hybrid")
_WORK_TYPE_MAP = {"1": "1", "2": "2", "3": "3", "on-site": "1", "onsite": "1", "remote": "2", "hybrid": "3"}


def _normalize_work_type(v: str) -> str:
    if not v:
        return ""
    k = str(v).strip().lower()
    return _WORK_TYPE_MAP.get(k, v)


def build_jobs_search_url(
    keywords: str,
    location: str,
    work_type: str = "",
    job_type: str = "",
    date_posted: str = "",
    experience_level: str = "",
    few_applicants: bool = False,
    geo_id: str = "",
) -> str:
    """Build LinkedIn jobs search URL with Easy Apply filter.
    work_type: 1=On-site, 2=Remote, 3=Hybrid (or "On-site"/"Remote"/"Hybrid").
    job_type: F=Full-time, P=Part-time, C=Contract, T=Temporary, V=Volunteer, I=Internship, O=Other.
    date_posted: r86400=24h, r604800=week, r2592000=month.
    experience_level: 1=Intern, 2=Associate, 3=Junior, 4=Mid-Senior, 5=Director, 6=Executive (comma-separated for multiple).
    few_applicants: true -> jobs with fewer than 10 applicants.
    geo_id: LinkedIn geographic ID (optional; overrides location if set).
    """
    base = "https://www.linkedin.com/jobs/search/"
    params = {
        "keywords": keywords,
        "location": location,
        "f_AL": "true",   # LinkedIn Apply / Easy Apply only (both casings in case LinkedIn is strict)
    }
    wt = _normalize_work_type(work_type)
    if wt:
        params["f_WT"] = wt
    if job_type:
        params["f_JT"] = job_type
    if date_posted:
        params["f_TPR"] = date_posted
    if experience_level:
        params["f_E"] = experience_level.strip()
    if few_applicants:
        params["f_JIYN"] = "true"
    if geo_id:
        params["geoId"] = geo_id.strip()
    return base + "?" + urllib.parse.urlencode(params)


def _url_with_easy_apply(url: str) -> str:
    """Return the same URL with f_AL=true added or set (so only Easy Apply jobs show)."""
    parsed = urlparse(url)
    if not parsed.path or "/jobs/search" not in parsed.path:
        return url
    q = parse_qs(parsed.query)
    q["f_AL"] = ["true"]
    q.pop("f_Al", None)
    new_query = urlencode(q, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))


def ensure_easy_apply_url(driver) -> None:
    """Ensure current page URL has f_AL=true so the job list stays filtered to Easy Apply only. Call after skip/apply so we don't lose the filter."""
    try:
        current = driver.current_url
        if "/jobs/search" not in current:
            return
        if "f_AL=true" in current or "f_Al=true" in current:
            return
        new_url = _url_with_easy_apply(current)
        if new_url != current:
            driver.get(new_url)
            time.sleep(2)
    except Exception:
        pass


def _ensure_linkedin_apply_filter(driver) -> None:
    """Turn on 'LinkedIn Apply' filter: ensure URL has f_AL=true so only Easy Apply jobs are shown."""
    try:
        time.sleep(2)
        current = driver.current_url
        if "f_AL=true" not in current and "f_Al=true" not in current:
            new_url = _url_with_easy_apply(current)
            if new_url != current:
                driver.get(new_url)
                time.sleep(3)
        # 2) Open "All filters" panel to ensure LinkedIn Apply is on
        all_filters = driver.find_elements(By.XPATH, "//button[contains(., 'All filters')]")
        if all_filters and all_filters[0].is_displayed():
            try:
                all_filters[0].click()
                time.sleep(2)
            except Exception:
                pass
        # 3) Find LinkedIn Apply toggle (in filter panel or on page) and turn on if off
        for xpath in [
            "//label[contains(., 'LinkedIn Apply')]/..//button",
            "//*[contains(., 'LinkedIn Apply')]//button[@role='switch']",
            "//button[@aria-label and contains(@aria-label, 'LinkedIn Apply')]",
            "//span[contains(., 'LinkedIn Apply')]/ancestor::button",
        ]:
            toggles = driver.find_elements(By.XPATH, xpath)
            for t in toggles:
                if not t.is_displayed():
                    continue
                try:
                    checked = t.get_attribute("aria-checked")
                    if checked == "false" or checked is None:
                        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", t)
                        time.sleep(0.3)
                        t.click()
                        time.sleep(2)
                    break
                except Exception:
                    pass
            else:
                continue
            break
        # 4) If we opened All filters, click "Show results" to apply and close
        show_btn = driver.find_elements(By.XPATH, "//button[contains(., 'Show') and (contains(., 'result') or contains(., 'results'))]")
        if show_btn and show_btn[0].is_displayed():
            try:
                show_btn[0].click()
                time.sleep(2)
            except Exception:
                pass
    except Exception:
        pass


def navigate_to_search(
    driver,
    keywords: str,
    location: str,
    work_type: str = "",
    job_type: str = "",
    date_posted: str = "",
    experience_level: str = "",
    few_applicants: bool = False,
    geo_id: str = "",
) -> bool:
    """Open job search results (Easy Apply filtered)."""
    url = build_jobs_search_url(
        keywords, location, work_type, job_type, date_posted,
        experience_level, few_applicants, geo_id,
    )
    driver.get(url)
    time.sleep(PAGE_LOAD_WAIT)
    if "jobs" not in driver.current_url:
        return False
    time.sleep(2)
    _ensure_linkedin_apply_filter(driver)
    time.sleep(2)
    try:
        driver.execute_script("document.querySelector('.jobs-search-results-list, .scaffold-layout__list-container')?.scrollBy(0, 300);")
        time.sleep(1)
    except Exception:
        pass
    return True


def get_job_cards(driver):
    """Get list of job card elements from the left-hand list."""
    try:
        _scroll_list_into_view(driver)
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "ul.scaffold-layout__list-container li, li.jobs-search-results__list-item, [data-occludable-job-id]")
                )
            )
        except Exception:
            logger.debug("Timeout waiting for job list to appear.", exc_info=True)
        time.sleep(2)
        # Try multiple selectors (LinkedIn changes DOM often)
        cards = []
        for sel in JOB_LIST_SELECTORS:
            cards = driver.find_elements(By.CSS_SELECTOR, sel)
            if cards:
                break
        if not cards:
            for xpath in JOB_LIST_XPATH_FALLBACKS:
                cards = driver.find_elements(By.XPATH, xpath)
                if cards:
                    break
        visible_cards = [c for c in cards if c.is_displayed()]
        if not visible_cards:
            logger.warning("No visible job cards found with known selectors.")
        return visible_cards
    except Exception:
        logger.exception("Failed to collect job cards.")
        return []


def job_has_easy_apply(card) -> bool:
    """Check if a job card shows Easy Apply or 'In Apply' (badge or button)."""
    try:
        text = card.text.lower()
        if "easy apply" in text or "in apply" in text:
            return True
        btn = card.find_elements(By.XPATH, EASY_APPLY_TEXT_XPATH)
        if btn:
            return True
        aria = []
        for sel in EASY_APPLY_ARIA_SELECTORS:
            aria.extend(card.find_elements(By.CSS_SELECTOR, sel))
        return len(aria) > 0
    except Exception:
        return False


def get_job_title_and_company(card) -> tuple[str, str]:
    """Extract job title and company from card. Fallback to empty strings."""
    try:
        title_el = card.find_elements(By.CSS_SELECTOR, "a.job-card-list__title, [data-tracking-control-name='job_list_job']")
        if not title_el:
            title_el = card.find_elements(By.XPATH, ".//a[contains(@href,'/jobs/')]")
        title = title_el[0].text.strip() if title_el else ""
        # Company often in same card
        company_el = card.find_elements(By.CSS_SELECTOR, "span.job-card-container__primary-description, h4.job-card-container__company-name")
        if not company_el:
            company_el = card.find_elements(By.XPATH, ".//h4 | .//span[contains(@class,'company')]")
        company = company_el[0].text.strip() if company_el else "Unknown"
        return title or "Unknown", company
    except Exception:
        return "Unknown", "Unknown"


def get_job_url_from_card(card) -> str:
    """Get job URL from card link."""
    try:
        link = card.find_element(By.XPATH, ".//a[contains(@href,'/jobs/')]")
        return link.get_attribute("href") or ""
    except Exception:
        return ""


def select_job_card(driver, card) -> bool:
    """Click job card to load job detail in right panel. Returns True if succeeded."""
    try:
        link = card.find_element(By.XPATH, ".//a[contains(@href,'/jobs/')]")
        if not link.is_displayed():
            return False
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", link)
        time.sleep(0.5)
        link.click()
        time.sleep(2)
        return True
    except Exception:
        return False


def open_job_by_url(driver, job_url: str) -> bool:
    """Open a job's detail page by URL (fallback when card click fails). Returns True if navigated."""
    if not job_url or "/jobs/view" not in job_url:
        return False
    try:
        driver.get(job_url)
        time.sleep(2)
        return "jobs" in driver.current_url
    except Exception:
        return False


def _get_detail_panel(driver):
    """Get the right-hand job details panel so we don't click Apply in the left list."""
    try:
        for sel in [
            "div[data-job-id]",
            ".jobs-search__job-details",
            ".scaffold-layout__detail",
            "div.jobs-search-right-panel",
            "main .scaffold-layout__main",
        ]:
            el = driver.find_elements(By.CSS_SELECTOR, sel)
            for e in el:
                if e.is_displayed() and e.size.get("width", 0) > 200:
                    return e
    except Exception:
        pass
    return None


def _click_apply_button(driver, btn) -> bool:
    """Scroll into view and click the button; fallback to JS click."""
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        time.sleep(0.5)
        btn.click()
        return True
    except Exception:
        try:
            driver.execute_script("arguments[0].click();", btn)
            return True
        except Exception:
            pass
    return False


def click_easy_apply_in_detail_panel(driver) -> bool:
    """Click Easy Apply / In Apply / Apply button in the job detail (right) panel. Returns True if found and clicked."""
    try:
        time.sleep(2)
        scope = _get_detail_panel(driver)
        search_in = scope if scope else driver

        # 1) LinkedIn's known class for the apply button
        for sel in [
            "button.jobs-apply-button",
            ".jobs-apply-button",
            "button[class*='jobs-apply-button']",
            "button.artdeco-button--primary",
            "button[aria-label*='Apply'][aria-label*='job']",
            "button[aria-label*='Easy Apply']",
            "button[aria-label*='In Apply']",
        ]:
            btns = search_in.find_elements(By.CSS_SELECTOR, sel)
            for b in btns:
                if b.is_displayed() and _click_apply_button(driver, b):
                    return True

        # 2) By text (button or span inside button)
        for xpath in [
            ".//button[contains(., 'Easy Apply') or contains(., 'In Apply') or contains(., 'Apply')]",
            ".//span[normalize-space()='Easy Apply']/ancestor::button[1]",
            ".//span[normalize-space()='In Apply']/ancestor::button[1]",
            ".//span[contains(., 'Apply')]/ancestor::button[1]",
        ]:
            btns = search_in.find_elements(By.XPATH, xpath)
            for b in btns:
                if b.is_displayed() and _click_apply_button(driver, b):
                    return True

        # 3) Full page fallback (in case detail panel wasn't found)
        for sel in [
            "button.jobs-apply-button",
            "button[class*='jobs-apply-button']",
            "//button[contains(., 'Easy Apply') or contains(., 'In Apply')]",
            "//span[contains(., 'Easy Apply') or contains(., 'In Apply')]/ancestor::button[1]",
        ]:
            by = By.CSS_SELECTOR if "button" in sel and not sel.startswith("//") else By.XPATH
            btns = driver.find_elements(by, sel)
            for b in btns:
                if b.is_displayed() and _click_apply_button(driver, b):
                    return True

        return False
    except Exception:
        return False


def _fill_phone(driver, saved_answers: dict) -> None:
    """Fill Mobile phone number and optionally country code in Contact info / Easy Apply modal."""
    phone = saved_answers.get("phone") or ""
    phone = str(phone).strip()
    if not phone:
        return
    digits_only = "".join(c for c in phone if c.isdigit())
    country_code = str(saved_answers.get("phone_country_code") or "").strip()
    if country_code:
        try:
            for trigger in driver.find_elements(By.XPATH, "//*[contains(.,'Phone country code') or contains(.,'Country code')]/following::button[1] | //*[contains(.,'Phone country code')]/following::*[@role='combobox'][1]"):
                if trigger.is_displayed():
                    trigger.click()
                    time.sleep(0.5)
                    for opt in driver.find_elements(By.XPATH, f"//*[contains(., '{country_code}')]"):
                        if opt.is_displayed() and (country_code in opt.text or (len(country_code) <= 4 and country_code in opt.text)):
                            opt.click()
                            time.sleep(0.3)
                            break
                    break
        except Exception:
            pass
    for sel in [
        "input[type='tel']",
        "input[placeholder*='Mobile phone']",
        "input[placeholder*='phone number']",
        "input[placeholder*='Phone']",
        "input[id*='phone']",
        "input[name*='phone']",
        "input[name*='mobile']",
    ]:
        inputs = driver.find_elements(By.CSS_SELECTOR, sel)
        for inp in inputs:
            if not inp.is_displayed():
                continue
            try:
                inp.clear()
                inp.send_keys(phone if len(phone) <= 20 else digits_only)
                time.sleep(0.3)
                return
            except Exception:
                pass
    for xpath in [
        "//label[contains(.,'Mobile phone') or contains(.,'Phone number')]/following::input[1]",
        "//*[contains(.,'Mobile phone number')]/following::input[1]",
        "//input[contains(@placeholder,'phone') or contains(@placeholder,'Phone')]",
        "//input[contains(@aria-label,'phone') or contains(@aria-label,'Phone')]",
    ]:
        try:
            inputs = driver.find_elements(By.XPATH, xpath)
            for inp in inputs:
                if inp.is_displayed():
                    inp.clear()
                    inp.send_keys(phone if len(phone) <= 20 else digits_only)
                    time.sleep(0.3)
                    return
        except Exception:
            pass


def _fill_contact_info(driver, saved_answers: dict) -> None:
    """Fill first name, last name, and email in Contact info / Easy Apply modal."""
    for label_text, key in [
        ("First name", "first_name"),
        ("Last name", "last_name"),
        ("Email", "email"),
        ("Email address", "email"),
    ]:
        val = (saved_answers.get(key) or "").strip()
        if not val:
            continue
        try:
            inputs = driver.find_elements(
                By.XPATH,
                f"//label[contains(.,'{label_text}')]/following::input[1] | //*[contains(.,'{label_text}')]/following::input[1]"
            )
            for inp in inputs:
                if inp.is_displayed():
                    inp.clear()
                    inp.send_keys(val)
                    time.sleep(0.2)
                    break
        except Exception:
            pass
        for sel in [f"input[name*='{key.replace('_','')}']", f"input[id*='{key.replace('_','')}']", "input[type='email']"]:
            if key != "email" and "email" in sel:
                continue
            try:
                inps = driver.find_elements(By.CSS_SELECTOR, sel)
                for inp in inps:
                    if inp.is_displayed():
                        inp.clear()
                        inp.send_keys(val)
                        time.sleep(0.2)
                        break
            except Exception:
                pass


def _fill_easy_apply_step(driver, saved_answers: dict, resume_path: str) -> str:
    """One step: fill visible fields then return 'next', 'submitted', or 'skip'."""
    try:
        _fill_contact_info(driver, saved_answers)
        _fill_phone(driver, saved_answers)

        # Optional: city, cover letter, etc.
        if saved_answers.get("city"):
            try:
                city_input = driver.find_elements(By.CSS_SELECTOR, "input[id*='city'], input[name*='city'], input[placeholder*='City']")
                for inp in city_input:
                    if inp.is_displayed():
                        inp.clear()
                        inp.send_keys(saved_answers["city"])
                        break
            except Exception:
                pass

        # Resume upload
        if resume_path and Path(resume_path).exists():
            try:
                file_input = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                for fi in file_input:
                    if fi.is_displayed():
                        fi.send_keys(str(Path(resume_path).resolve()))
                        time.sleep(1)
                        break
            except Exception:
                pass

        # Cover letter textarea
        if saved_answers.get("cover_letter"):
            try:
                ta = driver.find_elements(By.CSS_SELECTOR, "textarea")
                for t in ta:
                    if t.is_displayed() and "cover" in (t.get_attribute("name") or t.get_attribute("id") or "").lower():
                        t.clear()
                        t.send_keys(saved_answers["cover_letter"])
                        break
            except Exception:
                pass

        # Start date (dropdown or input)
        if saved_answers.get("start_date"):
            try:
                start_val = saved_answers["start_date"]
                # Try dropdown: click and pick option containing our value
                dropdowns = driver.find_elements(By.CSS_SELECTOR, "select, [role='listbox']")
                for dd in dropdowns:
                    if not dd.is_displayed():
                        continue
                    label = driver.find_elements(By.XPATH, "//label[contains(.,'start') or contains(.,'Start') or contains(.,'available')]")
                    if dd.get_attribute("id") or (label and dd.location == label[0].location):
                        try:
                            dd.click()
                            time.sleep(0.5)
                            opts = driver.find_elements(By.XPATH, f"//*[contains(translate(., '{start_val[:4].upper()}', '{start_val[:4].lower()}'), '{start_val[:4].lower()}')]")
                            for o in opts:
                                if o.is_displayed():
                                    o.click()
                                    break
                        except Exception:
                            pass
                        break
                # Fallback: input with placeholder/label about date
                inputs = driver.find_elements(By.XPATH, "//input[contains(@placeholder,'date') or contains(@placeholder,'Date') or contains(@id,'start')]")
                for inp in inputs:
                    if inp.is_displayed():
                        inp.clear()
                        inp.send_keys(start_val)
                        break
            except Exception:
                pass

        # Next (e.g. past "Your profile matches" screen) or Submit
        next_btns = driver.find_elements(By.XPATH, "//button[contains(translate(., 'NEXT', 'next'), 'next')]")
        submit_btns = driver.find_elements(By.XPATH, "//button[contains(translate(., 'SUBMIT', 'submit'), 'submit')]")
        if not submit_btns:
            submit_btns = driver.find_elements(By.XPATH, "//button[contains(., 'Submit')]")

        if next_btns and next_btns[0].is_displayed():
            next_btns[0].click()
            time.sleep(2)
            return "next"
        if submit_btns and submit_btns[0].is_displayed():
            submit_btns[0].click()
            time.sleep(2)
            return "submitted"
        return "skip"
    except Exception:
        return "error"


def fill_easy_apply_modal(driver, saved_answers: dict, resume_path: str) -> str:
    """
    Fill the Easy Apply modal with saved answers and optional resume.
    Clicks Next to get past 'Your profile matches' and similar screens, then fills and submits.
    Returns: 'submitted' | 'next' (gave up after max steps) | 'skip' | 'error'
    """
    time.sleep(2)
    max_steps = 5
    for _ in range(max_steps):
        result = _fill_easy_apply_step(driver, saved_answers, resume_path)
        if result == "submitted":
            return "submitted"
        if result == "skip":
            return "skip"
        if result == "error":
            return "error"
        assert result == "next"
    return "next"


def close_modal(driver) -> None:
    """Close Easy Apply or any overlay modal (Discard / Cancel / X)."""
    try:
        discard = driver.find_elements(By.XPATH, "//button[contains(., 'Discard') or contains(., 'Cancel') or contains(., 'Close')]")
        if discard and discard[0].is_displayed():
            discard[0].click()
        else:
            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        time.sleep(2)
        _scroll_list_into_view(driver)
    except Exception:
        pass


def _scroll_list_into_view(driver) -> None:
    """Scroll the left-hand job list into view so it's visible after closing a modal."""
    try:
        driver.execute_script(
            "var el = document.querySelector('.scaffold-layout__list-container') || document.querySelector('.jobs-search-results-list') || document.querySelector('[data-occludable-job-id]')?.closest('ul'); if(el) el.scrollIntoView({block:'start', behavior:'instant'});"
        )
        time.sleep(1)
    except Exception:
        pass


def apply_to_job(
    driver,
    card,
    saved_answers: dict,
    resume_path: str,
) -> tuple[str, str, str, str]:
    """
    Select job card, open Easy Apply in detail panel, fill and submit if simple.
    Returns (job_title, company_name, job_url, status) where status is 'applied' | 'skipped' | 'error'.
    """
    job_title, company_name = get_job_title_and_company(card)
    job_url = get_job_url_from_card(card)

    selected = select_job_card(driver, card)
    if not selected and job_url:
        open_job_by_url(driver, job_url)
    elif not selected:
        return job_title, company_name, job_url, "skipped (no job link)"
    if not click_easy_apply_in_detail_panel(driver):
        return job_title, company_name, job_url, "skipped (Apply button not found)"

    time.sleep(2)
    result = fill_easy_apply_modal(driver, saved_answers, resume_path or "")

    if result == "submitted":
        close_modal(driver)
        return job_title, company_name, job_url, "applied"
    if result == "next":
        close_modal(driver)
        return job_title, company_name, job_url, "skipped (multi-step)"
    close_modal(driver)
    return job_title, company_name, job_url, "skipped (no submit)" if result == "skip" else "error"
