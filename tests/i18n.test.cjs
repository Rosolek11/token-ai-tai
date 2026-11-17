const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {translate, dictionary} = require('../frontend/i18n.js');

test('PL translates all static UI text, EN preserves source', () => {
  for (const [english, polish] of Object.entries(dictionary)) {
    assert.equal(translate(english, 'pl'), polish, english);
    assert.equal(translate(english, 'en'), english);
  }
});

test('dynamic reports retain values and source identifiers', () => {
  assert.equal(translate('3 pairs found · selected raydium pair by highest known liquidity.'), 'Znalezione pary: 3 · wybrano parę raydium o największej znanej płynności.');
  assert.equal(translate('12 observations · 7 provider flags · 2 data gaps'), 'Obserwacje: 12 · flagi dostawców: 7 · braki danych: 2');
  assert.equal(translate('DEXSCREENER · Data unavailable'), 'DEXSCREENER · Dane niedostępne');
  assert.equal(translate('Mint authority · Disabled'), 'Uprawnienie do emisji · Wyłączone');
  assert.equal(translate('01 / Dev holdings'), '01 / Zasoby dewelopera');
  assert.equal(translate('No data / No data'), 'Brak danych / Brak danych');
  assert.equal(translate('GMGN / NOT CONFIGURED · Sniper count: No data'), 'GMGN / BRAK KONFIGURACJI · Liczba sniperów: Brak danych');
  assert.equal(translate('SOL'), 'SOL');
  assert.equal(translate('So11111111111111111111111111111111111111112'), 'So11111111111111111111111111111111111111112');
});

test('translation never interprets provider HTML', () => {
  const payload = '<img src=x onerror=alert(1)>';
  assert.equal(translate(payload), payload);
  assert.equal(translate('  Start an analysis  '), '  Rozpocznij analizę  ');
});

test('every page loads dictionaries and controller before its view scripts', () => {
  for (const file of ['index.html', 'analysis.html', 'token.html']) {
    const html = fs.readFileSync('frontend/'+file, 'utf8');
    assert(html.indexOf('/assets/translations.js') < html.indexOf('/assets/i18n.js'));
    assert(html.includes('class="site-header"'));
  }
});
