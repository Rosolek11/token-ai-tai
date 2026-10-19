from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_home_serves_web_application() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Token AI" in response.text
    assert 'id="tab-token"' in response.text
    assert 'id="tab-wallet"' in response.text
    assert "/assets/main.js" in response.text


def test_frontend_assets_are_available() -> None:
    for path in ("/assets/styles.css", "/assets/main.js", "/assets/logo.png"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.content


def test_client_config_does_not_expose_secrets() -> None:
    response = client.get("/api/client-config")
    assert response.status_code == 200
    assert response.json() == {"apiBaseUrl": app.state.settings.public_api_base_url}
    assert "api_key" not in response.text.lower()
