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


def test_analysis_page_serves_address_form() -> None:
    response = client.get("/analysis")
    assert response.status_code == 200
    assert 'id="analysis-form"' in response.text
    assert 'name="subject-type" value="token"' in response.text
    assert 'name="subject-type" value="wallet"' in response.text
    assert 'id="address" name="address"' in response.text
    assert 'required minlength="32" maxlength="64"' in response.text
    assert "/assets/analysis.js" in response.text


def test_frontend_assets_are_available() -> None:
    for path in ("/assets/styles.css", "/assets/main.js", "/assets/analysis.js", "/assets/logo.png"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.content


def test_analysis_form_validates_and_prevents_duplicate_submissions() -> None:
    response = client.get("/assets/analysis.js")
    assert response.status_code == 200
    assert "base58Pattern" in response.text
    assert "32,64" in response.text
    assert "submitButton.disabled = true" in response.text
    assert "event.preventDefault()" in response.text
    assert "Enter a Solana address to continue." in response.text


def test_client_config_does_not_expose_secrets() -> None:
    response = client.get("/api/client-config")
    assert response.status_code == 200
    assert response.json() == {"apiBaseUrl": app.state.settings.public_api_base_url}
    assert "api_key" not in response.text.lower()
