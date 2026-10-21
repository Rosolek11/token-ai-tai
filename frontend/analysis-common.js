/* Shared browser-side contract for the address form and token report. */
window.TokenAI = (() => {
  const alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
  const messages = {
    INVALID_ADDRESS: 'Enter a valid Solana address: 32–44 Base58 characters that decode to 32 bytes.',
    MARKET_DATA_TIMEOUT: 'The market data source took too long to respond. Please try again.',
    MARKET_DATA_UNAVAILABLE: 'The market data source is temporarily unavailable. Please try again.',
  };
  function isSolanaAddress(address) {
    if (typeof address !== 'string' || !/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(address)) return false;
    let value = 0n;
    for (const character of address) value = value * 58n + BigInt(alphabet.indexOf(character));
    let bytes = 0;
    while (value > 0n) { bytes += 1; value >>= 8n; }
    return address.match(/^1*/)[0].length + bytes === 32;
  }
  async function requestJson(url, options = {}) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(url, { ...options, signal: controller.signal, cache: 'no-store' });
      let result;
      try { result = await response.json(); }
      catch { throw new Error('The service returned an unreadable response. Please try again.'); }
      if (!response.ok) throw new Error(messages[result?.detail] || 'The analysis service could not complete this request. Please try again.');
      return result;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('The request timed out. Check your connection and try again.');
      if (error instanceof TypeError) throw new Error('Cannot reach the analysis service. Check your connection and try again.');
      throw error;
    } finally { window.clearTimeout(timeout); }
  }
  async function apiBase() {
    const config = await requestJson('/api/client-config');
    if (!config || typeof config.apiBaseUrl !== 'string') throw new Error('The analysis service configuration is unavailable.');
    return (config.apiBaseUrl || window.location.origin).replace(/\/$/, '');
  }
  function parseMarketNumber(value) {
    if (typeof value !== 'number' && typeof value !== 'string') return null;
    if (typeof value === 'string' && value.trim() === '') return null;
    const amount = Number(value);
    return Number.isFinite(amount) ? amount : null;
  }
  function formatUsd(value) {
    const amount = parseMarketNumber(value);
    if (amount === null) return 'No data';
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: amount < 1 ? 8 : 2 }).format(amount);
  }
  function formatPercent(value) {
    const amount = parseMarketNumber(value);
    if (amount === null) return 'No data';
    return `${new Intl.NumberFormat('en-US', { signDisplay: 'always', maximumFractionDigits: 2 }).format(amount)}%`;
  }
  function formatUpdatedAt(value) {
    if (!value) return 'No data';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'No data';
    return new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
  }
  function updateMarketReport(result, address) {
    const report = document.getElementById('market-report');
    const marketData = result.market_data || {};
    for (const metric of ['price_usd', 'liquidity_usd', 'volume_24h_usd']) {
      report.querySelector(`[data-market-value="${metric}"]`).textContent = formatUsd(marketData[metric]);
    }
    const change = report.querySelector('[data-market-value="price_change_24h_percent"]');
    change.textContent = formatPercent(marketData.price_change_24h_percent);
    const amount = parseMarketNumber(marketData.price_change_24h_percent);
    change.dataset.direction = amount === null || amount === 0 ? 'neutral' : amount > 0 ? 'up' : 'down';
    const time = report.querySelector('[data-market-value="updated_at"]');
    time.textContent = formatUpdatedAt(marketData.updated_at);
    if (marketData.updated_at && !Number.isNaN(new Date(marketData.updated_at).getTime())) time.setAttribute('datetime', marketData.updated_at);
    else time.removeAttribute('datetime');
    const sourceLink = report.querySelector('[data-market-source]');
    let sourceUrl = `https://dexscreener.com/solana/${encodeURIComponent(address)}`;
    if (typeof marketData.source_url === 'string') {
      try { const parsed = new URL(marketData.source_url); if (parsed.protocol === 'https:') sourceUrl = parsed.href; }
      catch { /* Keep the source fallback for an invalid provider URL. */ }
    }
    sourceLink.href = sourceUrl;
    sourceLink.textContent = 'Verify on DEX Screener ↗';
  }
  return { isSolanaAddress, requestJson, apiBase, parseMarketNumber, formatUsd, formatPercent, formatUpdatedAt, updateMarketReport };
})();
