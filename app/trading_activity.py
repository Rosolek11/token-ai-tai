"""Optional read-only GMGN Agent API enrichment."""
from datetime import datetime, timezone
from time import time
from typing import Iterator, Literal
from uuid import uuid4

import httpx
from fastapi import Request
from pydantic import BaseModel

from app.market_data import OptionalCount


class GmgnActivity(BaseModel):
    source: Literal["gmgn"] = "gmgn"
    source_url: str = "https://openapi.gmgn.ai/v1/token/security"
    updated_at: datetime
    status: Literal["ok", "no_data", "not_configured", "unauthorized", "rate_limited", "unavailable"]
    sniper_count: OptionalCount = None


class GmgnClient:
    def __init__(self, client: httpx.Client, api_key: str | None):
        self.client = client
        self.api_key = api_key

    def fetch_activity(self, address: str) -> GmgnActivity:
        result = GmgnActivity(updated_at=datetime.now(timezone.utc), status="not_configured")
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
                return result
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("code") != 0:
                result.status = "unavailable"
                return result
            data = payload.get("data")
            if data is None:
                result.status = "no_data"
                return result
            if not isinstance(data, dict):
                raise ValueError("Invalid GMGN data")
            return GmgnActivity(
                updated_at=result.updated_at,
                status="ok" if data.get("sniper_count") is not None else "no_data",
                sniper_count=data.get("sniper_count"),
            )
        except (httpx.HTTPError, ValueError):
            result.status = "unavailable"
            return result


def get_gmgn_client(request: Request) -> Iterator[GmgnClient]:
    with httpx.Client(timeout=10.0) as client:
        yield GmgnClient(client, request.app.state.settings.gmgn_api_key)
