const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const address = 'So11111111111111111111111111111111111111112';
const source = fs.readFileSync(path.join(__dirname, '../frontend/analysis.js'), 'utf8');

function element() {
  return {
    hidden: true,
    disabled: false,
    textContent: '',
    dataset: {},
    listeners: {},
    attributes: {},
    children: {},
    addEventListener(event, handler) { this.listeners[event] = handler; },
    setAttribute(name, value) { this.attributes[name] = value; },
    removeAttribute(name) { delete this.attributes[name]; },
    focus() {},
    querySelector(selector) { return this.children[selector]; },
  };
}

function page(fetchHandler = async () => { throw new Error('Unexpected request'); }) {
  const elements = Object.fromEntries([
    'analysis-form', 'address', 'analysis-submit', 'analysis-message', 'market-report',
  ].map(name => [name, element()]));
  elements.address.value = address;
  elements['analysis-form'].elements = { 'subject-type': { value: 'token' } };
  elements['analysis-submit'].children.span = element();
  const metrics = ['price_usd', 'liquidity_usd', 'volume_24h_usd', 'price_change_24h_percent', 'updated_at'];
  for (const metric of metrics) {
    elements['market-report'].children[`[data-market-value="${metric}"]`] = element();
  }
  elements['market-report'].children['[data-market-source]'] = element();
  const context = {
    document: { getElementById: name => elements[name] },
    window: { location: { origin: 'https://token.example.test' } },
    URL, Intl, Date, fetch: fetchHandler,
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  return {
    elements,
    context,
    report: elements['market-report'],
    submit: () => elements['analysis-form'].listeners.submit({ preventDefault() {} }),
    metric: name => elements['market-report'].children[`[data-market-value="${name}"]`].textContent,
  };
}

for (const value of [undefined, null, '', ' ', '\t\n', false, true, [], {}, 'NaN', 'Infinity', 'invalid']) {
  test(`missing or invalid metric stays unavailable: ${JSON.stringify(value)}`, () => {
    const current = page();
    assert.equal(current.context.formatUsd(value), 'Brak danych');
    assert.equal(current.context.formatPercent(value), 'Brak danych');
  });
}

test('zero, tiny prices and negative changes are displayed', () => {
  const current = page();
  assert.equal(current.context.formatUsd(0), '$0.00');
  assert.equal(current.context.formatUsd('0.00000001'), '$0.00000001');
  assert.equal(current.context.formatPercent(0), '+0%');
  assert.equal(current.context.formatPercent(-2.22), '-2.22%');
});

test('report displays metrics, timestamp and exact source from API', () => {
  const current = page();
  current.context.updateMarketReport({ market_data: {
    price_usd: 106.65, liquidity_usd: 0, volume_24h_usd: null,
    price_change_24h_percent: -2.22, updated_at: '2026-10-21T07:57:07Z',
    source_url: 'https://api.dexscreener.com/token-pairs/v1/solana/' + address,
  } }, address, 'token');
  assert.equal(current.report.hidden, false);
  assert.equal(current.metric('price_usd'), '$106.65');
  assert.equal(current.metric('liquidity_usd'), '$0.00');
  assert.equal(current.metric('volume_24h_usd'), 'Brak danych');
  assert.equal(current.metric('price_change_24h_percent'), '-2.22%');
  assert.notEqual(current.metric('updated_at'), 'Brak danych');
  assert.equal(current.report.children['[data-market-source]'].href,
    'https://api.dexscreener.com/token-pairs/v1/solana/' + address);
});

test('empty response clears every previously displayed metric', () => {
  const current = page();
  current.context.updateMarketReport({ market_data: { price_usd: 106.65 } }, address, 'token');
  current.context.updateMarketReport({ market_data: { status: 'no_data', pairs: [] } }, address, 'token');
  for (const metric of ['price_usd', 'liquidity_usd', 'volume_24h_usd', 'price_change_24h_percent', 'updated_at']) {
    assert.equal(current.metric(metric), 'Brak danych');
  }
});

for (const sourceUrl of ['javascript:alert(1)', 'http://example.test', 'malformed']) {
  test(`unsafe or malformed source falls back to DexScreener: ${sourceUrl}`, () => {
    const current = page();
    current.context.updateMarketReport({ market_data: { source_url: sourceUrl } }, address, 'token');
    assert.equal(current.report.children['[data-market-source]'].href,
      'https://dexscreener.com/solana/' + address);
  });
}

test('wallet result hides token metrics', () => {
  const current = page();
  current.report.hidden = false;
  current.context.updateMarketReport({}, address, 'wallet');
  assert.equal(current.report.hidden, true);
});

for (const status of [502, 504]) {
  test(`failed analysis hides the previous token report (${status})`, async () => {
    let calls = 0;
    const current = page(async () => {
      calls += 1;
      if (calls === 1) return { ok: true, json: async () => ({ apiBaseUrl: '' }) };
      return { ok: false, json: async () => ({ detail: status === 504 ? 'MARKET_DATA_TIMEOUT' : 'MARKET_DATA_UNAVAILABLE' }) };
    });
    current.context.updateMarketReport({ market_data: { price_usd: 100 } }, address, 'token');
    await current.submit();
    assert.equal(current.report.hidden, true);
    assert.equal(current.elements['analysis-message'].dataset.state, 'error');
    assert.equal(current.elements['analysis-submit'].disabled, false);
    assert.equal(current.elements['analysis-submit'].children.span.textContent, 'Analyze address');
  });
}

test('pending analysis hides old results and blocks duplicate submissions', async () => {
  let finishConfig;
  let calls = 0;
  const current = page(() => {
    calls += 1;
    return new Promise(resolve => { finishConfig = resolve; });
  });
  current.report.hidden = false;
  const pending = current.submit();
  const hiddenWhilePending = current.report.hidden;
  const disabledWhilePending = current.elements['analysis-submit'].disabled;
  await current.submit();
  finishConfig({ ok: false });
  await pending;
  assert.equal(hiddenWhilePending, true);
  assert.equal(disabledWhilePending, true);
  assert.equal(calls, 1);
  assert.equal(current.elements['analysis-submit'].disabled, false);
});

test('successful submission sends the token address and renders response', async () => {
  const calls = [];
  const current = page(async (url, options) => {
    calls.push({ url, options });
    if (calls.length === 1) {
      return { ok: true, json: async () => ({ apiBaseUrl: 'https://api.example.test/' }) };
    }
    return { ok: true, json: async () => ({
      subject_type: 'token', address, market_data: { price_usd: 106.65 },
    }) };
  });
  await current.submit();
  assert.equal(calls.length, 2);
  assert.equal(calls[1].url, 'https://api.example.test/analyses/token');
  assert.equal(calls[1].options.method, 'POST');
  assert.deepEqual(JSON.parse(calls[1].options.body), { address });
  assert.equal(current.metric('price_usd'), '$106.65');
  assert.equal(current.report.hidden, false);
  assert.equal(current.elements['analysis-message'].dataset.state, 'success');
  assert.equal(current.elements['analysis-submit'].disabled, false);
});

for (const failure of ['config-network', 'config-json', 'analysis-network', 'analysis-json']) {
  test(`request failure clears old report and restores submit button: ${failure}`, async () => {
    let calls = 0;
    const current = page(async () => {
      calls += 1;
      if (calls === 1) {
        if (failure === 'config-network') throw new Error('Network failure');
        if (failure === 'config-json') return { ok: true, json: async () => { throw new Error('Invalid JSON'); } };
        return { ok: true, json: async () => ({ apiBaseUrl: '' }) };
      }
      if (failure === 'analysis-network') throw new Error('Network failure');
      return { ok: true, json: async () => { throw new Error('Invalid JSON'); } };
    });
    current.report.hidden = false;
    await current.submit();
    assert.equal(current.report.hidden, true);
    assert.equal(current.elements['analysis-message'].dataset.state, 'error');
    assert.equal(current.elements['analysis-submit'].disabled, false);
  });
}

for (const invalidAddress of ['', 'invalid']) {
  test(`invalid input makes no HTTP call and hides old report: ${JSON.stringify(invalidAddress)}`, async () => {
    let calls = 0;
    const current = page(async () => { calls += 1; });
    current.elements.address.value = invalidAddress;
    current.report.hidden = false;
    await current.submit();
    assert.equal(current.report.hidden, true);
    assert.equal(calls, 0);
    assert.equal(current.elements['analysis-message'].dataset.state, 'error');
    assert.equal(current.elements.address.attributes['aria-invalid'], 'true');
    assert.equal(current.elements['analysis-submit'].disabled, false);
  });
}
