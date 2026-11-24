import json
from collections import Counter
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.market_data import TokenMarketData
from app.onchain_data import TokenOnChainData
from app.security_data import SecurityDataClient, get_security_client
from app.source_cache import SourceCache

ADDRESS = "So11111111111111111111111111111111111111112"
REPORT = "/analyses/token"
ONCHAIN = f"/api/tokens/{ADDRESS}/onchain"
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def cached_api(monkeypatch):
    time = [0]
    cache = SourceCache(clock=lambda: time[0])
    monkeypatch.setattr(app.state, "source_cache", cache)
    monkeypatch.setattr(
        app.state, "settings", replace(app.state.settings, solscan_api_key="test", gmgn_api_key=None)
    )
    dex = json.loads((FIXTURES / "dexscreener_solana.json").read_text())
    solscan = json.loads((FIXTURES / "solscan_solana.json").read_text())
    calls = Counter()
    failures = {}
    client_type = httpx.Client

    def handle(request):
        endpoint = request.url.path.rsplit("/", 1)[-1]
        calls[endpoint] += 1
        if endpoint in failures:
            status, payload = failures.pop(endpoint)
            return httpx.Response(status, json=payload)
        if endpoint == ADDRESS:
            return httpx.Response(200, json=dex)
        return httpx.Response(200, json=solscan[endpoint])

    def provider_client(*, timeout):
        return client_type(transport=httpx.MockTransport(handle), timeout=timeout)

    with client_type(transport=httpx.MockTransport(lambda request: httpx.Response(404))) as security:
        monkeypatch.setitem(
            app.dependency_overrides, get_security_client, lambda: SecurityDataClient(security)
        )
        with TestClient(app) as api:
            monkeypatch.setattr(httpx, "Client", provider_client)
            yield api, time, calls, failures, cache


def test_cache_miss_hit_and_expiry_for_both_sources(cached_api):
    api, time, calls, _, cache = cached_api
    initial = api.post(REPORT, json={"address": ADDRESS})
    assert initial.status_code == 201
    initial = initial.json()
    assert initial["market_data"]["price_usd"] == 106.65
    assert initial["onchain_data"]["metadata"]["name"] == "Wrapped SOL"
    assert calls == {ADDRESS: 1, "meta": 1, "holders": 1}

    market_key = ("solana", ADDRESS, "dexscreener")
    market = cache.get(market_key, TokenMarketData)
    assert market is not None
    market.pairs.clear()
    assert cache.get(("solana-devnet", ADDRESS, "dexscreener"), TokenMarketData) is None
    other_address = ("solana", "11111111111111111111111111111111", "dexscreener")
    assert cache.get(other_address, TokenMarketData) is None
    assert cache.get(("solana", ADDRESS, "solscan"), TokenOnChainData) is not None

    time[0] = 29
    hit = api.post(REPORT, json={"address": ADDRESS}).json()
    assert hit["market_data"] == initial["market_data"]
    assert api.get(ONCHAIN).json() == initial["onchain_data"]
    assert calls == {ADDRESS: 1, "meta": 1, "holders": 1}

    time[0] = 30
    refreshed = api.post(REPORT, json={"address": ADDRESS}).json()
    assert refreshed["market_data"]["updated_at"] != initial["market_data"]["updated_at"]
    assert refreshed["onchain_data"] == initial["onchain_data"]
    assert calls == {ADDRESS: 2, "meta": 1, "holders": 1}

    time[0] = 120
    assert api.get(ONCHAIN).json()["updated_at"] != initial["onchain_data"]["updated_at"]
    assert calls == {ADDRESS: 2, "meta": 2, "holders": 2}


@pytest.mark.parametrize("status", [401, 429, 200])
def test_market_retries_after_errors_and_empty_data(cached_api, status):
    api, _, calls, failures, _ = cached_api
    failures[ADDRESS] = (status, [])
    first = api.post(REPORT, json={"address": ADDRESS})
    if status == 200:
        assert first.status_code == 201
        assert first.json()["market_data"]["status"] == "no_data"
    else:
        assert first.status_code == 502

    recovered = api.post(REPORT, json={"address": ADDRESS})
    assert recovered.json()["market_data"]["status"] == "ok"
    assert calls == {ADDRESS: 2, "meta": 1, "holders": 1}


@pytest.mark.parametrize("endpoint", ["meta", "holders"])
@pytest.mark.parametrize("status", [401, 429, 200])
def test_onchain_retries_after_errors_and_empty_data(cached_api, endpoint, status):
    api, _, calls, failures, _ = cached_api
    empty = {} if endpoint == "meta" else {"items": []}
    failures[endpoint] = (status, {"success": True, "data": empty})

    first = api.get(ONCHAIN)
    assert first.status_code == 200
    data = first.json()
    if status != 200:
        assert data["http_status"] == status
    elif endpoint == "meta":
        assert data["metadata"]["name"] is None
    else:
        assert data["holders"] == []

    recovered = api.get(ONCHAIN).json()
    assert recovered["status"] == "ok"
    assert recovered["metadata"]["name"] == "Wrapped SOL"
    assert recovered["holders"]
    assert calls[endpoint] == 2
