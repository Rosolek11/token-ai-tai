/* Provider observations, never an AI prediction or a guarantee of safety. */
(function (root) {
  const providers = ['rugcheck', 'dexscreener', 'dextools', 'gmgn'];
  const weights = {critical: 6, high: 5, warn: 4, low: 3, info: 2, ok: 1};
  function flagValue(value) {
    if (typeof value === 'boolean') return value ? 'Enabled' : 'Disabled';
    if (typeof value === 'number') return Number.isFinite(value) ? new Intl.NumberFormat('en-US',{maximumFractionDigits:2}).format(value) : '';
    // Some provider values contain serialized account dumps; the explanation is
    // useful, the multi-kilobyte raw payload is not a readable warning title.
    if (typeof value === 'string' && value.length <= 80) return value;
    return '';
  }
  function warningModel(result) {
    const security = result?.security_data || {};
    const sources = security.sources || {};
    const missing = providers.filter(name => sources[name]?.status !== 'ok');
    const flags = (Array.isArray(security.flags) ? security.flags : []).map(flag => ({
      ...flag, severity: weights[flag.severity] ? flag.severity : 'info',
      source: providers.includes(flag.source) || flag.source === 'aggregated' ? flag.source : 'unknown',
    })).sort((a, b) => weights[b.severity] - weights[a.severity]);
    const observed = security.risk_summary?.risk_level;
    const hasAudit = ['rugcheck', 'dextools', 'gmgn'].some(name => sources[name]?.status === 'ok');
    const level = hasAudit && ['low','medium','high','critical'].includes(observed) ? observed : 'unknown';
    return {flags, missing, sources, level, complete: missing.length === 0,
      explanation: level === 'unknown' ? 'Insufficient audit evidence. Missing data is not evidence of safety.' :
        (security.risk_summary?.verdict_summary || 'Provider-reported risk classification. Review individual observations and coverage below.')};
  }
  function nonNegative(value, max = Infinity) {
    if (typeof value !== 'number' && (typeof value !== 'string' || !value.trim())) return null;
    const number = Number(value);
    return Number.isFinite(number) && number >= 0 && number <= max ? number : null;
  }
  const sourceNames = {rugcheck:'RugCheck', dexscreener:'DEX Screener', dextools:'DEXTools', gmgn:'GMGN', solscan:'Solscan'};
  function holderModel(result) {
    const chain = result?.onchain_data;
    const security = result?.security_data;
    const distribution = security?.holder_distribution;
    const sample = chain?.holder_sample;
    const rows = Array.isArray(chain?.holders) ? chain.holders : [];
    const measurement = (value, source) => ({value, source: value === null ? null : source});
    const fallbackSource = key => sourceNames[security?.normalized_data?.holders?.[key]?.sourceId] || 'Security aggregation';
    const authority = kind => {
      const active = security?.authorities?.[kind + '_authority_active'];
      if (typeof active === 'boolean') return measurement(active, 'Security aggregation');
      const address = chain?.metadata?.[kind + '_authority'];
      // Solscan also serializes missing fields as null.
      if (typeof address === 'string' && address.trim()) return measurement(true, 'Solscan');
      return measurement(null);
    };
    const chainTotal = nonNegative(chain?.supply?.ui_amount) ?? nonNegative(chain?.total_supply);
    const chainCount = nonNegative(chain?.holder_count) ?? nonNegative(sample?.total_holders);
    const chainShare = nonNegative(sample?.top_10_share_percent, 100) ?? nonNegative(chain?.top_10_share_percent, 100);
    const decimals = nonNegative(chain?.supply?.decimals) ?? nonNegative(chain?.decimals);
    return {
      supply: chainTotal !== null ? measurement(chainTotal, 'Solscan') : measurement(nonNegative(security?.market_activity?.total_supply), 'Security aggregation'),
      count: chainCount !== null ? measurement(chainCount, 'Solscan') : measurement(nonNegative(distribution?.holder_count), fallbackSource('holder_count')),
      top10: chainShare !== null ? measurement(chainShare, 'Solscan holder sample') : measurement(nonNegative(distribution?.top_10_holders_pct, 100), fallbackSource('top_10_holders_pct')),
      mint: authority('mint'),
      freeze: authority('freeze'),
      decimals: decimals !== null ? measurement(decimals, 'Solscan') : measurement(nonNegative(security?.market_activity?.token_decimals), 'Security aggregation'),
      sampleSize: nonNegative(sample?.sample_size) ?? (rows.length || null),
      rankedCount: nonNegative(sample?.top_10_count, 10),
      totalHolders: nonNegative(sample?.total_holders) ?? chainCount,
      sampleBasis: sample?.calculation_basis,
      sampleDescription: chain?.sample_description || sample?.sample_description,
      rows: rows.slice(0, 10),
      fallbackRows: Array.isArray(distribution?.top_holders) && distribution.top_holders.length > 0,
    };
  }
  if (typeof module !== 'undefined') module.exports = {warningModel,flagValue,holderModel};
  if (!root.document) return;
  const doc = root.document;
  const content = doc.getElementById('report-content');
  const security = doc.getElementById('security-report');
  if (!content || !security) return;
  const create = (tag, cls, text) => {
    const el = doc.createElement(tag); if (cls) el.className = cls;
    if (text !== undefined) el.textContent = text;
    return el;
  };
  const views = [ ['intelligence','Overview','00'], ['metrics','All signals','01'], ['market','Market','01'], ['warnings','Warnings','02'], ['contract','Contract','03'],
    ['holders','Holders','04'], ['liquidity','Liquidity','05'], ['activity','Activity','06'], ['audit','Audit scores','07'], ['sources','Sources','08'], ['map','Bubble map','09'], ['local','Local engine','10'] ];
  views.forEach((view,index) => { view[2] = String(index+1).padStart(2,'0'); });
  const nav = create('div','workspace-nav'); nav.setAttribute('role','tablist'); nav.setAttribute('aria-label','Report screens');
  const panes = {};
  const market = doc.getElementById('market-report');
  market.classList.add('workspace-pane'); panes.market = market;
  const grids = [...security.querySelectorAll('.security-metrics-grid')];
  const headings = [...security.querySelectorAll('.security-subheading')];
  views.filter(([key]) => key !== 'market').forEach(([key,label]) => {
    const pane = create('section','workspace-pane');
    pane.append(create('p','section-kicker','TOKEN INTELLIGENCE / '+key.toUpperCase()),create('h2','workspace-title',label));
    security.append(pane); panes[key] = pane;
  });
  const summary = create('div','warning-summary');
  const dial = create('div','warning-dial'); const level = create('strong',null,'UNKNOWN');
  dial.append(create('span',null,'OBSERVED RISK'),level,create('small',null,'NOT A SAFETY GUARANTEE'));
  const summaryText = create('div'); const coverage = create('p','coverage-note');
  const explanation = create('p','warning-explanation');
  summaryText.append(create('p','section-kicker','PROVIDER OBSERVATIONS'),explanation,coverage);
  summary.append(dial,summaryText); panes.warnings.append(summary);
  const filters = create('div','warning-filters'); filters.setAttribute('role','group'); filters.setAttribute('aria-label','Filter observations');
  const list = doc.getElementById('security-flags-list'); list.setAttribute('aria-live','polite');
  const count = create('p','warning-count'); count.setAttribute('role','status');
  panes.warnings.append(filters,count,list);
  if (grids[0]) panes.audit.append(grids[0]);
  panes.audit.append(create('p','coverage-note','Scores are provider observations, not an AI assessment. A high safety score does not certify a token as safe. Missing checks remain unknown.'));
  if (grids[1]) panes.contract.append(grids[1]);
  const holderFacts = create('dl','holder-facts');
  const onchainNote = create('p','coverage-note holder-method');
  const holderListTitle = create('h3','holder-list-title','Ranked holder sample');
  const sampleTable = create('table','holder-sample');
  const sampleHead = create('thead');
  const sampleHeaders = create('tr');
  for (const label of ['Owner or token account','Token balance','Share']) {
    const heading = create('th',null,label);
    heading.scope = 'col';
    sampleHeaders.append(heading);
  }
  sampleHead.append(sampleHeaders);
  const sampleList = create('tbody');
  sampleTable.append(sampleHead,sampleList);
  const holdersList = doc.getElementById('top-holders-list');
  panes.holders.append(holderFacts,onchainNote,holderListTitle,sampleTable);
  if (holdersList) panes.holders.append(holdersList);
  if (grids[2]) {
    ['holder_count','top_10_holders_pct'].forEach(key => {
      const row = grids[2].querySelector(`[data-security-value="${key}"]`)?.parentElement;
      if (row) row.hidden = true;
    });
    panes.holders.append(grids[2]);
  }
  if (grids[3]) {
    const activity = create('dl','market-metrics security-metrics-grid');
    for (const key of ['short_term_volume','short_term_price_change','txns_buys_sells_24h','txns_short_term','pair_age_boosts']) {
      const row = grids[3].querySelector(`[data-security-value="${key}"]`)?.parentElement;
      if (row) activity.append(row);
    }
    const supply = grids[3].querySelector('[data-security-value="supply_decimals"]')?.parentElement;
    if (supply) supply.hidden = true;
    const verification = grids[3].querySelector('[data-security-value="verification_status"]')?.parentElement;
    if (verification && grids[1]) grids[1].append(verification);
    panes.liquidity.append(grids[3]); panes.activity.append(activity);
  }
  const reportSources = create('ul','source-notes report-source-notes');
  panes.sources.append(reportSources);
  const badges = doc.getElementById('security-source-badges'); if (badges) panes.sources.append(badges);
  const sourceNotes = create('ul','source-notes'); panes.sources.append(sourceNotes);
  const context = doc.querySelector('.report-context'); if (context) panes.sources.append(context);
  // Retain compatibility with the existing shared data renderer without displaying its long layout.
  [...security.children].filter(el => !el.classList.contains('workspace-pane')).forEach(el => el.hidden = true);
  headings.forEach(el => el.hidden = true);
  doc.getElementById('report-stage').before(nav);
  doc.body.classList.add('workspace-ready');
  let selected = 'warnings'; let initialized = false; let filter = 'all'; let model = warningModel(null); let pending = true;
  const buttons = [];
  function select(key, focus = false) {
    if (!panes[key]) key = 'intelligence';
    const previous = selected;
    const commit = () => {
      selected = key;
      doc.body.dataset.view = key;
      doc.body.style.setProperty('--chapter', '"'+views.find((view)=>view[0]===key)[2]+'"');
      content.scrollTop = 0;
      const panelLabel = doc.querySelector('.report-panel__bar > span:first-child');
      if (panelLabel) panelLabel.textContent = 'TAI / '+views.find(([id]) => id === key)[1].toUpperCase();
      views.forEach(([id], i) => {
        panes[id].hidden = id !== key;
        buttons[i].setAttribute('aria-selected',String(id === key)); buttons[i].tabIndex = id === key ? 0 : -1;
        if (id === key && focus) buttons[i].focus();
      });
      root.history.replaceState(null,'','#'+key);
    };
    if (focus) buttons[views.findIndex(view=>view[0]===key)]?.focus();
    if (initialized && root.ScreenMotion) {
      const direction = views.findIndex(view=>view[0]===key) >= views.findIndex(view=>view[0]===previous) ? 1 : -1;
      root.ScreenMotion.transition(panes[previous],panes[key],commit,direction);
    } else commit();
    initialized = true;
  }
  views.forEach(([key,label,number], i) => {
    const button = create('button','workspace-tab'); button.type = 'button'; button.id = 'tab-'+key;
    button.setAttribute('role','tab'); button.setAttribute('aria-controls','screen-'+key);
    button.append(create('span',null,number),create('strong',null,label),create('i',null,'↗'));
    panes[key].id = key === 'market' ? 'market-report' : 'screen-'+key;
    button.setAttribute('aria-controls',panes[key].id); panes[key].setAttribute('role','tabpanel');
    panes[key].setAttribute('aria-labelledby',button.id); panes[key].tabIndex = 0;
    button.addEventListener('click',() => select(key));
    button.addEventListener('keydown',event => {
      let next;
      if (event.key === 'ArrowRight') next = (i+1)%views.length;
      if (event.key === 'ArrowLeft') next = (i+views.length-1)%views.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = views.length-1;
      if (next !== undefined) { event.preventDefault(); select(views[next][0],true); }
    }); buttons.push(button); nav.append(button);
  });
  const filterButtons = [];
  ['all','critical','warnings','coverage'].forEach(key => {
    const button = create('button',null,{all:'All observations',critical:'Critical / high',warnings:'Warnings',coverage:'Data gaps'}[key]);
    button.type = 'button'; button.addEventListener('click',() => { filter = key; draw(); });
    filterButtons.push([key,button]); filters.append(button);
  });
  function sourceLink(source) {
    const address = encodeURIComponent(root.location.pathname.split('/')[2] || '');
    return {rugcheck:'https://rugcheck.xyz/tokens/'+address,dexscreener:'https://dexscreener.com/solana/'+address,
      dextools:'https://www.dextools.io/',gmgn:'https://gmgn.ai/sol/token/'+address,
      solscan:'https://solscan.io/token/'+address}[source];
  }
  function observation(item) {
    const li = create('li','security-flag-item'); li.dataset.severity = item.severity;
    li.append(create('span',null,item.severity.toUpperCase()));
    const value = flagValue(item.value);
    const body = create('div'); body.append(create('strong',null,item.title+(value ? ' · '+value : '')),create('small',null,item.description || 'No explanation supplied. Verify the observation at its source.'));
    const url = sourceLink(item.source);
    if (url) { const link = create('a','flag-source',item.source.toUpperCase()+' ↗'); link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; body.append(link); }
    else body.append(create('small','flag-source',item.source === 'aggregated' ? 'AGGREGATED / CROSS-SOURCE RULE' : 'SOURCE NOT PROVIDED'));
    li.append(body); return li;
  }
  function draw() {
    level.textContent = pending ? 'READING' : model.level.toUpperCase(); summary.dataset.risk = pending ? 'unknown' : model.level;
    explanation.textContent = pending ? 'Collecting source-backed observations…' : model.explanation;
    coverage.textContent = pending ? 'Provider coverage is being checked.' : model.complete ? '4 / 4 providers responded. Coverage does not guarantee safety.' : `${4-model.missing.length} / 4 providers responded. Incomplete coverage — never interpret missing checks as safe.`;
    const gaps = model.missing.map(name => ({severity:'warn',source:name,title:name.toUpperCase()+' · Data unavailable',description:'This check could not be completed. '+(model.sources[name]?.reason || 'The provider supplied no usable response.').replace(/_/g,' ')}));
    let items = filter === 'coverage' ? gaps : filter === 'critical' ? model.flags.filter(f => ['critical','high'].includes(f.severity)) : filter === 'warnings' ? model.flags.filter(f => ['warn','low'].includes(f.severity)).concat(gaps) : model.flags.concat(gaps);
    filterButtons.forEach(([key,button]) => button.setAttribute('aria-pressed',String(key === filter)));
    count.textContent = pending ? 'Waiting for provider responses' : `${items.length} observations · ${model.flags.length} provider flags · ${model.missing.length} data gaps`;
    list.replaceChildren(...(pending ? [] : items.map(observation)));
    if (!pending && !items.length) list.append(observation({severity:'info',title:'No matching observations',description:'No flags match this view. This is not a safety certification.',source:'aggregated'}));
    sourceNotes.replaceChildren(...providers.map(name => sourceRow(name, model.sources[name], 'Security checks')));
  }
  function sourceRow(name, data, purpose) {
    const status = data?.status || 'unavailable';
    const notes = [];
    if (purpose) notes.push(purpose);
    if (pending) notes.push('Waiting for response.');
    else {
      if (data?.reason) notes.push(data.reason);
      if (data?.updated_at && ['ok','partial','no_data'].includes(status)) {
        notes.push('Retrieved: '+root.TokenAI.formatUpdatedAt(data.updated_at));
      }
    }
    return observation({
      severity: status === 'ok' ? 'info' : 'warn',
      source: name,
      title: sourceNames[name]+' / '+(pending ? 'Checking' : status),
      description: notes.join(' · ') || 'Provider status',
    });
  }
  const overview = create('div','report-overview');
  const overviewSections = [['market','Market'],['warnings','Warnings'],['holders','Holders'],['sources','Sources']];
  const overviewValues = overviewSections.map(([key,label]) => {
    const button = create('button','report-overview-link');
    button.type = 'button';
    const value = create('strong');
    const detail = create('small');
    button.append(create('span',null,label),value,detail);
    button.addEventListener('click',() => select(key,true));
    overview.append(button);
    return {value,detail};
  });
  panes.intelligence.append(overview);
  const formatAmount = new Intl.NumberFormat('en-US',{maximumSignificantDigits: 12});
  const formatShare = new Intl.NumberFormat('en-US',{maximumFractionDigits: 4});
  function holderValue(value, suffix = '') {
    if (value === null) return 'No data';
    if (typeof value === 'boolean') return value ? 'Active' : 'Renounced';
    return (suffix === '%' ? formatShare : formatAmount).format(value) + suffix;
  }
  function renderHolders(holders) {
    holderFacts.replaceChildren(...[
      ['Total supply',holders.supply,''],
      ['Reported holder count',holders.count,''],
      ['Top 10 concentration',holders.top10,'%'],
      ['Mint authority',holders.mint,''],
      ['Freeze authority',holders.freeze,''],
      ['Token decimals',holders.decimals,''],
    ].map(([label,reading,suffix]) => {
      const item = create('div','holder-fact');
      item.append(create('dt',null,label),create('dd',null,holderValue(reading.value,suffix)));
      if (reading.source) item.append(create('small',null,reading.source));
      return item;
    }));
    const mode = holders.sampleBasis === 'total_supply' ? 'Share of total token supply.' :
      holders.sampleBasis === 'provider_percentage' ? 'Uses percentages reported by Solscan.' : '';
    if (pending) onchainNote.textContent = 'Checking on-chain coverage…';
    else if (holders.sampleSize > 0) {
      const count = `${holderValue(holders.sampleSize)} sampled`;
      const total = holders.totalHolders === null ? 'Total holder count unavailable.' : `${holderValue(holders.totalHolders)} reported holders.`;
      onchainNote.textContent = [count+' · '+total, 'Only the first page was checked.', mode, holders.rankedCount > 0 && holders.rankedCount < 10 ? `Holders included in Top 10: ${holders.rankedCount}.` : ''].filter(Boolean).join(' ');
    } else {
      onchainNote.textContent = holders.sampleDescription || 'No Solscan holder sample available. Holder counts and concentration may still be available from security sources.';
    }
    holderListTitle.hidden = !holders.rows.length && !holders.fallbackRows;
    holderListTitle.textContent = holders.rows.length ? 'Solscan holder sample' : 'Security provider holder breakdown';
    sampleTable.hidden = !holders.rows.length;
    sampleList.replaceChildren(...holders.rows.map(row => {
      const item = create('tr');
      const identity = create('td');
      identity.append(create('code',null,row.owner || row.address || 'No data'));
      const amount = create('td',null,holderValue(nonNegative(row.ui_amount)));
      const share = create('td',null,holderValue(nonNegative(row.share_percent,100),'%'));
      item.append(identity,amount,share);
      return item;
    }));
    if (holdersList) holdersList.hidden = !!holders.rows.length || !holders.fallbackRows;
  }
  function renderOverview(result, holders) {
    const market = result?.market_data;
    const sourceStates = [market, result?.onchain_data, ...providers.filter(key => key !== 'dexscreener').map(key => model.sources[key])];
    const responding = sourceStates.filter(source => ['ok','no_data','partial'].includes(source?.status)).length;
    const readings = [
      [root.TokenAI.formatUsd(market?.price_usd), market?.status === 'no_data' ? 'No trading pairs' : 'Price / USD'],
      [model.level.toUpperCase(), 'Observed risk'],
      [holderValue(holders.count.value), 'Reported holder count'],
      [`${responding} / ${sourceStates.length}`, 'Report feeds responded'],
    ];
    overviewValues.forEach(({value,detail},index) => {
      value.textContent = pending ? '—' : readings[index][0];
      detail.textContent = readings[index][1];
    });
  }
  const activityNote = create('p','coverage-note'); panes.activity.prepend(activityNote);
  root.ReportWorkspace = {render(result, loading = false) {
    model = warningModel(result); pending = loading; draw();
    root.TokenLens?.render(result, loading);
    const holders = holderModel(result);
    renderHolders(holders);
    renderOverview(result,holders);
    reportSources.replaceChildren(
      sourceRow('dexscreener',result?.market_data,'Market snapshot'),
      sourceRow('solscan',result?.onchain_data,'Supply and holder sample')
    );
    const gmgn = result?.gmgn_activity;
    activityNote.textContent = loading ? 'Checking trading activity…' : 'GMGN / '+(gmgn?.status || 'unavailable').replace(/_/g,' ').toUpperCase()+
      ' · Sniper count: '+(root.TokenAI.parseMarketNumber(gmgn?.sniper_count) ?? 'No data');
  }, holderModel};
  select(root.location.hash.slice(1)); draw();
  root.addEventListener('hashchange',() => { const key = root.location.hash.slice(1); if (panes[key]) select(key); });
})(typeof window === 'undefined' ? {} : window);
