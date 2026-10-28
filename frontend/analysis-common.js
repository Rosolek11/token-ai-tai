/* Shared browser-side contract for the address form and token report. */
window.TokenAI = (() => {
  const alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
  const messages = {
    INVALID_ADDRESS: 'Enter a valid Solana address: 32–44 Base58 characters that decode to 32 bytes.',
    MARKET_DATA_TIMEOUT: 'The market data source took too long to respond. Please try again.',
    MARKET_DATA_UNAVAILABLE: 'The market data source is temporarily unavailable. Please try again.',
  };
  function isSolanaAddress(address) {
    if (typeof address !== 'string' || !/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(address)) return false;
    let value = 0n;
    for (const character of address) value = value * 58n + BigInt(alphabet.indexOf(character));
    let bytes = 0;
    while (value > 0n) { bytes += 1; value >>= 8n; }
    return address.match(/^1*/)[0].length + bytes === 32;
  }
  async function requestJson(url, options = {}) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(url, { ...options, signal: controller.signal, cache: 'no-store' });
      let result;
      try { result = await response.json(); }
      catch { throw new Error('The service returned an unreadable response. Please try again.'); }
      if (!response.ok) throw new Error(messages[result?.detail] || 'The analysis service could not complete this request. Please try again.');
      return result;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('The request timed out. Check your connection and try again.');
      if (error instanceof TypeError) throw new Error('Cannot reach the analysis service. Check your connection and try again.');
      throw error;
    } finally { window.clearTimeout(timeout); }
  }
  async function apiBase() {
    const config = await requestJson('/api/client-config');
    if (!config || typeof config.apiBaseUrl !== 'string') throw new Error('The analysis service configuration is unavailable.');
    return (config.apiBaseUrl || window.location.origin).replace(/\/$/, '');
  }
  function parseMarketNumber(value) {
    if (typeof value !== 'number' && typeof value !== 'string') return null;
    if (typeof value === 'string' && value.trim() === '') return null;
    const amount = Number(value);
    return Number.isFinite(amount) ? amount : null;
  }
  function formatUsd(value) {
    const amount = parseMarketNumber(value);
    if (amount === null) return 'No data';
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: amount < 1 ? 8 : 2 }).format(amount);
  }
  function formatPercent(value) {
    const amount = parseMarketNumber(value);
    if (amount === null) return 'No data';
    return `${new Intl.NumberFormat('en-US', { signDisplay: 'always', maximumFractionDigits: 2 }).format(amount)}%`;
  }
  function formatUpdatedAt(value) {
    if (!value) return 'No data';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'No data';
    return new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
  }
  function updateMarketReport(result, address) {
    const report = document.getElementById('market-report');
    const marketData = result.market_data || {};
    for (const metric of ['price_usd', 'liquidity_usd', 'volume_24h_usd']) {
      report.querySelector(`[data-market-value="${metric}"]`).textContent = formatUsd(marketData[metric]);
    }
    const change = report.querySelector('[data-market-value="price_change_24h_percent"]');
    change.textContent = formatPercent(marketData.price_change_24h_percent);
    const amount = parseMarketNumber(marketData.price_change_24h_percent);
    change.dataset.direction = amount === null || amount === 0 ? 'neutral' : amount > 0 ? 'up' : 'down';
    const time = report.querySelector('[data-market-value="updated_at"]');
    time.textContent = formatUpdatedAt(marketData.updated_at);
    if (marketData.updated_at && !Number.isNaN(new Date(marketData.updated_at).getTime())) time.setAttribute('datetime', marketData.updated_at);
    else time.removeAttribute('datetime');
    const sourceLink = report.querySelector('[data-market-source]');
    let sourceUrl = `https://dexscreener.com/solana/${encodeURIComponent(address)}`;
    if (typeof marketData.source_url === 'string') {
      try { const parsed = new URL(marketData.source_url); if (parsed.protocol === 'https:') sourceUrl = parsed.href; }
      catch { /* Keep the source fallback for an invalid provider URL. */ }
    }
    sourceLink.href = sourceUrl;
    sourceLink.textContent = 'Verify on DEX Screener ↗';
    updateSecurityReport(result, address);
  }
  function formatCompactNumber(value) {
    const amount = parseMarketNumber(value);
    if (amount === null) return 'No data';
    return new Intl.NumberFormat('en-US', { notation: amount >= 100000 ? 'compact' : 'standard', maximumFractionDigits: 2 }).format(amount);
  }
  function formatPlainPercent(value) {
    const amount = parseMarketNumber(value);
    if (amount === null) return 'No data';
    return `${new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(amount)}%`;
  }
  function formatBoolFlag(value, trueText, falseText) {
    if (value === true) return trueText;
    if (value === false) return falseText;
    return 'No data';
  }
  function shortenAddress(addr) {
    if (typeof addr !== 'string' || addr.length < 12) return addr || 'No data';
    return `${addr.slice(0, 6)}…${addr.slice(-4)}`;
  }
  function updateSecurityReport(result, address) {
    const secEl = document.getElementById('security-report');
    if (!secEl) return;
    const sec = result?.security_data || {};
    const risk = sec.risk_summary || {};
    const auth = sec.authorities || {};
    const holders = sec.holder_distribution || {};
    const liq = sec.liquidity_security || {};
    const act = sec.market_activity || {};
    const ver = sec.verification_and_metadata || {};
    const sources = sec.sources || {};

    const setVal = (key, text, direction) => {
      const node = secEl.querySelector?.(`[data-security-value="${key}"]`);
      if (!node) return;
      node.textContent = text ?? 'No data';
      if (direction) node.dataset.direction = direction;
      else if (node.dataset) delete node.dataset.direction;
    };

    for (const srcName of ['rugcheck', 'dexscreener', 'dextools', 'gmgn']) {
      const srcInfo = sources[srcName];
      const badge = secEl.querySelector?.(`[data-security-source="${srcName}"]`);
      const label = secEl.querySelector?.(`[data-source-status="${srcName}"]`);
      const st = srcInfo?.status || 'unavailable';
      if (badge && badge.dataset) badge.dataset.state = st;
      if (label) {
        const reason = srcInfo?.reason ? ` (${srcInfo.reason.replace(/_/g, ' ')})` : '';
        label.textContent = st === 'ok' ? 'OK' : st === 'no_data' ? 'NO DATA' : `UNAVAILABLE${reason}`;
      }
    }

    const verdictEl = document.getElementById('security-verdict');
    if (verdictEl) verdictEl.textContent = risk.verdict_summary || 'No security verdict available.';

    const level = typeof risk.risk_level === 'string' ? risk.risk_level.toUpperCase() : 'UNKNOWN';
    setVal('risk_level', level === 'UNKNOWN' ? 'No data' : level, level === 'LOW' ? 'up' : ['HIGH', 'CRITICAL'].includes(level) ? 'down' : 'neutral');
    setVal('safety_score', parseMarketNumber(risk.safety_score) !== null ? `${formatCompactNumber(risk.safety_score)} / 100` : 'No data');
    setVal('normalized_score', parseMarketNumber(risk.normalized_score) !== null ? `${formatCompactNumber(risk.normalized_score)} / 100` : 'No data');
    setVal('risk_score', formatCompactNumber(risk.risk_score));
    setVal('is_honeypot', formatBoolFlag(risk.is_honeypot, 'HONEYPOT', 'Safe (No)'), risk.is_honeypot === true ? 'down' : risk.is_honeypot === false ? 'up' : '');
    setVal('rugged', formatBoolFlag(risk.rugged, 'RUGGED', 'Not rugged'), risk.rugged === true ? 'down' : risk.rugged === false ? 'up' : '');
    setVal('dextools_score', parseMarketNumber(ver.dextools_score) !== null ? `${formatCompactNumber(ver.dextools_score)} / 100` : 'No data');
    setVal('flags_counts', typeof risk.total_flags_count === 'number' && risk.total_flags_count > 0 ? `${risk.critical_flags_count || 0} crit · ${risk.warning_flags_count || 0} warn · ${risk.safe_flags_count || 0} ok` : 'No data');

    setVal('mint_authority_active', formatBoolFlag(auth.mint_authority_active, 'ACTIVE (Risk)', 'Renounced'), auth.mint_authority_active === true ? 'down' : auth.mint_authority_active === false ? 'up' : '');
    setVal('mint_authority', auth.mint_authority ? `Authority: ${shortenAddress(auth.mint_authority)}` : 'Minting permission state');
    setVal('freeze_authority_active', formatBoolFlag(auth.freeze_authority_active, 'ACTIVE (Risk)', 'Renounced'), auth.freeze_authority_active === true ? 'down' : auth.freeze_authority_active === false ? 'up' : '');
    setVal('freeze_authority', auth.freeze_authority ? `Authority: ${shortenAddress(auth.freeze_authority)}` : 'Account freeze permission');
    setVal('mutable_metadata', formatBoolFlag(auth.mutable_metadata, 'Mutable', 'Immutable'), auth.mutable_metadata === true ? 'down' : auth.mutable_metadata === false ? 'up' : '');
    setVal('update_authority', auth.update_authority ? `Update auth: ${shortenAddress(auth.update_authority)}` : 'Metadata modification state');
    setVal('token_program', auth.is_token_2022 === true ? 'Token-2022' : auth.is_token_2022 === false ? 'SPL Token' : auth.token_program ? shortenAddress(auth.token_program) : 'No data');
    setVal('transfer_fee_pct', formatPlainPercent(auth.transfer_fee_pct));

    const buyTax = formatPlainPercent(ver.buy_tax_pct);
    const sellTax = formatPlainPercent(ver.sell_tax_pct);
    setVal('buy_sell_tax', buyTax === 'No data' && sellTax === 'No data' ? 'No data' : `${buyTax} / ${sellTax}`);

    const openSrc = formatBoolFlag(auth.is_open_source, 'Verified', 'Unverified');
    const proxy = formatBoolFlag(auth.is_proxy, 'Proxy', 'No proxy');
    setVal('contract_verification', openSrc === 'No data' && proxy === 'No data' ? 'No data' : `${openSrc} · ${proxy}`);

    const bl = formatBoolFlag(ver.is_blacklisted, 'Blacklisted', 'Clean');
    const scam = formatBoolFlag(ver.is_potentially_scam, 'Scam flag', 'Clean');
    setVal('blacklist_scam_check', bl === 'No data' && scam === 'No data' ? 'No data' : `${bl} · ${scam}`);

    setVal('holder_count', formatCompactNumber(holders.holder_count));
    setVal('top_holder_pct', formatPlainPercent(holders.top_holder_pct));
    setVal('top_holder_address', holders.top_holder_address ? `Top wallet: ${shortenAddress(holders.top_holder_address)}` : 'Largest wallet share');
    setVal('top_5_holders_pct', formatPlainPercent(holders.top_5_holders_pct));
    setVal('top_10_holders_pct', formatPlainPercent(holders.top_10_holders_pct));
    setVal('creator_balance_pct', formatPlainPercent(holders.creator_balance_pct));
    setVal('creator_address', holders.creator_address ? `Creator: ${shortenAddress(holders.creator_address)}` : 'Deployer held supply');

    const insNets = parseMarketNumber(holders.insider_networks_count);
    const insPct = formatPlainPercent(holders.insider_supply_pct);
    setVal('insider_summary', insNets === null && insPct === 'No data' ? 'No data' : `${insNets ?? 0} nets (${insPct})`);
    setVal('bundled_supply_pct', formatPlainPercent(holders.bundled_supply_pct));

    const snipers = parseMarketNumber(holders.sniper_holders_count);
    const rugs = parseMarketNumber(holders.dev_rug_history_count);
    setVal('snipers_and_rugs', snipers === null && rugs === null ? 'No data' : `${snipers ?? 0} snipers · ${rugs ?? 0} dev rugs`);

    setVal('total_market_liquidity_usd', formatUsd(liq.total_market_liquidity_usd));
    setVal('lp_locked_pct', formatPlainPercent(liq.lp_locked_pct));
    setVal('lp_burned_pct', formatPlainPercent(liq.lp_burned_pct));
    setVal('lp_locked_usd', formatUsd(liq.lp_locked_usd));
    setVal('lp_providers_count', parseMarketNumber(liq.lp_providers_count) !== null ? `${liq.lp_providers_count} LP providers · ${liq.lockers_count ?? 0} lockers` : 'LP lock valuation');

    const fdv = formatUsd(act.fdv_usd);
    const mcap = formatUsd(act.market_cap_usd);
    setVal('fdv_mcap', fdv === 'No data' && mcap === 'No data' ? 'No data' : `${fdv} / ${mcap}`);

    const v5m = formatUsd(act.volume_5m_usd);
    const v1h = formatUsd(act.volume_1h_usd);
    const v6h = formatUsd(act.volume_6h_usd);
    setVal('short_term_volume', [v5m, v1h, v6h].every(v => v === 'No data') ? 'No data' : `${v5m} · ${v1h} · ${v6h}`);

    const c5m = formatPercent(act.price_change_5m_percent);
    const c1h = formatPercent(act.price_change_1h_percent);
    const c6h = formatPercent(act.price_change_6h_percent);
    setVal('short_term_price_change', [c5m, c1h, c6h].every(v => v === 'No data') ? 'No data' : `${c5m} · ${c1h} · ${c6h}`);

    const b24 = parseMarketNumber(act.buys_24h);
    const s24 = parseMarketNumber(act.sells_24h);
    setVal('txns_buys_sells_24h', b24 === null && s24 === null ? 'No data' : `${b24 ?? 0} B / ${s24 ?? 0} S`);
    setVal('buy_sell_ratio_24h', parseMarketNumber(act.buy_sell_ratio_24h) !== null ? `Buy/Sell ratio: ${act.buy_sell_ratio_24h}x (${act.total_txns_24h ?? 0} total)` : 'Order flow balance');

    const b1h = parseMarketNumber(act.buys_1h);
    const s1h = parseMarketNumber(act.sells_1h);
    const b5m = parseMarketNumber(act.buys_5m);
    const s5m = parseMarketNumber(act.sells_5m);
    setVal('txns_short_term', [b1h, s1h, b5m, s5m].every(v => v === null) ? 'No data' : `1h: ${b1h ?? 0}/${s1h ?? 0} · 5m: ${b5m ?? 0}/${s5m ?? 0}`);

    const age = parseMarketNumber(act.pair_age_hours);
    const boosts = parseMarketNumber(act.active_boosts);
    setVal('pair_age_boosts', age === null && boosts === null ? 'No data' : `${age !== null ? `${age}h old` : 'Age n/a'} · ${boosts ?? 0} boosts`);
    setVal('dex_list', Array.isArray(act.dex_list) && act.dex_list.length > 0 ? `DEXes: ${act.dex_list.join(', ')}` : 'Pool maturity & DEXes');

    const sup = formatCompactNumber(act.total_supply);
    const dec = parseMarketNumber(act.token_decimals);
    setVal('supply_decimals', sup === 'No data' && dec === null ? 'No data' : `${sup}${dec !== null ? ` (${dec} dec)` : ''}`);

    const jup = formatBoolFlag(ver.jupiter_verified, 'Jupiter ✓', 'Unverified');
    setVal('verification_status', jup);
    setVal('social_links', Array.isArray(ver.socials) && ver.socials.length > 0 ? `${ver.socials.length} social link(s) · ${ver.websites?.length || 0} web` : 'Jupiter, RugCheck & socials');

    const countEl = document.getElementById('security-flags-count');
    const flags = Array.isArray(sec.flags) ? sec.flags : [];
    if (countEl) countEl.textContent = String(flags.length);

    const renderListItems = (listEl, items) => {
      if (!listEl) return;
      if (typeof listEl.replaceChildren === 'function' && typeof document.createElement === 'function') {
        const nodes = items.map(item => {
          const li = document.createElement('li');
          li.className = 'security-flag-item';
          li.dataset.severity = item.severity || 'info';
          const badge = document.createElement('span');
          badge.textContent = item.badge;
          const body = document.createElement('div');
          const strong = document.createElement('strong');
          strong.textContent = item.title;
          const small = document.createElement('small');
          small.textContent = item.detail;
          body.append(strong, small);
          li.append(badge, body);
          return li;
        });
        listEl.replaceChildren(...nodes);
      } else {
        listEl.textContent = items.map(item => `[${item.badge}] ${item.title}: ${item.detail}`).join(' | ');
      }
    };

    const flagsList = document.getElementById('security-flags-list');
    renderListItems(
      flagsList,
      flags.length === 0
        ? [{ severity: 'info', badge: 'INFO', title: 'No security flags', detail: 'No normalized security flags returned by available providers.' }]
        : flags.map(f => ({
            severity: f.severity || 'info',
            badge: `${(f.severity || 'info').toUpperCase()} · ${(f.source || '').toUpperCase()}`,
            title: `${f.title}${f.value !== null && f.value !== undefined ? ` (${f.value})` : ''}`,
            detail: f.description || '',
          }))
    );

    const holdersList = document.getElementById('top-holders-list');
    const topHolders = Array.isArray(holders.top_holders) ? holders.top_holders : [];
    renderListItems(
      holdersList,
      topHolders.length === 0
        ? [{ severity: 'info', badge: 'HOLDERS', title: 'No holder breakdown available', detail: 'Provider did not return individual wallet balances.' }]
        : topHolders.slice(0, 10).map((h, i) => ({
            severity: h.is_insider ? 'high' : (h.pct || 0) >= 10 ? 'warn' : 'ok',
            badge: `#${i + 1} · ${formatPlainPercent(h.pct)}`,
            title: `${shortenAddress(h.address)}${h.is_insider ? ' · INSIDER' : ''}`,
            detail: `Amount: ${formatCompactNumber(h.ui_amount)}${h.owner ? ` · Owner: ${shortenAddress(h.owner)}` : ''}`,
          }))
    );

    const rcLink = secEl.querySelector?.('[data-rugcheck-source]');
    if (rcLink) rcLink.href = `https://rugcheck.xyz/tokens/${encodeURIComponent(address)}`;

    const overallEl = document.getElementById('security-overall-status');
    if (overallEl) overallEl.textContent = `READ-ONLY · ${(sec.overall_status || 'unavailable').toUpperCase()}`;
  }
  return { isSolanaAddress, requestJson, apiBase, parseMarketNumber, formatUsd, formatPercent, formatUpdatedAt, updateMarketReport, updateSecurityReport };
})();
