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
let lastSuccessfulReport = null;
let lastSuccessfulAt = null;
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
  const busy = state === 'loading' || state === 'refreshing';
  const keepPreviousReport = Boolean(lastSuccessfulReport) && ['refreshing', 'stale'].includes(state);
  loadingState.hidden = state !== 'loading' || keepPreviousReport;
  errorState.hidden = state !== 'error' || keepPreviousReport;
  reportContent.hidden = keepPreviousReport ? false : !['ready', 'no_data', 'partial'].includes(state);
  document.getElementById('report-stage').setAttribute('aria-busy', String(busy));
  document.getElementById('report-state-badge').dataset.state = state;
  document.getElementById('report-state-label').textContent = { loading: 'CONNECTING', refreshing: 'REFRESHING', ready: 'SNAPSHOT READY', no_data: 'NO PAIRS FOUND', partial: 'PARTIAL REPORT', stale: 'STALE DATA', error: 'UNAVAILABLE' }[state];
  const refreshLabel = document.getElementById('refresh-label');
  if (refreshLabel) refreshLabel.textContent = state === 'refreshing' ? 'Refreshing…' : 'Refresh data';
  document.getElementById('report-status').textContent = text;
  document.getElementById('source-state').textContent = { loading: 'Waiting for DEX Screener', refreshing: 'Refreshing report', ready: 'Snapshot retrieved', no_data: 'Source returned no pairs', partial: 'Market data unavailable', stale: 'Showing previous snapshot', error: 'Could not retrieve data' }[state];
  document.getElementById('source-led').className = state === 'ready' ? 'is-ready' : busy ? 'is-loading' : '';
  refreshButton.disabled = busy || !TokenAI.isSolanaAddress(reportAddress);
  retryButton.disabled = busy || !TokenAI.isSolanaAddress(reportAddress);
}

function reportTimestamp(result) {
  const timestamps = [result?.created_at, result?.market_data?.updated_at, result?.security_data?.updated_at,
    result?.onchain_data?.updated_at, result?.gmgn_activity?.updated_at];
  return timestamps.find(value => typeof value === 'string' && !Number.isNaN(new Date(value).getTime())) || null;
}

function formatReportAge(value) {
  if (!value) return 'time unavailable';
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return 'just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? '' : 's'} ago`;
}

function renderLastUpdated(stale = false) {
  const time = document.getElementById('report-last-updated');
  if (!time) return;
  const age = formatReportAge(lastSuccessfulAt);
  time.textContent = `Last updated ${age}${stale ? ' · Showing previous data' : ''}`;
  time.dataset.state = stale ? 'stale' : 'current';
  if (lastSuccessfulAt) {
    time.setAttribute('datetime', lastSuccessfulAt);
    time.title = TokenAI.formatUpdatedAt(lastSuccessfulAt);
  } else {
    time.removeAttribute('datetime');
    time.removeAttribute('title');
  }
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
  const refreshing = Boolean(lastSuccessfulReport);
  if (!refreshing) window.ReportWorkspace?.render(null, true);
  setReportState(refreshing ? 'refreshing' : 'loading', refreshing ? 'Refreshing the report. Your current data remains visible.' : 'Requesting current market data from DEX Screener.');
  try {
    const base = await TokenAI.apiBase();
    const result = await TokenAI.requestJson(`${base}/analyses/token?allow_partial=true`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ address: reportAddress }),
    }, 90000);
    const market = result?.market_data;
    if (result?.address !== reportAddress || result?.subject_type !== 'token' || !market || !['ok', 'no_data', 'unavailable'].includes(market.status) || !Array.isArray(market.pairs)) {
      throw new Error('The source returned an incomplete report. Please try again.');
    }
    lastSuccessfulReport = result;
    lastSuccessfulAt = reportTimestamp(result);
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
    renderLastUpdated();
    const secStateEl = document.getElementById('security-source-state');
    const secLedEl = document.getElementById('security-source-led');
    const secStatus = result?.security_data?.overall_status;
    if (secStateEl) secStateEl.textContent = secStatus === 'ok' ? 'All security sources ready' : secStatus === 'partial' ? 'Partial security telemetry' : 'Unavailable / limited sources';
    if (secLedEl) secLedEl.className = ['ok', 'partial'].includes(secStatus) ? 'is-ready' : '';
  } catch (error) {
    if (lastSuccessfulReport) {
      const age = formatReportAge(lastSuccessfulAt);
      setReportState('stale', `Refresh failed. Showing the previous report, last updated ${age}.`);
      renderLastUpdated(true);
    } else {
      window.ReportWorkspace?.render(null);
      document.getElementById('error-title').textContent = "We couldn't load this report.";
      document.getElementById('error-detail').textContent = error.message || 'The analysis service is unavailable. Please try again.';
      setReportState('error', 'Your address is preserved. Retry when the source is available.');
    }
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
