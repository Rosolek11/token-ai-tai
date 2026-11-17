import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.ai_analysis import (
    AIAnalysisClient, MAX_INPUT_BYTES, PROMPT_VERSION, TIMEOUT_SECONDS,
    build_messages, get_ai_client,
)
from app.main import app
from app.security_data import get_security_client
from app.source_data import NormalizedSourceData, SourceValue

ADDRESS = 'So11111111111111111111111111111111111111112'


def data(value=0):
    return NormalizedSourceData(price={'price_usd': SourceValue(
        value=value, unit='USD', sourceId='dexscreener')})


def test_only_numeric_facts_with_known_provenance():
    source = data()
    source.flags['gmgn:gmgn_honeypot'] = SourceValue(value=False, unit='signal', sourceId='gmgn')
    source.price['price_native_sol'] = SourceValue(value='<script>secret</script>', unit='SOL', sourceId='dexscreener')
    source.holders['holder_count'] = SourceValue(value=42, unit='count', sourceId='unknown')
    source.price['api_key'] = SourceValue(value=123, unit='secret', sourceId='gmgn')
    source.price['price_usd'].url = 'https://example.test?api_key=secret'
    source.price['price_usd'].unit = '<html>secret</html>'
    messages = build_messages(source)
    assert json.loads(messages[1]['content']) == {'facts': [
        {'field': 'price.price_usd', 'value': 0, 'sourceId': 'dexscreener'},
        {'field': 'flags.gmgn:gmgn_honeypot', 'value': False, 'sourceId': 'gmgn'},
    ]}
    assert 'secret' not in json.dumps(messages)
    assert len(json.dumps(messages).encode()) <= MAX_INPUT_BYTES


@pytest.mark.parametrize('value', [None, '<html>unsafe</html>', {'api_key': 'secret'}, [], float('inf')])
def test_no_safe_data_does_not_call_model(value):
    def unexpected(request):
        pytest.fail('Model must not be called')
    with httpx.Client(transport=httpx.MockTransport(unexpected)) as client:
        assert AIAnalysisClient(client, 'secret').analyse(data(value)).status == 'no_data'


def test_input_limit(monkeypatch):
    monkeypatch.setattr('app.ai_analysis.MAX_INPUT_BYTES', 10)
    with httpx.Client(transport=httpx.MockTransport(lambda r: pytest.fail('Over limit'))) as client:
        assert AIAnalysisClient(client, 'secret').analyse(data()).status == 'input_too_large'


def test_missing_key():
    with httpx.Client() as client:
        assert AIAnalysisClient(client, None).analyse(data()).status == 'not_configured'


@pytest.mark.parametrize('outcome, expected', [('ok', 'completed'), ('timeout', 'timeout'), ('http', 'unavailable'), ('invalid', 'unavailable')])
def test_transport(outcome, expected):
    def handler(request):
        body = json.loads(request.content)
        assert 'secret' not in request.content.decode()
        assert request.headers['Authorization'] == 'Bearer secret'
        assert PROMPT_VERSION in body['messages'][0]['content']
        assert all(value == TIMEOUT_SECONDS for value in request.extensions['timeout'].values())
        if outcome == 'timeout':
            raise httpx.ReadTimeout('timeout', request=request)
        if outcome == 'http':
            return httpx.Response(503)
        if outcome == 'invalid':
            return httpx.Response(200, json={})
        return httpx.Response(200, json={'choices': [{'message': {'content': 'Analiza (dexscreener).'}}]})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = AIAnalysisClient(client, 'secret').analyse(data())
    assert result.status == expected
    assert result.prompt_version == PROMPT_VERSION


def test_solana_endpoint_with_normalized_report():
    def handler(request):
        return httpx.Response(200, json={'choices': [{'message': {'content': 'Dane źródłowe: dexscreener.'}}]})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        ai = AIAnalysisClient(client, 'secret')
        app.dependency_overrides[get_ai_client] = lambda: ai
        app.dependency_overrides[get_security_client] = lambda: SimpleNamespace(
            fetch_token_security=lambda address: SimpleNamespace(normalized_data=data()))
        try:
            response = TestClient(app).post(f'/api/tokens/{ADDRESS}/ai-analysis')
            assert response.status_code == 200
            assert response.json()['status'] == 'completed'
            assert TestClient(app).post('/api/tokens/invalid/ai-analysis').status_code == 422
        finally:
            app.dependency_overrides.pop(get_ai_client)
            app.dependency_overrides.pop(get_security_client)
