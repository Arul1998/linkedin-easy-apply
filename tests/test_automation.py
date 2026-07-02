"""Tests for LinkedIn URL building and helper utilities."""

from linkedin_automation import (
    build_jobs_search_url,
    _normalize_work_type,
    classify_modal_button_label,
    normalize_job_url,
)
from errors import humanize_skip_reason


def test_build_jobs_search_url_includes_easy_apply_filter():
    url = build_jobs_search_url("software engineer", "United Kingdom")
    assert "f_AL=true" in url
    assert "keywords=software+engineer" in url or "keywords=software%20engineer" in url


def test_build_jobs_search_url_includes_filters():
    url = build_jobs_search_url(
        keywords="frontend developer",
        location="London",
        work_type="Remote",
        job_type="F",
        date_posted="r604800",
        experience_level="3,4",
        few_applicants=True,
        geo_id="90009496",
    )
    assert "f_WT=2" in url
    assert "f_JT=F" in url
    assert "f_TPR=r604800" in url
    assert "f_E=3%2C4" in url or "f_E=3,4" in url
    assert "f_JIYN=true" in url
    assert "geoId=90009496" in url


def test_normalize_work_type_aliases():
    assert _normalize_work_type("Remote") == "2"
    assert _normalize_work_type("hybrid") == "3"
    assert _normalize_work_type("on-site") == "1"


def test_humanize_skip_reason():
    assert "duplicate" in humanize_skip_reason("already_applied").lower()
    assert humanize_skip_reason("applied") == "Application submitted successfully"


def test_normalize_job_url_strips_tracking_params():
    url = "https://www.linkedin.com/jobs/view/4012345678/?eBP=abc&refId=xyz&trackingId=123"
    assert normalize_job_url(url) == "https://www.linkedin.com/jobs/view/4012345678/"


def test_normalize_job_url_same_job_different_params_matches():
    a = normalize_job_url("https://www.linkedin.com/jobs/view/4012345678/?refId=aaa")
    b = normalize_job_url("https://www.linkedin.com/jobs/view/4012345678?trackingId=bbb")
    assert a == b


def test_normalize_job_url_uses_current_job_id_param():
    url = "https://www.linkedin.com/jobs/search/?currentJobId=4012345678&keywords=dev"
    assert normalize_job_url(url) == "https://www.linkedin.com/jobs/view/4012345678/"


def test_normalize_job_url_falls_back_to_stripping_query():
    assert normalize_job_url("") == ""
    assert (
        normalize_job_url("https://www.linkedin.com/jobs/collections/recommended/?foo=1")
        == "https://www.linkedin.com/jobs/collections/recommended/"
    )


def test_classify_modal_button_label():
    assert classify_modal_button_label("Submit application") == "submit"
    assert classify_modal_button_label("Continue to next step") == "next"
    assert classify_modal_button_label("Review your application") == "review"
    assert classify_modal_button_label("Discard") is None
    assert classify_modal_button_label("Easy Apply") is None

