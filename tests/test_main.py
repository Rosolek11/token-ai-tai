from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
VALID_ADDRESS = "So11111111111111111111111111111111111111112"


def test_health_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_wallet_analysis_accepts_base58_solana_address() -> None:
    response = client.post("/analyses/wallet", json={"address": VALID_ADDRESS})
    assert response.status_code == 201
    assert response.json()["subject_type"] == "wallet"


def test_token_analysis_rejects_non_base58_address() -> None:
    response = client.post("/analyses/token", json={"address": "invalid-address-!"})
    assert response.status_code == 422
