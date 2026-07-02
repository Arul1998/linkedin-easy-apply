"""Tests for configuration loading and validation."""

import json
import os
from pathlib import Path

import pytest

from config import get_config, validate_config


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LINKEDIN_EMAIL", "user@example.com")
    monkeypatch.setenv("LINKEDIN_PASSWORD", "secret")
    monkeypatch.setenv("CONFIG_FILE", str(tmp_path / "config.json"))
    return tmp_path


def test_get_config_from_env_only(isolated_env):
    (isolated_env / "config.json").write_text("{}", encoding="utf-8")
    cfg = get_config()
    assert cfg.email == "user@example.com"
    assert cfg.password == "secret"


def test_validate_config_missing_credentials(isolated_env, monkeypatch):
    monkeypatch.delenv("LINKEDIN_EMAIL")
    monkeypatch.delenv("LINKEDIN_PASSWORD")
    cfg = get_config()
    issues = validate_config(cfg)
    assert any(i.level == "error" for i in issues)


def test_validate_config_warns_missing_resume(isolated_env):
    cfg = get_config()
    cfg.resume_path = str(isolated_env / "missing.pdf")
    issues = validate_config(cfg)
    assert any("Resume file not found" in i.message for i in issues)


def test_config_file_overrides_search(isolated_env):
    config = {
        "search": {"keywords": "backend engineer", "location": "London"},
        "max_applications": 3,
    }
    path = isolated_env / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    cfg = get_config()
    assert cfg.keywords == "backend engineer"
    assert cfg.location == "London"
    assert cfg.max_applications == 3
