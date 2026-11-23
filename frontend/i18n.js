/* Translate presentation text only; never mutate API payloads or HTML structure. */
(function (root) {
  const dictionary = root.TokenTranslations || (typeof require === 'function' ? require('./translations.js') : {});
  const normalize = text => text.trim().replace(/\s+/g, ' ');
  const patterns = [
    [/^(.+) Available facts are shown below\.$/, (_, failure) => `${part(failure)} Dostępne fakty są poniżej.`],
    [/^(\S+) sampled · (.+) Only the first page was checked\.(.*)$/, (_, count, total, rest) => `W próbce: ${count} · ${part(total)} Sprawdzono tylko pierwszą stronę.${rest ? ' '+part(rest.trim()) : ''}`],
    [/^(\S+) reported holders\.$/, (_, count) => `Liczba posiadaczy według dostawcy: ${count}.`],
    [/^Holders included in Top 10: (\d+)\.$/, (_, count) => `Liczba posiadaczy uwzględnionych w Top 10: ${count}.`],
    [/^(Share of total token supply\.|Uses percentages reported by Solscan\.) (Holders included in Top 10: \d+\.)$/, (_, basis, scope) => `${part(basis)} ${part(scope)}`],
    [/^Solscan Pro API access failed \((.*)\); holder pagination was skipped\.$/, (_, reason) => `Dostęp do Solscan Pro API nie powiódł się (${part(reason)}); pominięto pobieranie stron posiadaczy.`],
    [/^Top (\d+) holders from Solscan Pro API sample \((.*)\) control (.*)% of (.*)\.$/, (_, n, sample, pct, basis) => `${n} największych posiadaczy z próbki Solscan Pro API (${sample}) kontroluje ${pct}% ${part(basis)}.`],
    [/^No holders returned in Solscan Pro API sample \((.*)\); top 10 share is unavailable\.$/, (_, sample) => `Próbka Solscan Pro API nie zawiera posiadaczy (${sample}); udział 10 największych jest niedostępny.`],
    [/^Fetched (\d+) holder\(s\) from Solscan Pro API sample \((.*)\), but total token supply is missing or zero so top 10 share could not be computed\.$/, (_, n, sample) => `Pobrano ${n} posiadaczy z próbki Solscan Pro API (${sample}), ale brak łącznej podaży lub wynosi ona zero, więc nie można obliczyć udziału 10 największych.`],
    [/^Token charges a (.*)% transfer fee\.$/, (_, n) => `Token pobiera opłatę transferową ${n}%.`],
    [/^Top 10 holders control (.*)% of token supply\.$/, (_, n) => `10 największych posiadaczy kontroluje ${n}% podaży tokena.`],
    [/^(.*)% of LP tokens are locked or burned\.$/, (_, n) => `${n}% tokenów LP jest zablokowanych lub spalonych.`],
    [/^Primary DEX pair has \$(.*) liquidity\.$/, (_, n) => `Główna para DEX ma płynność ${n} USD.`],
    [/^GMGN reports (.*)% LP burned\.$/, (_, n) => `GMGN zgłasza ${n}% spalonych LP.`],
    [/^GMGN reports (.*)% bundled transaction supply\.$/, (_, n) => `GMGN zgłasza ${n}% podaży w transakcjach pakietowanych.`],
    [/^Aggregated from (.+) \((\d+) critical\/high, (\d+) warning, (\d+) safe signals\)\.(.*)$/, (_, names,a,b,c,rest) => `Agregacja źródeł: ${names} (${a} sygnałów krytycznych/wysokich, ${b} ostrzeżeń, ${c} bezpiecznych).${rest ? ' '+part(rest.trim()) : ''}`],
    [/^Unavailable sources \((.*)\) are marked explicitly and not treated as safe\.$/, (_, names) => `Niedostępne źródła (${names}) są jawnie oznaczone i nie są traktowane jako bezpieczne.`],
    [/^(\d+) pairs? found · selected (.+) pair by highest known liquidity\.$/, (_, n, dex) => `Znalezione pary: ${n} · wybrano parę ${dex} o największej znanej płynności.`],
    [/^(.+) \/ Market snapshot$/, (_, symbol) => `${symbol} / Obraz rynku`],
    [/^(\d+) \/ 4 providers responded\. Incomplete coverage — never interpret missing checks as safe\.$/, (_, n) => `Odpowiedziało ${n} / 4 dostawców. Niepełny zakres danych — brak kontroli nigdy nie oznacza bezpieczeństwa.`],
    [/^(\d+) observations · (\d+) provider flags · (\d+) data gaps$/, (_, a, b, c) => `Obserwacje: ${a} · flagi dostawców: ${b} · braki danych: ${c}`],
    [/^(.+) · Data unavailable$/, (_, source) => `${source} · Dane niedostępne`],
    [/^This check could not be completed\. (.*)$/, (_, reason) => `Nie udało się wykonać kontroli. ${part(reason)}`],
    [/^Historical approved tokenProfile order\. Ads and boosts do not count; not a safety check\. Retrieved: (.*)$/, (_, time) => `Historyczne zatwierdzone zamówienie tokenProfile. Reklamy i promocje nie są uwzględniane; nie jest to kontrola bezpieczeństwa. Pobrano: ${time}`],
    [/^LOCAL DATA UNAVAILABLE \/ (.*) A working RPC endpoint may be required; missing data is not zero\.$/, (_, error) => `DANE LOKALNE NIEDOSTĘPNE / ${part(error)} Może być wymagany działający endpoint RPC; brak danych nie oznacza zera.`],
    [/^(\d+) \/ (.*)$/, (_, n, label) => `${n} / ${part(label)}`],
    [/^TAI \/ (.*)$/, (_, label) => `TAI / ${part(label)}`],
    [/^TOKEN INTELLIGENCE \/ (.*)$/, (_, key) => `ANALIZA TOKENA / ${part(({INTELLIGENCE:'Overview',METRICS:'All signals',MARKET:'Market',WARNINGS:'Warnings',CONTRACT:'Contract',HOLDERS:'Holders',LIQUIDITY:'Liquidity',ACTIVITY:'Activity',AUDIT:'Audit scores',SOURCES:'Sources',MAP:'Bubble map',LOCAL:'Local engine'})[key] || key)}`],
    [/^(Authority|Update auth|Top wallet|Creator|Amount|Owner|Sniper count|Buy\/Sell ratio|DEXes): (.*)$/, (_, label, value) => `${({'Authority':'Uprawnienie','Update auth':'Uprawnienie aktualizacji','Top wallet':'Największy portfel','Creator':'Twórca','Amount':'Ilość','Owner':'Właściciel','Sniper count':'Liczba sniperów','Buy/Sell ratio':'Stosunek kupna do sprzedaży','DEXes':'Giełdy DEX'})[label]}: ${part(value)}`],
    [/^(\d+) crit · (\d+) warn · (\d+) ok$/, (_, a,b,c) => `${a} kryt. · ${b} ostrz. · ${c} bezp.`],
    [/^(\d+) snipers · (\d+) dev rugs$/, (_, a,b) => `${a} sniperów · ${b} rug pulli twórcy`],
    [/^(\d+) LP providers · (\d+) lockers$/, (_, a,b) => `${a} dostawców LP · ${b} blokad`],
    [/^(.*)h old$/, (_, age) => `${age} h`],
    [/^(\d+) boosts$/, (_, n) => `${n} promocji`],
    [/^(\d+) nets \((.*)\)$/, (_, n, pct) => `${n} sieci (${pct})`],
    [/^(\d+) social link\(s\) · (\d+) web$/, (_, n, sites) => `${n} odnośników społecznościowych · ${sites} stron`],
    [/^(.*) \((\d+) total\)$/, (_, ratio, n) => `${part(ratio)} (${n} łącznie)`],
    [/^(.+) \/ (ok|partial|no_data|unavailable|not_configured|unauthorized|rate_limited)$/, (_, name, state) => `${name} / ${part(state)}`],
    [/^UNAVAILABLE \((.*)\)$/, (_, reason) => `NIEDOSTĘPNE (${part(reason)})`],
    [/^(.+) · Retrieved: (.*)$/, (_, status, time) => `${part(status)} · Pobrano: ${time}`],
    [/^(.+) · (Enabled|Disabled)$/, (_, title, value) => `${part(title)} · ${part(value)}`],
  ];
  function part(text) {
    if (Object.hasOwn(dictionary, text)) return dictionary[text];
    const upper = Object.keys(dictionary).find(key => key.toUpperCase() === text && key !== text);
    if (upper) return dictionary[upper].toUpperCase();
    for (const [pattern, render] of patterns) if (pattern.test(text)) return text.replace(pattern, render);
    // Delimiters preserve numeric values, token symbols and provider names.
    for (const separator of [' · ', ' / ', ' — ']) {
      if (text.includes(separator)) return text.split(separator).map(part).join(separator);
    }
    return text;
  }
  function translate(text, language = 'pl') {
    if (language !== 'pl' || typeof text !== 'string' || !text.trim()) return text;
    const source = normalize(text);
    return text.replace(text.trim(), part(source));
  }
  if (typeof module !== 'undefined') module.exports = {translate, dictionary};
  if (!root.document) return;
  const doc = root.document;
  const storageKey = 'token-ai-language';
  let language = 'en';
  try { if (root.localStorage.getItem(storageKey) === 'pl') language = 'pl'; } catch { /* Storage is optional. */ }
  const originals = new WeakMap();
  const attributes = ['aria-label', 'placeholder', 'title', 'alt'];
  const ignored = 'script, style, code, textarea, select, option, [translate="no"], #report-address, #intro-address';
  function update(node, key, value, write) {
    let state = originals.get(node);
    if (!state) { state = {}; originals.set(node, state); }
    let record = state[key];
    if (!record || value !== record.rendered) record = {source: value};
    record.rendered = translate(record.source, language);
    state[key] = record;
    if (record.rendered !== value) write(record.rendered);
  }
  const observer = new root.MutationObserver(() => refresh());
  function refresh() {
    observer.disconnect();
    const walker = doc.createTreeWalker(doc.documentElement, root.NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (!node.parentElement?.closest(ignored)) update(node, 'text', node.nodeValue, value => { node.nodeValue = value; });
    }
    doc.querySelectorAll('[aria-label], [placeholder], [title], [alt], meta[name="description"]').forEach(node => {
      if (node.closest(ignored)) return;
      for (const attr of attributes.concat(node.matches('meta') ? ['content'] : [])) {
        if (node.hasAttribute(attr)) update(node, attr, node.getAttribute(attr), value => node.setAttribute(attr, value));
      }
    });
    doc.documentElement.lang = language;
    doc.querySelectorAll('[data-language-select]').forEach(select => {
      select.value = language;
      select.setAttribute('aria-label', language === 'pl' ? 'Język aplikacji' : 'Application language');
    });
    observer.observe(doc.documentElement, {subtree:true, childList:true, characterData:true, attributes:true, attributeFilter:attributes});
  }
  function setLanguage(value) {
    if (!['en', 'pl'].includes(value)) return;
    language = value;
    try { root.localStorage.setItem(storageKey, value); } catch { /* Continue without persistence. */ }
    refresh();
  }
  function init() {
    const header = doc.querySelector('.site-header');
    if (header) {
      const actions = doc.createElement('div'); actions.className = 'header-actions';
      const link = header.querySelector('.header-link, .report-nav');
      if (link) { header.insertBefore(actions, link); actions.append(link); } else header.append(actions);
      const select = doc.createElement('select'); select.className = 'language-select';
      select.dataset.languageSelect = '';
      for (const [value,label] of [['pl','PL'],['en','EN']]) {
        const option = doc.createElement('option'); option.value = value; option.textContent = label; option.lang = value; select.append(option);
      }
      select.addEventListener('change', () => setLanguage(select.value)); actions.append(select);
    }
    refresh();
  }
  root.TokenI18n = {setLanguage, translate: text => translate(text, language), get language() {return language;}};
  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', init); else init();
})(typeof window === 'undefined' ? {} : window);
