import httpx
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.listing_data import ListingClient, get_listing_client


@pytest.mark.parametrize('payload,expected', [
    ({'orders':[{'type':'tokenProfile','status':'approved'}]}, True),
    ([{'type':'tokenProfile','status':'approved'}], True),
    ({'orders':[{'type':'tokenProfile','status':'cancelled'}]}, False),
    ({'orders':[], 'boosts':[{'amount':100}]}, False),
    ({'orders':[{'type':'tokenAd','status':'approved'}]}, False),
    ({'orders':[{'type':'tokenProfile'}]}, None),
    ({}, None),
    ({'orders':['invalid']}, None),
])
def test_order_semantics(payload, expected):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))) as client:
        assert ListingClient(client).fetch('test').dex_paid is expected


@pytest.mark.parametrize('status', [401,403,429,500])
def test_failed_provider_is_unknown(status):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status))) as client:
        result = ListingClient(client).fetch('test')
        assert result.status == 'unavailable'
        assert result.dex_paid is None


def test_listing_route_validates_address_before_http():
    class Provider:
        def fetch(self, address):
            raise AssertionError('Must not send an invalid address')
    app.dependency_overrides[get_listing_client] = lambda: Provider()
    try:
        assert TestClient(app).get('/api/tokens/invalid/listing').status_code == 422
    finally:
        app.dependency_overrides.pop(get_listing_client)


def test_public_map_config_contains_no_api_secrets():
    data = TestClient(app).get('/api/research-config').json()
    assert list(data) == ['bubblemapsPartnerId']
