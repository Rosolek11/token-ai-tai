import json
from pathlib import Path

import httpx
import pytest

from app.security_data import SecurityDataClient

ADDRESS = "So11111111111111111111111111111111111111112"
FIXTURES = Path(__file__).parent / "fixtures"


def report(payloads):
    urls = {
        "rugcheck": f"{SecurityDataClient.RUGCHECK_BASE_URL}/{ADDRESS}/report",
        "dexscreener": f"{SecurityDataClient.DEXSCREENER_BASE_URL}/{ADDRESS}",
        "dextools": f"{SecurityDataClient.DEXTOOLS_BASE_URL}/{ADDRESS}/audit",
        "gmgn": f"{SecurityDataClient.GMGN_BASE_URL}/{ADDRESS}",
    }
    def handler(request):
        source = next(key for key, url in urls.items() if url == str(request.url))
        return httpx.Response(200, json=payloads.get(source))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = SecurityDataClient(client, gmgn_api_key="test").fetch_token_security(ADDRESS)
    return result, urls


def test_fixture_mapping_and_provenance():
    payloads = {name: json.loads((FIXTURES / f"{name}_solana.json").read_text())
                for name in ("rugcheck", "dexscreener", "dextools", "gmgn")}
    result, urls = report(payloads)
    data = result.normalized_data
    assert data.price["price_usd"].value == float(payloads["dexscreener"][0]["priceUsd"])
    assert data.price["price_usd"].unit == "USD"
    assert data.holders["holder_count"].value == payloads["rugcheck"]["totalHolders"]
    assert data.holders["holder_count"].sourceId == "rugcheck"
    assert data.holders["holder_count"].unit == "count"
    assert data.liquidity["lp_locked_pct"].unit == "percent"
    assert data.flags
    assert {item.sourceId for item in data.flags.values()} == set(urls)
    for group in (data.price, data.liquidity, data.holders, data.flags):
        for item in group.values():
            if item.sourceId:
                assert item.url == urls[item.sourceId]
                assert item.timestamp == result.sources[item.sourceId].updated_at
                assert item.timestamp.utcoffset().total_seconds() == 0
    assert result.ai_context_payload["normalized_data"] == data.model_dump(mode="json")


@pytest.mark.parametrize("value", [None, 0])
def test_missing_values_and_real_zero(value):
    result, _ = report({"rugcheck": {"totalHolders": value,
                                     "totalMarketLiquidity": value}})
    assert result.normalized_data.holders["holder_count"].value == value
    assert result.normalized_data.liquidity["total_market_liquidity_usd"].value == value
    assert result.normalized_data.price["price_usd"].value is None
    assert result.normalized_data.holders["top_holders"].value is None
    assert result.normalized_data.flags == {}


def test_false_flag_is_preserved():
    result, _ = report({"gmgn": {"data": {"is_honeypot": False}}})
    assert any(item.value is False for item in result.normalized_data.flags.values())
