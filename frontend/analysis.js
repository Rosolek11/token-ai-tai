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
  if (value === null || value === undefined || value === '') return 'Brak danych';
  const amount = Number(value);
  if (!Number.isFinite(amount)) return 'Brak danych';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: amount < 1 ? 8 : 2,
  }).format(amount);
}

function formatPercent(value) {
  if (value === null || value === undefined || value === '') return 'Brak danych';
  const amount = Number(value);
  if (!Number.isFinite(amount)) return 'Brak danych';
  return `${new Intl.NumberFormat('en-US', { signDisplay: 'always', maximumFractionDigits: 2 }).format(amount)}%`;
}

function formatUpdatedAt(value) {
  if (!value) return 'Brak danych';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Brak danych';
  return new Intl.DateTimeFormat('pl-PL', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
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
  const fallbackUrl = `https://dexscreener.com/solana/${encodeURIComponent(address)}`;
  let sourceUrl = fallbackUrl;
  if (typeof marketData.source_url === 'string') {
    try {
      const parsedUrl = new URL(marketData.source_url);
      if (parsedUrl.protocol === 'https:') sourceUrl = parsedUrl.href;
    } catch {
      sourceUrl = fallbackUrl;
    }
  }
  sourceLink.href = sourceUrl;
  sourceLink.textContent = sourceUrl === fallbackUrl ? 'Open DEX Screener source ↗' : 'Open data source ↗';
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
