const form = document.getElementById('analysis-form');
const addressInput = document.getElementById('address');
const submitButton = document.getElementById('analysis-submit');
const message = document.getElementById('analysis-message');

function showMessage(text, state) {
  message.textContent = text;
  message.dataset.state = state;
}
function resetSubmit() {
  submitButton.disabled = false;
  submitButton.querySelector('span').textContent = 'Analyze address';
}
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (submitButton.disabled) return;
  const address = addressInput.value.trim();
  if (!TokenAI.isSolanaAddress(address)) {
    addressInput.setAttribute('aria-invalid', 'true');
    showMessage(address ? 'Enter a valid Solana address: 32–44 Base58 characters that decode to 32 bytes.' : 'Enter a Solana address to continue.', 'error');
    addressInput.focus();
    return;
  }
  addressInput.removeAttribute('aria-invalid');
  submitButton.disabled = true;
  const subjectType = form.elements['subject-type'].value;
  if (subjectType === 'token') {
    submitButton.querySelector('span').textContent = 'Opening report…';
    window.location.assign(`/token/${encodeURIComponent(address)}`);
    return;
  }
  submitButton.querySelector('span').textContent = 'Submitting…';
  showMessage('Submitting wallet address…', 'pending');
  try {
    const base = await TokenAI.apiBase();
    await TokenAI.requestJson(`${base}/analyses/wallet`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ address }),
    });
    showMessage('Wallet address accepted. Wallet activity reports are coming in a later stage.', 'success');
  } catch (error) { showMessage(error.message || 'The analysis service is unavailable. Please try again.', 'error'); }
  finally { resetSubmit(); }
});
addressInput.addEventListener('input', () => {
  addressInput.removeAttribute('aria-invalid');
  showMessage('', '');
});
document.getElementById('use-example').addEventListener('click', () => {
  addressInput.value = 'So11111111111111111111111111111111111111112';
  addressInput.removeAttribute('aria-invalid');
  showMessage('', '');
  addressInput.focus();
});
// A form restored from the back/forward cache must be usable again.
window.addEventListener('pageshow', resetSubmit);
