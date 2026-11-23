const loadingState = document.getElementById('loading-state');
const errorState = document.getElementById('error-state');
const reportContent = document.getElementById('report-content');
const refreshButton = document.getElementById('refresh-report');
const retryButton = document.getElementById('retry-analysis');
const copyButton = document.getElementById('copy-address');
const marketUnavailable = document.getElementById('market-unavailable');
let reportAddress = '';
let inFlight = false;
let aiRequestId = 0;
function requestAnalysis(base, result, timeout = 120000) {
  return TokenAI.requestJson(base + analysisPath(), {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(result.id ? {report_id:result.id} : {}),
  }, timeout);
}

function analysisPath() {
  return `/api/tokens/${encodeURIComponent(reportAddress)}/ai-analysis`;
}

async function setUpCopilot(result, requestId) {
  const workspace = window.ReportWorkspace;
  let account;
  try { account = await TokenAI.requestJson('/api/auth/github/session'); }
  catch { account = { statusUnavailable: true }; }
  if (requestId !== aiRequestId) return;
  const loginHref = `/api/auth/github/login?address=${encodeURIComponent(reportAddress)}`;
  const callbackStatus = new URLSearchParams(window.location.search).get('github');
  const callbackFailed = ['login_failed', 'setup_failed'].includes(callbackStatus);
  if (callbackFailed) window.history.replaceState(null, '', `${window.location.pathname}${window.location.hash}`);
  let running = false;
  let ran = false;

  function showAccount(busy = false) {
    workspace?.renderCopilotAccount(account, {loginHref, run, logout, busy});
  }
  async function run() {
    if (running || requestId !== aiRequestId) return;
    running = true;
    ran = true;
    showAccount(true);
    workspace?.renderAI(result, {message:'Copilot is analysing the report. This may take a few minutes.'}, true);
    try {
      const output = await requestAnalysis('', result, 200000);
      if (requestId === aiRequestId) workspace?.renderAI(result, output);
    } catch (error) {
      if (requestId === aiRequestId) workspace?.renderAI(result, {message: error.message});
    } finally {
      running = false;
      if (requestId === aiRequestId) showAccount();
    }
  }
  async function logout() {
    showAccount(true);
    try {
      const response = await fetch('/api/auth/github/logout', {method:'POST', cache:'no-store'});
      if (!response.ok) throw new Error();
      if (requestId !== aiRequestId) return;
      account = {...account, login:null};
      showAccount();
      workspace?.renderAI(result, {status:'copilot_idle'});
    } catch {
      if (requestId !== aiRequestId) return;
      showAccount();
      workspace?.renderAI(result, {message:'Could not sign out of GitHub. Try again.'});
    }
  }
  showAccount();
  workspace?.renderAI(result, {status:'copilot_idle', reason: callbackFailed ? `github_${callbackStatus}` : null});
  if (account.login && !callbackFailed) {
    try {
      const saved = await TokenAI.requestJson(analysisPath());
      if (!ran && account.login && requestId === aiRequestId && saved.status === 'completed') {
        workspace?.renderAI(result, saved);
      }
    } catch { /* A failed history lookup does not prevent a new analysis. */ }
  }
}
try { reportAddress = decodeURIComponent(window.location.pathname.split('/')[2] || ''); }
catch { /* Invalid URL encoding is handled as an invalid address. */ }
document.getElementById('report-address').textContent = reportAddress || 'Invalid address';

function setReportState(state, text) {
  loadingState.hidden = state !== 'loading';
  errorState.hidden = state !== 'error';
  reportContent.hidden = !['ready', 'no_data', 'partial'].includes(state);
  document.getElementById('report-stage').setAttribute('aria-busy', String(state === 'loading'));
  document.getElementById('report-state-badge').dataset.state = state;
  document.getElementById('report-state-label').textContent = { loading: 'CONNECTING', ready: 'SNAPSHOT READY', no_data: 'NO PAIRS FOUND', partial: 'PARTIAL REPORT', error: 'UNAVAILABLE' }[state];
  document.getElementById('report-status').textContent = text;
  document.getElementById('source-state').textContent = { loading: 'Waiting for DEX Screener', ready: 'Snapshot retrieved', no_data: 'Source returned no pairs', partial: 'Market data unavailable', error: 'Could not retrieve data' }[state];
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
  const currentAiRequest = ++aiRequestId;
  window.ReportWorkspace?.render(null, true);
  setReportState('loading', 'Requesting current market data from DEX Screener.');
  try {
    const base = await TokenAI.apiBase();
    const result = await TokenAI.requestJson(`${base}/analyses/token?allow_partial=true`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ address: reportAddress }),
    }, 90000);
    const market = result?.market_data;
    if (result?.address !== reportAddress || result?.subject_type !== 'token' || !market || !['ok', 'no_data', 'unavailable'].includes(market.status) || !Array.isArray(market.pairs)) {
      throw new Error('The source returned an incomplete report. Please try again.');
    }
    TokenAI.updateMarketReport(result, reportAddress);
    window.ReportWorkspace?.render(result);
    if (result.copilot_enabled) {
      window.ReportWorkspace?.renderAI(result, {status:'copilot_idle'});
      void setUpCopilot(result, currentAiRequest);
    } else {
      window.ReportWorkspace?.renderAI(result, null, true);
      requestAnalysis(base, result).then(aiResult => { if (currentAiRequest === aiRequestId) window.ReportWorkspace?.renderAI(result, aiResult); })
        .catch(() => { if (currentAiRequest === aiRequestId) window.ReportWorkspace?.renderAI(result, {status:'unavailable'}); });
    }
    const unavailable = market.status === 'unavailable';
    const empty = !unavailable && (market.status === 'no_data' || market.pairs.length === 0);
    marketUnavailable.hidden = !unavailable;
    document.getElementById('empty-market').hidden = !empty;
    document.getElementById('partial-market').hidden = unavailable || empty || ['price_usd', 'liquidity_usd', 'volume_24h_usd', 'price_change_24h_percent'].every(key => TokenAI.parseMarketNumber(market[key]) !== null);
    const primary = market.pairs.find(pair => pair.pair_address === market.primary_pair_address);
    const token = primary?.base_token;
    document.getElementById('report-token-name').textContent = token?.symbol ? `${token.symbol} / Market snapshot` : 'Token market data';
    const marketGap = market.reason === 'timeout' ? 'The market data source took too long to respond. Please try again.' : 'The market data source is temporarily unavailable. Please try again.';
    document.getElementById('pair-summary').textContent = unavailable ? marketGap : empty ? 'No market pair is available for this address.' : primary ? `${market.pairs.length} pair${market.pairs.length === 1 ? '' : 's'} found · selected ${primary.dex_id || 'DEX'} pair by highest known liquidity.` : 'No base-token pair available. Source pairs are quote-token pairs, so summary metrics are unavailable.';
    if (unavailable) setReportState('partial', 'Market data is unavailable. You can still inspect the other report sections.');
    else if (empty) setReportState('no_data', 'The source returned no trading pairs for this address.');
    else setReportState('ready', 'Report ready. Coverage varies by section.');
    const secStateEl = document.getElementById('security-source-state');
    const secLedEl = document.getElementById('security-source-led');
    const secStatus = result?.security_data?.overall_status;
    if (secStateEl) secStateEl.textContent = secStatus === 'ok' ? 'All security sources ready' : secStatus === 'partial' ? 'Partial security telemetry' : 'Unavailable / limited sources';
    if (secLedEl) secLedEl.className = ['ok', 'partial'].includes(secStatus) ? 'is-ready' : '';
  } catch (error) {
    window.ReportWorkspace?.render(null);
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
