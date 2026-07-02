"""
LinkedIn automation: login, job search, Easy Apply flow.
Uses Selenium with Chrome; rate limiting applied by caller.
"""
import logging
import re
import time
import urllib.parse
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

from errors import LoginResult
from session_store import load_cookies, save_cookies


logger = logging.getLogger("linkedin_easy_apply.automation")

# Timeout for page loads and element appearance
WAIT_TIMEOUT = 15
PAGE_LOAD_WAIT = 3
EASY_APPLY_MAX_STEPS = 12

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

EASY_APPLY_MODAL_SELECTORS = [
    "div.jobs-easy-apply-modal",
    "div[data-test-modal]",
    "div.artdeco-modal[role='dialog']",
    "div[role='dialog']",
]

MODAL_ACTION_SELECTORS = {
    "submit": [
        "button[aria-label='Submit application']",
        "button[aria-label*='Submit application']",
        "button[aria-label*='Submit']",
        "footer button.artdeco-button--primary",
        ".jobs-easy-apply-footer button.artdeco-button--primary",
    ],
    "review": [
        "button[aria-label='Review your application']",
        "button[aria-label*='Review your application']",
        "button[aria-label*='Review']",
    ],
    "next": [
        "button[aria-label='Continue to next step']",
        "button[aria-label*='Continue to next step']",
        "button[aria-label*='Next step']",
        "button[aria-label*='Continue']",
    ],
}

MODAL_ACTION_XPATHS = {
    "submit": [
        ".//button[.//span[normalize-space()='Submit application']]",
        ".//button[.//span[normalize-space()='Submit']]",
        ".//span[normalize-space()='Submit application']/ancestor::button[1]",
        ".//span[normalize-space()='Submit']/ancestor::button[1]",
    ],
    "review": [
        ".//button[.//span[normalize-space()='Review']]",
        ".//button[contains(translate(., 'REVIEW', 'review'), 'review')]",
        ".//span[normalize-space()='Review']/ancestor::button[1]",
    ],
    "next": [
        ".//button[.//span[normalize-space()='Next']]",
        ".//button[.//span[normalize-space()='Continue']]",
        ".//button[contains(translate(., 'NEXT', 'next'), 'next')]",
        ".//span[normalize-space()='Next']/ancestor::button[1]",
        ".//span[normalize-space()='Continue']/ancestor::button[1]",
    ],
}

APPLICATION_SENT_PHRASES = (
    "your application was sent",
    "application was sent",
    "application submitted",
    "successfully submitted",
)


def classify_modal_button_label(label: str) -> str | None:
    """Map visible button text / aria-label to a modal action."""
    lower = " ".join(label.lower().split())
    if not lower:
        return None
    if any(token in lower for token in ("discard", "cancel", "close", "back")):
        return None
    if "submit application" in lower or lower == "submit":
        return "submit"
    if "review your application" in lower or lower == "review":
        return "review"
    if (
        "continue to next step" in lower
        or lower in {"next", "continue"}
        or "next step" in lower
    ):
        return "next"
    if lower.endswith(" next"):
        return "next"
    return None


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


def _find_visible(driver, by, value):
    for el in driver.find_elements(by, value):
        if el.is_displayed():
            return el
    return None


def _wait_for_url_change(driver, previous_url: str, timeout: int = WAIT_TIMEOUT) -> None:
    try:
        WebDriverWait(driver, timeout).until(lambda d: d.current_url != previous_url)
    except Exception:
        logger.debug("URL did not change within %ss (was %s)", timeout, previous_url)


def _is_challenge_page(driver) -> bool:
    url = driver.current_url.lower()
    return any(token in url for token in ("checkpoint", "challenge", "captcha", "verification"))


def _login_error_on_page(driver) -> str:
    for sel in ("#error-for-username", "#error-for-password", ".form__label--error", "[role='alert']"):
        for el in driver.find_elements(By.CSS_SELECTOR, sel):
            text = (el.text or "").strip()
            if text:
                return text
    return ""


def _pause_for_user_challenge() -> None:
    print(
        "\n>>> LinkedIn verification detected (CAPTCHA / 2FA / security check).\n"
        ">>> Complete it in the Chrome window, then press Enter here to continue...\n"
    )
    input()


def login(driver, email: str, password: str, pause_on_challenge: bool = False) -> LoginResult:
    """Log into LinkedIn. Returns structured result with user-friendly message."""
    driver.get("https://www.linkedin.com/login")
    time.sleep(PAGE_LOAD_WAIT)

    try:
        email_el = _find_visible(driver, By.CSS_SELECTOR, "input[type='email']")
        if email_el is None:
            email_el = _wait(driver, By.ID, "username")
        email_el.clear()
        email_el.send_keys(email)

        pass_el = _find_visible(driver, By.CSS_SELECTOR, "input[type='password']")
        if pass_el is None:
            pass_el = driver.find_element(By.ID, "password")
        pass_el.clear()
        pass_el.send_keys(password)

        previous_url = driver.current_url
        pass_el.send_keys(Keys.RETURN)
        _wait_for_url_change(driver, previous_url, timeout=10)
        time.sleep(PAGE_LOAD_WAIT)

        if _is_challenge_page(driver):
            if pause_on_challenge:
                _pause_for_user_challenge()
                time.sleep(PAGE_LOAD_WAIT)
                if not _is_challenge_page(driver) and "login" not in driver.current_url.lower():
                    return LoginResult.ok()
            return LoginResult.fail("challenge_required")

        if "login" in driver.current_url.lower():
            page_error = _login_error_on_page(driver)
            if page_error:
                logger.warning("LinkedIn login page error: %s", page_error)
            return LoginResult.fail("invalid_credentials")

        return LoginResult.ok()
    except Exception as exc:
        logger.exception("Login failed due to an unexpected error.")
        if "username" in str(exc).lower() or "email" in str(exc).lower():
            return LoginResult.fail("form_not_found", str(exc))
        return LoginResult.fail("unknown", str(exc))


def ensure_logged_in(
    driver,
    email: str,
    password: str,
    *,
    use_session: bool = True,
    fresh_login: bool = False,
    pause_on_challenge: bool = False,
) -> LoginResult:
    """Reuse saved session when possible; otherwise log in and persist cookies."""
    if use_session and not fresh_login:
        if load_cookies(driver):
            if _is_challenge_page(driver):
                if pause_on_challenge:
                    _pause_for_user_challenge()
                    if not _is_challenge_page(driver):
                        return LoginResult.ok()
                return LoginResult.fail("challenge_required")
            return LoginResult.ok()

    result = login(driver, email, password, pause_on_challenge=pause_on_challenge)
    if result.success:
        save_cookies(driver)
    return result


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
        company_el = card.find_elements(By.CSS_SELECTOR, "span.job-card-container__primary-description, h4.job-card-container__company-name, .artdeco-entity-lockup__subtitle span, .artdeco-entity-lockup__subtitle")
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


def normalize_job_url(url: str) -> str:
    """Canonicalize a job URL to https://www.linkedin.com/jobs/view/<id>/.

    Card hrefs carry per-session tracking params (refId, trackingId, eBP...),
    so raw URLs for the same job differ across runs and break dedup.
    """
    if not url:
        return ""
    match = re.search(r"/jobs/view/(\d+)", url)
    if match:
        return f"https://www.linkedin.com/jobs/view/{match.group(1)}/"
    try:
        job_id = parse_qs(urlparse(url).query).get("currentJobId", [""])[0]
        if job_id.isdigit():
            return f"https://www.linkedin.com/jobs/view/{job_id}/"
    except Exception:
        pass
    return url.split("?")[0]


def select_job_card(driver, card) -> bool:
    """Click job card to load job detail in right panel. Returns True if succeeded."""
    try:
        link = card.find_element(By.XPATH, ".//a[contains(@href,'/jobs/')]")
        if not link.is_displayed():
            return False
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", link)
        time.sleep(0.5)
        link.click()
        # Wait for the detail panel to actually load (up to 10s)
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR,
                    "button.jobs-apply-button, [aria-label*='Easy Apply'], [class*='jobs-apply-button']"
                ))
            )
        except Exception:
            time.sleep(3)  # Fallback if button never appears
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
    """Get the right-hand job details panel so we don't click Apply in the left list.

    Note: div[data-job-id] must NOT be used here — LinkedIn now puts that
    attribute on the left-list job cards, which contain no apply button.
    """
    try:
        for sel in [
            ".jobs-search__job-details",
            ".scaffold-layout__detail",
            ".jobs-details",
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


def _button_label(btn) -> str:
    aria = (btn.get_attribute("aria-label") or "").strip()
    text = (btn.text or "").strip()
    return f"{aria} {text}".strip()


def _is_button_interactable(driver, btn) -> bool:
    try:
        return bool(
            driver.execute_script(
                "var b=arguments[0];"
                "if(!b||b.disabled||b.getAttribute('aria-disabled')==='true') return false;"
                "var r=b.getBoundingClientRect();"
                "return r.width>0&&r.height>0&&b.offsetParent!==null;",
                btn,
            )
        )
    except Exception:
        return btn.is_displayed() and btn.is_enabled()


def _get_easy_apply_modal(driver):
    """Return the visible Easy Apply modal, or None if it is not open."""
    for sel in EASY_APPLY_MODAL_SELECTORS:
        for el in driver.find_elements(By.CSS_SELECTOR, sel):
            if el.is_displayed():
                return el
    return None


def _get_easy_apply_scope(driver):
    """Return the Easy Apply modal element, or the whole page as fallback for buttons."""
    modal = _get_easy_apply_modal(driver)
    return modal if modal is not None else driver


def _find_in_modal(scope, by, value):
    """Find elements relative to the Easy Apply modal only."""
    if by == By.XPATH and not value.startswith("."):
        value = "." + value
    return scope.find_elements(by, value)


def _find_modal_action_button(driver, scope, action: str):
    """Find Next / Review / Submit inside the Easy Apply modal."""
    for sel in MODAL_ACTION_SELECTORS.get(action, []):
        for btn in scope.find_elements(By.CSS_SELECTOR, sel):
            if _is_button_interactable(driver, btn):
                label = _button_label(btn)
                classified = classify_modal_button_label(label)
                if classified == action or (action == "submit" and classified is None and "submit" in label.lower()):
                    logger.debug("Found %s button via selector %r (%r)", action, sel, label)
                    return btn

    for xpath in MODAL_ACTION_XPATHS.get(action, []):
        for btn in scope.find_elements(By.XPATH, xpath):
            if _is_button_interactable(driver, btn):
                logger.debug("Found %s button via xpath %r (%r)", action, xpath, _button_label(btn))
                return btn

    for btn in scope.find_elements(By.TAG_NAME, "button"):
        if not _is_button_interactable(driver, btn):
            continue
        if classify_modal_button_label(_button_label(btn)) == action:
            logger.debug("Found %s button via label scan (%r)", action, _button_label(btn))
            return btn

    return None


def _application_submitted(driver) -> bool:
    """Detect LinkedIn confirmation that the application was sent."""
    try:
        scope = _get_easy_apply_scope(driver)
        text = (scope.text or "").lower()
        if any(phrase in text for phrase in APPLICATION_SENT_PHRASES):
            return True
    except Exception:
        pass
    page = driver.page_source.lower()
    return any(phrase in page for phrase in APPLICATION_SENT_PHRASES)


def _click_modal_action(driver, action: str):
    scope = _get_easy_apply_scope(driver)
    btn = _find_modal_action_button(driver, scope, action)
    if btn and _click_apply_button(driver, btn):
        return True
    return False


def _advance_easy_apply_step(driver) -> str:
    """
    Click the correct footer button in the Easy Apply modal.
    Priority: Submit > Review > Next, matching popular LinkedIn bot patterns.
    """
    if _application_submitted(driver):
        logger.debug("Application already marked as sent on page.")
        return "submitted"

    if _click_modal_action(driver, "submit"):
        time.sleep(2)
        if _application_submitted(driver):
            return "submitted"
        # Some flows need a second submit on the confirmation screen.
        if _click_modal_action(driver, "submit"):
            time.sleep(2)
        return "submitted" if _application_submitted(driver) else "next"

    if _click_modal_action(driver, "review"):
        time.sleep(2)
        if _click_modal_action(driver, "submit"):
            time.sleep(2)
        return "submitted" if _application_submitted(driver) else "next"

    if _click_modal_action(driver, "next"):
        time.sleep(2)
        return "next"

    # JS fallback: scan modal footer buttons from right to left (primary action is usually last).
    clicked = driver.execute_script(
        """
        const modal = document.querySelector('.jobs-easy-apply-modal')
            || document.querySelector('[data-test-modal]')
            || document.querySelector('div[role="dialog"]');
        const root = modal || document;
        const buttons = Array.from(root.querySelectorAll('button')).filter((b) => {
            const r = b.getBoundingClientRect();
            return r.width > 0 && r.height > 0 && !b.disabled && b.getAttribute('aria-disabled') !== 'true';
        });
        const labels = buttons.map((b) => ({
            btn: b,
            label: ((b.getAttribute('aria-label') || '') + ' ' + (b.innerText || '')).toLowerCase(),
        }));
        const priority = [
            ['submit application', 'submit'],
            ['review your application', 'review'],
            ['continue to next step', 'next', 'continue'],
        ];
        for (const keys of priority) {
            const match = labels.find(({label}) => keys.some((k) => label.includes(k)));
            if (match) {
                match.btn.scrollIntoView({block: 'center'});
                match.btn.click();
                return keys[0];
            }
        }
        const footerPrimary = root.querySelector('.jobs-easy-apply-footer button.artdeco-button--primary');
        if (footerPrimary) {
            footerPrimary.scrollIntoView({block: 'center'});
            footerPrimary.click();
            return 'footer-primary';
        }
        return '';
        """
    )
    if clicked:
        logger.debug("Clicked modal action via JS fallback: %s", clicked)
        time.sleep(2)
        if "submit" in str(clicked) or _application_submitted(driver):
            return "submitted"
        return "next"

    logger.warning(
        "No Next/Review/Submit button found in Easy Apply modal. Visible buttons: %s",
        [
            _button_label(b)
            for b in _get_easy_apply_scope(driver).find_elements(By.TAG_NAME, "button")
            if _is_button_interactable(driver, b)
        ][:8],
    )
    return "skip"


def _is_filter_control(btn) -> bool:
    """True for search-filter UI (e.g. the 'Easy Apply filter.' pill), which must
    never be clicked as an apply button — it toggles the search filter off."""
    try:
        btn_id = btn.get_attribute("id") or ""
        label = (btn.get_attribute("aria-label") or "").lower()
        return btn_id.startswith("searchFilter") or "filter" in label
    except Exception:
        return False


def _wait_for_easy_apply_modal(driver, timeout: int = 8) -> bool:
    """Wait until the Easy Apply modal is visible after clicking the apply button."""
    try:
        WebDriverWait(driver, timeout).until(lambda d: _get_easy_apply_modal(d) is not None)
        return True
    except Exception:
        return False


def click_easy_apply_in_detail_panel(driver) -> bool:
    """Click Easy Apply / In Apply in the job detail (right) panel.
    Returns True only if the Easy Apply modal actually opened."""
    try:
        scope = _get_detail_panel(driver)
        search_in = scope if scope else driver
        logger.debug("Detail panel found: %s", scope is not None)

        # 1) Most reliable: LinkedIn's dedicated apply button id/class, then aria-label
        for sel in [
            "button#jobs-apply-button-id",
            "button.jobs-apply-button",
            "button[class*='jobs-apply-button']",
            "button[aria-label*='Easy Apply']",
            "button[aria-label*='In Apply']",
        ]:
            btns = search_in.find_elements(By.CSS_SELECTOR, sel)
            logger.debug("Selector %r found %d buttons", sel, len(btns))
            for b in btns:
                if _is_filter_control(b):
                    continue
                try:
                    visible = driver.execute_script(
                        "var r=arguments[0].getBoundingClientRect();"
                        "return r.width>0&&r.height>0&&arguments[0].offsetParent!==null;", b
                    )
                except Exception:
                    visible = b.is_displayed()
                if visible and _click_apply_button(driver, b):
                    logger.debug("Clicked apply button via selector %r", sel)
                    if _wait_for_easy_apply_modal(driver):
                        return True
                    logger.warning("Apply button clicked but Easy Apply modal did not open.")
                    return False

        # 2) By span text inside button — most stable across LinkedIn DOM changes
        for xpath in [
            ".//button[.//span[normalize-space()='Easy Apply']]",
            ".//button[.//span[normalize-space()='In Apply']]",
            ".//span[normalize-space()='Easy Apply']/ancestor::button[1]",
            ".//span[normalize-space()='In Apply']/ancestor::button[1]",
        ]:
            btns = search_in.find_elements(By.XPATH, xpath)
            logger.debug("XPath %r found %d buttons", xpath, len(btns))
            for b in btns:
                if _is_filter_control(b):
                    continue
                if _click_apply_button(driver, b):
                    logger.debug("Clicked apply button via xpath %r", xpath)
                    if _wait_for_easy_apply_modal(driver):
                        return True
                    logger.warning("Apply button clicked but Easy Apply modal did not open.")
                    return False

        # 3) JS fallback — scoped to the detail pane and skipping search-filter
        #    controls, so it can never hit the "Easy Apply filter" pill.
        clicked = driver.execute_script("""
            var scope = document.querySelector('.jobs-search__job-details')
                || document.querySelector('.scaffold-layout__detail')
                || document.querySelector('.jobs-details')
                || document;
            var btns = Array.from(scope.querySelectorAll('button'));
            for (var b of btns) {
                var id = b.id || '';
                var label = (b.getAttribute('aria-label') || '').toLowerCase();
                var text = (b.textContent || '').trim().toLowerCase();
                if (id.indexOf('searchFilter') === 0 || label.indexOf('filter') !== -1) continue;
                if (b.closest('.search-reusables__filter-list, .search-filters-bar')) continue;
                if (label.indexOf('easy apply') === 0 || label.indexOf('in apply') !== -1 ||
                    text === 'easy apply' || text === 'in apply') {
                    var r = b.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0) {
                        b.scrollIntoView({block:'center'});
                        b.click();
                        return true;
                    }
                }
            }
            return false;
        """)
        if clicked:
            logger.debug("Clicked apply button via JS fallback")
            if _wait_for_easy_apply_modal(driver):
                return True
            logger.warning("Apply button clicked (JS fallback) but Easy Apply modal did not open.")
            return False

        logger.warning("Easy Apply button not found on this job. Page URL: %s", driver.current_url)
        return False
    except Exception:
        logger.exception("Exception in click_easy_apply_in_detail_panel")
        return False


def _fill_phone(scope, saved_answers: dict) -> None:
    """Fill Mobile phone number and optionally country code in Contact info / Easy Apply modal."""
    phone = saved_answers.get("phone") or ""
    phone = str(phone).strip()
    if not phone:
        return
    digits_only = "".join(c for c in phone if c.isdigit())
    country_code = str(saved_answers.get("phone_country_code") or "").strip()
    if country_code:
        try:
            for trigger in _find_in_modal(
                scope,
                By.XPATH,
                ".//*[contains(.,'Phone country code') or contains(.,'Country code')]/following::button[1]"
                " | .//*[contains(.,'Phone country code')]/following::*[@role='combobox'][1]",
            ):
                if trigger.is_displayed():
                    trigger.click()
                    time.sleep(0.5)
                    for opt in scope.find_elements(By.XPATH, f".//*[contains(., '{country_code}')]"):
                        if opt.is_displayed() and (
                            country_code in opt.text
                            or (len(country_code) <= 4 and country_code in opt.text)
                        ):
                            opt.click()
                            time.sleep(0.3)
                            break
                    break
        except Exception:
            logger.debug("Phone country code selection failed.", exc_info=True)
    for sel in [
        "input[type='tel']",
        "input[placeholder*='Mobile phone']",
        "input[placeholder*='phone number']",
        "input[placeholder*='Phone']",
        "input[id*='phone']",
        "input[name*='phone']",
        "input[name*='mobile']",
    ]:
        for inp in _find_in_modal(scope, By.CSS_SELECTOR, sel):
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
        ".//label[contains(.,'Mobile phone') or contains(.,'Phone number')]/following::input[1]",
        ".//*[contains(.,'Mobile phone number')]/following::input[1]",
        ".//input[contains(@placeholder,'phone') or contains(@placeholder,'Phone')]",
        ".//input[contains(@aria-label,'phone') or contains(@aria-label,'Phone')]",
    ]:
        try:
            for inp in _find_in_modal(scope, By.XPATH, xpath):
                if inp.is_displayed():
                    inp.clear()
                    inp.send_keys(phone if len(phone) <= 20 else digits_only)
                    time.sleep(0.3)
                    return
        except Exception:
            pass


def _field_hint_for_input(driver, inp) -> str:
    """Label or nearby text describing what this input is for."""
    try:
        return driver.execute_script(
            "var el=arguments[0];"
            "if(el.labels&&el.labels.length) return el.labels[0].innerText||'';"
            "var c=el.closest('div,fieldset,section,li');"
            "var lab=c&&c.querySelector('label');"
            "return lab?(lab.innerText||''):'';",
            inp,
        ) or ""
    except Exception:
        return ""


def _input_for_label(driver, scope, label_text: str):
    """Return the input/textarea that actually belongs to a label.

    Uses the label's `for` attribute (or a wrapped input), falling back to inputs
    inside the same field container. Avoids the old `following::input[1]` bug where
    email could land in the next unrelated field (e.g. Location/city).
    """
    lt = label_text.strip().lower()
    if not lt:
        return None
    label_xpath = (
        ".//label[contains(translate(normalize-space(.), "
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), "
        f"'{lt}')]"
    )
    for label in _find_in_modal(scope, By.XPATH, label_xpath):
        if not label.is_displayed():
            continue
        target_id = (label.get_attribute("for") or "").strip()
        if target_id:
            # By.ID handles ids with dots/colons that would break a raw #id CSS selector.
            try:
                for inp in scope.find_elements(By.ID, target_id):
                    if inp.is_displayed() and _input_accepts_text(inp):
                        return inp
            except Exception:
                logger.debug("Lookup by label 'for' id %r failed.", target_id, exc_info=True)
        for inp in label.find_elements(By.XPATH, ".//input | .//textarea"):
            if inp.is_displayed() and _input_accepts_text(inp):
                return inp
        for container_xpath in (
            "./ancestor::div[contains(@class,'field')][1]",
            "./ancestor::div[contains(@class,'form-group')][1]",
            "./ancestor::*[self::div or self::fieldset][1]",
        ):
            containers = label.find_elements(By.XPATH, container_xpath)
            if not containers:
                continue
            container = containers[0]
            for inp in container.find_elements(By.XPATH, ".//input | .//textarea"):
                if inp.is_displayed() and _input_accepts_text(inp):
                    return inp
    return None


def _looks_like_email(val: str) -> bool:
    val = str(val or "").strip()
    return "@" in val and "." in val.split("@", 1)[-1]


def _hint_mentions(hint: str, *needles: str) -> bool:
    h = hint.lower()
    return any(n.lower() in h for n in needles)


def _fill_contact_info(driver, scope, saved_answers: dict) -> None:
    """Fill first name, last name, and email inside the Easy Apply modal only."""
    field_map = [
        ("First name", "first_name", ["first"], ["input[name*='first']", "input[id*='first']"]),
        ("Last name", "last_name", ["last"], ["input[name*='last']", "input[id*='last']"]),
        ("Email address", "email", ["email"], ["input[type='email']", "input[name*='email']", "input[id*='email']"]),
        ("Email", "email", ["email"], ["input[type='email']", "input[name*='email']", "input[id*='email']"]),
    ]
    seen_keys: set[str] = set()
    for label_text, key, hint_needles, css_selectors in field_map:
        if key in seen_keys:
            continue
        val = (saved_answers.get(key) or "").strip()
        if not val:
            continue
        filled = False
        inp = _input_for_label(driver, scope, label_text)
        if inp is not None:
            hint = _field_hint_for_input(driver, inp)
            if _hint_mentions(hint, *hint_needles) and not _hint_mentions(
                hint, "city", "location", "town", "phone"
            ):
                try:
                    inp.clear()
                    inp.send_keys(val)
                    time.sleep(0.2)
                    filled = True
                except Exception:
                    logger.debug("Label-based fill failed for %r", label_text, exc_info=True)
        if not filled:
            for sel in css_selectors:
                try:
                    for inp in _find_in_modal(scope, By.CSS_SELECTOR, sel):
                        if not inp.is_displayed() or not _input_accepts_text(inp):
                            continue
                        hint = _field_hint_for_input(driver, inp)
                        if _hint_mentions(hint, "city", "location", "town") and not _hint_mentions(
                            hint, "email"
                        ):
                            continue
                        inp.clear()
                        inp.send_keys(val)
                        time.sleep(0.2)
                        filled = True
                        break
                    if filled:
                        break
                except Exception:
                    pass
        if filled:
            seen_keys.add(key)


def _input_accepts_text(inp) -> bool:
    """True if this input takes typed text (not a select/file/checkbox/radio/button)."""
    try:
        tag = (inp.tag_name or "").lower()
        if tag == "textarea":
            return True
        if tag == "select":
            return False
        itype = (inp.get_attribute("type") or "text").lower()
        return itype not in ("file", "checkbox", "radio", "button", "submit", "hidden", "image")
    except Exception:
        return True


_IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "webp", "bmp", "heic", "svg"}
_DOC_EXTS = {"pdf", "doc", "docx", "rtf", "txt", "odt"}


def _file_input_accept(fi) -> str:
    try:
        return (fi.get_attribute("accept") or "").lower()
    except Exception:
        return ""


def _file_input_accepts_document(fi, resume_ext: str) -> bool:
    """True if a file input's `accept` explicitly allows the resume's type."""
    accept = _file_input_accept(fi)
    if not accept:
        return False
    if resume_ext and (f".{resume_ext}" in accept or f"/{resume_ext}" in accept):
        return True
    if "application/pdf" in accept and resume_ext == "pdf":
        return True
    tokens = [t.strip() for t in accept.split(",") if t.strip()]
    return any(t.lstrip(".") in _DOC_EXTS for t in tokens)


def _file_input_is_image_only(fi) -> bool:
    """True if a file input only accepts images (so a PDF would be rejected)."""
    accept = _file_input_accept(fi)
    if not accept:
        return False
    tokens = [t.strip().lstrip(".") for t in accept.split(",") if t.strip()]
    if not tokens:
        return False
    for t in tokens:
        if t == "image/*" or t in _IMAGE_EXTS or t.startswith("image/"):
            continue
        return False
    return True


def _file_input_looks_like_photo(fi) -> bool:
    """Heuristic: nearby label/attrs mention photo/picture/avatar/headshot."""
    try:
        blob = " ".join(
            (fi.get_attribute(a) or "")
            for a in ("id", "name", "aria-label", "data-test-id")
        ).lower()
        driver = fi.parent
        nearby = driver.execute_script(
            "var el=arguments[0];"
            "var c=el.closest('div,fieldset,section');"
            "return c?(c.innerText||''):'';",
            fi,
        ) or ""
        blob += " " + str(nearby).lower()
        return any(k in blob for k in ("photo", "picture", "avatar", "headshot", "profile image"))
    except Exception:
        return False


def _file_input_accepts_image(fi, image_ext: str) -> bool:
    """True if a file input accepts the given image type."""
    if _file_input_is_image_only(fi):
        return True
    accept = _file_input_accept(fi)
    if not accept:
        return _file_input_looks_like_photo(fi)
    if image_ext and (f".{image_ext}" in accept or f"image/{image_ext}" in accept):
        return True
    if "image/*" in accept:
        return image_ext in _IMAGE_EXTS
    tokens = [t.strip().lstrip(".") for t in accept.split(",") if t.strip()]
    return any(t in _IMAGE_EXTS or t.startswith("image/") for t in tokens)


def _reveal_and_upload_file(driver, fi, abs_path: str) -> bool:
    try:
        driver.execute_script(
            "arguments[0].style.display='block';"
            "arguments[0].style.visibility='visible';"
            "arguments[0].style.opacity='1';",
            fi,
        )
        fi.send_keys(abs_path)
        time.sleep(2)
        return True
    except Exception:
        return False


def _select_label_text(driver, select_el) -> str:
    """Get the question/label text associated with a <select> in the modal."""
    try:
        return driver.execute_script(
            "var s=arguments[0];"
            "if(s.labels&&s.labels.length) return s.labels[0].innerText||'';"
            "var c=s.closest('div'); return c?(c.innerText||'').split('\\n')[0]:'';",
            select_el,
        ) or ""
    except Exception:
        return ""


def _choose_select_option(select_el, prefer_texts: list[str], allow_first: bool) -> bool:
    """Pick an option in a native <select> if it still shows the placeholder.
    Prefers options containing any of prefer_texts; if allow_first, falls back
    to the first real option. Returns True if a real value ends up selected."""
    try:
        sel = Select(select_el)
        options = sel.options
        if not options:
            return False
        current = (sel.first_selected_option.text or "").strip().lower()
        if current and "select an option" not in current:
            return True
        for want in prefer_texts:
            w = str(want or "").strip().lower()
            if not w:
                continue
            for i, o in enumerate(options):
                text = (o.text or "").strip()
                if text and w in text.lower():
                    sel.select_by_index(i)
                    time.sleep(0.3)
                    return True
        if allow_first:
            for i, o in enumerate(options):
                text = (o.text or "").strip().lower()
                if text and "select an option" not in text:
                    sel.select_by_index(i)
                    time.sleep(0.3)
                    return True
    except Exception:
        logger.debug("Could not choose select option.", exc_info=True)
    return False


def _fill_required_selects(driver, scope, saved_answers: dict) -> None:
    """Handle required dropdowns LinkedIn leaves on 'Select an option'.

    Email and phone-country-code selects only list the user's own verified
    values, so picking is safe. Sponsorship/visa selects use the saved answer.
    Anything else is left alone — better to skip the job than guess an answer.
    """
    email = str(saved_answers.get("email") or "").strip()
    country_code = str(saved_answers.get("phone_country_code") or "").strip()
    sponsorship = str(saved_answers.get("sponsorship") or "").strip()
    for select_el in _find_in_modal(scope, By.TAG_NAME, "select"):
        try:
            if not select_el.is_displayed():
                continue
            label = _select_label_text(driver, select_el).lower()
            if "email" in label:
                _choose_select_option(select_el, [email], allow_first=True)
            elif "country code" in label or "phone country" in label:
                _choose_select_option(select_el, [country_code], allow_first=True)
            elif sponsorship and any(k in label for k in ("sponsor", "visa", "work authorization")):
                _choose_select_option(select_el, [sponsorship], allow_first=False)
        except Exception:
            logger.debug("Required-select fill failed.", exc_info=True)


def _fill_text_by_label(driver, scope, label_text: str, value: str) -> None:
    val = str(value or "").strip()
    if not val:
        return
    try:
        inp = _input_for_label(driver, scope, label_text)
        if inp is not None and _input_accepts_text(inp):
            inp.clear()
            inp.send_keys(val)
            time.sleep(0.2)
    except Exception:
        logger.debug("Could not fill field for label %r", label_text, exc_info=True)


def _fill_city(driver, scope, city_val: str) -> None:
    """Fill Location/City fields only — never put email or other values here."""
    city_val = str(city_val or "").strip()
    if not city_val or _looks_like_email(city_val):
        return
    city_inp = None
    for sel in (
        "input[id*='city']",
        "input[name*='city']",
        "input[placeholder*='City']",
        "input[aria-label*='city']",
        "input[aria-label*='City']",
    ):
        for inp in _find_in_modal(scope, By.CSS_SELECTOR, sel):
            if inp.is_displayed() and _input_accepts_text(inp):
                city_inp = inp
                break
        if city_inp is not None:
            break
    if city_inp is None:
        for label in ("Location (city)", "City", "Location", "Town"):
            cand = _input_for_label(driver, scope, label)
            if cand is None or not _input_accepts_text(cand):
                continue
            hint = _field_hint_for_input(driver, cand)
            if _hint_mentions(hint, "city", "location", "town") or label.lower() in hint.lower():
                city_inp = cand
                break
    if city_inp is not None:
        hint = _field_hint_for_input(driver, city_inp)
        if _hint_mentions(hint, "email") and not _hint_mentions(hint, "city", "location", "town"):
            logger.debug("Skipping city fill — input looks like an email field (%r).", hint)
            return
        city_inp.clear()
        city_inp.send_keys(city_val)


def _fill_yes_no_question(scope, question_hint: str, answer: str) -> None:
    """Select Yes/No for sponsorship-style radio questions inside the modal."""
    val = str(answer or "").strip().lower()
    if val not in ("yes", "no"):
        return
    try:
        xpath = (
            f".//*[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), "
            f"'{question_hint.lower()}')]/following::label[contains(., '{answer.capitalize()}')][1]"
        )
        for opt in _find_in_modal(scope, By.XPATH, xpath):
            if opt.is_displayed():
                opt.click()
                time.sleep(0.2)
                return
    except Exception:
        logger.debug("Could not answer yes/no question %r", question_hint, exc_info=True)


def _fill_easy_apply_step(driver, saved_answers: dict, resume_path: str, photo_path: str = "") -> str:
    """One step: fill visible fields then return 'next', 'submitted', or 'skip'."""
    try:
        modal = _get_easy_apply_modal(driver)
        if modal is None:
            logger.warning("Easy Apply modal is not open; will only try footer buttons.")
            return _advance_easy_apply_step(driver)

        _fill_contact_info(driver, modal, saved_answers)
        _fill_phone(modal, saved_answers)
        _fill_required_selects(driver, modal, saved_answers)

        if saved_answers.get("city"):
            try:
                _fill_city(driver, modal, saved_answers["city"])
            except Exception:
                logger.debug("City fill failed.", exc_info=True)

        # Photo upload — only to image/photo file inputs (never the resume PDF).
        if photo_path and Path(photo_path).exists():
            abs_photo = str(Path(photo_path).resolve())
            photo_ext = Path(abs_photo).suffix.lower().lstrip(".")
            uploaded_photo = False
            try:
                file_inputs = _find_in_modal(modal, By.CSS_SELECTOR, "input[type='file']")
                photo_inputs = [
                    fi for fi in file_inputs
                    if _file_input_accepts_image(fi, photo_ext)
                    and not _file_input_accepts_document(fi, "pdf")
                ]
                if not photo_inputs:
                    photo_inputs = [
                        fi for fi in file_inputs
                        if _file_input_looks_like_photo(fi) or _file_input_is_image_only(fi)
                    ]
                for fi in photo_inputs:
                    if _reveal_and_upload_file(driver, fi, abs_photo):
                        uploaded_photo = True
                        logger.debug("Photo uploaded via file input: %s", abs_photo)
                        break
            except Exception:
                logger.debug("Photo upload failed.", exc_info=True)
            if not uploaded_photo:
                logger.debug("No photo file input found on this step. Path: %s", abs_photo)

        # Resume upload — scoped to modal only. Only send the CV to a file input
        # that actually accepts documents; never to an image/photo field.
        if resume_path and Path(resume_path).exists():
            abs_path = str(Path(resume_path).resolve())
            resume_ext = Path(abs_path).suffix.lower().lstrip(".")
            uploaded = False
            try:
                file_inputs = _find_in_modal(modal, By.CSS_SELECTOR, "input[type='file']")
                doc_inputs = [fi for fi in file_inputs if _file_input_accepts_document(fi, resume_ext)]
                if not doc_inputs:
                    doc_inputs = [
                        fi for fi in file_inputs
                        if not _file_input_is_image_only(fi) and not _file_input_looks_like_photo(fi)
                    ]
                for fi in doc_inputs:
                    if _reveal_and_upload_file(driver, fi, abs_path):
                        uploaded = True
                        logger.debug("Resume uploaded via file input: %s", abs_path)
                        break
            except Exception:
                logger.debug("Resume upload failed.", exc_info=True)
            if not uploaded:
                logger.warning(
                    "No document file input found for resume (skipped image/photo inputs). Path: %s",
                    abs_path,
                )

        # Cover letter textarea
        if saved_answers.get("cover_letter"):
            try:
                for t in _find_in_modal(modal, By.CSS_SELECTOR, "textarea"):
                    if t.is_displayed() and "cover" in (
                        t.get_attribute("name") or t.get_attribute("id") or ""
                    ).lower():
                        t.clear()
                        t.send_keys(saved_answers["cover_letter"])
                        break
            except Exception:
                logger.debug("Cover letter fill failed.", exc_info=True)

        if saved_answers.get("salary"):
            _fill_text_by_label(driver, modal, "salary", saved_answers["salary"])
            _fill_text_by_label(driver, modal, "compensation", saved_answers["salary"])
            _fill_text_by_label(driver, modal, "desired salary", saved_answers["salary"])

        if saved_answers.get("sponsorship"):
            _fill_yes_no_question(modal, "sponsorship", saved_answers["sponsorship"])
            _fill_yes_no_question(modal, "visa", saved_answers["sponsorship"])
            _fill_yes_no_question(modal, "work authorization", saved_answers["sponsorship"])

        # Start date (dropdown or input)
        if saved_answers.get("start_date"):
            try:
                start_val = saved_answers["start_date"]
                for dd in _find_in_modal(modal, By.CSS_SELECTOR, "select, [role='listbox']"):
                    if not dd.is_displayed():
                        continue
                    label = _find_in_modal(
                        modal,
                        By.XPATH,
                        ".//label[contains(.,'start') or contains(.,'Start') or contains(.,'available')]",
                    )
                    if dd.get_attribute("id") or (label and dd.location == label[0].location):
                        try:
                            dd.click()
                            time.sleep(0.5)
                            for o in _find_in_modal(
                                modal,
                                By.XPATH,
                                f".//*[contains(translate(., '{start_val[:4].upper()}', "
                                f"'{start_val[:4].lower()}'), '{start_val[:4].lower()}')]",
                            ):
                                if o.is_displayed():
                                    o.click()
                                    break
                        except Exception:
                            pass
                        break
                for inp in _find_in_modal(
                    modal,
                    By.XPATH,
                    ".//input[contains(@placeholder,'date') or contains(@placeholder,'Date') or contains(@id,'start')]",
                ):
                    if inp.is_displayed():
                        inp.clear()
                        inp.send_keys(start_val)
                        break
            except Exception:
                logger.debug("Start date fill failed.", exc_info=True)

        # Advance the Easy Apply wizard (Submit / Review / Next)
        return _advance_easy_apply_step(driver)
    except Exception:
        logger.exception("Error while filling Easy Apply step.")
        return "error"


def fill_easy_apply_modal(driver, saved_answers: dict, resume_path: str, photo_path: str = "") -> str:
    """
    Fill the Easy Apply modal with saved answers and optional resume.
    Clicks Next to get past 'Your profile matches' and similar screens, then fills and submits.
    Returns: 'submitted' | 'next' (gave up after max steps) | 'skip' | 'error'
    """
    try:
        WebDriverWait(driver, WAIT_TIMEOUT).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, ".jobs-easy-apply-modal, div[role='dialog'], [data-test-modal]")
            )
        )
    except Exception:
        logger.debug("Easy Apply modal container not detected immediately.", exc_info=True)
    time.sleep(1.5)
    max_steps = EASY_APPLY_MAX_STEPS
    for step in range(max_steps):
        result = _fill_easy_apply_step(driver, saved_answers, resume_path, photo_path)
        logger.debug("Easy Apply step %d/%d -> %s", step + 1, max_steps, result)
        if result == "submitted" or _application_submitted(driver):
            return "submitted"
        if result == "skip":
            return "skip"
        if result == "error":
            return "error"
        assert result == "next"
    return "next"


def close_modal(driver) -> None:
    """Close the Easy Apply modal (X / ESC), then confirm LinkedIn's
    'Save this application?' prompt by clicking Discard so no overlay is left
    blocking the next job."""
    try:
        dismissed = False
        modal = _get_easy_apply_modal(driver)
        if modal is not None:
            for b in modal.find_elements(By.CSS_SELECTOR, "button[aria-label*='Dismiss']"):
                if b.is_displayed():
                    b.click()
                    dismissed = True
                    break
        if not dismissed:
            discard = driver.find_elements(By.XPATH, "//button[contains(., 'Discard') or contains(., 'Cancel') or contains(., 'Close')]")
            if discard and discard[0].is_displayed():
                discard[0].click()
            else:
                driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        time.sleep(1.5)
        # Confirm the discard prompt if LinkedIn asks to save the application.
        for b in driver.find_elements(By.XPATH, "//button[contains(., 'Discard')]"):
            if b.is_displayed():
                b.click()
                break
        time.sleep(1.5)
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
    photo_path: str = "",
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
    result = fill_easy_apply_modal(driver, saved_answers, resume_path or "", photo_path or "")

    if result == "submitted" or _application_submitted(driver):
        close_modal(driver)
        return job_title, company_name, job_url, "applied"
    if result == "next":
        close_modal(driver)
        return job_title, company_name, job_url, "skipped (multi-step)"
    close_modal(driver)
    return job_title, company_name, job_url, "skipped (no submit)" if result == "skip" else "error"
