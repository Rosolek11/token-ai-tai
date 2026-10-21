import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.market_data import DexScreenerClient, get_dexscreener_client

ADDRESS = "So11111111111111111111111111111111111111112"
SOURCE_URL = f"https://api.dexscreener.com/token-pairs/v1/solana/{ADDRESS}"


@pytest.fixture
def source_pairs() -> list[dict]:
    fixture = Path(__file__).parent / "fixtures" / "dexscreener_solana.json"
    return json.loads(fixture.read_text(encoding="utf-8"))


@pytest.fixture
def http_handler(source_pairs: list[dict]) -> Mock:
    return Mock(return_value=httpx.Response(200, json=source_pairs))


@pytest.fixture
def api_client(http_handler: Mock) -> Iterator[TestClient]:
    with httpx.Client(transport=httpx.MockTransport(http_handler), timeout=10.0) as client:
        provider = DexScreenerClient(client)
        app.dependency_overrides[get_dexscreener_client] = lambda: provider
        try:
            with TestClient(app) as test_client:
                yield test_client
        finally:
            app.dependency_overrides.pop(get_dexscreener_client, None)


def test_token_report_fetches_pairs_and_records_source(
    api_client: TestClient, http_handler: Mock
) -> None:
    before = datetime.now(timezone.utc)
    response = api_client.post("/analyses/token", json={"address": ADDRESS})
    after = datetime.now(timezone.utc)

    assert response.status_code == 201
    data = response.json()["market_data"]
    assert data["status"] == "ok"
    assert data["source"] == "dexscreener"
    assert data["source_url"] == SOURCE_URL
    updated_at = datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00"))
    assert before <= updated_at <= after
    assert updated_at.utcoffset().total_seconds() == 0
    assert len(data["pairs"]) == 2
    assert data["primary_pair_address"] == data["pairs"][0]["pair_address"]
    assert data["price_usd"] == 106.65
    assert data["liquidity_usd"] == 29632649.49
    assert data["volume_24h_usd"] == 144375727.36
    assert data["price_change_24h_percent"] == 2.22
    assert data["pairs"][1]["price_change_24h_percent"] == -1.5
    assert data["pairs"][0]["base_token"]["address"] == ADDRESS
    assert data["pairs"][0]["url"].startswith("https://dexscreener.com/solana/")
    http_handler.assert_called_once()
    request = http_handler.call_args.args[0]
    assert request.method == "GET"
    assert str(request.url) == SOURCE_URL
    assert request.extensions["timeout"]["read"] == 10.0


@pytest.mark.parametrize("payload", [[], None])
def test_empty_response_has_no_metrics(
    payload: object, api_client: TestClient, http_handler: Mock
) -> None:
    http_handler.return_value = httpx.Response(
        200, content=json.dumps(payload), headers={"Content-Type": "application/json"}
    )
    response = api_client.post("/analyses/token", json={"address": ADDRESS})
    assert response.status_code == 201
    data = response.json()["market_data"]
    assert data["status"] == "no_data"
    assert data["pairs"] == []
    assert data["primary_pair_address"] is None
    assert data["source_url"] == SOURCE_URL
    assert data["updated_at"]
    for metric in ("price_usd", "liquidity_usd", "volume_24h_usd"):
        assert data[metric] is None


@pytest.mark.parametrize(
    "missing_metrics",
    [
        {},
        {"priceUsd": None, "liquidity": None, "volume": None},
        {"priceUsd": "", "liquidity": {}, "volume": {}},
        {"priceUsd": " ", "liquidity": {"usd": None}, "volume": {"h24": None}},
        {"liquidity": {"usd": ""}, "volume": {"h24": ""}},
    ],
)
def test_missing_metrics_remain_null(
    missing_metrics: dict,
    source_pairs: list[dict],
    api_client: TestClient,
    http_handler: Mock,
) -> None:
    pair = source_pairs[0]
    for field in ("priceUsd", "liquidity", "volume", "priceChange"):
        pair.pop(field)
    pair.update(missing_metrics)
    http_handler.return_value = httpx.Response(200, json=[pair])
    response = api_client.post("/analyses/token", json={"address": ADDRESS})
    assert response.status_code == 201
    data = response.json()["market_data"]
    assert len(data["pairs"]) == 1
    for metric in ("price_usd", "liquidity_usd", "volume_24h_usd", "price_change_24h_percent"):
        assert data[metric] is None
        assert data["pairs"][0][metric] is None


def test_zero_is_preserved_and_summary_uses_one_pair(
    source_pairs: list[dict], api_client: TestClient, http_handler: Mock
) -> None:
    source_pairs[0].update({"priceUsd": "0", "liquidity": None})
    source_pairs[1].update(
        {"priceUsd": "0", "liquidity": {"usd": 0}, "volume": {"h24": 0}}
    )
    http_handler.return_value = httpx.Response(200, json=source_pairs)
    response = api_client.post("/analyses/token", json={"address": ADDRESS})
    data = response.json()["market_data"]
    assert data["primary_pair_address"] == source_pairs[1]["pairAddress"]
    assert data["price_usd"] == 0
    assert data["liquidity_usd"] == 0
    assert data["volume_24h_usd"] == 0
    assert data["pairs"][0]["liquidity_usd"] is None


def test_summary_selects_highest_liquidity_independent_of_response_order(
    source_pairs: list[dict], api_client: TestClient, http_handler: Mock
) -> None:
    http_handler.return_value = httpx.Response(200, json=list(reversed(source_pairs)))
    response = api_client.post("/analyses/token", json={"address": ADDRESS})
    data = response.json()["market_data"]
    assert data["primary_pair_address"] == source_pairs[0]["pairAddress"]
    assert data["price_usd"] == 106.65
    assert data["liquidity_usd"] == 29632649.49
    assert data["volume_24h_usd"] == 144375727.36


def test_pairs_from_other_chains_and_tokens_are_excluded(
    source_pairs: list[dict], api_client: TestClient, http_handler: Mock
) -> None:
    source_pairs[0]["chainId"] = "ethereum"
    source_pairs[1]["baseToken"]["address"] = "another-token"
    http_handler.return_value = httpx.Response(200, json=source_pairs)
    response = api_client.post("/analyses/token", json={"address": ADDRESS})
    assert response.json()["market_data"]["status"] == "no_data"
    assert response.json()["market_data"]["pairs"] == []


def test_quote_token_does_not_receive_base_token_price(
    source_pairs: list[dict], api_client: TestClient, http_handler: Mock
) -> None:
    pair = source_pairs[0]
    pair["baseToken"], pair["quoteToken"] = pair["quoteToken"], pair["baseToken"]
    http_handler.return_value = httpx.Response(200, json=[pair])
    response = api_client.post("/analyses/token", json={"address": ADDRESS})
    data = response.json()["market_data"]
    assert len(data["pairs"]) == 1
    assert data["pairs"][0]["price_usd"] == 106.65
    assert data["price_usd"] is None
    assert data["primary_pair_address"] is None


@pytest.mark.parametrize("status_code", [404, 429, 500, 503])
def test_provider_http_error_is_not_an_empty_report(
    status_code: int, api_client: TestClient, http_handler: Mock
) -> None:
    http_handler.return_value = httpx.Response(status_code)
    response = api_client.post("/analyses/token", json={"address": ADDRESS})
    assert response.status_code == 502
    assert response.json() == {"detail": "MARKET_DATA_UNAVAILABLE"}


@pytest.mark.parametrize(
    ("error", "status_code", "detail"),
    [
        (httpx.ReadTimeout("timeout"), 504, "MARKET_DATA_TIMEOUT"),
        (httpx.ConnectError("connection error"), 502, "MARKET_DATA_UNAVAILABLE"),
    ],
)
def test_provider_network_errors(
    error: Exception,
    status_code: int,
    detail: str,
    api_client: TestClient,
    http_handler: Mock,
) -> None:
    http_handler.side_effect = error
    response = api_client.post("/analyses/token", json={"address": ADDRESS})
    assert response.status_code == status_code
    assert response.json() == {"detail": detail}


@pytest.mark.parametrize("payload", ["not-json", "{}", '[{"chainId":"solana"}]'])
def test_invalid_provider_payload_is_reported(
    payload: str, api_client: TestClient, http_handler: Mock
) -> None:
    http_handler.return_value = httpx.Response(200, content=payload)
    response = api_client.post("/analyses/token", json={"address": ADDRESS})
    assert response.status_code == 502
    assert response.json() == {"detail": "MARKET_DATA_UNAVAILABLE"}


@pytest.mark.parametrize("value", ["invalid", "NaN", "Infinity", -1, True])
def test_invalid_metric_is_not_reported_as_zero(
    value: object, source_pairs: list[dict], api_client: TestClient, http_handler: Mock
) -> None:
    source_pairs[0]["priceUsd"] = value
    http_handler.return_value = httpx.Response(200, json=source_pairs)
    response = api_client.post("/analyses/token", json={"address": ADDRESS})
    assert response.status_code == 502
    assert response.json() == {"detail": "MARKET_DATA_UNAVAILABLE"}


def test_invalid_address_does_not_call_provider(
    api_client: TestClient, http_handler: Mock
) -> None:
    response = api_client.post("/analyses/token", json={"address": "invalid"})
    assert response.status_code == 422
    http_handler.assert_not_called()


def test_wallet_analysis_does_not_call_market_provider(
    api_client: TestClient, http_handler: Mock
) -> None:
    response = api_client.post("/analyses/wallet", json={"address": ADDRESS})
    assert response.status_code == 201
    assert "market_data" not in response.json()
    http_handler.assert_not_called()
