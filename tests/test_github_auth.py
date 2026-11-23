from base64 import urlsafe_b64encode
from dataclasses import replace
from hashlib import sha256
from html.parser import HTMLParser
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
import pytest

from app import config, copilot_analysis, github_auth
from app.main import app
from app.security_data import get_security_client
from app.source_data import NormalizedSourceData, SourceValue

ORIGIN = "http://localhost:8000"
AUTH = "/api/auth/github"
ADDRESS = "So11111111111111111111111111111111111111112"
ANALYSIS = f"/api/tokens/{ADDRESS}/ai-analysis"


@pytest.fixture
def copilot_settings(monkeypatch):
    settings = replace(app.state.settings, ai_provider="github_copilot", public_origin=ORIGIN,
                       github_oauth_client_id="test-id", github_oauth_client_secret="test-secret",
                       bazaarlink_api_key="legacy-provider-key")
    monkeypatch.setattr(app.state, "settings", settings)
    monkeypatch.setattr(app.state, "github_sessions", github_auth.GitHubSessions())
    return settings


def begin_login(client):
    response = client.get(f"{AUTH}/login", params={"address": ADDRESS}, follow_redirects=False)
    url = urlsplit(response.headers["location"])
    assert (url.scheme, url.netloc, url.path) == ("https", "github.com", "/login/oauth/authorize")
    assert "HttpOnly" in response.headers["set-cookie"]
    return {key: values[0] for key, values in parse_qs(url.query).items()}


def finish_login(client, state, name):
    return client.get(f"{AUTH}/callback", params={"state": state, "code": name}, follow_redirects=False)


def test_two_users_keep_their_copilot_credentials_and_reports_separate(monkeypatch, copilot_settings):
    with TestClient(app, base_url=ORIGIN) as alice, TestClient(app, base_url=ORIGIN) as bob:
        alice_request, bob_request = begin_login(alice), begin_login(bob)
        assert alice_request["state"] != bob_request["state"]
        assert alice_request["redirect_uri"] == f"{ORIGIN}{AUTH}/callback"
        assert alice_request["code_challenge_method"] == "S256"
        assert finish_login(bob, alice_request["state"], "alice").status_code == 400

        def exchange(settings, code, verifier):
            challenge = urlsafe_b64encode(sha256(verifier.encode()).digest()).decode().rstrip("=")
            assert challenge == {"alice": alice_request, "bob": bob_request}[code]["code_challenge"]
            return code, f"gho_{code}", 60

        monkeypatch.setattr(github_auth, "exchange_code", exchange)
        for client, attempt, login in [(alice, alice_request, "alice"), (bob, bob_request, "bob")]:
            response = finish_login(client, attempt["state"], login)
            assert response.headers["location"] == f"/token/{ADDRESS}#ai"
            assert "HttpOnly" in response.headers["set-cookie"]
            assert f"gho_{login}" not in str(response.headers)
            assert finish_login(client, attempt["state"], login).status_code == 400
            assert client.get(f"{AUTH}/session").json() == {"enabled": True, "configured": True, "login": login}

        data = NormalizedSourceData(price={"price_usd": SourceValue(value=2, unit="USD", sourceId="dexscreener")})
        monkeypatch.setitem(app.dependency_overrides, get_security_client, lambda: SimpleNamespace(
            fetch_token_security=lambda address: SimpleNamespace(normalized_data=data)))
        tokens = []

        def complete(token, messages, schema):
            tokens.append(token)
            assert "price.price_usd" in messages[1]["content"]
            assert "score" in schema["properties"]
            score = {"gho_alice": 12, "gho_bob": 56}[token]
            return json.dumps({"score": score, "summary": "Podsumowanie.", "fact_ids": ["price.price_usd"]})

        monkeypatch.setattr(copilot_analysis, "complete", complete)
        assert alice.post(ANALYSIS).status_code == 403
        assert alice.post(ANALYSIS, headers={"Origin": ORIGIN}).json()["score"] == 12
        assert bob.get(ANALYSIS).json()["status"] == "no_data"
        assert bob.post(ANALYSIS, headers={"Origin": ORIGIN}).json()["score"] == 56
        assert tokens == ["gho_alice", "gho_bob"]
        assert alice.get(ANALYSIS).json()["score"] == 12
        assert bob.get(ANALYSIS).headers["cache-control"] == "no-store"
        assert alice.post(f"{AUTH}/logout", headers={"Origin": "https://other.example"}).status_code == 403
        assert alice.post(f"{AUTH}/logout", headers={"Origin": ORIGIN}).status_code == 204
        assert alice.get(ANALYSIS).status_code == 401
        assert alice.post(ANALYSIS, headers={"Origin": ORIGIN}).status_code == 401
        assert bob.get(ANALYSIS).json()["score"] == 56


def test_missing_oauth_config_blocks_legacy_provider_fallback(monkeypatch, copilot_settings):
    monkeypatch.setattr(app.state, "settings", replace(copilot_settings, github_oauth_client_secret=None))
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get(f"{AUTH}/session").json() == {"enabled": True, "configured": False, "login": None}
        assert client.get(f"{AUTH}/login").status_code == 503
        assert client.post(ANALYSIS, headers={"Origin": ORIGIN}).status_code == 503


def test_local_first_click_registers_an_app_then_starts_normal_sign_in(monkeypatch, tmp_path, copilot_settings):
    monkeypatch.setattr(app.state, "settings", replace(copilot_settings, github_oauth_client_id=None,
                       github_oauth_client_secret=None, github_local_setup=True))
    registration = tmp_path / ".env.github"
    monkeypatch.setattr(config, "GITHUB_LOCAL_CONFIG", registration)

    class GitHubForm(HTMLParser):
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "form":
                self.action = urlsplit(attrs["action"])
            if tag == "input" and attrs.get("name") == "manifest":
                self.manifest = json.loads(attrs["value"])

    with TestClient(app, base_url=ORIGIN, client=("127.0.0.1", 50001)) as client:
        assert client.get(f"{AUTH}/session").json()["setupAvailable"]
        response = client.get(f"{AUTH}/login", params={"address": ADDRESS}, headers={"Sec-Fetch-Site": "same-origin"})
        assert response.status_code == 200
        assert ".submit()" in response.text
        form = GitHubForm()
        form.feed(response.text)
        assert (form.action.netloc, form.action.path) == ("github.com", "/settings/apps/new")
        assert form.manifest["callback_urls"] == [f"{ORIGIN}{AUTH}/callback"]
        assert form.manifest["redirect_url"] == f"{ORIGIN}{AUTH}/setup/callback"
        assert form.manifest["public"] and form.manifest["default_permissions"] == {}
        assert form.manifest["hook_attributes"] == {"url": "https://example.com/github/webhook", "active": False}
        state = parse_qs(form.action.query)["state"][0]
        with TestClient(app, base_url=ORIGIN, client=("203.0.113.1", 50001)) as remote:
            assert remote.get(f"{AUTH}/login").status_code == 503
        assert client.get(f"{AUTH}/setup/callback", params={"state": "wrong", "code": "registration"}).status_code == 400

        def exchange(code):
            assert code == "registration"
            return "test-app-id", "synthetic-secret"

        monkeypatch.setattr(github_auth, "exchange_manifest", exchange)
        redirect = client.get(f"{AUTH}/setup/callback", params={"state": state, "code": "registration"},
                              follow_redirects=False)
        assert redirect.headers["location"] == f"{AUTH}/login?address={ADDRESS}"
        assert "synthetic-secret" not in redirect.text and "synthetic-secret" not in str(redirect.headers)
        assert client.get(f"{AUTH}/session").json()["configured"]
        assert begin_login(client)["scope"] == "offline_access"
        assert client.get(f"{AUTH}/setup/callback", params={"state": state, "code": "registration"}).status_code == 400

    monkeypatch.setenv("TAI_PUBLIC_ORIGIN", ORIGIN)
    monkeypatch.setenv("GITHUB_LOCAL_SETUP", "1")
    monkeypatch.delenv("GITHUB_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GITHUB_OAUTH_CLIENT_SECRET", raising=False)
    settings = config.Settings.from_env()
    assert settings.github_app and settings.github_oauth_client_id == "test-app-id"
    assert settings.github_oauth_client_secret == "synthetic-secret"


@pytest.mark.parametrize("last_event, expected_reason", [
    (None, None),
    ("model.call_start", "copilot_answer_timeout"),
    ("assistant.message", "copilot_completion_timeout"),
])
def test_sdk_uses_the_user_token_and_reports_where_a_timeout_occurred(monkeypatch, last_event, expected_reason):
    class SDK:
        def __init__(self, **options):
            assert options["github_token"] == "gho_test"
            assert options["use_logged_in_user"] is False
            assert options["mode"] == "empty"
            assert "BAZAARLINK_API_KEY" not in options["env"]
            assert options["working_directory"] == options["base_directory"]

        async def start(self):
            pass

        async def create_session(self, **options):
            assert options["model"] == "auto"
            assert options["available_tools"] == []
            assert options["enable_config_discovery"] is False
            assert options["system_message"] == {"mode": "replace", "content": "system"}
            return self

        async def send_and_wait(self, message, *, response_schema, timeout):
            assert message == "facts"
            assert response_schema == {"type": "object"}
            assert timeout == copilot_analysis.ANSWER_TIMEOUT
            if last_event is not None:
                self.handler(SimpleNamespace(type=SimpleNamespace(value=last_event), agent_id=None))
                raise TimeoutError()
            return SimpleNamespace(data=SimpleNamespace(content="{}"))

        def on(self, handler):
            self.handler = handler
            return lambda: None

        async def force_stop(self):
            pass

    monkeypatch.setenv("BAZAARLINK_API_KEY", "test-key")
    monkeypatch.setattr(copilot_analysis, "CopilotClient", SDK)
    def complete():
        return copilot_analysis.complete("gho_test", [{"content": "system"}, {"content": "facts"}], {"type": "object"})

    if expected_reason is None:
        assert complete() == "{}"
    else:
        with pytest.raises(copilot_analysis.CopilotTimeout) as error:
            complete()
        assert error.value.reason == expected_reason
