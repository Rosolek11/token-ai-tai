const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const address = 'So11111111111111111111111111111111111111112';
const read = name => fs.readFileSync(path.join(__dirname, '../frontend', name), 'utf8');
function element() {
  return {
    hidden: false, disabled: false, textContent: '', value: '', className: '',
    dataset: {}, listeners: {}, attributes: {}, children: {},
    addEventListener(event, handler) { this.listeners[event] = handler; },
    setAttribute(name, value) { this.attributes[name] = value; },
    removeAttribute(name) { delete this.attributes[name]; },
    focus() { this.focused = true; },
    querySelector(selector) { return this.children[selector]; },
  };
}
function page(fetchHandler = async () => { throw new Error('Unexpected request'); }, pathname = '/analysis') {
  const names = ['analysis-form', 'address', 'analysis-submit', 'analysis-message', 'use-example',
    'market-report', 'loading-state', 'error-state', 'report-content', 'refresh-report',
    'retry-analysis', 'copy-address', 'report-address', 'report-stage', 'report-state-badge',
    'report-state-label', 'report-status', 'source-state', 'source-led', 'error-title',
    'error-detail', 'empty-market', 'partial-market', 'report-token-name', 'pair-summary', 'copy-feedback',
    'security-report', 'security-verdict', 'security-flags-count', 'security-flags-list',
    'top-holders-list', 'security-overall-status', 'security-source-state', 'security-source-led'];
  const elements = Object.fromEntries(names.map(name => [name, element()]));
  elements.address.value = address;
  elements['analysis-form'].elements = { 'subject-type': { value: 'token' } };
  elements['analysis-submit'].children.span = element();
  for (const key of ['price_usd', 'liquidity_usd', 'volume_24h_usd', 'price_change_24h_percent', 'updated_at']) {
    elements['market-report'].children[`[data-market-value="${key}"]`] = element();
  }
  elements['market-report'].children['[data-market-source]'] = element();
  for (const src of ['rugcheck', 'dexscreener', 'dextools', 'gmgn']) {
    elements['security-report'].children[`[data-security-source="${src}"]`] = element();
    elements['security-report'].children[`[data-source-status="${src}"]`] = element();
  }
  for (const key of [
    'risk_level', 'safety_score', 'normalized_score', 'risk_score', 'is_honeypot', 'rugged',
    'dextools_score', 'flags_counts', 'mint_authority_active', 'mint_authority',
    'freeze_authority_active', 'freeze_authority', 'mutable_metadata', 'update_authority',
    'token_program', 'transfer_fee_pct', 'buy_sell_tax', 'contract_verification',
    'blacklist_scam_check', 'holder_count', 'top_holder_pct', 'top_holder_address',
    'top_5_holders_pct', 'top_10_holders_pct', 'creator_balance_pct', 'creator_address',
    'insider_summary', 'bundled_supply_pct', 'snipers_and_rugs', 'total_market_liquidity_usd',
    'lp_locked_pct', 'lp_burned_pct', 'lp_locked_usd', 'lp_providers_count', 'fdv_mcap',
    'short_term_volume', 'short_term_price_change', 'txns_buys_sells_24h', 'buy_sell_ratio_24h',
    'txns_short_term', 'pair_age_boosts', 'dex_list', 'supply_decimals', 'verification_status', 'social_links'
  ]) {
    elements['security-report'].children[`[data-security-value="${key}"]`] = element();
  }
  elements['security-report'].children['[data-rugcheck-source]'] = element();
  const navigations = [];
  const listeners = {};
  const context = {
    document: { getElementById: name => elements[name] },
    location: { origin: 'https://token.example.test', pathname, assign: url => navigations.push(url) },
    addEventListener: (name, handler) => { listeners[name] = handler; },
    setTimeout, clearTimeout, AbortController, TypeError, URL, Intl, Date, fetch: fetchHandler,
    navigator: { clipboard: { writeText: async () => {} } },
  };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(read('analysis-common.js'), context);
  return { context, elements, navigations, listeners,
    common: context.TokenAI,
    form() { vm.runInContext(read('analysis.js'), context); },
    report() { vm.runInContext(read('token.js'), context); return context.reportRequest; },
    submit() { return elements['analysis-form'].listeners.submit({ preventDefault() {} }); },
    metric: key => elements['market-report'].children[`[data-market-value="${key}"]`].textContent,
  };
}
const config = () => ({ ok: true, json: async () => ({ apiBaseUrl: '' }) });
const data = (market = {}) => ({
  subject_type: 'token', address, market_data: {
    status: 'ok', pairs: [{ pair_address: 'pair', dex_id: 'raydium', base_token: { symbol: 'SOL' } }],
    primary_pair_address: 'pair', price_usd: 106.65, liquidity_usd: 0,
    volume_24h_usd: 100, price_change_24h_percent: -2.22,
    updated_at: '2026-10-21T07:57:07Z', ...market,
  },
});
const ok = value => ({ ok: true, json: async () => value });
for (const value of [undefined, null, '', ' ', '\t\n', false, true, [], {}, 'NaN', 'Infinity', 'invalid']) {
  test(`missing or invalid metric stays unavailable: ${JSON.stringify(value)}`, () => {
    const current = page();
    assert.equal(current.common.formatUsd(value), 'No data');
    assert.equal(current.common.formatPercent(value), 'No data');
  });
}
test('zero, tiny prices and negative changes remain distinct from missing data', () => {
  const current = page();
  assert.equal(current.common.formatUsd(0), '$0.00');
  assert.equal(current.common.formatUsd('0.00000001'), '$0.00000001');
  assert.equal(current.common.formatPercent(0), '+0%');
  assert.equal(current.common.formatPercent(-2.22), '-2.22%');
});
test('report renders metrics, exact source and clears stale values on empty response', () => {
  const current = page();
  const source_url = 'https://api.dexscreener.com/token-pairs/v1/solana/' + address;
  current.common.updateMarketReport(data({ source_url }), address);
  assert.equal(current.metric('price_usd'), '$106.65');
  assert.equal(current.metric('liquidity_usd'), '$0.00');
  assert.equal(current.metric('price_change_24h_percent'), '-2.22%');
  assert.notEqual(current.metric('updated_at'), 'No data');
  assert.equal(current.elements['market-report'].children['[data-market-source]'].href, source_url);
  current.common.updateMarketReport({ market_data: {} }, address);
  for (const metric of ['price_usd','liquidity_usd','volume_24h_usd','price_change_24h_percent','updated_at']) assert.equal(current.metric(metric), 'No data');
});
for (const source_url of ['javascript:alert(1)', 'http://example.test', 'malformed']) {
  test(`unsafe source falls back to DEX Screener: ${source_url}`, () => {
    const current = page();
    current.common.updateMarketReport(data({ source_url }), address);
    assert.equal(current.elements['market-report'].children['[data-market-source]'].href, 'https://dexscreener.com/solana/' + address);
  });
}
for (const value of [address, '1'.repeat(32), '1'.repeat(31) + '2', '1' + 'z'.repeat(42), 'JEKNVnkbo3jma5nREBBJCDoXFVeKkD56V3xKrvRmWxFG']) {
  test(`accepts a 32-byte Solana address: ${value}`, () => assert.equal(page().common.isSolanaAddress(value), true));
}
for (const value of ['', 'invalid-address-!', '1'.repeat(31), '1'.repeat(33), 'z'.repeat(32), 'z'.repeat(44), '1'.repeat(64)]) {
  test(`invalid input makes no request or navigation: ${value}`, async () => {
    const current = page();
    current.form();
    current.elements.address.value = value;
    await current.submit();
    assert.equal(current.elements.address.attributes['aria-invalid'], 'true');
    assert.equal(current.elements['analysis-message'].dataset.state, 'error');
    assert.equal(current.navigations.length, 0);
  });
}
test('token submit navigates to address URL, blocks duplicate navigation and resets on back', async () => {
  const current = page();
  current.form();
  current.elements.address.value = ' ' + address + ' ';
  await current.submit();
  await current.submit();
  assert.deepEqual(current.navigations, ['/token/' + address]);
  assert.equal(current.elements['analysis-submit'].disabled, true);
  current.listeners.pageshow();
  assert.equal(current.elements['analysis-submit'].disabled, false);
});
test('example fills the address and clears validation errors', () => {
  const current = page();
  current.form();
  current.elements.address.value = 'invalid';
  current.elements['use-example'].listeners.click();
  assert.equal(current.elements.address.value, address);
  assert.equal(current.elements.address.focused, true);
});
test('wallet uses configured API and remains explicit about report availability', async () => {
  const calls = [];
  const current = page(async (url, options) => {
    calls.push({url, options});
    return calls.length === 1 ? ok({ apiBaseUrl: 'https://api.example.test/' }) : ok({subject_type:'wallet',address});
  });
  current.form();
  current.elements['analysis-form'].elements['subject-type'].value = 'wallet';
  await current.submit();
  assert.equal(calls[1].url, 'https://api.example.test/analyses/wallet');
  assert.deepEqual(JSON.parse(calls[1].options.body), {address});
  assert.match(current.elements['analysis-message'].textContent, /coming in a later stage/);
  assert.equal(current.elements['analysis-submit'].disabled, false);
});
test('report waits with spinner, hides old content and prevents parallel requests', async () => {
  let resolveConfig;
  let calls = 0;
  const current = page(async () => {
    calls += 1;
    return calls === 1 ? new Promise(resolve => { resolveConfig = resolve; }) : ok(data());
  }, '/token/' + address);
  const pending = current.report();
  assert.equal(current.elements['loading-state'].hidden, false);
  assert.equal(current.elements['report-content'].hidden, true);
  assert.equal(current.elements['report-stage'].attributes['aria-busy'], 'true');
  assert.equal(current.elements['refresh-report'].disabled, true);
  await current.context.loadReport();
  assert.equal(calls, 1);
  resolveConfig(config());
  await pending;
  assert.equal(current.elements['loading-state'].hidden, true);
  assert.equal(current.elements['report-content'].hidden, false);
  assert.equal(current.elements['refresh-report'].disabled, false);
  assert.equal(current.elements['report-state-badge'].dataset.state, 'ready');
});
test('direct report visit and page reload use the address in the URL', async () => {
  for (let reload = 0; reload < 2; reload++) {
    const calls = [];
    const current = page(async (url, options) => {
      calls.push({url, options});
      return calls.length === 1 ? config() : ok(data());
    }, '/token/' + address);
    await current.report();
    assert.equal(current.elements['report-address'].textContent, address);
    assert.equal(calls[1].url, 'https://token.example.test/analyses/token');
    assert.equal(calls[1].options.method, 'POST');
    assert.deepEqual(JSON.parse(calls[1].options.body), {address});
    assert.equal(current.metric('price_usd'), '$106.65');
    assert.equal(current.elements['report-token-name'].textContent, 'SOL / Market snapshot');
  }
});
test('no pairs show a distinct empty state with no invented zeros', async () => {
  let calls = 0;
  const market = { status:'no_data', pairs:[], primary_pair_address:null, price_usd:null, liquidity_usd:null, volume_24h_usd:null, price_change_24h_percent:null };
  const current = page(async () => ++calls === 1 ? config() : ok(data(market)), '/token/' + address);
  await current.report();
  assert.equal(current.elements['report-state-badge'].dataset.state, 'no_data');
  assert.equal(current.elements['empty-market'].hidden, false);
  assert.equal(current.elements['report-content'].hidden, false);
  assert.equal(current.elements['partial-market'].hidden, true);
  assert.equal(current.metric('price_usd'), 'No data');
});
test('partial metrics retain real zero and disclose missing metrics', async () => {
  let calls = 0;
  const current = page(async () => ++calls === 1 ? config() : ok(data({price_usd:null})), '/token/' + address);
  await current.report();
  assert.equal(current.elements['partial-market'].hidden, false);
  assert.equal(current.metric('liquidity_usd'), '$0.00');
  assert.equal(current.metric('price_usd'), 'No data');
});
for (const code of ['MARKET_DATA_TIMEOUT','MARKET_DATA_UNAVAILABLE','INVALID_ADDRESS']) {
  test(`provider failure is readable and can be retried: ${code}`, async () => {
    let calls = 0;
    const current = page(async () => {
      calls += 1;
      if (calls % 2 === 1) return config();
      return calls === 2 ? {ok:false,json:async()=>({detail:code})} : ok(data());
    }, '/token/' + address);
    await current.report();
    assert.equal(current.elements['error-state'].hidden, false);
    assert.equal(current.elements['report-content'].hidden, true);
    assert.equal(current.elements['loading-state'].hidden, true);
    assert.equal(current.elements['retry-analysis'].disabled, false);
    assert.ok(!current.elements['error-detail'].textContent.includes(code));
    await current.context.loadReport();
    assert.equal(current.elements['error-state'].hidden, true);
    assert.equal(current.elements['report-state-badge'].dataset.state, 'ready');
  });
}
for (const failure of ['network','json','wrong-address','missing-market']) {
  test(`failed report hides all previous data: ${failure}`, async () => {
    let calls = 0;
    const current = page(async () => {
      if (++calls === 1) return config();
      if (failure === 'network') throw new TypeError('Failed to fetch');
      if (failure === 'json') return {ok:true,json:async()=>{throw new Error('bad json');}};
      return ok(failure === 'wrong-address' ? {...data(),address:'1'.repeat(32)} : {address,subject_type:'token'});
    }, '/token/' + address);
    await current.report();
    assert.equal(current.elements['report-content'].hidden, true);
    assert.equal(current.elements['error-state'].hidden, false);
    assert.equal(current.elements['refresh-report'].disabled, false);
    assert.equal(current.elements['report-stage'].attributes['aria-busy'], 'false');
  });
}
for (const invalid of ['invalid', '%E0%A4', '1'.repeat(64)]) {
  test(`invalid report URL avoids API requests: ${invalid}`, async () => {
    const current = page(undefined, '/token/' + invalid);
    await current.report();
    assert.equal(current.elements['error-state'].hidden, false);
    assert.equal(current.elements['retry-analysis'].disabled, true);
  });
}
test('a browser request timeout restores an actionable error', async () => {
  const current = page(async (_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(Object.assign(new Error('Aborted'), {name:'AbortError'})));
  }), '/token/' + address);
  current.context.setTimeout = callback => { queueMicrotask(callback); return 1; };
  current.context.clearTimeout = () => {};
  await current.report();
  assert.equal(current.elements['error-state'].hidden, false);
  assert.match(current.elements['error-detail'].textContent, /timed out/);
  assert.equal(current.elements['retry-analysis'].disabled, false);
});
test('security report renders normalized flags, parameters and unavailable sources', () => {
  const current = page();
  current.common.updateMarketReport({
    ...data(),
    security_data: {
      overall_status: 'partial',
      risk_summary: { risk_level: 'low', safety_score: 87.5, normalized_score: 12.5, risk_score: 100, is_honeypot: false, rugged: false, total_flags_count: 2, critical_flags_count: 0, warning_flags_count: 0, safe_flags_count: 2, verdict_summary: 'Aggregated from rugcheck, dexscreener.' },
      authorities: { mint_authority_active: false, freeze_authority_active: false, mutable_metadata: false, is_token_2022: false, transfer_fee_pct: 0, is_open_source: true, is_proxy: false },
      holder_distribution: { holder_count: 485210, top_holder_pct: 12.5, top_5_holders_pct: 18.0, top_10_holders_pct: 21.0, creator_balance_pct: 2.5, bundled_supply_pct: 4.2, sniper_holders_count: 3, dev_rug_history_count: 0, top_holders: [{ address, pct: 12.5, ui_amount: 1000, is_insider: false }] },
      liquidity_security: { total_market_liquidity_usd: 30632649.49, lp_locked_pct: 94.5, lp_burned_pct: 91.5, lp_locked_usd: 28000000 },
      market_activity: { fdv_usd: 61200000000, market_cap_usd: 50100000000, buys_24h: 12400, sells_24h: 10000, total_txns_24h: 22400, buy_sell_ratio_24h: 1.24, pair_age_hours: 48, active_boosts: 2, total_supply: 1000000000, token_decimals: 9 },
      verification_and_metadata: { jupiter_verified: true, dextools_score: 92, buy_tax_pct: 0, sell_tax_pct: 0, is_blacklisted: false, is_potentially_scam: false },
      flags: [{ code: 'mint_authority', title: 'Mint authority', severity: 'ok', source: 'rugcheck', description: 'Mint authority is renounced.' }],
      sources: {
        rugcheck: { status: 'ok' },
        dexscreener: { status: 'ok' },
        dextools: { status: 'unavailable', reason: 'rate_limited' },
        gmgn: { status: 'unavailable', reason: 'missing_api_key' },
      },
    },
  }, address);
  assert.equal(current.elements['security-report'].children['[data-security-value="risk_level"]'].textContent, 'LOW');
  assert.equal(current.elements['security-report'].children['[data-security-value="mint_authority_active"]'].textContent, 'Renounced');
  assert.equal(current.elements['security-report'].children['[data-security-value="lp_locked_pct"]'].textContent, '94.5%');
  assert.equal(current.elements['security-report'].children['[data-source-status="rugcheck"]'].textContent, 'OK');
  assert.match(current.elements['security-report'].children['[data-source-status="dextools"]'].textContent, /UNAVAILABLE/);
  assert.match(current.elements['security-report'].children['[data-source-status="gmgn"]'].textContent, /UNAVAILABLE/);
});
