"""Read-only DEX Screener profile orders; boosts are not paid listings."""
from datetime import datetime, timezone
from typing import Iterator, Literal

import httpx
from pydantic import BaseModel


class ListingStatus(BaseModel):
    status: Literal['ok', 'unavailable']
    dex_paid: bool | None = None
    reason: str | None = None
    source: str = 'dexscreener'
    source_url: str
    updated_at: datetime


class ListingClient:
    def __init__(self, client: httpx.Client):
        self.client = client

    def fetch(self, address: str) -> ListingStatus:
        url = f'https://api.dexscreener.com/orders/v1/solana/{address}'
        result = ListingStatus(status='unavailable', source_url=url, updated_at=datetime.now(timezone.utc))
        try:
            response = self.client.get(url)
            response.raise_for_status()
            data = response.json()
            orders = data.get('orders') if isinstance(data, dict) else data
            if not isinstance(orders, list) or any(not isinstance(item, dict) for item in orders):
                result.reason = 'invalid_response'
                return result
            # Preserve unknown when fields are missing rather than claiming unpaid.
            profiles = [item for item in orders if item.get('type') == 'tokenProfile']
            if any(not isinstance(item.get('status'), str) for item in profiles):
                result.reason = 'incomplete_orders'
                return result
            result.status = 'ok'
            result.dex_paid = any(item.get('status') == 'approved' for item in profiles)
        except (httpx.HTTPError, ValueError):
            result.reason = 'provider_unavailable'
        return result


def get_listing_client() -> Iterator[ListingClient]:
    with httpx.Client(timeout=5.0) as client:
        yield ListingClient(client)
