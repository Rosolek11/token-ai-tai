const views = {
  token: {
    title: 'Token anatomy',
    description: 'Market data, security signals and on-chain activity — brought together in context, beyond a single isolated metric.',
    badge: 'TOKEN VIEW',
    modules: [
      ['01', 'Market', 'Liquidity and volume'],
      ['02', 'Security', 'Risk signals'],
      ['03', 'On-chain', 'Holders and activity'],
    ],
  },
  wallet: {
    title: 'Wallet profile',
    description: 'Activity history, transaction patterns and token exposure — presented alongside the limits of the available data.',
    badge: 'WALLET VIEW',
    modules: [
      ['01', 'Activity', 'Transaction history'],
      ['02', 'Exposure', 'Token holdings'],
      ['03', 'Patterns', 'Behavior in context'],
    ],
  },
};

const tabs = [...document.querySelectorAll('.mode-tab')];
const panel = document.getElementById('mode-panel');
const modules = document.getElementById('preview-modules');

function renderMode(mode) {
  const view = views[mode];
  if (!view) return;
  tabs.forEach((tab) => {
    const active = tab.dataset.mode === mode;
    tab.classList.toggle('is-active', active);
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
  });
  panel.setAttribute('aria-labelledby', `tab-${mode}`);
  document.getElementById('preview-title').replaceChildren(document.createTextNode(view.title), Object.assign(document.createElement('span'), { textContent: '.' }));
  document.getElementById('preview-description').textContent = view.description;
  document.querySelector('.preview-badge').lastChild.textContent = ` ${view.badge}`;
  modules.replaceChildren(...view.modules.map(([number, label, detail]) => {
    const card = document.createElement('div');
    card.className = 'preview-module';
    const numberEl = document.createElement('span');
    numberEl.className = 'preview-module__number';
    numberEl.textContent = number;
    const title = document.createElement('strong');
    title.textContent = label;
    const subtitle = document.createElement('small');
    subtitle.textContent = detail;
    card.append(numberEl, title, subtitle);
    return card;
  }));
}

tabs.forEach((tab, index) => {
  tab.addEventListener('click', () => renderMode(tab.dataset.mode));
  tab.addEventListener('keydown', (event) => {
    let next = index;
    if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
    else if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = tabs.length - 1;
    else return;
    event.preventDefault();
    renderMode(tabs[next].dataset.mode);
    tabs[next].focus();
  });
});
renderMode('token');

const statusEl = document.getElementById('connection-status');
const detailEl = document.getElementById('connection-detail');
const lightEl = document.getElementById('connection-light');

async function checkApi() {
  try {
    const configResponse = await fetch('/api/client-config', { cache: 'no-store' });
    if (!configResponse.ok) throw new Error('API configuration is unavailable');
    const config = await configResponse.json();
    const base = config.apiBaseUrl || window.location.origin;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 5000);
    let response;
    try {
      response = await fetch(`${base.replace(/\/$/, '')}/health`, { signal: controller.signal, cache: 'no-store' });
    } finally {
      window.clearTimeout(timeout);
    }
    if (!response.ok) throw new Error('API response failed');
    const health = await response.json();
    if (health.status !== 'ok') throw new Error('API health check failed');
    statusEl.textContent = 'API connected';
    detailEl.textContent = 'Ready for future integrations';
    lightEl.classList.add('is-online');
  } catch {
    statusEl.textContent = 'API unavailable';
    detailEl.textContent = 'Check the server or API address';
    lightEl.classList.add('is-offline');
  }
}
checkApi();

document.getElementById('year').textContent = String(new Date().getFullYear());

if ('IntersectionObserver' in window) {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add('is-visible');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.08, rootMargin: '0px 0px 45px 0px' });
  document.querySelectorAll('.reveal').forEach((element) => observer.observe(element));
} else {
  document.querySelectorAll('.reveal').forEach((element) => element.classList.add('is-visible'));
}

const orbit = document.getElementById('orbit-field');
if (orbit && window.matchMedia('(pointer: fine) and (prefers-reduced-motion: no-preference)').matches) {
  orbit.addEventListener('pointermove', (event) => {
    const bounds = orbit.getBoundingClientRect();
    orbit.style.setProperty('--tilt-x', `${((event.clientX - bounds.left) / bounds.width - .5) * 13}px`);
    orbit.style.setProperty('--tilt-y', `${((event.clientY - bounds.top) / bounds.height - .5) * 13}px`);
  });
  orbit.addEventListener('pointerleave', () => {
    orbit.style.setProperty('--tilt-x', '0px');
    orbit.style.setProperty('--tilt-y', '0px');
  });
}
