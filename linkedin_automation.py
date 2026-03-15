"""
LinkedIn automation: login, job search, Easy Apply flow.
Uses Selenium with Chrome; rate limiting applied by caller.
"""
import time
import urllib.parse
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager


# Timeout for page loads and element appearance
WAIT_TIMEOUT = 15
PAGE_LOAD_WAIT = 5


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


def build_jobs_search_url(
    keywords: str,
    location: str,
    remote: str,
    job_type: str = "",
    date_posted: str = "",
) -> str:
    """Build LinkedIn jobs search URL with Easy Apply filter.
    job_type: F=Full-time, P=Part-time, C=Contract, T=Temporary, I=Internship. Empty = no filter.
    date_posted: r86400=24h, r604800=week, r2592000=month. Empty = no filter.
    """
    base = "https://www.linkedin.com/jobs/search/"
    params = {
        "keywords": keywords,
        "location": location,
        "f_AL": "true",  # Easy Apply only
    }
    if remote:
        params["f_WT"] = "2"  # Remote
    if job_type:
        params["f_JT"] = job_type
    if date_posted:
        params["f_TPR"] = date_posted
    return base + "?" + urllib.parse.urlencode(params)


def navigate_to_search(
    driver,
    keywords: str,
    location: str,
    remote: str,
    job_type: str = "",
    date_posted: str = "",
) -> bool:
    """Open job search results (Easy Apply filtered)."""
    url = build_jobs_search_url(keywords, location, remote, job_type, date_posted)
    driver.get(url)
    time.sleep(PAGE_LOAD_WAIT)
    return "jobs" in driver.current_url


def get_job_cards(driver):
    """Get list of job card elements from the left-hand list."""
    # LinkedIn job list container; selectors may need adjustment if LinkedIn changes DOM
    try:
        # Job list items in the left panel
        cards = driver.find_elements(By.CSS_SELECTOR, "div.job-search-results-list ul li")
        if not cards:
            cards = driver.find_elements(By.CSS_SELECTOR, "ul.scaffold-layout__list-container li")
        if not cards:
            cards = driver.find_elements(By.XPATH, "//ul[contains(@class,'scaffold-layout')]//li[.//a[contains(@href,'/jobs/')]]")
        return [c for c in cards if c.is_displayed()]
    except Exception:
        return []


def job_has_easy_apply(card) -> bool:
    """Check if a job card shows Easy Apply (badge or button)."""
    try:
        text = card.text.lower()
        if "easy apply" in text:
            return True
        btn = card.find_elements(By.XPATH, ".//*[contains(translate(text(),'EASY APPLY','easy apply'),'easy apply')]")
        if btn:
            return True
        aria = card.find_elements(By.CSS_SELECTOR, "[aria-label*='Easy Apply'], [aria-label*='easy apply']")
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
        if link.is_displayed():
            link.click()
            time.sleep(2)
            return True
        return False
    except Exception:
        return False


def click_easy_apply_in_detail_panel(driver) -> bool:
    """Click Easy Apply button in the job detail (right) panel. Returns True if found and clicked."""
    try:
        # Right panel / job details container
        btns = driver.find_elements(By.XPATH, "//button[contains(translate(., 'EASY APPLY', 'easy apply'), 'easy apply')]")
        if not btns:
            btns = driver.find_elements(By.CSS_SELECTOR, "button[aria-label*='Easy Apply'], button[aria-label*='easy apply']")
        for b in btns:
            if b.is_displayed():
                b.click()
                return True
        return False
    except Exception:
        return False


def fill_easy_apply_modal(driver, saved_answers: dict, resume_path: str) -> str:
    """
    Fill the Easy Apply modal with saved answers and optional resume.
    Returns: 'submitted' | 'next' (multi-step) | 'skip' | 'error'
    """
    time.sleep(2)
    try:
        # Phone
        if saved_answers.get("phone"):
            try:
                phone_input = driver.find_elements(By.CSS_SELECTOR, "input[type='tel'], input[id*='phone'], input[name*='phone']")
                for inp in phone_input:
                    if inp.is_displayed():
                        inp.clear()
                        inp.send_keys(saved_answers["phone"])
                        break
            except Exception:
                pass

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

        # Submit: look for "Submit" or "Review" then "Submit"
        submit_btns = driver.find_elements(By.XPATH, "//button[contains(translate(., 'SUBMIT', 'submit'), 'submit')]")
        if not submit_btns:
            submit_btns = driver.find_elements(By.XPATH, "//button[contains(., 'Submit')]")
        next_btns = driver.find_elements(By.XPATH, "//button[contains(translate(., 'NEXT', 'next'), 'next')]")

        if next_btns and next_btns[0].is_displayed():
            # Multi-step: we could click Next and repeat, but for safety we skip complex flows
            return "next"
        if submit_btns and submit_btns[0].is_displayed():
            submit_btns[0].click()
            time.sleep(2)
            return "submitted"
        return "skip"
    except Exception:
        return "error"


def close_modal(driver) -> None:
    """Close Easy Apply or any overlay modal (Discard / Cancel / X)."""
    try:
        discard = driver.find_elements(By.XPATH, "//button[contains(., 'Discard') or contains(., 'Cancel') or contains(., 'Close')]")
        if discard and discard[0].is_displayed():
            discard[0].click()
        else:
            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
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

    if not select_job_card(driver, card):
        return job_title, company_name, job_url, "skipped"
    if not click_easy_apply_in_detail_panel(driver):
        return job_title, company_name, job_url, "skipped"

    time.sleep(2)
    result = fill_easy_apply_modal(driver, saved_answers, resume_path or "")

    if result == "submitted":
        close_modal(driver)
        return job_title, company_name, job_url, "applied"
    if result == "next":
        close_modal(driver)
        return job_title, company_name, job_url, "skipped"
    close_modal(driver)
    return job_title, company_name, job_url, "skipped" if result == "skip" else "error"
