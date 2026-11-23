"""GitHub OAuth for personal Copilot accounts. User tokens stay in process memory."""

import base64
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from hashlib import sha256
from html import escape
from hmac import compare_digest
import json
from pathlib import Path
import re
from secrets import token_urlsafe
from tempfile import NamedTemporaryFile
from threading import Lock
from time import monotonic
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from app import config
from app.ai_analysis import AIAnalysisStore

router = APIRouter(prefix="/api/auth/github")
SESSION_COOKIE = "tai_github_session"
OAUTH_COOKIE = "tai_github_state"
SETUP_COOKIE = "tai_github_setup"
OAUTH_AGE = 600
SESSION_AGE = 8 * 60 * 60
PRIVATE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


@dataclass
class GitHubSession:
    login: str
    token: str = field(repr=False)
    expires_at: float
    store: AIAnalysisStore = field(default_factory=AIAnalysisStore, repr=False)
    inference_lock: Lock = field(default_factory=Lock, repr=False)


@dataclass
class OAuthAttempt:
    verifier: str = field(repr=False)
    destination: str
    expires_at: float


@dataclass
class SetupAttempt:
    address: str
    expires_at: float


class GitHubSessions:
    def __init__(self):
        self.sessions: OrderedDict[str, GitHubSession] = OrderedDict()
        self.attempts: OrderedDict[str, OAuthAttempt] = OrderedDict()
        self.setups: OrderedDict[str, SetupAttempt] = OrderedDict()
        self.setup_lock = Lock()
        self.lock = Lock()

    def access(self, records, key, *, add=None, remove=False):
        with self.lock:
            now = monotonic()
            for expired in [key for key, value in records.items() if value.expires_at <= now]:
                del records[expired]
            if add is not None:
                records[key] = add
                if len(records) > 256:
                    records.popitem(last=False)
            return records.pop(key, None) if remove else records.get(key)


def enabled(settings) -> bool:
    return settings.ai_provider == "github_copilot"


def configured(settings) -> bool:
    return enabled(settings) and bool(settings.github_oauth_client_id and settings.github_oauth_client_secret)


def setup_available(request: Request) -> bool:
    settings = request.app.state.settings
    origin = urlsplit(settings.public_origin)
    return (enabled(settings) and not configured(settings) and settings.github_local_setup
            and not (settings.github_oauth_client_id or settings.github_oauth_client_secret)
            and origin.scheme == "http" and origin.hostname in config.LOOPBACK_HOSTS
            and request.client is not None and request.client.host in config.LOOPBACK_HOSTS)


def current_session(request: Request) -> GitHubSession | None:
    registry = request.app.state.github_sessions
    return registry.access(registry.sessions, request.cookies.get(SESSION_COOKIE))


def require_origin(request: Request) -> None:
    if request.headers.get("origin") != request.app.state.settings.public_origin:
        raise HTTPException(403, "GITHUB_ORIGIN_REQUIRED", headers=PRIVATE_HEADERS)


def redirect(destination: str) -> RedirectResponse:
    return RedirectResponse(destination, status_code=303, headers=PRIVATE_HEADERS)


def cookie(response: Response, key: str, value: str, age: int, origin: str) -> None:
    response.set_cookie(key, value, max_age=age, httponly=True, samesite="lax",
                        secure=origin.startswith("https://"))


@router.get("/session")
def session_status(request: Request, response: Response) -> dict:
    settings = request.app.state.settings
    ready = configured(settings)
    session = current_session(request) if ready else None
    response.headers.update(PRIVATE_HEADERS)
    status = {"enabled": enabled(settings), "configured": ready, "login": session.login if session else None}
    if setup_available(request):
        status["setupAvailable"] = True
    return status


@router.get("/login")
def login(request: Request, address: str = "") -> Response:
    settings = request.app.state.settings
    if not configured(settings) and not setup_available(request):
        raise HTTPException(503, "GITHUB_OAUTH_NOT_CONFIGURED", headers=PRIVATE_HEADERS)
    address = address if re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", address) else ""
    query = "?" + urlencode({"address": address}) if address else ""
    if request.url.netloc != urlsplit(settings.public_origin).netloc:
        return redirect(f"{settings.public_origin}{router.prefix}/login{query}")
    if not configured(settings):
        return begin_setup(request, address)

    state, verifier = token_urlsafe(32), token_urlsafe(48)
    destination = f"/token/{address}" if address else "/analysis"
    registry = request.app.state.github_sessions
    registry.access(registry.attempts, state, add=OAuthAttempt(verifier, destination, monotonic() + OAUTH_AGE))
    challenge = base64.urlsafe_b64encode(sha256(verifier.encode()).digest()).decode().rstrip("=")
    query = urlencode({"client_id": settings.github_oauth_client_id, "redirect_uri": callback_url(settings),
                       "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
                       "scope": "offline_access" if settings.github_app else "read:user", "prompt": "select_account"})
    response = redirect(f"https://github.com/login/oauth/authorize?{query}")
    cookie(response, OAUTH_COOKIE, state, OAUTH_AGE, settings.public_origin)
    return response


def callback_url(settings) -> str:
    return f"{settings.public_origin}{router.prefix}/callback"


def begin_setup(request: Request, address: str) -> HTMLResponse:
    settings = request.app.state.settings
    origin = settings.public_origin
    state = token_urlsafe(32)
    registry = request.app.state.github_sessions
    registry.access(registry.setups, state, add=SetupAttempt(address, monotonic() + OAUTH_AGE))
    manifest = json.dumps({
        "name": f"Token AI {state[:8]}", "url": origin,
        "description": "Sign in to Token AI and run analysis using your own GitHub Copilot subscription.",
        "redirect_url": f"{origin}{router.prefix}/setup/callback",
        "callback_urls": [callback_url(settings)], "public": True,
        # GitHub validates the URL even when webhook delivery is disabled.
        "hook_attributes": {"url": "https://example.com/github/webhook", "active": False},
        "default_permissions": {}, "default_events": [],
    })
    nonce = token_urlsafe(16)
    auto_submit = request.headers.get("sec-fetch-site") in {"same-origin", "none"}
    script = f"<script nonce='{nonce}'>document.getElementById('github').submit()</script>" if auto_submit else ""
    response = HTMLResponse(f'''<!doctype html><html lang="pl"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Token AI · GitHub</title>
<form action="https://github.com/settings/apps/new?state={state}" method="post" id="github">
<input type="hidden" name="manifest" value="{escape(manifest, quote=True)}">
<button type="submit">Kontynuuj na GitHubie</button></form>
{script}</html>''', headers={
        **PRIVATE_HEADERS, "Content-Security-Policy": f"default-src 'none'; script-src 'nonce-{nonce}'; "
        "form-action https://github.com; base-uri 'none'; frame-ancestors 'none'",
    })
    cookie(response, SETUP_COOKIE, state, OAUTH_AGE, origin)
    return response


def exchange_manifest(code: str) -> tuple[str, str]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", code):
        raise ValueError("Invalid GitHub manifest code")
    response = httpx.post(f"https://api.github.com/app-manifests/{code}/conversions", timeout=12, headers={
        "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
    }, trust_env=False)
    response.raise_for_status()
    data = response.json()
    client_id, secret = data.get("client_id"), data.get("client_secret")
    if not all(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]+", value) for value in (client_id, secret)):
        raise ValueError("Invalid GitHub App credentials")
    return client_id, secret


def save_registration(settings, client_id: str, secret: str) -> None:
    path = config.GITHUB_LOCAL_CONFIG
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                prefix=path.name + ".", delete=False) as output:
            temporary = Path(output.name)
            output.write(f"TAI_PUBLIC_ORIGIN={settings.public_origin}\nGITHUB_OAUTH_CLIENT_ID={client_id}\n"
                         f"GITHUB_OAUTH_CLIENT_SECRET={secret}\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@router.get("/setup/callback")
def setup_callback(request: Request, state: str = "", code: str = "") -> Response:
    settings = request.app.state.settings
    registry = request.app.state.github_sessions
    state_cookie = request.cookies.get(SETUP_COOKIE, "")
    if (not setup_available(request) or request.url.netloc != urlsplit(settings.public_origin).netloc
            or not state_cookie or not compare_digest(state.encode(), state_cookie.encode())):
        raise HTTPException(400, "GITHUB_SETUP_STATE_INVALID", headers=PRIVATE_HEADERS)
    attempt = registry.access(registry.setups, state, remove=True)
    if attempt is None:
        raise HTTPException(400, "GITHUB_SETUP_STATE_INVALID", headers=PRIVATE_HEADERS)

    destination = f"/token/{attempt.address}?github=setup_failed#ai" if attempt.address else "/analysis?github=setup_failed"
    with registry.setup_lock:
        if setup_available(request) and code:
            try:
                client_id, secret = exchange_manifest(code)
                save_registration(settings, client_id, secret)
                request.app.state.settings = replace(settings, github_oauth_client_id=client_id,
                                                     github_oauth_client_secret=secret, github_app=True)
            except (httpx.HTTPError, OSError, ValueError, AttributeError, TypeError):
                pass
        if configured(request.app.state.settings):
            destination = f"{router.prefix}/login"
            if attempt.address:
                destination += "?" + urlencode({"address": attempt.address})
    response = redirect(destination)
    response.delete_cookie(SETUP_COOKIE, httponly=True)
    return response


def exchange_code(settings, code: str, verifier: str) -> tuple[str, str, int]:
    with httpx.Client(timeout=8, follow_redirects=False, trust_env=False) as client:
        exchange = client.post("https://github.com/login/oauth/access_token", data={
            "client_id": settings.github_oauth_client_id, "client_secret": settings.github_oauth_client_secret,
            "code": code, "redirect_uri": callback_url(settings), "code_verifier": verifier,
        }, headers={"Accept": "application/json"})
        exchange.raise_for_status()
        data = exchange.json()
        token = data.get("access_token")
        expected_prefix = "ghu_" if settings.github_app else "gho_"
        if not isinstance(token, str) or not token.startswith(expected_prefix):
            raise ValueError("Expected a GitHub user access token")
        profile = client.get("https://api.github.com/user", headers={
            "Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        profile.raise_for_status()
        login = profile.json().get("login")
        if not isinstance(login, str) or not login:
            raise ValueError("Missing GitHub login")
        age = min(SESSION_AGE, int(data.get("expires_in", SESSION_AGE)))
        if age <= 0:
            raise ValueError("Expired GitHub token")
        return login, token, age


@router.get("/callback")
def callback(request: Request, state: str = "", code: str = "") -> RedirectResponse:
    settings = request.app.state.settings
    registry = request.app.state.github_sessions
    state_cookie = request.cookies.get(OAUTH_COOKIE, "")
    attempt = None
    if configured(settings) and state_cookie and compare_digest(state.encode(), state_cookie.encode()):
        attempt = registry.access(registry.attempts, state, remove=True)
    if attempt is None:
        raise HTTPException(400, "GITHUB_OAUTH_STATE_INVALID", headers=PRIVATE_HEADERS)
    destination = attempt.destination
    report = destination.startswith("/token/")
    response = redirect(destination + ("?github=login_failed#ai" if report else "?github=login_failed"))
    if code:
        try:
            login, token, age = exchange_code(settings, code, attempt.verifier)
        except (httpx.HTTPError, ValueError, AttributeError, TypeError):
            pass
        else:
            session_id = token_urlsafe(32)
            registry.access(registry.sessions, request.cookies.get(SESSION_COOKIE), remove=True)
            registry.access(registry.sessions, session_id, add=GitHubSession(login, token, monotonic() + age))
            response = redirect(destination + ("#ai" if report else ""))
            cookie(response, SESSION_COOKIE, session_id, age, settings.public_origin)
    response.delete_cookie(OAUTH_COOKIE, secure=settings.public_origin.startswith("https://"), httponly=True)
    return response


@router.post("/logout", status_code=204)
def logout(request: Request) -> Response:
    require_origin(request)
    registry = request.app.state.github_sessions
    registry.access(registry.sessions, request.cookies.get(SESSION_COOKIE), remove=True)
    response = Response(status_code=204, headers=PRIVATE_HEADERS)
    response.delete_cookie(SESSION_COOKIE, secure=request.app.state.settings.public_origin.startswith("https://"),
                           httponly=True)
    return response
