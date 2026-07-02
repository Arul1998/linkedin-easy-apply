"""
Build an answer profile from the configured resume and answer Easy Apply
form questions from it.

The profile is extracted once per resume file (cached) and used to answer
questions like "How many years of experience do you have with Angular?",
"Are you legally authorized to work in the UK?", or "What is your notice
period?" that are not covered by the static saved_answers config.

Answer priority (highest first):
1. `custom_answers` from config.json (question-substring -> answer)
2. Rules driven by the parsed resume (skills, years, authorization, ...)
3. Relevant `saved_answers` values (salary, start date, city)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

logger = logging.getLogger("linkedin_easy_apply.resume")

# Skills we can recognize in resumes and in question text. Lowercase.
KNOWN_SKILLS = [
    "angular", "react", "vue", "svelte", "typescript", "javascript", "rxjs",
    "html", "css", "scss", "sass", "tailwind", "bootstrap", "ionic", "capacitor",
    "c#", ".net", "asp.net", "dotnet", "java", "python", "node.js", "node",
    "sql", "sql server", "mysql", "postgresql", "mongodb", "firebase", "redis",
    "rest", "graphql", "websocket", "docker", "kubernetes", "aws", "azure", "gcp",
    "git", "github actions", "ci/cd", "agile", "scrum", "selenium", "jest",
    "openai", "ai", "machine learning", "php", "ruby", "go", "rust", "c++",
    "swift", "kotlin", "flutter", "react native", "next.js", "express",
]

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_DATE_RANGE_RE = re.compile(
    r"([A-Za-z]{3,9})\s+(\d{4})\s*[–—‒-]\s*(?:([A-Za-z]{3,9})\s+(\d{4})|Present|Current)",
    re.IGNORECASE,
)


@dataclass
class ResumeProfile:
    text: str = ""
    skills: set[str] = field(default_factory=set)
    total_years: int = 0
    skill_years: dict[str, int] = field(default_factory=dict)
    right_to_work: bool = False
    notice_period: str = ""
    has_bachelors: bool = False
    has_masters: bool = False
    email: str = ""
    phone: str = ""


def _extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            logger.warning("pypdf not installed — cannot read resume for answers. Run: pip install pypdf")
            return ""
        try:
            reader = PdfReader(str(path))
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception:
            logger.warning("Could not extract text from resume PDF: %s", path, exc_info=True)
            return ""
    if suffix in (".txt", ".md"):
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""
    if suffix in (".doc", ".docx"):
        try:
            import docx  # optional dependency

            return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)
        except Exception:
            logger.warning("Could not read %s resume (install python-docx for .docx support).", suffix)
            return ""
    return ""


def _parse_month(token: str) -> int | None:
    return _MONTHS.get(token[:3].lower())


def _job_blocks(text: str) -> list[tuple[int, str]]:
    """Split resume text into (duration_months, block_text) per date range."""
    matches = list(_DATE_RANGE_RE.finditer(text))
    blocks: list[tuple[int, str]] = []
    today = date.today()
    for i, m in enumerate(matches):
        start_month = _parse_month(m.group(1))
        if start_month is None:
            continue
        start = date(int(m.group(2)), start_month, 1)
        if m.group(3) and m.group(4):
            end_month = _parse_month(m.group(3)) or 12
            end = date(int(m.group(4)), end_month, 1)
        else:
            end = today
        months = max(0, (end.year - start.year) * 12 + (end.month - start.month))
        block_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        blocks.append((months, text[m.end():block_end]))
    return blocks


def _skill_pattern(skill: str) -> re.Pattern[str]:
    # Escape and use lookarounds instead of \b so symbols like C# and .NET work.
    escaped = re.escape(skill)
    return re.compile(rf"(?<![\w#+.]){escaped}(?![\w#+])", re.IGNORECASE)


def _find_skills(text: str) -> set[str]:
    return {s for s in KNOWN_SKILLS if _skill_pattern(s).search(text)}


def build_profile(text: str) -> ResumeProfile:
    """Parse raw resume text into an answerable profile."""
    profile = ResumeProfile(text=text)
    if not text.strip():
        return profile

    lower = text.lower()
    profile.skills = _find_skills(text)

    # Explicit "N+ years" claim wins; otherwise sum distinct job durations.
    m = re.search(r"(\d{1,2})\s*\+?\s*years?", lower)
    blocks = _job_blocks(text)
    computed_months = sum(months for months, _ in blocks)
    if m:
        profile.total_years = int(m.group(1))
    elif computed_months:
        profile.total_years = max(1, computed_months // 12)

    for skill in profile.skills:
        pattern = _skill_pattern(skill)
        months = sum(m_ for m_, block in blocks if pattern.search(block))
        if months:
            years = max(1, months // 12)
            # Overlapping job date ranges can over-count; never exceed total.
            if profile.total_years:
                years = min(years, profile.total_years)
            profile.skill_years[skill] = years

    profile.right_to_work = bool(
        re.search(r"right to work|authori[sz]ed to work|work authori[sz]ation", lower)
    )
    notice = re.search(r"notice period\s*[:\-]?\s*([^\n]+)", lower)
    if notice:
        profile.notice_period = notice.group(1).strip().rstrip(".")

    profile.has_masters = bool(re.search(r"\bmsc\b|master'?s|\bm\.?tech\b|\bmba\b", lower))
    profile.has_bachelors = profile.has_masters or bool(
        re.search(r"\bbsc\b|bachelor|\bb\.?e\.?\b|\bb\.?tech\b", lower)
    )

    email = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
    if email:
        profile.email = email.group(0)
    phone = re.search(r"\+?\d[\d ()\-]{8,}\d", text)
    if phone:
        profile.phone = phone.group(0).strip()

    return profile


_PROFILE_CACHE: dict[str, ResumeProfile] = {}


def get_profile(resume_path: str) -> ResumeProfile:
    """Load (and cache) the profile for a resume file. Empty profile if unreadable."""
    if not resume_path:
        return ResumeProfile()
    path = Path(resume_path).expanduser()
    key = str(path.resolve()) if path.exists() else str(path)
    if key in _PROFILE_CACHE:
        return _PROFILE_CACHE[key]
    text = _extract_text(path) if path.exists() else ""
    profile = build_profile(text)
    if profile.skills or profile.total_years:
        logger.info(
            "Resume profile loaded: %d skills, %s years total experience, right_to_work=%s, notice=%r",
            len(profile.skills),
            profile.total_years,
            profile.right_to_work,
            profile.notice_period,
        )
    elif resume_path:
        logger.warning("Resume profile is empty — form questions will rely on custom_answers only.")
    _PROFILE_CACHE[key] = profile
    return profile


def _skill_in_question(question: str, profile: ResumeProfile) -> str | None:
    """Longest known skill mentioned in the question, or None."""
    found = [s for s in KNOWN_SKILLS if _skill_pattern(s).search(question)]
    return max(found, key=len) if found else None


_YES = "Yes"
_NO = "No"


def answer_question(
    question: str,
    profile: ResumeProfile,
    saved_answers: dict | None = None,
    custom_answers: dict | None = None,
) -> str | None:
    """Best answer for an Easy Apply form question, or None if we shouldn't guess."""
    q = " ".join(str(question or "").split()).lower()
    if not q:
        return None
    saved = saved_answers or {}
    resume_known = bool(profile.skills or profile.total_years)

    # 1) Explicit user-configured answers win. A key matches when it is a
    # substring of the question, or when every word of the key appears in it.
    for key, value in (custom_answers or {}).items():
        key_l = str(key or "").lower().strip()
        if not key_l:
            continue
        if key_l in q or all(w in q for w in key_l.split()):
            return str(value)

    # 2) Work authorization / sponsorship.
    if any(k in q for k in ("sponsor", "visa")):
        if "sponsor" in q or "require" in q or "need" in q:
            return _NO if profile.right_to_work else str(saved.get("sponsorship") or _YES)
    if any(k in q for k in ("authori", "right to work", "legally", "eligible to work", "permit")):
        if profile.right_to_work:
            return _YES
        return None

    # 3) Notice period / start availability.
    if "notice period" in q or ("notice" in q and "period" in q):
        return profile.notice_period or str(saved.get("start_date") or "") or None
    if any(k in q for k in ("when can you start", "start date", "available to start", "availability")):
        return str(saved.get("start_date") or "") or profile.notice_period or None

    # 4) Years-of-experience questions (only when we actually parsed a resume).
    if "experience" in q and ("year" in q or "how many" in q):
        if not resume_known:
            return None
        skill = _skill_in_question(q, profile)
        if skill is not None:
            if skill in profile.skills:
                return str(profile.skill_years.get(skill) or profile.total_years or 1)
            return "0"
        if profile.total_years:
            return str(profile.total_years)
        return None

    # 5) Have-you / are-you skill questions -> Yes/No from resume.
    if resume_known and any(
        k in q for k in ("do you have", "have you", "are you familiar", "are you proficient",
                         "experience with", "experience in", "experience using", "knowledge of")
    ):
        skill = _skill_in_question(q, profile)
        if skill is not None:
            return _YES if skill in profile.skills else _NO

    # 6) Education.
    if "master" in q and ("degree" in q or "master's" in q or "msc" in q):
        return _YES if profile.has_masters else _NO
    if "bachelor" in q or ("degree" in q and "do you" in q):
        return _YES if profile.has_bachelors else (_NO if "bachelor" in q else None)

    # 7) Language proficiency (forms usually just need Yes / proficiency level).
    if "english" in q:
        return _YES

    # 8) Commute / relocation / onsite-hybrid willingness.
    if any(k in q for k in ("commut", "relocat", "willing to work", "on-site", "onsite", "hybrid")):
        return _YES

    # 9) Salary expectations from config only (never guess).
    if any(k in q for k in ("salary", "compensation", "pay expectation", "rate")):
        return str(saved.get("salary") or "") or None

    if "city" in q or "location" in q:
        return str(saved.get("city") or "") or None

    return None


def numeric_part(answer: str) -> str | None:
    """Digits from an answer for numeric-only inputs (e.g. '8 weeks' -> '8')."""
    m = re.search(r"\d+(?:\.\d+)?", str(answer or ""))
    return m.group(0) if m else None
