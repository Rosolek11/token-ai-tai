import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.market_data import DexScreenerClient, MarketDataError, get_dexscreener_client

ADDRESS = "So11111111111111111111111111111111111111112"
SOURCE_URL = f"https://api.dexscreener.com/token-pairs/v1/solana/{ADDRESS}"
METRIC_FIELDS = [
    pytest.param(("priceUsd",), "price_usd", id="price"),
    pytest.param(("liquidity", "usd"), "liquidity_usd", id="liquidity"),
    pytest.param(("volume", "h24"), "volume_24h_usd", id="volume"),
    pytest.param(("priceChange", "h24"), "price_change_24h_percent", id="change"),
]


def set_source_metric(pair: dict, field_path: tuple[str, ...], value: object) -> None:
    if len(field_path) == 1:
        pair[field_path[0]] = value
    else:
        pair[field_path[0]][field_path[1]] = value


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


@pytest.mark.parametrize(("field_path", "output_field"), METRIC_FIELDS)
@pytest.mark.parametrize("value", [None, "", "  ", "\t\n"])
def test_each_missing_metric_preserves_other_metrics(
    field_path: tuple[str, ...], output_field: str, value: object,
    source_pairs: list[dict], api_client: TestClient, http_handler: Mock,
) -> None:
    baseline = {
        "price_usd": 106.65,
        "liquidity_usd": 29632649.49,
        "volume_24h_usd": 144375727.36,
        "price_change_24h_percent": 2.22,
    }
    set_source_metric(source_pairs[0], field_path, value)
    http_handler.return_value = httpx.Response(200, json=[source_pairs[0]])
    response = api_client.post("/analyses/token", json={"address": ADDRESS})
    assert response.status_code == 201
    data = response.json()["market_data"]
    baseline[output_field] = None
    for metric, expected in baseline.items():
        assert data[metric] == expected
        assert data["pairs"][0][metric] == expected


@pytest.mark.parametrize(("field_path", "output_field"), METRIC_FIELDS)
@pytest.mark.parametrize("value", [0, 0.0, "0", "0.000", "1.23e-9", " 1.23 "])
def test_each_metric_accepts_zero_and_small_numeric_values(
    field_path: tuple[str, ...], output_field: str, value: object,
    source_pairs: list[dict], api_client: TestClient, http_handler: Mock,
) -> None:
    set_source_metric(source_pairs[0], field_path, value)
    http_handler.return_value = httpx.Response(200, json=[source_pairs[0]])
    response = api_client.post("/analyses/token", json={"address": ADDRESS})
    assert response.status_code == 201
    data = response.json()["market_data"]
    assert data[output_field] == float(value)
    assert data["pairs"][0][output_field] == float(value)


@pytest.mark.parametrize(("field_path", "output_field"), METRIC_FIELDS)
@pytest.mark.parametrize(
    "value",
    [True, False, [], {}, "invalid", "NaN", "Infinity", "-Infinity", "1e309", 10**400],
    ids=["true", "false", "list", "object", "text", "nan", "inf", "negative-inf", "overflow-string", "overflow-int"],
)
def test_each_invalid_metric_produces_provider_error(
    field_path: tuple[str, ...], output_field: str, value: object,
    source_pairs: list[dict], api_client: TestClient, http_handler: Mock,
) -> None:
    set_source_metric(source_pairs[0], field_path, value)
    http_handler.return_value = httpx.Response(200, json=[source_pairs[0]])
    response = api_client.post("/analyses/token", json={"address": ADDRESS})
    assert response.status_code == 502
    assert response.json() == {"detail": "MARKET_DATA_UNAVAILABLE"}


@pytest.mark.parametrize(("field_path", "output_field"), METRIC_FIELDS[:3])
def test_amounts_cannot_be_negative(
    field_path: tuple[str, ...], output_field: str,
    source_pairs: list[dict], api_client: TestClient, http_handler: Mock,
) -> None:
    set_source_metric(source_pairs[0], field_path, -0.01)
    http_handler.return_value = httpx.Response(200, json=[source_pairs[0]])
    response = api_client.post("/analyses/token", json={"address": ADDRESS})
    assert response.status_code == 502
    assert response.json() == {"detail": "MARKET_DATA_UNAVAILABLE"}


@pytest.mark.parametrize("field", ["liquidity", "volume", "priceChange", "baseToken", "quoteToken"])
@pytest.mark.parametrize("value", ["", [], 0, True])
def test_malformed_nested_objects_are_provider_errors(
    field: str, value: object, source_pairs: list[dict],
    api_client: TestClient, http_handler: Mock,
) -> None:
    source_pairs[0][field] = value
    http_handler.return_value = httpx.Response(200, json=source_pairs)
    response = api_client.post("/analyses/token", json={"address": ADDRESS})
    assert response.status_code == 502
    assert response.json() == {"detail": "MARKET_DATA_UNAVAILABLE"}


@pytest.mark.parametrize("payload", ["", True, 0, {}, [None], [False], [[]]])
def test_wrong_root_shapes_are_not_empty_data(
    payload: object, api_client: TestClient, http_handler: Mock,
) -> None:
    http_handler.return_value = httpx.Response(200, json=payload)
    response = api_client.post("/analyses/token", json={"address": ADDRESS})
    assert response.status_code == 502
    assert response.json() == {"detail": "MARKET_DATA_UNAVAILABLE"}


@pytest.mark.parametrize("liquidity", [None, 100])
def test_liquidity_ties_select_first_pair(
    liquidity: float | None, source_pairs: list[dict],
    api_client: TestClient, http_handler: Mock,
) -> None:
    for pair in source_pairs:
        pair["liquidity"] = {"usd": liquidity}
    http_handler.return_value = httpx.Response(200, json=source_pairs)
    response = api_client.post("/analyses/token", json={"address": ADDRESS})
    assert response.status_code == 201
    data = response.json()["market_data"]
    assert data["primary_pair_address"] == source_pairs[0]["pairAddress"]
    assert data["price_usd"] == 106.65
    assert data["liquidity_usd"] == liquidity


@pytest.mark.parametrize(
    "error_type",
    [httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout],
)
def test_all_timeout_phases_are_reported_as_gateway_timeout(
    error_type: type[httpx.TimeoutException], api_client: TestClient, http_handler: Mock,
) -> None:
    http_handler.side_effect = error_type("provider-internal-detail")
    response = api_client.post("/analyses/token", json={"address": ADDRESS})
    assert response.status_code == 504
    assert response.json() == {"detail": "MARKET_DATA_TIMEOUT"}
    http_handler.assert_called_once()


@pytest.mark.parametrize("status_code", [204, 301, 302, 403])
def test_empty_body_redirect_and_forbidden_are_provider_errors(
    status_code: int, api_client: TestClient, http_handler: Mock,
) -> None:
    http_handler.return_value = httpx.Response(
        status_code, headers={"Location": "https://example.test/redirect"}
    )
    response = api_client.post("/analyses/token", json={"address": ADDRESS})
    assert response.status_code == 502
    assert response.json() == {"detail": "MARKET_DATA_UNAVAILABLE"}
    http_handler.assert_called_once()


def test_consecutive_analyses_do_not_reuse_old_metrics(
    source_pairs: list[dict], api_client: TestClient, http_handler: Mock,
) -> None:
    http_handler.side_effect = [
        httpx.Response(200, json=source_pairs),
        httpx.Response(503),
        httpx.Response(200, json=[]),
        httpx.Response(200, json=[source_pairs[1]]),
    ]
    populated = api_client.post("/analyses/token", json={"address": ADDRESS})
    failed = api_client.post("/analyses/token", json={"address": ADDRESS})
    empty = api_client.post("/analyses/token", json={"address": ADDRESS})
    recovered = api_client.post("/analyses/token", json={"address": ADDRESS})
    assert populated.json()["market_data"]["price_usd"] == 106.65
    assert failed.status_code == 502
    assert empty.json()["market_data"]["price_usd"] is None
    assert empty.json()["market_data"]["pairs"] == []
    assert recovered.json()["market_data"]["price_usd"] == 106.6
    assert populated.json()["id"] != recovered.json()["id"]
    assert http_handler.call_count == 4


@pytest.mark.parametrize("fails", [False, True])
def test_production_dependency_closes_http_client(
    fails: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
    )
    try:
        factory = Mock(return_value=client)
        monkeypatch.setattr("app.market_data.httpx.Client", factory)
        dependency = get_dexscreener_client()
        provider = next(dependency)
        assert provider.client is client
        assert not client.is_closed
        if fails:
            with pytest.raises(MarketDataError):
                dependency.throw(MarketDataError("test failure"))
        else:
            provider.fetch_token_market(ADDRESS)
            dependency.close()
        assert client.is_closed
        factory.assert_called_once_with(timeout=10.0)
    finally:
        client.close()
