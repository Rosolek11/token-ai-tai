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

function parseSourceUrl(value) {
  if (typeof value !== 'string') return null;
  try {
    const parsedUrl = new URL(value);
    return parsedUrl.protocol === 'https:' ? parsedUrl.href : null;
  } catch {
    return null;
  }
}

function getSourceUrl(marketData, address) {
  return parseSourceUrl(marketData.source_url)
    || `https://dexscreener.com/solana/${encodeURIComponent(address)}`;
}

function getMetricProvenance(marketData, metricKey, address) {
  const provenance = marketData.provenance?.[metricKey] || {};
  const reportedUrl = parseSourceUrl(provenance.source_url || marketData.source_url);
  const sourceAvailable = provenance.available === false
    ? false
    : provenance.available === true || Boolean(reportedUrl);
  return {
    sourceUrl: reportedUrl || `https://dexscreener.com/solana/${encodeURIComponent(address)}`,
    sourceAvailable,
    sourceName: provenance.source_name || marketData.source_name || 'data source',
    fetchedAt: provenance.fetched_at || provenance.updated_at || marketData.updated_at,
  };
}

function updateMetricAttribution(container, marketData, metricKey, address) {
  const provenance = getMetricProvenance(marketData, metricKey, address);
  const sourceLink = container.querySelector(`[data-source-for="${metricKey}"]`);
  const fetchedAt = container.querySelector(`[data-updated-for="${metricKey}"]`);
  if (sourceLink) {
    sourceLink.href = provenance.sourceUrl;
    sourceLink.dataset.available = String(provenance.sourceAvailable);
    sourceLink.textContent = provenance.sourceAvailable
      ? `Open ${provenance.sourceName} ↗`
      : 'Source unavailable · Open DEX Screener ↗';
  }
  if (fetchedAt) fetchedAt.textContent = `Fetched: ${formatUpdatedAt(provenance.fetchedAt)}`;
}

function updateDataSources(marketData, address, hasMetricData) {
  const sourcesSection = document.getElementById('data-sources');
  const sourceList = sourcesSection.querySelector('[data-source-list]');
  const reportedSources = Array.isArray(marketData.sources) ? marketData.sources : [];
  const metricKeys = [
    'price_usd', 'liquidity_usd', 'volume_24h_usd', 'price_change_24h_percent',
    ...['m5', 'h1', 'h6', 'h24'].flatMap((windowName) => [
      `txns.${windowName}.buys`, `txns.${windowName}.sells`, `volume.${windowName}`,
    ]),
  ];
  const metricSources = metricKeys
    .map((metricKey) => marketData.provenance?.[metricKey])
    .filter((source) => source?.source_url)
    .map((source) => ({
      name: source.source_name || 'Data source',
      url: source.source_url,
      available: source.available,
      status: source.status,
    }));
  const sources = reportedSources.length > 0
    ? reportedSources
    : metricSources.length > 0
      ? metricSources
      : [{
        name: marketData.source_name || 'DEX Screener',
        url: marketData.source_url,
        available: Boolean(marketData.source_url) && hasMetricData,
      }];
  const uniqueSources = [...new Map(sources.map((source) => [source.url || source.name, source])).values()];

  sourceList.replaceChildren(...uniqueSources.map((source) => {
    const item = document.createElement('li');
    item.className = 'data-source';
    const sourceUrl = parseSourceUrl(source.url) || getSourceUrl(marketData, address);
    const explicitlyUnavailable = source.available === false || source.status === 'unavailable';
    const explicitlyAvailable = source.available === true || source.status === 'available';
    const isAvailable = explicitlyAvailable || (!explicitlyUnavailable && Boolean(parseSourceUrl(source.url)) && hasMetricData);
    const link = document.createElement('a');
    link.href = sourceUrl;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = `${source.name || 'Data source'} ↗`;
    const status = document.createElement('span');
    status.className = `data-source__status${isAvailable ? ' is-available' : ' is-unavailable'}`;
    status.textContent = isAvailable ? 'Available' : 'Unavailable';
    item.append(link, status);
    return item;
  }));
  sourcesSection.hidden = false;
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
    updateMetricAttribution(activityReport, marketData, `txns.${windowName}.buys`, address);
    updateMetricAttribution(activityReport, marketData, `txns.${windowName}.sells`, address);
    updateMetricAttribution(activityReport, marketData, `volume.${windowName}`, address);
  });

  activityTable.hidden = !hasActivityData;
  emptyMessage.hidden = hasActivityData;
}

function updateMarketReport(result, address, subjectType) {
  const report = document.getElementById('market-report');
  if (subjectType !== 'token') {
    report.hidden = true;
    document.getElementById('data-sources').hidden = true;
    return;
  }

  const marketData = result.market_data || {};
  const marketMetricKeys = ['price_usd', 'liquidity_usd', 'volume_24h_usd', 'price_change_24h_percent'];
  report.querySelector('[data-market-value="price_usd"]').textContent = formatUsd(marketData.price_usd);
  report.querySelector('[data-market-value="liquidity_usd"]').textContent = formatUsd(marketData.liquidity_usd);
  report.querySelector('[data-market-value="volume_24h_usd"]').textContent = formatUsd(marketData.volume_24h_usd);
  report.querySelector('[data-market-value="price_change_24h_percent"]').textContent = formatPercent(marketData.price_change_24h_percent);
  report.querySelector('[data-market-value="updated_at"]').textContent = formatUpdatedAt(marketData.updated_at);

  const sourceLink = report.querySelector('[data-market-source]');
  const sourceUrl = getSourceUrl(marketData, address);
  sourceLink.href = sourceUrl;
  sourceLink.textContent = parseSourceUrl(marketData.source_url)
    ? 'Open data source ↗'
    : 'Source unavailable · Open DEX Screener ↗';
  marketMetricKeys.forEach((metricKey) => updateMetricAttribution(report, marketData, metricKey, address));
  updateActivityReport(marketData, address);
  const hasMetricData = marketMetricKeys.some((metricKey) => {
    const value = marketData[metricKey];
    return value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
  }) || ['m5', 'h1', 'h6', 'h24'].some((windowName) => {
    const transactions = marketData.txns?.[windowName] || {};
    const values = [transactions.buys, transactions.sells, marketData.volume?.[windowName]];
    return values.some((value) => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value)));
  });
  updateDataSources(marketData, address, hasMetricData);
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
  document.getElementById('market-report').hidden = true;
  document.getElementById('data-sources').hidden = true;
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
