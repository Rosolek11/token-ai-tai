const form = document.getElementById('analysis-form');
const addressInput = document.getElementById('address');
const submitButton = document.getElementById('analysis-submit');
const message = document.getElementById('analysis-message');
const base58Pattern = /^[1-9A-HJ-NP-Za-km-z]{32,64}$/;

function showMessage(text, state) {
  message.textContent = text;
  message.dataset.state = state;
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
