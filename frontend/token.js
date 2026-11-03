const loadingState = document.getElementById('loading-state');
const errorState = document.getElementById('error-state');
const reportContent = document.getElementById('report-content');
const refreshButton = document.getElementById('refresh-report');
const retryButton = document.getElementById('retry-analysis');
const copyButton = document.getElementById('copy-address');
let reportAddress = '';
let inFlight = false;
try { reportAddress = decodeURIComponent(window.location.pathname.split('/')[2] || ''); }
catch { /* Invalid URL encoding is handled as an invalid address. */ }
document.getElementById('report-address').textContent = reportAddress || 'Invalid address';

function setReportState(state, text) {
  loadingState.hidden = state !== 'loading';
  errorState.hidden = state !== 'error';
  reportContent.hidden = !['ready', 'no_data'].includes(state);
  document.getElementById('report-stage').setAttribute('aria-busy', String(state === 'loading'));
  document.getElementById('report-state-badge').dataset.state = state;
  document.getElementById('report-state-label').textContent = { loading: 'CONNECTING', ready: 'SNAPSHOT READY', no_data: 'NO PAIRS FOUND', error: 'UNAVAILABLE' }[state];
  document.getElementById('report-status').textContent = text;
  document.getElementById('source-state').textContent = { loading: 'Waiting for DEX Screener', ready: 'Snapshot retrieved', no_data: 'Source returned no pairs', error: 'Could not retrieve data' }[state];
  document.getElementById('source-led').className = state === 'ready' ? 'is-ready' : state === 'loading' ? 'is-loading' : '';
  refreshButton.disabled = state === 'loading' || !TokenAI.isSolanaAddress(reportAddress);
  retryButton.disabled = state === 'loading' || !TokenAI.isSolanaAddress(reportAddress);
}

async function loadReport() {
  if (inFlight) return;
  if (!TokenAI.isSolanaAddress(reportAddress)) {
    document.getElementById('error-title').textContent = 'This address is not valid.';
    document.getElementById('error-detail').textContent = 'Use a Solana Base58 address with 32–44 characters that decode to 32 bytes.';
    copyButton.disabled = true;
    setReportState('error', 'Check the address in this page’s URL or start a new analysis.');
    return;
  }
  inFlight = true;
  setReportState('loading', 'Requesting current market data from DEX Screener.');
  try {
    const base = await TokenAI.apiBase();
    const result = await TokenAI.requestJson(`${base}/analyses/token`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ address: reportAddress }),
    });
    const market = result?.market_data;
    if (result?.address !== reportAddress || result?.subject_type !== 'token' || !market || !['ok', 'no_data'].includes(market.status) || !Array.isArray(market.pairs)) {
      throw new Error('The source returned an incomplete report. Please try again.');
    }
    TokenAI.updateMarketReport(result, reportAddress);
    const empty = market.status === 'no_data' || market.pairs.length === 0;
    document.getElementById('empty-market').hidden = !empty;
    document.getElementById('partial-market').hidden = empty || ['price_usd', 'liquidity_usd', 'volume_24h_usd', 'price_change_24h_percent'].every(key => TokenAI.parseMarketNumber(market[key]) !== null);
    const primary = market.pairs.find(pair => pair.pair_address === market.primary_pair_address);
    const token = primary?.base_token;
    document.getElementById('report-token-name').textContent = token?.symbol ? `${token.symbol} / Market snapshot` : 'Token market data';
    document.getElementById('pair-summary').textContent = empty ? 'No market pair is available for this address.' : primary ? `${market.pairs.length} pair${market.pairs.length === 1 ? '' : 's'} found · selected ${primary.dex_id || 'DEX'} pair by highest known liquidity.` : 'No base-token pair available. Source pairs are quote-token pairs, so summary metrics are unavailable.';
    setReportState(empty ? 'no_data' : 'ready', empty ? 'The source returned no trading pairs for this address.' : 'Market snapshot ready. All metrics refer to the selected trading pair.');
    const secStateEl = document.getElementById('security-source-state');
    const secLedEl = document.getElementById('security-source-led');
    const secStatus = result?.security_data?.overall_status;
    if (secStateEl) secStateEl.textContent = secStatus === 'ok' ? 'All security sources ready' : secStatus === 'partial' ? 'Partial security telemetry' : 'Unavailable / limited sources';
    if (secLedEl) secLedEl.className = ['ok', 'partial'].includes(secStatus) ? 'is-ready' : '';
  } catch (error) {
    document.getElementById('error-title').textContent = "We couldn't load this report.";
    document.getElementById('error-detail').textContent = error.message || 'The analysis service is unavailable. Please try again.';
    setReportState('error', 'Your address is preserved. Retry when the source is available.');
  } finally { inFlight = false; }
}

refreshButton.addEventListener('click', loadReport);
retryButton.addEventListener('click', loadReport);
copyButton.addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(reportAddress);
    document.getElementById('copy-feedback').textContent = 'Token address copied.';
    copyButton.textContent = 'Copied';
  } catch {
    document.getElementById('copy-feedback').textContent = 'Copy is unavailable. Select the address to copy it manually.';
    document.getElementById('report-address').focus();
  }
});
var reportRequest = loadReport();
