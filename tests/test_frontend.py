from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
ADDRESS = "So11111111111111111111111111111111111111112"


def test_home_serves_web_application() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Token AI" in response.text
    assert 'href="/analysis"' in response.text


def test_analysis_page_serves_address_form() -> None:
    response = client.get("/analysis")
    assert response.status_code == 200
    assert 'id="analysis-form"' in response.text
    assert 'name="subject-type" value="token"' in response.text
    assert 'name="subject-type" value="wallet"' in response.text
    assert 'required minlength="32" maxlength="44"' in response.text
    assert "/assets/analysis-common.js" in response.text
    assert "/assets/analysis.js" in response.text


def test_token_report_supports_direct_visits_and_reload() -> None:
    for _ in range(2):
        response = client.get(f"/token/{ADDRESS}")
        assert response.status_code == 200
        assert 'id="loading-state"' in response.text
        assert 'id="error-state"' in response.text
        assert 'id="report-content"' in response.text
        assert 'data-market-value="price_usd"' in response.text
        assert "/assets/token.js" in response.text


def test_invalid_token_route_still_serves_error_capable_interface() -> None:
    response = client.get("/token/not-a-solana-address")
    assert response.status_code == 200
    assert 'id="error-detail"' in response.text


def test_frontend_assets_are_available() -> None:
    for asset in ("styles.css", "token.css", "report-intro.css", "main.js", "analysis-common.js", "analysis.js", "report-intro.js", "token.js", "logo.png"):
        response = client.get(f"/assets/{asset}")
        assert response.status_code == 200
        assert response.content


def test_client_config_does_not_expose_secrets() -> None:
    response = client.get("/api/client-config")
    assert response.status_code == 200
    assert response.json() == {"apiBaseUrl": app.state.settings.public_api_base_url}
    assert "api_key" not in response.text.lower()
