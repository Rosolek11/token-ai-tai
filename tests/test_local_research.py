import httpx
import pytest
from app.local_research import concentration, tagged_supply, profitable_holders, fresh_activity, LocalResearchClient


def test_raw_integer_precision_and_account_concentration():
    scale = 10**25
    result = concentration([{'amount':str(scale*3)},{'amount':str(scale*2)}],str(scale*10))
    assert result['top10_accounts_pct'] == 50
    assert result['sample_accounts'] == 2


@pytest.mark.parametrize('supply', [None, 0, '0', False, -1, 'NaN'])
def test_no_denominator_means_unknown(supply):
    assert concentration([{'amount':'10'}], supply)['top10_accounts_pct'] is None


def test_inconsistent_supply_does_not_become_over_100_percent():
    assert concentration([{'amount':'101'}], '100')['top10_accounts_pct'] is None


def test_tagged_share_requires_complete_population():
    rows=[{'amount':'40','tags':['sniper']},{'amount':'60','tags':[]}]
    assert tagged_supply(rows,100,'sniper',complete=False) is None
    assert tagged_supply(rows,100,'sniper',complete=True) == 40


def test_profit_coverage_not_extrapolated_to_all_holders():
    rows=[{'ui_amount':10,'remaining_cost_usd':5},{'ui_amount':5,'remaining_cost_usd':None}]
    result=profitable_holders(rows,1,complete=True)
    assert result['known_cost_coverage_pct'] == 50
    assert result['profitable_known_cost_pct'] == 100
    assert result['all_holders_in_profit_pct'] is None


def test_full_profit_population_excludes_closed_positions_and_break_even():
    rows=[{'ui_amount':10,'remaining_cost_usd':5},{'ui_amount':5,'remaining_cost_usd':5},{'ui_amount':0,'remaining_cost_usd':0}]
    assert profitable_holders(rows,1,complete=True)['all_holders_in_profit_pct'] == 50
    assert profitable_holders(rows,1,complete=False)['all_holders_in_profit_pct'] is None


def test_fresh_buys_and_supply_have_separate_denominators():
    now=2000000
    trades=[{'side':'buy','timestamp':now-60,'wallet_first_activity':now-100},
            {'side':'sell','timestamp':now-60,'wallet_first_activity':now-100},
            {'side':'buy','timestamp':now-90000,'wallet_first_activity':now-100000}]
    positions=[{'amount':40,'wallet_first_activity':now-100},{'amount':60,'wallet_first_activity':now-900000}]
    result=fresh_activity(trades,positions,100,now=now,complete_trades=True,complete_holders=True)
    assert result['fresh_buys_24h'] == 1
    assert result['fresh_holding_pct'] == 40
    result=fresh_activity(trades,positions,100,now=now,complete_trades=False,complete_holders=False)
    assert result['fresh_buys_24h'] is None and result['fresh_holding_pct'] is None


def test_rpc_failure_has_no_manufactured_zero():
    with httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(429))) as client:
        result=LocalResearchClient(client,'https://rpc.invalid').fetch('address')
    assert result['status'] == 'unavailable'
    assert result['top10_accounts_pct'] is None
    assert result['mint_authority_active'] is None
    assert result['sample_accounts'] is None


def test_rpc_uses_mint_and_account_sample_without_private_provider():
    def handler(request):
        import json
        body=json.loads(request.content)
        value=({'owner':'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA','data':{'parsed':{'type':'mint','info':{'supply':'1000','mintAuthority':None,'freezeAuthority':'authority'}}}}
               if body['method']=='getAccountInfo' else [{'address':'account','amount':'250'}])
        return httpx.Response(200,json={'result':{'context':{'slot':42},'value':value}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result=LocalResearchClient(client,'https://rpc.invalid').fetch('address')
    assert result['status'] == 'ok'
    assert result['top10_accounts_pct'] == 25
    assert result['mint_authority_active'] is False
    assert result['freeze_authority_active'] is True


def test_wrapped_sol_does_not_get_false_zero_concentration():
    def handler(request):
        return httpx.Response(200,json={'result':{'value':{'owner':'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA','data':{'parsed':{'type':'mint','info':{'supply':'0','mintAuthority':None,'freezeAuthority':None}}}}}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result=LocalResearchClient(client,'https://rpc.invalid').fetch('So11111111111111111111111111111111111111112')
    assert result['top10_accounts_pct'] is None
    assert result['reason'] == 'native_wrapped_sol_supply_not_applicable'


def test_local_route_validates_address_without_contacting_rpc():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.local_research import get_local_research_client
    class Provider:
        def fetch(self, address):
            raise AssertionError('Invalid address must not reach the network')
    app.dependency_overrides[get_local_research_client] = lambda: Provider()
    try:
        assert TestClient(app).get('/api/tokens/invalid/local-research').status_code == 422
    finally:
        app.dependency_overrides.pop(get_local_research_client)
