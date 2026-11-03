/* The introduction has its own clock; API requests continue independently. */
window.ReportIntro = (() => {
  const intro = document.getElementById('report-intro');
  const app = document.getElementById('report-app');
  let timer;
  function finish() {
    window.clearTimeout(timer);
    if (!intro || !app) return;
    intro.hidden = true;
    intro.classList.remove('is-running');
    app.removeAttribute('inert');
    document.body.classList.remove('intro-active');
  }
  function start() {
    if (!intro || !app) return;
    window.clearTimeout(timer);
    let address = '';
    try { address = decodeURIComponent(window.location.pathname.split('/')[2] || ''); }
    catch { /* The report handles invalid addresses after the introduction. */ }
    document.getElementById('intro-address').textContent = address || 'SOLANA NETWORK';
    intro.hidden = false;
    intro.classList.remove('is-running');
    app.setAttribute('inert', '');
    document.body.classList.add('intro-active');
    // Restart the CSS timeline when a report is restored from the browser cache.
    void intro.offsetWidth;
    intro.classList.add('is-running');
    timer = window.setTimeout(finish, 3000);
  }
  window.addEventListener('pagehide', finish);
  window.addEventListener('pageshow', event => { if (event.persisted) start(); });
  return { start, finish };
})();
window.ReportIntro.start();
