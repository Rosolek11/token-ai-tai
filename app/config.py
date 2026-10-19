"""Configuration loaded from environment variables, never from committed secrets."""

from dataclasses import dataclass
from os import environ


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

    @classmethod
    def from_env(cls) -> "Settings":
        public_api_base_url = environ.get("PUBLIC_API_BASE_URL", "").strip().rstrip("/")
        if public_api_base_url and not public_api_base_url.startswith(("http://", "https://")):
            raise ValueError("PUBLIC_API_BASE_URL must be an HTTP(S) URL or empty")

        def optional_secret(name: str) -> str | None:
            return environ.get(name, "").strip() or None

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
        )
