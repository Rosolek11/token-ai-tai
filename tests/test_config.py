import pytest

from app.config import Settings


def test_settings_are_loaded_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUBLIC_API_BASE_URL", "https://api.example.test/")
    monkeypatch.setenv("AI_API_KEY", "test-secret")
    settings = Settings.from_env()
    assert settings.public_api_base_url == "https://api.example.test"
    assert settings.ai_api_key == "test-secret"


def test_public_api_url_must_be_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUBLIC_API_BASE_URL", "javascript:alert(1)")
    with pytest.raises(ValueError, match="HTTP"):
        Settings.from_env()
