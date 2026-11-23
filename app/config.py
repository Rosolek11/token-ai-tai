"""Configuration loaded from environment variables, never from committed secrets."""

from dataclasses import dataclass, field
from os import environ
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

GITHUB_LOCAL_CONFIG = Path(__file__).resolve().parents[1] / ".env.github"
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    solana_rpc_url: str
    public_api_base_url: str
    rugcheck_api_key: str | None
    birdeye_api_key: str | None
    solscan_api_key: str | None
    gmgn_api_key: str | None
    ai_api_key: str | None
    dextools_api_key: str | None = None
    openrouter_api_key: str | None = field(default=None, repr=False)
    bazaarlink_api_key: str | None = field(default=None, repr=False)
    ai_provider: str = "api"
    github_oauth_client_id: str | None = None
    github_oauth_client_secret: str | None = field(default=None, repr=False)
    public_origin: str = "http://localhost:8000"
    github_local_setup: bool = False
    github_app: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        public_api_base_url = environ.get("PUBLIC_API_BASE_URL", "").strip().rstrip("/")
        if public_api_base_url and not public_api_base_url.startswith(("http://", "https://")):
            raise ValueError("PUBLIC_API_BASE_URL must be an HTTP(S) URL or empty")

        def optional_secret(name: str) -> str | None:
            return environ.get(name, "").strip() or None

        ai_provider = environ.get("AI_PROVIDER", "api").strip()
        if ai_provider not in {"api", "github_copilot"}:
            raise ValueError("AI_PROVIDER must be api or github_copilot")
        public_origin = environ.get("TAI_PUBLIC_ORIGIN", "http://localhost:8000").strip().rstrip("/")
        origin = urlsplit(public_origin)
        if (not origin.hostname or origin.username is not None or origin.path or origin.query
                or origin.fragment or origin.scheme not in {"https", "http"}
                or origin.scheme == "http" and origin.hostname not in LOOPBACK_HOSTS
                or public_origin != f"{origin.scheme}://{origin.netloc}"):
            raise ValueError("TAI_PUBLIC_ORIGIN must be an HTTPS origin or an HTTP loopback origin")

        local_setup = (environ.get("GITHUB_LOCAL_SETUP") == "1" and origin.scheme == "http"
                       and origin.hostname in LOOPBACK_HOSTS)
        client_id = optional_secret("GITHUB_OAUTH_CLIENT_ID")
        client_secret = optional_secret("GITHUB_OAUTH_CLIENT_SECRET")
        github_app = environ.get("GITHUB_APP") == "1"
        if local_setup and not (client_id or client_secret) and GITHUB_LOCAL_CONFIG.is_file():
            registration = dotenv_values(GITHUB_LOCAL_CONFIG, interpolate=False)
            if registration.get("TAI_PUBLIC_ORIGIN") == public_origin:
                client_id = registration.get("GITHUB_OAUTH_CLIENT_ID") or None
                client_secret = registration.get("GITHUB_OAUTH_CLIENT_SECRET") or None
                github_app = bool(client_id and client_secret)

        return cls(
            database_url=environ.get("DATABASE_URL", "sqlite:///./token_ai.db"),
            solana_rpc_url=environ.get(
                "SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"
            ),
            public_api_base_url=public_api_base_url,
            rugcheck_api_key=optional_secret("RUGCHECK_API_KEY"),
            birdeye_api_key=optional_secret("BIRDEYE_API_KEY"),
            solscan_api_key=optional_secret("SOLSCAN_API_KEY"),
            gmgn_api_key=optional_secret("GMGN_API_KEY"),
            ai_api_key=optional_secret("AI_API_KEY"),
            dextools_api_key=optional_secret("DEXTOOLS_API_KEY"),
            openrouter_api_key=optional_secret("OPENROUTER_API_KEY"),
            bazaarlink_api_key=optional_secret("BAZAARLINK_API_KEY"),
            ai_provider=ai_provider,
            github_oauth_client_id=client_id,
            github_oauth_client_secret=client_secret,
            public_origin=public_origin,
            github_local_setup=local_setup,
            github_app=github_app,
        )
