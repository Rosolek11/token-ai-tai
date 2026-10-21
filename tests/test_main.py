from typing import Iterator
from unittest.mock import Mock

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app, validate_solana_address
from app.market_data import DexScreenerClient, get_dexscreener_client

client = TestClient(app)
VALID_ADDRESS = "So11111111111111111111111111111111111111112"
VALID_ADDRESSES = [
    VALID_ADDRESS,
    "1" * 32,
    "1" * 31 + "2",
    "1" + "z" * 42,
    "JEKNVnkbo3jma5nREBBJCDoXFVeKkD56V3xKrvRmWxFG",
]
INVALID_ADDRESSES = [
    "",
    "1" * 31,
    "1" * 33,
    "z" * 32,
    "2" * 43,
    "z" * 44,
    "1" + "z" * 43,
    "1" * 45,
    "1" * 64,
    "1" * 65,
    " " + VALID_ADDRESS,
    VALID_ADDRESS + " ",
    VALID_ADDRESS + "\n",
    "invalid-address-!",
    *["1" * 31 + character for character in "0OIl! ł"],
]


@pytest.fixture(autouse=True)
def mock_market_provider() -> Iterator[None]:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
    with httpx.Client(transport=transport) as http_client:
        app.dependency_overrides[get_dexscreener_client] = lambda: DexScreenerClient(
            http_client
        )
        try:
            yield
        finally:
            app.dependency_overrides.pop(get_dexscreener_client, None)


def test_health_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize("address", VALID_ADDRESSES)
def test_validate_solana_address_accepts_32_decoded_bytes(address: str) -> None:
    validate_solana_address(address)


@pytest.mark.parametrize("address", INVALID_ADDRESSES)
def test_validate_solana_address_rejects_invalid_address(address: str) -> None:
    with pytest.raises(HTTPException) as error:
        validate_solana_address(address)
    assert error.value.status_code == 422
    assert error.value.detail == "INVALID_ADDRESS"


@pytest.mark.parametrize("subject_type", ["wallet", "token"])
@pytest.mark.parametrize("address", VALID_ADDRESSES)
def test_analysis_accepts_base58_solana_address(subject_type: str, address: str) -> None:
    response = client.post(f"/analyses/{subject_type}", json={"address": address})
    assert response.status_code == 201
    assert response.json()["subject_type"] == subject_type
    assert response.json()["address"] == address


@pytest.fixture
def analysis_id_factory(monkeypatch: pytest.MonkeyPatch) -> Mock:
    factory = Mock(side_effect=AssertionError("Invalid input must not start an analysis"))
    monkeypatch.setattr("app.main.uuid4", factory)
    return factory


@pytest.mark.parametrize("subject_type", ["wallet", "token"])
@pytest.mark.parametrize("address", [*INVALID_ADDRESSES, None, 123, True, [], {}])
def test_analysis_rejects_invalid_address_before_processing(
    subject_type: str, address: object, analysis_id_factory: Mock
) -> None:
    response = client.post(f"/analyses/{subject_type}", json={"address": address})
    assert response.status_code == 422
    assert response.json() == {"detail": "INVALID_ADDRESS"}
    analysis_id_factory.assert_not_called()


@pytest.mark.parametrize("subject_type", ["wallet", "token"])
@pytest.mark.parametrize("payload", [{}, {"other": VALID_ADDRESS}, [], VALID_ADDRESS, 123])
def test_analysis_rejects_missing_address(
    subject_type: str, payload: object, analysis_id_factory: Mock
) -> None:
    response = client.post(f"/analyses/{subject_type}", json=payload)
    assert response.status_code == 422
    assert response.json() == {"detail": "INVALID_ADDRESS"}
    analysis_id_factory.assert_not_called()


@pytest.mark.parametrize("subject_type", ["wallet", "token"])
@pytest.mark.parametrize("body", ["", "null", '{"address":'])
def test_analysis_rejects_missing_or_malformed_body(
    subject_type: str, body: str, analysis_id_factory: Mock
) -> None:
    response = client.post(
        f"/analyses/{subject_type}",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "INVALID_ADDRESS"}
    analysis_id_factory.assert_not_called()


@pytest.mark.parametrize("address", VALID_ADDRESSES)
def test_token_analyses_accepts_base58_solana_address(address: str) -> None:
    response = client.post("/api/token-analyses", json={"address": address})
    assert response.status_code == 202
    body = response.json()
    assert body["id"]
    assert body["status"] == "pending"
    assert body["subject_type"] == "token"
    assert body["address"] == address


@pytest.mark.parametrize("address", [*INVALID_ADDRESSES, None, 123, True, [], {}])
def test_token_analyses_rejects_invalid_address_before_processing(
    address: object, analysis_id_factory: Mock
) -> None:
    response = client.post("/api/token-analyses", json={"address": address})
    assert response.status_code == 422
    assert response.json() == {"detail": "INVALID_ADDRESS"}
    analysis_id_factory.assert_not_called()


@pytest.mark.parametrize("payload", [{}, {"other": VALID_ADDRESS}, [], VALID_ADDRESS, 123])
def test_token_analyses_rejects_missing_address(
    payload: object, analysis_id_factory: Mock
) -> None:
    response = client.post("/api/token-analyses", json=payload)
    assert response.status_code == 422
    assert response.json() == {"detail": "INVALID_ADDRESS"}
    analysis_id_factory.assert_not_called()


@pytest.mark.parametrize("body", ["", "null", '{"address":'])
def test_token_analyses_rejects_missing_or_malformed_body(
    body: str, analysis_id_factory: Mock
) -> None:
    response = client.post(
        "/api/token-analyses",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "INVALID_ADDRESS"}
    analysis_id_factory.assert_not_called()
