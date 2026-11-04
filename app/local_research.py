"""Local calculations from verifiable facts. No proprietary provider scores."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Iterator

import httpx
from fastapi import Request


def decimal_amount(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        n = Decimal(str(value))
        return n if n.is_finite() and n >= 0 else None
    except (InvalidOperation, ValueError):
        return None


def concentration(accounts: list[dict], supply) -> dict:
    """Account share, NOT owner concentration. RPC returns at most 20 accounts."""
    total = decimal_amount(supply)
    amounts = [decimal_amount(row.get('amount')) for row in accounts]
    if not total or any(value is None for value in amounts):
        return {'top10_accounts_pct': None, 'sample_supply_pct': None, 'sample_accounts': len(accounts)}
    amounts.sort(reverse=True)
    if sum(amounts) > total:
        return {'top10_accounts_pct': None, 'sample_supply_pct': None, 'sample_accounts': len(accounts)}
    return {'top10_accounts_pct': float(sum(amounts[:10]) / total * 100),
            'sample_supply_pct': float(sum(amounts) / total * 100), 'sample_accounts': len(accounts)}


def tagged_supply(positions: list[dict], supply, tag: str, *, complete: bool) -> float | None:
    """Requires an explicitly complete labelled holder population, not a top-N sample."""
    total = decimal_amount(supply)
    if not complete or not total:
        return None
    balances = [decimal_amount(row.get('amount')) for row in positions]
    if any(value is None for value in balances) or sum(balances) > total:
        return None
    selected = sum((balance for row, balance in zip(positions, balances) if tag in row.get('tags', [])), Decimal(0))
    return float(selected / total * 100)


def profitable_holders(positions: list[dict], price, *, complete: bool) -> dict:
    """Unrealized profit among current owners with known remaining cost basis."""
    current = decimal_amount(price)
    owners = [row for row in positions if (decimal_amount(row.get('ui_amount')) or 0) > 0]
    known, profitable = 0, 0
    for row in owners:
        balance = decimal_amount(row.get('ui_amount'))
        cost = decimal_amount(row.get('remaining_cost_usd'))
        if current is None or cost is None:
            continue
        known += 1
        profitable += balance * current > cost
    return {'known_cost_holders': known, 'sample_holders': len(owners),
            'known_cost_coverage_pct': known / len(owners) * 100 if owners else None,
            'profitable_known_cost_pct': profitable / known * 100 if known else None,
            'all_holders_in_profit_pct': profitable / known * 100 if complete and known and known == len(owners) else None}


def fresh_activity(trades: list[dict], positions: list[dict], supply, *, now: int,
                   complete_trades: bool, complete_holders: bool) -> dict:
    """v1 definition: first on-chain activity within 7 days; buy window 24h.
    Records must include full-history first activity, not first tx in a truncated page.
    A newly funded address is only a heuristic, not proof of a new person.
    """
    start = now - 86400
    buys = [trade for trade in trades if trade.get('side') == 'buy' and start <= trade.get('timestamp', -1) <= now]
    all_dated = all(type(t.get('wallet_first_activity')) is int for t in buys)
    count = sum(now - 7 * 86400 <= trade['wallet_first_activity'] <= trade['timestamp'] for trade in buys) if all_dated else None
    labelled = []
    all_holders_dated = True
    for row in positions:
        first = row.get('wallet_first_activity')
        all_holders_dated &= type(first) is int
        labelled.append({**row, 'tags': ['fresh'] if type(first) is int and now - 7 * 86400 <= first <= now else []})
    return {'fresh_buys_24h': count if complete_trades and all_dated else None,
            'fresh_holding_pct': tagged_supply(labelled, supply, 'fresh', complete=complete_holders and all_holders_dated),
            'definition': 'first_activity_7d_buy_window_24h_v1'}


class LocalResearchClient:
    def __init__(self, client: httpx.Client, rpc_url: str):
        self.client, self.rpc_url = client, rpc_url

    def rpc(self, method, params):
        response = self.client.post(self.rpc_url, json={'jsonrpc': '2.0', 'id': method, 'method': method, 'params': params})
        response.raise_for_status()
        body = response.json()
        if isinstance(body, dict) and isinstance(body.get('error'), dict):
            code = body['error'].get('code')
            raise ValueError('rpc_error_code_' + str(code) if type(code) is int else 'rpc_error')
        if not isinstance(body, dict) or body.get('error') or not isinstance(body.get('result'), dict):
            raise ValueError('rpc_error')
        return body['result']

    def fetch(self, address: str) -> dict:
        result = {'address': address, 'source': 'solana_rpc_local_math', 'status': 'unavailable',
                  'updated_at': datetime.now(timezone.utc).isoformat(), 'mint_authority_active': None,
                  'freeze_authority_active': None, 'top10_accounts_pct': None, 'sample_supply_pct': None,
                  'sample_accounts': None, 'slots': {},
                  'methodology': 'Top 20 token-account sample; not unique owners. Pool vaults are included. Different slots may differ. Native SOL wrapper has no ordinary supply denominator.'}
        try:
            mint = self.rpc('getAccountInfo', [address, {'encoding': 'jsonParsed', 'commitment': 'finalized'}])
            value = mint.get('value')
            if not isinstance(value, dict):
                raise ValueError('mint_unavailable')
            parsed = value.get('data', {}).get('parsed', {})
            info = parsed.get('info', {})
            if parsed.get('type') != 'mint' or value.get('owner') not in (
                'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA', 'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'):
                raise ValueError('unsupported_mint')
            for source, target in [('mintAuthority', 'mint_authority_active'), ('freezeAuthority', 'freeze_authority_active')]:
                if source in info:
                    authority = info[source]
                    if authority is None:
                        result[target] = False
                    elif isinstance(authority, str) and authority:
                        result[target] = True
            result['slots']['mint'] = mint.get('context', {}).get('slot')
            result['status'] = 'partial'
            if address == 'So11111111111111111111111111111111111111112':
                result['reason'] = 'native_wrapped_sol_supply_not_applicable'
                return result
            largest = self.rpc('getTokenLargestAccounts', [address, {'commitment': 'finalized'}])
            rows = largest.get('value')
            if not isinstance(rows, list) or len(rows) > 20 or any(not isinstance(row, dict) for row in rows):
                raise ValueError('invalid_account_sample')
            ids = [row.get('address') for row in rows]
            if any(not isinstance(item, str) for item in ids) or len(set(ids)) != len(ids):
                raise ValueError('duplicate_or_missing_accounts')
            result.update(concentration(rows, info.get('supply')))
            result['slots']['accounts'] = largest.get('context', {}).get('slot')
            result['status'] = 'ok' if result['top10_accounts_pct'] is not None else 'partial'
        except httpx.HTTPStatusError as error:
            result['reason'] = 'rpc_http_' + str(error.response.status_code)
        except (httpx.HTTPError, ValueError, TypeError, AttributeError) as error:
            result['reason'] = 'rpc_unavailable_or_incomplete'
            if isinstance(error, ValueError) and str(error).startswith('rpc_error_code_'):
                result['reason'] = str(error)
        return result


def get_local_research_client(request: Request) -> Iterator[LocalResearchClient]:
    with httpx.Client(timeout=4.0) as client:
        yield LocalResearchClient(client, request.app.state.settings.solana_rpc_url)
