from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.source_cache import SourceCache
from app.wallet_data import SolscanWalletClient, get_wallet_client

EXAMPLE_ADDRESS = "So11111111111111111111111111111111111111112"
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_wallet_fixture() -> dict:
    return json.loads(
        (FIXTURES_DIR / "solscan_wallet_transactions.json").read_text(encoding="utf-8")
    )


def test_solscan_wallet_fetches_recent_transactions_and_history_limit() -> None:
    fixture = load_wallet_fixture()
    requests_made: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_made.append(request)
        assert request.headers.get("token") == "test-solscan-pro-key"
        assert request.url.path == "/v2.0/account/transactions"
        assert request.url.params.get("address") == EXAMPLE_ADDRESS
        assert request.url.params.get("limit") == "20"
        return httpx.Response(200, json=fixture)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        wallet_client = SolscanWalletClient(http_client, api_key="test-solscan-pro-key")
        report = wallet_client.fetch_wallet_transactions(EXAMPLE_ADDRESS)

    assert len(requests_made) == 1
    assert report.status == "ok"
    assert report.reason is None
    assert report.read_only is True
    assert report.address == EXAMPLE_ADDRESS
    assert report.transaction_count == 3
    assert len(report.transactions) == 3

    # First tx: Jupiter swap (ComputeBudget instruction ignored in favor of meaningful swap route)
    tx0 = report.transactions[0]
    assert tx0.signature == fixture["data"][0]["tx_hash"]
    assert tx0.block_time == 1731870000
    assert tx0.timestamp == datetime(2024, 11, 17, 19, 0, 0, tzinfo=timezone.utc)
    assert tx0.time == tx0.timestamp
    assert tx0.type == "swap"
    assert tx0.tx_type == "swap"
    assert tx0.status == "success"
    assert tx0.fee_lamports == 15000

    # Second tx: SOL transfer
    tx1 = report.transactions[1]
    assert tx1.signature == fixture["data"][1]["tx_hash"]
    assert tx1.type == "sol_transfer"
    assert tx1.timestamp == datetime(2024, 11, 17, 18, 0, 0, tzinfo=timezone.utc)
    assert tx1.status == "success"

    # Third tx: failed SPL transferChecked
    tx2 = report.transactions[2]
    assert tx2.signature == fixture["data"][2]["tx_hash"]
    assert tx2.type == "transfer_checked"
    assert tx2.status == "failed"

    # History limit metadata (3 returned < 20 limit => not truncated)
    assert report.history_limit.max_transactions == 20
    assert report.history_limit.requested_limit == 20
    assert report.history_limit.returned_count == 3
    assert report.history_limit.max_pages == 1
    assert report.history_limit.pages_fetched == 1
    assert report.history_limit.is_truncated is False
    assert report.history_limit.history_complete is True
    assert "max_transactions=20" in report.limit_description


def test_wallet_bounds_limit_and_reports_truncation_explicitly() -> None:
    fixture = load_wallet_fixture()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.params.get("limit") == "10"
        return httpx.Response(200, json=fixture)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        # Clamp check on oversized limits
        oversized = SolscanWalletClient(
            http_client, api_key="test-key", limit=500, max_pages=15
        )
        assert oversized.limit == SolscanWalletClient.MAX_TX_LIMIT
        assert oversized.max_pages == 1

        # Bounded limit=2 on 3 available transactions marks history as truncated
        bounded = SolscanWalletClient(http_client, api_key="test-key", limit=2)
        report = bounded.fetch_wallet_transactions(EXAMPLE_ADDRESS)

    assert calls == 1
    assert len(report.transactions) == 2
    assert report.transaction_count == 2
    assert report.history_limit.max_transactions == 2
    assert report.history_limit.returned_count == 2
    assert report.history_limit.max_pages == 1
    assert report.history_limit.pages_fetched == 1
    assert report.history_limit.is_truncated is True
    assert report.history_limit.history_complete is False
    assert "older wallet transactions were not fetched" in report.limit_description


@pytest.mark.parametrize(
    "empty_payload,status_code",
    [
        ({"success": True, "data": []}, 200),
        ({"success": True, "data": None}, 200),
        ({"success": True, "data": {"items": []}}, 200),
        ({"success": False, "data": []}, 404),
    ],
)
def test_wallet_handles_no_data_and_missing_fields_gracefully(
    empty_payload: dict, status_code: int
) -> None:
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(status_code, json=empty_payload)
        )
    ) as http_client:
        client = SolscanWalletClient(http_client, api_key="test-key")
        empty_report = client.fetch_wallet_transactions(EXAMPLE_ADDRESS)

    assert empty_report.status == "no_data"
    assert empty_report.reason == "not_found"
    assert empty_report.transactions == []
    assert empty_report.transaction_count == 0
    assert empty_report.history_limit.returned_count == 0
    assert empty_report.history_limit.is_truncated is False
    assert empty_report.history_limit.history_complete is True

    # Transaction with missing timestamp and no instructions does not invent epoch 0 or fake type
    sparse_payload = {
        "success": True,
        "data": [
            {
                "tx_hash": "SparseSig111111111111111111111111111111111111111111111111111",
                "block_time": None,
                "parsed_instructions": [],
            }
        ],
    }
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=sparse_payload))
    ) as http_client:
        sparse_report = SolscanWalletClient(
            http_client, api_key="test-key"
        ).fetch_wallet_transactions(EXAMPLE_ADDRESS)

    assert sparse_report.status == "ok"
    assert len(sparse_report.transactions) == 1
    assert sparse_report.transactions[0].timestamp is None
    assert sparse_report.transactions[0].block_time is None
    assert sparse_report.transactions[0].type == "unknown"


@pytest.mark.parametrize(
    ("mode", "expected_status", "expected_reason"),
    [
        ("no_key", "not_configured", "missing_api_key"),
        ("401", "unauthorized", "access_denied"),
        ("403", "unauthorized", "access_denied"),
        ("429", "rate_limited", "rate_limited"),
        ("500", "unavailable", "http_error"),
        ("timeout", "unavailable", "timeout"),
        ("invalid_json", "unavailable", "invalid_payload"),
    ],
)
def test_wallet_handles_missing_key_auth_rate_limit_and_errors(
    mode: str, expected_status: str, expected_reason: str
) -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        if mode in {"401", "403", "429", "500"}:
            return httpx.Response(int(mode), json={"success": False})
        if mode == "timeout":
            raise httpx.ReadTimeout("timed out")
        return httpx.Response(200, content="not-json")

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        wallet_client = SolscanWalletClient(
            http_client, api_key=None if mode == "no_key" else "secret-solscan-key"
        )
        report = wallet_client.fetch_wallet_transactions(EXAMPLE_ADDRESS)

    if mode == "no_key":
        assert called is False
    assert report.status == expected_status
    assert report.reason == expected_reason
    assert report.transactions == []
    assert report.transaction_count == 0
    assert "secret-solscan-key" not in report.model_dump_json()


def test_wallet_endpoints_and_cache_integration() -> None:
    fixture = load_wallet_fixture()
    clock = [0.0]
    cache = SourceCache(clock=lambda: clock[0])
    calls = 0

    def override_wallet() -> Iterator[SolscanWalletClient]:
        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, json=fixture)

        with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
            yield SolscanWalletClient(
                http_client, api_key="secret-solscan-key", cache=cache
            )

    app.dependency_overrides[get_wallet_client] = override_wallet
    try:
        with TestClient(app) as client:
            # 1. POST /analyses/wallet returns 201 with transactions & history_limit
            post_res = client.post("/analyses/wallet", json={"address": EXAMPLE_ADDRESS})
            assert post_res.status_code == 201
            body = post_res.json()
            assert body["subject_type"] == "wallet"
            assert body["address"] == EXAMPLE_ADDRESS
            assert body["status"] == "ok"
            assert len(body["transactions"]) == 3
            assert body["transactions"][0]["signature"] == fixture["data"][0]["tx_hash"]
            assert body["transactions"][0]["type"] == "swap"
            assert body["transactions"][0]["timestamp"] == "2024-11-17T19:00:00Z"
            assert body["history_limit"]["max_transactions"] == 20
            assert body["history_limit"]["returned_count"] == 3
            assert body["wallet_data"]["status"] == "ok"
            assert "secret-solscan-key" not in post_res.text
            assert calls == 1

            # 2. GET /api/wallets/{address}/transactions hits cache within TTL
            clock[0] = 30.0
            get_res = client.get(f"/api/wallets/{EXAMPLE_ADDRESS}/transactions")
            assert get_res.status_code == 200
            get_body = get_res.json()
            assert get_body["status"] == "ok"
            assert get_body["transaction_count"] == 3
            assert calls == 1

            # 3. After TTL expires, fetches fresh data
            clock[0] = 61.0
            refreshed = client.get(f"/api/wallets/{EXAMPLE_ADDRESS}/transactions")
            assert refreshed.status_code == 200
            assert calls == 2

            # 4. Invalid Solana address returns 422 INVALID_ADDRESS without calling provider
            invalid_post = client.post("/analyses/wallet", json={"address": "invalid-wallet"})
            assert invalid_post.status_code == 422
            assert invalid_post.json() == {"detail": "INVALID_ADDRESS"}

            invalid_get = client.get("/api/wallets/invalid-wallet/transactions")
            assert invalid_get.status_code == 422
            assert invalid_get.json() == {"detail": "INVALID_ADDRESS"}
            assert calls == 2
    finally:
        app.dependency_overrides.pop(get_wallet_client, None)
