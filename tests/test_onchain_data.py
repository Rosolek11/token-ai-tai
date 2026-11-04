import json
from pathlib import Path
from typing import Iterator

import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.market_data import DexScreenerClient, get_dexscreener_client
from app.onchain_data import SolscanClient, get_solscan_client

SOL_ADDRESS = "So11111111111111111111111111111111111111112"
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_solscan_fixture() -> dict:
    return json.loads(
        (FIXTURES_DIR / "solscan_solana.json").read_text(encoding="utf-8")
    )


def load_dex_fixture() -> dict:
    return json.loads(
        (FIXTURES_DIR / "dexscreener_solana.json").read_text(encoding="utf-8")
    )


def test_solscan_fetches_meta_supply_holders_and_calculates_top_10_share() -> None:
    fixture = load_solscan_fixture()
    requests_made: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_made.append(request)
        assert request.headers.get("token") == "test-solscan-pro-key"
        if request.url.path == "/v2.0/token/meta":
            assert request.url.params.get("address") == SOL_ADDRESS
            return httpx.Response(200, json=fixture["meta"])
        if request.url.path == "/v2.0/token/holders":
            assert request.url.params.get("address") == SOL_ADDRESS
            assert request.url.params.get("page") == "1"
            assert request.url.params.get("page_size") == "10"
            return httpx.Response(200, json=fixture["holders"])
        raise AssertionError(f"Unexpected URL: {request.url}")

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        solscan = SolscanClient(http_client, api_key="test-solscan-pro-key")
        report = solscan.fetch_token_onchain(SOL_ADDRESS)

    # Verify access confirmation order: meta first, then 1 bounded page of holders
    assert len(requests_made) == 2
    assert requests_made[0].url.path == "/v2.0/token/meta"
    assert requests_made[1].url.path == "/v2.0/token/holders"

    assert report.status == "ok"
    assert report.reason is None
    assert report.read_only is True
    assert report.address == SOL_ADDRESS

    # Metadata & supply
    assert report.metadata.name == "Wrapped SOL"
    assert report.metadata.symbol == "SOL"
    assert report.metadata.decimals == 9
    assert report.metadata.holder_count == 485210
    assert report.metadata.creator == "11111111111111111111111111111111"
    assert report.metadata.price_usd == 176.42
    assert report.supply.raw_amount == "1000000000000000"
    assert report.supply.decimals == 9
    assert report.supply.ui_amount == 1000000.0
    assert report.supply.circulating_supply == 1000000.0
    assert report.total_supply == 1000000.0
    assert report.holder_count == 485210

    # Holders & Top 10 share calculation:
    # (120k + 80k + 50k + 40k + 35k + 30k + 25k + 20k + 15k + 10k) / 1,000k = 425k / 1,000k = 42.5%
    assert len(report.holders) == 10
    assert report.holders[0].rank == 1
    assert report.holders[0].address == "HolderAcc1111111111111111111111111111111111"
    assert report.holders[0].owner == "OwnerWal11111111111111111111111111111111111"
    assert report.holders[0].ui_amount == 120000.0
    assert report.holders[0].share_percent == 12.0

    assert report.top_10_share_percent == 42.5
    assert report.holder_sample.page == 1
    assert report.holder_sample.page_size == 10
    assert report.holder_sample.max_pages == 1
    assert report.holder_sample.pages_fetched == 1
    assert report.holder_sample.sample_size == 10
    assert report.holder_sample.top_10_count == 10
    assert report.holder_sample.total_holders == 485210
    assert report.holder_sample.top_1_share_percent == 12.0
    assert report.holder_sample.top_5_share_percent == 32.5
    assert report.holder_sample.top_10_share_percent == 42.5
    assert report.holder_sample.calculation_basis == "total_supply"
    assert "page=1, page_size=10, max_pages=1" in report.sample_description
    assert "42.5000%" in report.sample_description


def test_solscan_bounds_pagination_to_single_page_and_max_page_size() -> None:
    fixture = load_solscan_fixture()
    holder_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal holder_calls
        if request.url.path == "/v2.0/token/meta":
            return httpx.Response(200, json=fixture["meta"])
        if request.url.path == "/v2.0/token/holders":
            holder_calls += 1
            assert request.url.params.get("page") == "1"
            assert request.url.params.get("page_size") == "20"
            return httpx.Response(200, json=fixture["holders"])
        raise AssertionError(f"Unexpected URL: {request.url}")

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        solscan = SolscanClient(
            http_client,
            api_key="test-solscan-pro-key",
            page_size=500,
            max_pages=25,
        )
        assert solscan.page_size == SolscanClient.MAX_PAGE_SIZE
        assert solscan.max_pages == 1
        report = solscan.fetch_token_onchain(SOL_ADDRESS)

    assert holder_calls == 1
    assert report.holder_sample.pages_fetched == 1
    assert report.holder_sample.max_pages == 1
    assert report.holder_sample.page_size == 20


def test_solscan_skips_requests_when_api_key_missing() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        solscan = SolscanClient(http_client, api_key=None)
        report = solscan.fetch_token_onchain(SOL_ADDRESS)

    assert called is False
    assert report.status == "not_configured"
    assert report.reason == "missing_api_key"
    assert report.holders == []
    assert report.top_10_share_percent is None
    assert report.holder_sample.pages_fetched == 0
    assert report.holder_sample.calculation_basis == "unavailable"


def test_solscan_skips_holders_when_access_confirmation_fails_on_meta() -> None:
    requests_made: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_made.append(request.url.path)
        return httpx.Response(401, json={"success": False, "errors": {"code": 401}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        solscan = SolscanClient(http_client, api_key="invalid-key")
        report = solscan.fetch_token_onchain(SOL_ADDRESS)

    # Holders endpoint must not be called when meta access confirmation fails
    assert requests_made == ["/v2.0/token/meta"]
    assert report.status == "unauthorized"
    assert report.reason == "access_denied"
    assert report.http_status == 401
    assert report.holders == []
    assert report.top_10_share_percent is None
    assert report.holder_sample.pages_fetched == 0


def test_solscan_handles_rate_limit_and_missing_data_without_inventing_zeroes() -> None:
    def empty_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "data": {}})

    with httpx.Client(transport=httpx.MockTransport(empty_handler)) as http_client:
        solscan = SolscanClient(http_client, api_key="test-key")
        empty_report = solscan.fetch_token_onchain(SOL_ADDRESS)

    assert empty_report.status == "no_data"
    assert empty_report.reason == "not_found"
    assert empty_report.total_supply is None
    assert empty_report.holder_count is None
    assert empty_report.top_10_share_percent is None
    assert empty_report.holders == []

    # Missing supply with holders that have no percentage -> top_10_share_percent must be None, not 0
    def no_supply_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2.0/token/meta":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "address": SOL_ADDRESS,
                        "name": "Mystery Token",
                        "symbol": "MYS",
                        "decimals": 6,
                        "supply": "0",
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "total": 1,
                    "items": [
                        {
                            "address": "HolderAcc1111111111111111111111111111111111",
                            "amount": 5000000,
                            "decimals": 6,
                            "rank": 1,
                        }
                    ],
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(no_supply_handler)) as http_client:
        solscan = SolscanClient(http_client, api_key="test-key")
        no_supply_report = solscan.fetch_token_onchain(SOL_ADDRESS)

    assert no_supply_report.status == "ok"
    assert len(no_supply_report.holders) == 1
    assert no_supply_report.holders[0].share_percent is None
    assert no_supply_report.top_10_share_percent is None
    assert no_supply_report.holder_sample.calculation_basis == "unavailable"
    assert "total token supply is missing or zero" in no_supply_report.sample_description


def test_onchain_api_endpoint_and_token_analysis_integration() -> None:
    solscan_fixture = load_solscan_fixture()
    dex_fixture = load_dex_fixture()

    def override_solscan() -> Iterator[SolscanClient]:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v2.0/token/meta":
                return httpx.Response(200, json=solscan_fixture["meta"])
            if request.url.path == "/v2.0/token/holders":
                return httpx.Response(200, json=solscan_fixture["holders"])
            return httpx.Response(404)

        with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
            yield SolscanClient(http_client, api_key="test-solscan-pro-key")

    def override_dex() -> Iterator[DexScreenerClient]:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json=dex_fixture)
        )
        with httpx.Client(transport=transport) as http_client:
            yield DexScreenerClient(http_client)

    app.dependency_overrides[get_solscan_client] = override_solscan
    app.dependency_overrides[get_dexscreener_client] = override_dex
    try:
        client = TestClient(app)

        # Direct GET /api/tokens/{address}/onchain
        onchain_res = client.get(f"/api/tokens/{SOL_ADDRESS}/onchain")
        assert onchain_res.status_code == 200
        body = onchain_res.json()
        assert body["status"] == "ok"
        assert body["address"] == SOL_ADDRESS
        assert body["metadata"]["symbol"] == "SOL"
        assert body["supply"]["ui_amount"] == 1000000.0
        assert body["top_10_share_percent"] == 42.5
        assert body["holder_sample"]["top_10_count"] == 10
        assert body["holder_sample"]["pages_fetched"] == 1

        # Invalid address on GET /api/tokens/{address}/onchain
        invalid_res = client.get("/api/tokens/not-a-valid-address/onchain")
        assert invalid_res.status_code == 422
        assert invalid_res.json() == {"detail": "INVALID_ADDRESS"}

        # POST /analyses/token includes onchain_data
        analysis_res = client.post("/analyses/token", json={"address": SOL_ADDRESS})
        assert analysis_res.status_code == 201
        analysis_body = analysis_res.json()
        assert analysis_body["onchain_data"]["status"] == "ok"
        assert analysis_body["onchain_data"]["top_10_share_percent"] == 42.5
        assert len(analysis_body["onchain_data"]["holders"]) == 10
    finally:
        app.dependency_overrides.clear()
