import json
import time
from pathlib import Path
from typing import Any, Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.market_data import DexScreenerClient, get_dexscreener_client
from app.onchain_data import SolscanClient, get_solscan_client
from app.security_data import SecurityDataClient, get_security_client
from app.source_data import combine_token_sources
from app.trading_activity import GmgnClient, get_gmgn_client

SOL_ADDRESS = "So11111111111111111111111111111111111111112"
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def test_parallel_execution_and_per_provider_timeout() -> None:
    dex_pairs = load_fixture("dexscreener_solana.json")
    solscan_fixture = load_fixture("solscan_solana.json")
    rugcheck_fixture = load_fixture("rugcheck_solana.json")
    dextools_fixture = load_fixture("dextools_solana.json")
    gmgn_sec_fixture = load_fixture("gmgn_solana.json")

    def make_slow_client(delay: float, handler) -> httpx.Client:
        def delayed_handler(request: httpx.Request) -> httpx.Response:
            time.sleep(delay)
            return handler(request)

        return httpx.Client(transport=httpx.MockTransport(delayed_handler))

    with (
        make_slow_client(0.08, lambda r: httpx.Response(200, json=dex_pairs)) as dex_http,
        make_slow_client(
            0.08,
            lambda r: httpx.Response(200, json={"code": 0, "data": {"sniper_count": 2}}),
        ) as gmgn_http,
        make_slow_client(
            0.08,
            lambda r: httpx.Response(
                200,
                json=(
                    solscan_fixture["meta"]
                    if r.url.path.endswith("/meta")
                    else solscan_fixture["holders"]
                ),
            ),
        ) as solscan_http,
        make_slow_client(
            0.02,
            lambda r: httpx.Response(
                200,
                json=(
                    rugcheck_fixture
                    if "rugcheck" in str(r.url)
                    else dex_pairs
                    if "dexscreener" in str(r.url)
                    else dextools_fixture
                    if "dextools" in str(r.url)
                    else gmgn_sec_fixture
                ),
            ),
        ) as sec_http,
    ):
        start = time.monotonic()
        combined = combine_token_sources(
            SOL_ADDRESS,
            market_provider=DexScreenerClient(dex_http),
            gmgn_provider=GmgnClient(gmgn_http, "gmgn-key"),
            security_provider=SecurityDataClient(
                sec_http,
                rugcheck_api_key="rc-key",
                dextools_api_key="dt-key",
                gmgn_api_key="gmgn-key",
            ),
            solscan_provider=SolscanClient(solscan_http, api_key="solscan-key"),
            provider_timeout=1.0,
        )
        elapsed = time.monotonic() - start

    # Sequential execution would take ~0.08 + 0.08 + 0.16 + 0.08 >= 0.40s.
    # Parallel execution completes in well under 0.30s.
    assert elapsed < 0.30
    assert combined.status == "ok"
    assert combined.partial is False
    assert combined.source_errors == []

    # Now verify per-provider timeout: GMGN and Solscan hang for 1.0s while timeout is 0.05s.
    class HungGmgnProvider:
        def fetch_activity(self, address: str):
            time.sleep(1.0)
            raise AssertionError("Should have timed out before returning")

    class HungSolscanProvider:
        def fetch_token_onchain(self, address: str):
            time.sleep(1.0)
            raise AssertionError("Should have timed out before returning")

    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=dex_pairs))
        ) as fast_dex_http,
        httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200,
                    json=(
                        rugcheck_fixture
                        if "rugcheck" in str(r.url)
                        else dex_pairs
                        if "dexscreener" in str(r.url)
                        else dextools_fixture
                        if "dextools" in str(r.url)
                        else gmgn_sec_fixture
                    ),
                )
            )
        ) as fast_sec_http,
    ):
        start_timeout = time.monotonic()
        timed_out_result = combine_token_sources(
            SOL_ADDRESS,
            market_provider=DexScreenerClient(fast_dex_http),
            gmgn_provider=HungGmgnProvider(),
            security_provider=SecurityDataClient(
                fast_sec_http,
                rugcheck_api_key="rc-key",
                dextools_api_key="dt-key",
                gmgn_api_key="gmgn-key",
            ),
            solscan_provider=HungSolscanProvider(),
            provider_timeout=0.05,
        )
        timeout_elapsed = time.monotonic() - start_timeout

    # Must not wait for the 1.0s hung threads
    assert timeout_elapsed < 0.35
    assert timed_out_result.market_data.status == "ok"
    assert timed_out_result.market_data.price_usd == 106.65
    assert timed_out_result.status == "partial"
    assert timed_out_result.partial is True
    assert timed_out_result.gmgn_activity.status == "unavailable"
    assert timed_out_result.gmgn_activity.reason == "timeout"
    assert timed_out_result.onchain_data.status == "unavailable"
    assert timed_out_result.onchain_data.reason == "timeout"

    errors_by_source = {err.source: err for err in timed_out_result.source_errors}
    assert "gmgn" in errors_by_source
    assert errors_by_source["gmgn"].reason == "timeout"
    assert "solscan" in errors_by_source
    assert errors_by_source["solscan"].reason == "timeout"


@pytest.mark.parametrize(
    ("gmgn_mode", "solscan_mode", "expected_gmgn_status", "expected_gmgn_reason", "expected_solscan_status", "expected_solscan_reason"),
    [
        ("http_500", "http_500", "unavailable", "source_error", "unavailable", "http_error"),
        ("http_429", "http_429", "rate_limited", "rate_limited", "rate_limited", "rate_limited"),
        ("http_401", "http_401", "unauthorized", "access_denied", "unauthorized", "access_denied"),
        ("no_key", "no_key", "not_configured", "missing_api_key", "not_configured", "missing_api_key"),
        ("timeout", "timeout", "unavailable", "timeout", "unavailable", "timeout"),
        ("exception", "exception", "unavailable", "source_error", "unavailable", "source_error"),
    ],
)
def test_gmgn_and_solscan_failures_do_not_block_market_data(
    gmgn_mode: str,
    solscan_mode: str,
    expected_gmgn_status: str,
    expected_gmgn_reason: str,
    expected_solscan_status: str,
    expected_solscan_reason: str,
) -> None:
    dex_pairs = load_fixture("dexscreener_solana.json")
    rugcheck_fixture = load_fixture("rugcheck_solana.json")
    dextools_fixture = load_fixture("dextools_solana.json")

    def gmgn_handler(request: httpx.Request) -> httpx.Response:
        if gmgn_mode == "http_500":
            return httpx.Response(500, json={"error": "server error"})
        if gmgn_mode == "http_429":
            return httpx.Response(429, json={"error": "rate limit"})
        if gmgn_mode == "http_401":
            return httpx.Response(401, json={"error": "unauthorized"})
        if gmgn_mode == "timeout":
            raise httpx.ReadTimeout("gmgn timed out")
        raise RuntimeError("Unexpected GMGN crash")

    def solscan_handler(request: httpx.Request) -> httpx.Response:
        if solscan_mode == "http_500":
            return httpx.Response(500, json={"success": False})
        if solscan_mode == "http_429":
            return httpx.Response(429, json={"success": False})
        if solscan_mode == "http_401":
            return httpx.Response(401, json={"success": False})
        if solscan_mode == "timeout":
            raise httpx.ReadTimeout("solscan timed out")
        raise RuntimeError("Unexpected Solscan crash")

    def sec_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "rugcheck" in url:
            return httpx.Response(200, json=rugcheck_fixture)
        if "dexscreener" in url:
            return httpx.Response(200, json=dex_pairs)
        if "dextools" in url:
            return httpx.Response(200, json=dextools_fixture)
        return httpx.Response(503)

    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=dex_pairs))
        ) as dex_http,
        httpx.Client(transport=httpx.MockTransport(gmgn_handler)) as gmgn_http,
        httpx.Client(transport=httpx.MockTransport(solscan_handler)) as solscan_http,
        httpx.Client(transport=httpx.MockTransport(sec_handler)) as sec_http,
    ):
        app.dependency_overrides[get_dexscreener_client] = lambda: DexScreenerClient(dex_http)
        app.dependency_overrides[get_gmgn_client] = lambda: GmgnClient(
            gmgn_http, None if gmgn_mode == "no_key" else "test-gmgn-key"
        )
        app.dependency_overrides[get_solscan_client] = lambda: SolscanClient(
            solscan_http, None if solscan_mode == "no_key" else "test-solscan-key"
        )
        app.dependency_overrides[get_security_client] = lambda: SecurityDataClient(
            sec_http,
            rugcheck_api_key="rc-key",
            dextools_api_key="dt-key",
            gmgn_api_key=None,
        )
        try:
            with TestClient(app) as client:
                response = client.post("/analyses/token", json={"address": SOL_ADDRESS})
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 201
    body = response.json()

    # Market data is completely unblocked
    assert body["market_data"]["status"] == "ok"
    assert body["market_data"]["price_usd"] == 106.65
    assert body["market_data"]["liquidity_usd"] == 29632649.49

    # Combined status is partial and source_errors lists per-source failures
    assert body["status"] == "partial"
    assert body["partial"] is True
    assert body["gmgn_activity"]["status"] == expected_gmgn_status
    assert body["onchain_data"]["status"] == expected_solscan_status

    errors_by_source = {err["source"]: err for err in body["source_errors"]}
    assert body["errors"] == body["source_errors"]
    assert errors_by_source["gmgn"]["status"] == expected_gmgn_status
    assert errors_by_source["gmgn"]["reason"] == expected_gmgn_reason
    assert errors_by_source["solscan"]["status"] == expected_solscan_status
    assert errors_by_source["solscan"]["reason"] == expected_solscan_reason
    assert "dexscreener" not in errors_by_source
    assert "rugcheck" not in errors_by_source
    assert "dextools" not in errors_by_source


def test_all_sources_ok_on_example_solana_address() -> None:
    dex_pairs = load_fixture("dexscreener_solana.json")
    solscan_fixture = load_fixture("solscan_solana.json")
    rugcheck_fixture = load_fixture("rugcheck_solana.json")
    dextools_fixture = load_fixture("dextools_solana.json")
    gmgn_sec_fixture = load_fixture("gmgn_solana.json")

    def sec_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "rugcheck" in url:
            return httpx.Response(200, json=rugcheck_fixture)
        if "dexscreener" in url:
            return httpx.Response(200, json=dex_pairs)
        if "dextools" in url:
            return httpx.Response(200, json=dextools_fixture)
        if "gmgn" in url:
            return httpx.Response(200, json=gmgn_sec_fixture)
        return httpx.Response(404)

    def solscan_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2.0/token/meta":
            return httpx.Response(200, json=solscan_fixture["meta"])
        return httpx.Response(200, json=solscan_fixture["holders"])

    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=dex_pairs))
        ) as dex_http,
        httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json={"code": 0, "data": {"sniper_count": 3}})
            )
        ) as gmgn_http,
        httpx.Client(transport=httpx.MockTransport(solscan_handler)) as solscan_http,
        httpx.Client(transport=httpx.MockTransport(sec_handler)) as sec_http,
    ):
        app.dependency_overrides[get_dexscreener_client] = lambda: DexScreenerClient(dex_http)
        app.dependency_overrides[get_gmgn_client] = lambda: GmgnClient(gmgn_http, "gmgn-key")
        app.dependency_overrides[get_solscan_client] = lambda: SolscanClient(
            solscan_http, api_key="solscan-key"
        )
        app.dependency_overrides[get_security_client] = lambda: SecurityDataClient(
            sec_http,
            rugcheck_api_key="rc-key",
            dextools_api_key="dt-key",
            gmgn_api_key="gmgn-key",
        )
        try:
            with TestClient(app) as client:
                response = client.post("/analyses/token", json={"address": SOL_ADDRESS})
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 201
    body = response.json()
    assert body["address"] == SOL_ADDRESS
    assert body["status"] == "ok"
    assert body["partial"] is False
    assert body["source_errors"] == []
    assert body["errors"] == []
    assert body["sources_status"] == {
        "dexscreener": "ok",
        "gmgn": "ok",
        "solscan": "ok",
        "rugcheck": "ok",
        "dextools": "ok",
    }
    assert body["market_data"]["price_usd"] == 106.65
    assert body["gmgn_activity"]["sniper_count"] == 3
    assert body["onchain_data"]["top_10_share_percent"] == 42.5


def test_no_data_across_sources_is_handled_without_invented_zeros() -> None:
    def sec_empty_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "dexscreener" in url:
            return httpx.Response(200, json=[])
        if "rugcheck" in url:
            return httpx.Response(404, json={"error": "not found"})
        if "dextools" in url:
            return httpx.Response(200, json={"data": {}})
        if "gmgn" in url:
            return httpx.Response(200, json={"code": 0, "data": {}})
        return httpx.Response(404)

    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[]))
        ) as dex_http,
        httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json={"code": 0, "data": {}})
            )
        ) as gmgn_http,
        httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json={"success": True, "data": {}})
            )
        ) as solscan_http,
        httpx.Client(transport=httpx.MockTransport(sec_empty_handler)) as sec_http,
    ):
        app.dependency_overrides[get_dexscreener_client] = lambda: DexScreenerClient(dex_http)
        app.dependency_overrides[get_gmgn_client] = lambda: GmgnClient(gmgn_http, "gmgn-key")
        app.dependency_overrides[get_solscan_client] = lambda: SolscanClient(
            solscan_http, api_key="solscan-key"
        )
        app.dependency_overrides[get_security_client] = lambda: SecurityDataClient(
            sec_http,
            rugcheck_api_key="rc-key",
            dextools_api_key="dt-key",
            gmgn_api_key="gmgn-key",
        )
        try:
            with TestClient(app) as client:
                response = client.post("/analyses/token", json={"address": SOL_ADDRESS})
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "no_data"
    assert body["partial"] is False
    assert body["source_errors"] == []
    assert body["market_data"]["status"] == "no_data"
    assert body["market_data"]["price_usd"] is None
    assert body["gmgn_activity"]["status"] == "no_data"
    assert body["gmgn_activity"]["sniper_count"] is None
    assert body["onchain_data"]["status"] == "no_data"
    assert body["onchain_data"]["top_10_share_percent"] is None
    assert body["security_data"]["overall_status"] == "no_data"
