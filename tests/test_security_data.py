import json
from pathlib import Path
from typing import Any, Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.market_data import DexScreenerClient, get_dexscreener_client
from app.security_data import SecurityDataClient, get_security_client

ADDRESS = "So11111111111111111111111111111111111111112"
RUGCHECK_URL = f"https://api.rugcheck.xyz/v1/tokens/{ADDRESS}/report"
DEXSCREENER_URL = f"https://api.dexscreener.com/token-pairs/v1/solana/{ADDRESS}"
DEXTOOLS_URL = f"https://public-api.dextools.io/trial/v2/token/solana/{ADDRESS}/audit"
GMGN_URL = f"https://gmgn.ai/defi/quotation/v1/tokens/security/sol/{ADDRESS}"


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def rugcheck_payload(fixtures_dir: Path) -> dict[str, Any]:
    return json.loads((fixtures_dir / "rugcheck_solana.json").read_text(encoding="utf-8"))


@pytest.fixture
def dexscreener_payload(fixtures_dir: Path) -> list[dict[str, Any]]:
    raw = json.loads((fixtures_dir / "dexscreener_solana.json").read_text(encoding="utf-8"))
    raw[0].update(
        {
            "priceNative": "1.0",
            "fdv": 61200000000.0,
            "marketCap": 50100000000.0,
            "pairCreatedAt": 1700000000000,
            "labels": ["CLMM"],
            "boosts": {"active": 2},
            "liquidity": {"usd": 29632649.49, "base": 150000.0, "quote": 13500000.0},
            "volume": {"m5": 250000.0, "h1": 4200000.0, "h6": 31000000.0, "h24": 144375727.36},
            "priceChange": {"m5": 0.15, "h1": 0.85, "h6": 1.4, "h24": 2.22},
            "txns": {
                "m5": {"buys": 42, "sells": 38},
                "h1": {"buys": 510, "sells": 480},
                "h6": {"buys": 3100, "sells": 2900},
                "h24": {"buys": 12400, "sells": 10000},
            },
            "info": {
                "imageUrl": "https://solana.com/logo.png",
                "websites": [{"label": "Website", "url": "https://solana.com"}],
                "socials": [{"type": "twitter", "url": "https://x.com/solana"}],
            },
        }
    )
    return raw


@pytest.fixture
def dextools_payload(fixtures_dir: Path) -> dict[str, Any]:
    return json.loads((fixtures_dir / "dextools_solana.json").read_text(encoding="utf-8"))


@pytest.fixture
def gmgn_payload(fixtures_dir: Path) -> dict[str, Any]:
    return json.loads((fixtures_dir / "gmgn_solana.json").read_text(encoding="utf-8"))


def test_security_report_aggregates_all_four_sources_and_normalizes_flags(
    rugcheck_payload: dict[str, Any],
    dexscreener_payload: list[dict[str, Any]],
    dextools_payload: dict[str, Any],
    gmgn_payload: dict[str, Any],
) -> None:
    recorded_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded_requests.append(request)
        url = str(request.url)
        if url == RUGCHECK_URL:
            return httpx.Response(200, json=rugcheck_payload)
        if url == DEXSCREENER_URL:
            return httpx.Response(200, json=dexscreener_payload)
        if url == DEXTOOLS_URL:
            return httpx.Response(200, json=dextools_payload)
        if url == GMGN_URL:
            return httpx.Response(200, json=gmgn_payload)
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        security_client = SecurityDataClient(
            http_client,
            rugcheck_api_key="rc-key",
            dextools_api_key="dt-key",
            gmgn_api_key="gmgn-key",
        )
        market_client = DexScreenerClient(http_client)
        app.dependency_overrides[get_dexscreener_client] = lambda: market_client
        app.dependency_overrides[get_security_client] = lambda: security_client
        try:
            with TestClient(app) as client:
                response = client.post("/analyses/token", json={"address": ADDRESS})
                direct_response = client.get(f"/api/tokens/{ADDRESS}/security")
        finally:
            app.dependency_overrides.pop(get_dexscreener_client, None)
            app.dependency_overrides.pop(get_security_client, None)

    assert response.status_code == 201
    assert direct_response.status_code == 200
    security = response.json()["security_data"]
    assert security["address"] == ADDRESS
    assert security["read_only"] is True
    assert security["overall_status"] == "ok"

    for source_name in ("rugcheck", "dexscreener", "dextools", "gmgn"):
        src = security["sources"][source_name]
        assert src["status"] == "ok"
        assert src["http_status"] == 200
        assert src["read_only"] is True

    # Normalized risk & authorities
    assert security["risk_summary"]["risk_level"] == "low"
    assert security["risk_summary"]["normalized_score"] == 12.5
    assert security["risk_summary"]["safety_score"] == 87.5
    assert security["risk_summary"]["is_honeypot"] is False
    assert security["risk_summary"]["rugged"] is False

    auth = security["authorities"]
    assert auth["mint_authority_active"] is False
    assert auth["freeze_authority_active"] is False
    assert auth["mutable_metadata"] is False
    assert auth["is_open_source"] is True
    assert auth["is_proxy"] is False
    assert auth["is_contract_renounced"] is True

    # Holder distribution & insider telemetry
    holders = security["holder_distribution"]
    assert holders["holder_count"] == 485210
    assert holders["top_holder_pct"] == 12.5
    assert holders["top_10_holders_pct"] == 21.0
    assert holders["bundled_supply_pct"] == 4.2
    assert holders["sniper_holders_count"] == 3
    assert holders["sniper_supply_pct"] == 1.5
    assert holders["dev_rug_history_count"] == 0
    assert len(holders["top_holders"]) == 2

    # Liquidity & deep market activity
    liq = security["liquidity_security"]
    assert liq["lp_locked_pct"] == 94.5
    assert liq["lp_burned_pct"] == 91.5
    assert liq["lp_providers_count"] == 142
    assert liq["lockers_count"] == 1

    act = security["market_activity"]
    assert act["fdv_usd"] == 61200000000.0
    assert act["market_cap_usd"] == 50100000000.0
    assert act["buys_24h"] == 12400
    assert act["sells_24h"] == 10000
    assert act["total_txns_24h"] == 22400
    assert act["buy_sell_ratio_24h"] == 1.24
    assert act["volume_1h_usd"] == 4200000.0
    assert act["active_boosts"] == 2

    # Normalized boolean flags
    norm_flags = security["normalized_flags"]
    assert norm_flags["mint_authority_enabled"] is False
    assert norm_flags["freeze_authority_enabled"] is False
    assert norm_flags["mutable_metadata"] is False
    assert norm_flags["lp_not_locked"] is False
    assert norm_flags["high_holder_concentration"] is False
    assert norm_flags["honeypot_detected"] is False
    assert norm_flags["rugged_token"] is False
    assert norm_flags["bundled_launch_detected"] is False
    assert norm_flags["low_liquidity_warning"] is False

    # Strictly read-only GET requests, no trading or scraping endpoints
    assert all(req.method == "GET" for req in recorded_requests)
    assert security["ai_context_payload"]["address"] == ADDRESS


@pytest.mark.parametrize(
    ("status_code", "expected_reason"),
    [
        (401, "access_denied"),
        (403, "access_denied"),
        (429, "rate_limited"),
        (500, "http_error"),
        (503, "http_error"),
    ],
)
def test_lack_of_access_and_429_are_marked_unavailable_without_crashing_report(
    status_code: int,
    expected_reason: str,
    dexscreener_payload: list[dict[str, Any]],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == DEXSCREENER_URL:
            return httpx.Response(200, json=dexscreener_payload)
        return httpx.Response(status_code, json={"error": "blocked or rate limited"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        security_client = SecurityDataClient(
            http_client,
            rugcheck_api_key="rc-key",
            dextools_api_key="dt-key",
            gmgn_api_key="gmgn-key",
        )
        result = security_client.fetch_token_security(ADDRESS)

    assert result.overall_status == "partial"
    assert result.sources["dexscreener"].status == "ok"
    for source_name in ("rugcheck", "dextools", "gmgn"):
        src = result.sources[source_name]
        assert src.status == "unavailable"
        assert src.reason == expected_reason
        assert src.http_status == status_code

    # Unavailable sources must not invent false-safe values
    assert result.authorities.mint_authority_active is None
    assert result.authorities.freeze_authority_active is None
    assert result.risk_summary.is_honeypot is None
    assert result.normalized_flags["mint_authority_enabled"] is None


def test_gmgn_without_api_key_is_marked_unavailable_and_not_called(
    rugcheck_payload: dict[str, Any],
    dexscreener_payload: list[dict[str, Any]],
    dextools_payload: dict[str, Any],
) -> None:
    called_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        called_urls.append(url)
        if url == RUGCHECK_URL:
            return httpx.Response(200, json=rugcheck_payload)
        if url == DEXSCREENER_URL:
            return httpx.Response(200, json=dexscreener_payload)
        if url == DEXTOOLS_URL:
            return httpx.Response(401)
        return httpx.Response(500)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        security_client = SecurityDataClient(
            http_client,
            rugcheck_api_key=None,
            dextools_api_key=None,
            gmgn_api_key=None,
        )
        result = security_client.fetch_token_security(ADDRESS)

    assert GMGN_URL not in called_urls
    assert result.sources["gmgn"].status == "unavailable"
    assert result.sources["gmgn"].reason == "missing_api_key"
    assert result.sources["dextools"].status == "unavailable"
    assert result.sources["dextools"].reason == "missing_api_key"
    assert result.sources["rugcheck"].status == "ok"
    assert result.sources["dexscreener"].status == "ok"


def test_missing_data_and_404_are_handled_gracefully() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == DEXSCREENER_URL:
            return httpx.Response(200, json=[])
        if url == RUGCHECK_URL:
            return httpx.Response(404, json={"error": "Token not found"})
        if url == DEXTOOLS_URL:
            return httpx.Response(200, json={"data": {}})
        if url == GMGN_URL:
            return httpx.Response(200, json={"code": 0, "data": {}})
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        security_client = SecurityDataClient(
            http_client,
            dextools_api_key="dt-key",
            gmgn_api_key="gmgn-key",
        )
        result = security_client.fetch_token_security(ADDRESS)

    assert result.overall_status == "no_data"
    for source_name in ("rugcheck", "dexscreener", "dextools", "gmgn"):
        assert result.sources[source_name].status == "no_data"
        assert result.sources[source_name].reason == "not_found"
    assert result.risk_summary.risk_level == "unknown"
    assert result.holder_distribution.holder_count is None
    assert result.liquidity_security.lp_locked_pct is None


def test_high_risk_token_flags_are_normalized_to_critical() -> None:
    risky_rugcheck = {
        "mintAuthority": "Auth111111111111111111111111111111111111111",
        "freezeAuthority": "Freez11111111111111111111111111111111111111",
        "tokenMeta": {"mutable": True},
        "topHolders": [{"address": "Whale1111111111111111111111111111111111111", "pct": 65.0}],
        "markets": [{"pubkey": "Pool11111111111111111111111111111111111111", "lp": {"lpLockedPct": 0.0}}],
        "rugged": True,
        "score": 8500,
        "score_normalised": 95.0,
        "transferFee": {"pct": 12.0},
    }
    risky_gmgn = {
        "code": 0,
        "data": {
            "security": {
                "is_honeypot": True,
                "bundler_rate": 0.45,
            }
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == RUGCHECK_URL:
            return httpx.Response(200, json=risky_rugcheck)
        if url == GMGN_URL:
            return httpx.Response(200, json=risky_gmgn)
        if url == DEXTOOLS_URL:
            return httpx.Response(429)
        return httpx.Response(200, json=[])

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        security_client = SecurityDataClient(http_client, gmgn_api_key="gmgn-key")
        result = security_client.fetch_token_security(ADDRESS)

    assert result.risk_summary.risk_level == "critical"
    assert result.risk_summary.is_honeypot is True
    assert result.risk_summary.rugged is True
    assert result.normalized_flags["mint_authority_enabled"] is True
    assert result.normalized_flags["freeze_authority_enabled"] is True
    assert result.normalized_flags["mutable_metadata"] is True
    assert result.normalized_flags["lp_not_locked"] is True
    assert result.normalized_flags["high_holder_concentration"] is True
    assert result.normalized_flags["single_holder_dominance"] is True
    assert result.normalized_flags["honeypot_detected"] is True
    assert result.normalized_flags["high_tax_or_fee"] is True
    assert result.normalized_flags["rugged_token"] is True
    assert result.normalized_flags["bundled_launch_detected"] is True
    assert result.sources["dextools"].status == "unavailable"
    assert result.sources["dextools"].reason == "rate_limited"


def test_security_endpoint_rejects_invalid_solana_address() -> None:
    with TestClient(app) as client:
        response = client.get("/api/tokens/not-a-valid-address/security")
    assert response.status_code == 422
    assert response.json() == {"detail": "INVALID_ADDRESS"}
