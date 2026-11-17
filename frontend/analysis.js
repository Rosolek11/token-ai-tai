const form = document.getElementById('analysis-form');
const addressInput = document.getElementById('address');
const submitButton = document.getElementById('analysis-submit');
const message = document.getElementById('analysis-message');
const base58Pattern = /^[1-9A-HJ-NP-Za-km-z]{32,64}$/;

function showMessage(text, state) {
  message.textContent = text;
  message.dataset.state = state;
}

function formatUsd(value) {
  if (value === null || value === undefined || value === '') return 'No data';
  const amount = Number(value);
  if (!Number.isFinite(amount)) return 'No data';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: amount < 1 ? 8 : 2,
  }).format(amount);
}

function formatPercent(value) {
  if (value === null || value === undefined || value === '') return 'No data';
  const amount = Number(value);
  if (!Number.isFinite(amount)) return 'No data';
  return `${new Intl.NumberFormat('en-US', { signDisplay: 'always', maximumFractionDigits: 2 }).format(amount)}%`;
}

function formatUpdatedAt(value) {
  if (!value) return 'No data';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'No data';
  return new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

function formatCount(value) {
  if (value === null || value === undefined || value === '') return 'No data';
  const count = Number(value);
  if (!Number.isInteger(count) || count < 0) return 'No data';
  return new Intl.NumberFormat('en-US').format(count);
}

function getSourceUrl(marketData, address) {
  const fallbackUrl = `https://dexscreener.com/solana/${encodeURIComponent(address)}`;
  if (typeof marketData.source_url !== 'string') return fallbackUrl;
  try {
    const parsedUrl = new URL(marketData.source_url);
    return parsedUrl.protocol === 'https:' ? parsedUrl.href : fallbackUrl;
  } catch {
    return fallbackUrl;
  }
}

function updateActivityReport(marketData, address) {
  const activityReport = document.getElementById('activity-report');
  const activityTable = activityReport.querySelector('[data-activity-table]');
  const emptyMessage = activityReport.querySelector('[data-activity-empty]');
  const windows = ['m5', 'h1', 'h6', 'h24'];
  let hasActivityData = false;

  windows.forEach((windowName) => {
    const row = activityReport.querySelector(`[data-activity-window="${windowName}"]`);
    const transactions = marketData.txns?.[windowName] || {};
    const volume = marketData.volume?.[windowName];
    const buys = Number.isInteger(Number(transactions.buys)) && transactions.buys !== null && transactions.buys !== ''
      ? Number(transactions.buys)
      : null;
    const sells = Number.isInteger(Number(transactions.sells)) && transactions.sells !== null && transactions.sells !== ''
      ? Number(transactions.sells)
      : null;
    const volumeValue = volume === null || volume === undefined || volume === '' || !Number.isFinite(Number(volume))
      ? null
      : Number(volume);
    const hasWindowData = buys !== null || sells !== null || volumeValue !== null;

    row.hidden = !hasWindowData;
    if (!hasWindowData) return;

    hasActivityData = true;
    row.querySelector('[data-activity-value="buys"]').textContent = formatCount(buys);
    row.querySelector('[data-activity-value="sells"]').textContent = formatCount(sells);
    row.querySelector('[data-activity-value="volume"]').textContent = formatUsd(volumeValue);
  });

  activityTable.hidden = !hasActivityData;
  emptyMessage.hidden = hasActivityData;
  const activitySource = activityReport.querySelector('[data-activity-source]');
  const sourceUrl = getSourceUrl(marketData, address);
  activitySource.href = sourceUrl;
  activitySource.textContent = sourceUrl.includes('dexscreener.com') ? 'Open DEX Screener source ↗' : 'Open data source ↗';
}

function updateMarketReport(result, address, subjectType) {
  const report = document.getElementById('market-report');
  if (subjectType !== 'token') {
    report.hidden = true;
    return;
  }

  const marketData = result.market_data || {};
  report.querySelector('[data-market-value="price_usd"]').textContent = formatUsd(marketData.price_usd);
  report.querySelector('[data-market-value="liquidity_usd"]').textContent = formatUsd(marketData.liquidity_usd);
  report.querySelector('[data-market-value="volume_24h_usd"]').textContent = formatUsd(marketData.volume_24h_usd);
  report.querySelector('[data-market-value="price_change_24h_percent"]').textContent = formatPercent(marketData.price_change_24h_percent);
  report.querySelector('[data-market-value="updated_at"]').textContent = formatUpdatedAt(marketData.updated_at);

  const sourceLink = report.querySelector('[data-market-source]');
  const sourceUrl = getSourceUrl(marketData, address);
  sourceLink.href = sourceUrl;
  sourceLink.textContent = sourceUrl.includes('dexscreener.com') ? 'Open DEX Screener source ↗' : 'Open data source ↗';
  updateActivityReport(marketData, address);
  report.hidden = false;
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (submitButton.disabled) return;

  const address = addressInput.value.trim();
  if (!address) {
    addressInput.setAttribute('aria-invalid', 'true');
    showMessage('Enter a Solana address to continue.', 'error');
    addressInput.focus();
    return;
  }
  if (!base58Pattern.test(address)) {
    addressInput.setAttribute('aria-invalid', 'true');
    showMessage('Address must be 32–64 characters in Solana Base58 format.', 'error');
    addressInput.focus();
    return;
  }

  addressInput.removeAttribute('aria-invalid');
  submitButton.disabled = true;
  submitButton.querySelector('span').textContent = 'Analyzing…';
  showMessage('Submitting address…', 'pending');

  try {
    const configResponse = await fetch('/api/client-config', { cache: 'no-store' });
    if (!configResponse.ok) throw new Error('Analysis service is unavailable. Try again later.');
    const config = await configResponse.json();
    const base = (config.apiBaseUrl || window.location.origin).replace(/\/$/, '');
    const subjectType = form.elements['subject-type'].value;
    const response = await fetch(`${base}/analyses/${subjectType}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ address }),
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(typeof result.detail === 'string' ? result.detail : 'Could not analyze this address. Check the format and try again.');
    }
    updateMarketReport(result, address, subjectType);
    showMessage(`Analysis request accepted for ${result.subject_type}: ${result.address}.`, 'success');
  } catch (error) {
    showMessage(error.message || 'No response from the analysis service. Try again later.', 'error');
  } finally {
    submitButton.disabled = false;
    submitButton.querySelector('span').textContent = 'Analyze address';
  }
});

addressInput.addEventListener('input', () => {
  addressInput.removeAttribute('aria-invalid');
  if (message.dataset.state === 'error') showMessage('', '');
});
