"""Tests for resume parsing and resume-driven form answers."""

from resume_profile import (
    ResumeProfile,
    answer_question,
    build_profile,
    numeric_part,
)

SAMPLE_RESUME = """
Arul Cornelious
Software Engineer | Angular, TypeScript, C#, .NET
London, UK | +44 7436 935144 | arulcornelious@example.com

PROFESSIONAL SUMMARY
Software Engineer with 5+ years of experience building enterprise web and
mobile B2B applications using Angular, TypeScript, .NET, SQL Server.
MSc Software Engineering (Merit) with the right to work in the UK.

PROFESSIONAL EXPERIENCE
Full Stack Developer, eoCiTO - London, UK Apr 2024 - Present
Delivered features using Angular, Capacitor, C#/.NET APIs, and SQL Server.

Front-End Developer, Raspberry Info Systems Sep 2023 - May 2024
Angular/Bootstrap interfaces; WebSocket real-time updates.

Software Developer, eProdCast Software May 2021 - Sep 2022
B2B collaboration platform with PDF signing and SQL storage.

Junior Developer, 10Decoders Oct 2019 - Apr 2021
EthOS Android app (Java); Venuelytics Angular booking UI; Node.js, MongoDB.

EDUCATION
MSc Software Engineering (Merit), University of Hertfordshire
B.E. Electronics and Communication Engineering

ADDITIONAL INFORMATION
Languages: English (Fluent), Tamil (Native)
Work authorization: Right to work in the UK
Notice Period: 8 weeks
"""


def _profile() -> ResumeProfile:
    return build_profile(SAMPLE_RESUME)


def test_build_profile_extracts_basics():
    p = _profile()
    assert p.total_years == 5
    assert "angular" in p.skills
    assert "typescript" in p.skills
    assert "c#" in p.skills
    assert ".net" in p.skills
    assert p.right_to_work is True
    assert p.notice_period.startswith("8 weeks")
    assert p.has_masters is True
    assert p.has_bachelors is True
    assert p.email == "arulcornelious@example.com"


def test_skill_years_from_job_blocks():
    p = _profile()
    # Angular appears in multiple job blocks spanning several years.
    assert p.skill_years.get("angular", 0) >= 3
    # Java only in the 2019-2021 job (~1.5 years).
    assert p.skill_years.get("java", 0) >= 1


def test_years_of_experience_questions():
    p = _profile()
    assert answer_question("How many years of work experience do you have with Angular?", p) not in (None, "0")
    assert answer_question("How many years of experience do you have with Rust?", p) == "0"
    assert answer_question("How many years of professional experience do you have?", p) == "5"


def test_authorization_and_sponsorship():
    p = _profile()
    assert answer_question("Are you legally authorized to work in the United Kingdom?", p) == "Yes"
    assert answer_question("Will you now or in the future require sponsorship for employment visa status?", p) == "No"


def test_notice_period_and_availability():
    p = _profile()
    assert "8" in answer_question("What is your notice period?", p)
    saved = {"start_date": "Immediately"}
    assert answer_question("When can you start?", p, saved) == "Immediately"


def test_skill_yes_no_and_education():
    p = _profile()
    assert answer_question("Do you have experience with Angular?", p) == "Yes"
    assert answer_question("Do you have experience with Kubernetes?", p) == "No"
    assert answer_question("Have you completed a Master's degree?", p) == "Yes"
    assert answer_question("Are you fluent in English?", p) == "Yes"


def test_custom_answers_take_priority():
    p = _profile()
    custom = {"years of experience with angular": "7"}
    assert (
        answer_question("How many years of experience do you have with Angular?", p, None, custom)
        == "7"
    )


def test_never_guess_salary_or_unknown():
    p = _profile()
    assert answer_question("What are your salary expectations?", p, {"salary": ""}) is None
    assert answer_question("What are your salary expectations?", p, {"salary": "45000"}) == "45000"
    assert answer_question("Describe a project you are proud of", p) is None


def test_numeric_part():
    assert numeric_part("8 weeks") == "8"
    assert numeric_part("5") == "5"
    assert numeric_part("Immediately") is None


def test_empty_profile_is_safe():
    p = build_profile("")
    assert answer_question("How many years of experience do you have with Angular?", p) is None
    assert answer_question("Are you legally authorized to work in the UK?", p) is None
