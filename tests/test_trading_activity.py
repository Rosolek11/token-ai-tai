import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.market_data import DexScreenerClient, get_dexscreener_client
from app.trading_activity import GmgnClient, get_gmgn_client

ADDRESS = "So11111111111111111111111111111111111111112"


@pytest.mark.parametrize("status,payload,expected,count", [
    (200, {"code": 0, "data": {"sniper_count": 3}}, "ok", 3),
    (200, {"code": 0, "data": {"sniper_count": 0}}, "ok", 0),
    (200, {"code": 0, "data": None}, "no_data", None),
    (200, {"code": 0, "data": {}}, "no_data", None),
    (200, {"code": 0, "data": {"sniper_count": -1}}, "unavailable", None),
    (200, {"code": 1}, "unavailable", None),
    (401, {}, "unauthorized", None),
    (429, {}, "rate_limited", None),
    (500, {}, "unavailable", None),
])
def test_report_survives_optional_provider(status, payload, expected, count):
    pairs = json.loads((Path(__file__).parent / "fixtures/dexscreener_solana.json").read_text())
    pairs[0]["txns"] = {"h24": {"buys": 10, "sells": 4}}
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, json=payload)
    with httpx.Client(transport=httpx.MockTransport(handler)) as gmgn_http, httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=pairs))
    ) as dex_http:
        app.dependency_overrides[get_gmgn_client] = lambda: GmgnClient(gmgn_http, "test-key")
        app.dependency_overrides[get_dexscreener_client] = lambda: DexScreenerClient(dex_http)
        try:
            with TestClient(app) as client:
                response = client.post("/analyses/token", json={"address": ADDRESS})
            assert response.status_code == 201
            report = response.json()
            assert report["market_data"]["transactions_24h"] == 14
            assert report["market_data"]["volume_24h_usd"] == 144375727.36
            assert report["gmgn_activity"]["status"] == expected
            assert report["gmgn_activity"]["sniper_count"] == count
            assert len(requests) == 1
            assert requests[0].headers["X-APIKEY"] == "test-key"
            assert requests[0].url.params["address"] == ADDRESS
            assert requests[0].method == "GET"
            assert "test-key" not in response.text
        finally:
            app.dependency_overrides.clear()


def test_no_key_skips_network():
    def unexpected(request):
        pytest.fail("GMGN called without credentials")
    with httpx.Client(transport=httpx.MockTransport(unexpected)) as client:
        assert GmgnClient(client, None).fetch_activity(ADDRESS).status == "not_configured"


@pytest.mark.parametrize("txns,total", [(None, None), ({}, None), ({"h24": {"buys": 0, "sells": 0}}, 0), ({"h24": {"buys": 2}}, None)])
def test_missing_transactions(txns, total):
    pairs = json.loads((Path(__file__).parent / "fixtures/dexscreener_solana.json").read_text())[:1]
    pairs[0]["txns"] = txns
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=pairs))) as client:
        assert DexScreenerClient(client).fetch_token_market(ADDRESS).transactions_24h == total


def test_gmgn_timeout_is_optional():
    def timeout(request):
        raise httpx.ReadTimeout("timeout")
    with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
        assert GmgnClient(client, "key").fetch_activity(ADDRESS).status == "unavailable"
