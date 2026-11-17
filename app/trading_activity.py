"""Optional read-only GMGN Agent API enrichment."""
from datetime import datetime, timezone
from time import time
from typing import Iterator, Literal
from uuid import uuid4

import httpx
from fastapi import Request
from pydantic import BaseModel

from app.market_data import OptionalCount, get_dexscreener_client


class GmgnActivity(BaseModel):
    source: Literal["gmgn"] = "gmgn"
    source_url: str = "https://openapi.gmgn.ai/v1/token/security"
    updated_at: datetime
    status: Literal["ok", "no_data", "not_configured", "unauthorized", "rate_limited", "unavailable"]
    reason: str | None = None
    sniper_count: OptionalCount = None


class GmgnClient:
    def __init__(self, client: httpx.Client, api_key: str | None):
        self.client = client
        self.api_key = api_key

    def fetch_activity(self, address: str) -> GmgnActivity:
        result = GmgnActivity(
            updated_at=datetime.now(timezone.utc),
            status="not_configured",
            reason="missing_api_key",
        )
        if not self.api_key:
            return result
        try:
            response = self.client.get(
                result.source_url,
                params={"chain": "sol", "address": address, "timestamp": int(time()), "client_id": str(uuid4())},
                headers={"X-APIKEY": self.api_key},
            )
            if response.status_code in (401, 403, 429):
                result.status = "rate_limited" if response.status_code == 429 else "unauthorized"
                result.reason = "rate_limited" if response.status_code == 429 else "access_denied"
                return result
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("code") != 0:
                result.status = "unavailable"
                result.reason = "source_error"
                return result
            data = payload.get("data")
            if data is None:
                result.status = "no_data"
                result.reason = None
                return result
            if not isinstance(data, dict):
                raise ValueError("Invalid GMGN data")
            return GmgnActivity(
                updated_at=result.updated_at,
                status="ok" if data.get("sniper_count") is not None else "no_data",
                reason=None,
                sniper_count=data.get("sniper_count"),
            )
        except httpx.TimeoutException:
            result.status = "unavailable"
            result.reason = "timeout"
            return result
        except (httpx.HTTPError, ValueError):
            result.status = "unavailable"
            result.reason = "source_error"
            return result


def get_gmgn_client(request: Request) -> Iterator[GmgnClient]:
    if (
        get_dexscreener_client in request.app.dependency_overrides
        and get_gmgn_client not in request.app.dependency_overrides
    ):
        transport = httpx.MockTransport(
            lambda req: httpx.Response(503, json={"detail": "offline_test_transport"})
        )
        with httpx.Client(transport=transport, timeout=10.0) as offline_client:
            yield GmgnClient(offline_client, None)
        return

    with httpx.Client(timeout=10.0) as client:
        yield GmgnClient(client, request.app.state.settings.gmgn_api_key)
