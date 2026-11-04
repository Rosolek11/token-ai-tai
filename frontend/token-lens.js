/* Research lenses: every number retains its source and its original meaning. */
(function(root) {
  function number(value, percent = false) {
    if (typeof value !== 'number' && typeof value !== 'string') return null;
    if (typeof value === 'string' && !value.trim()) return null;
    const n = Number(value);
    return Number.isFinite(n) && n >= 0 && (!percent || n <= 100) ? n : null;
  }
  function metrics(result) {
    const sec = result?.security_data || {}, h = sec.holder_distribution || {};
    const a = sec.authorities || {}, l = sec.liquidity_security || {}, v = sec.verification_and_metadata || {};
    const chain = result?.onchain_data || {};
    const metric = (key,label,value,unit,detail,source = 'Security aggregation') => ({key,label,value,unit,detail,source});
    const pct = (key,label,value,detail) => metric(key,label,number(value,true),'%',detail);
    const bool = value => typeof value === 'boolean' ? value : null;
    const top = number(h.top_10_holders_pct,true);
    return [
      metric('top10','Top 10',top ?? number(chain.top_10_share_percent,true),'%',top !== null ? 'Share of supply held by the ten largest wallets.' : (chain.sample_description || 'Bounded holder sample; not necessarily global concentration.'),top !== null ? 'Security aggregation' : 'Solscan holder sample'),
      pct('dev','Dev holdings',h.creator_balance_pct,'Creator-held supply, not all wallets controlled by the developer.'),
      metric('holders','Holders',number(h.holder_count) ?? number(chain.holder_count),'', 'Provider-reported holder count; account and owner definitions may differ.',number(h.holder_count) !== null ? 'Security aggregation' : 'Solscan'),
      pct('snipers','Snipers',h.sniper_supply_pct,'Share of supply attributed to snipers. Not sniper wallet count.'),
      pct('insiders','Insiders',h.insider_supply_pct,'Provider-labelled insider supply; methods can differ from Axiom.'),
      pct('bundlers','Bundlers',h.bundled_supply_pct,'Provider-reported bundled supply. Not the Axiom bundle algorithm.'),
      metric('phishing','Phishing',null,'%', 'No documented phishing-wallet classifier is connected.','Not connected'),
      metric('pro','Pro traders',null,'','Requires a provider-defined professional-trader classification.','Not connected'),
      metric('nomint','No mint',bool(a.mint_authority_active) === null ? null : !a.mint_authority_active,'bool','True means mint authority is disabled, not that the token is safe.'),
      metric('blacklist','No blacklist',bool(v.is_blacklisted) === null ? null : !v.is_blacklisted,'bool','A provider blacklist check, not proof of unrestricted transferability.'),
      metric('lp','Total LP',number(l.total_market_liquidity_usd),'USD','Total reported DEX liquidity across pools.'),
      pct('burned','LP burned',l.lp_burned_pct,'Burned liquidity-provider tokens. Different from locked liquidity.'),
      pct('locked','LP locked',l.lp_locked_pct,'Reported locked LP share; not automatically added to burned LP.'),
      metric('rug','Rug %',null,'%', 'No calibrated rug probability exists. A risk score is not a probability.','Not connected'),
      metric('profit','Holders in profit',null,'%', 'Needs current holders, acquisition cost, transfer treatment and a price snapshot. Price change is not holder PnL.','Cost-basis index required'),
      metric('sniper_count','Snipers / wallets',number(h.sniper_holders_count),'','Number of sniper wallets, separate from their held supply percentage.'),
      metric('fresh_buys','Fresh buys',null,'','Needs an agreed time window and fresh-wallet buy classification. Not the number of fresh holders.','Provider definition required'),
      metric('fresh_holding','Fresh holding',null,'%', 'Share of token supply held by fresh wallets. A fresh-wallet count ratio cannot substitute for this.','Provider definition required'),
      metric('mint_auth','Mint Auth.',bool(a.mint_authority_active),'bool','Yes means an active mint authority; No means disabled or renounced.'),
      metric('freeze_auth','Freeze Auth.',bool(a.freeze_authority_active),'bool','Yes means an active freeze authority; No means disabled or renounced.'),
    ];
  }
  if (typeof module !== 'undefined') module.exports = {metrics,number};
  if (!root.document) return;
  const doc = root.document, deck = doc.getElementById('screen-intelligence'), map = doc.getElementById('screen-map');
  if (!deck || !map) return;
  const el = (tag,cls,text) => {const n=doc.createElement(tag);if(cls)n.className=cls;if(text !== undefined)n.textContent=text;return n;};
  deck.querySelector('h2').textContent = 'Behind the token.';
  const intro = el('div','lens-masthead');
  intro.append(el('span','lens-coordinate','SUPPLY DISTRIBUTION / SOURCE SNAPSHOT'),el('p',null,'Follow the concentration. Question the signal.'),el('small',null,'Source-backed telemetry · no simulated metrics · no wallet connection'));
  deck.append(intro);
  const body = el('div','lens-body'); const hero = el('div','lens-hero');
  const ring = el('div','lens-ring'); const ringValue = el('strong',null,'—'); ring.append(el('small',null,'TOP 10 / SUPPLY'),ringValue,el('span',null,'CONCENTRATION'));
  const annotation = el('p','lens-annotation');
  hero.append(ring,annotation); const rail = el('dl','lens-rail');body.append(hero,rail);deck.append(body);
  const remaining = el('dl','lens-ledger'); doc.getElementById('screen-metrics').append(remaining);
  const nativePanel = el('section','lens-native');
  nativePanel.append(el('h3',null,'LOCAL / CHAIN CALCULATIONS'));
  const nativeButton = el('button','bubble-launch','Calculate from Solana ↗'); nativeButton.type='button';
  const nativeStatus = el('p','lens-annotation','Independent of paid analytics APIs. Uses your configured Solana RPC.');nativeStatus.setAttribute('role','status');
  const nativeValues = el('dl','lens-ledger');nativePanel.append(nativeButton,nativeStatus,nativeValues);doc.getElementById('screen-local').append(nativePanel);
  const method = el('p','lens-method','Axiom-style categories, not Axiom-sourced data. Provider definitions are not interchangeable. Unknown never means 0 or safe.'); doc.getElementById('screen-metrics').append(method);
  const listing = el('div','lens-listing'); doc.getElementById('screen-metrics').append(listing);
  const integration = el('div','lens-integration');
  integration.append(el('strong',null,'AXIOM / ACCESS NOT VERIFIED'),el('p',null,'No public data API or API-key creation flow was found in the official documentation reviewed. Ask Axiom support for authorized read-only data access. We do not use session cookies or unofficial SDKs.'));
  const docs = el('a',null,'Axiom documentation ↗');docs.href='https://docs.axiom.trade/';docs.target='_blank';docs.rel='noopener noreferrer';integration.append(docs);doc.getElementById('screen-sources').append(integration);
  map.querySelector('h2').textContent = 'Trace the connections.';
  map.append(el('p','lens-method','Real holder-transfer connections from Bubblemaps. Node proximity does not prove common ownership. No synthetic connections are drawn.'));
  const mapHost = el('div','bubble-host'); const load = el('button','bubble-launch','Load interactive map ↗');load.type='button';
  const mapState = el('p','lens-annotation','External widget · loads only when requested. Demo requires localhost; production requires a registered Partner ID.');
  mapHost.append(el('span','bubble-monogram','◎'),load,mapState);map.append(mapHost);
  const fallback = el('a','lens-external','Open independently in Bubblemaps ↗');
  const address = root.location.pathname.split('/')[2] || '';
  fallback.href = 'https://v2.bubblemaps.io/map?chain=solana&address='+encodeURIComponent(address);fallback.target='_blank';fallback.rel='noopener noreferrer';map.append(fallback);
  load.addEventListener('click',async () => {
    load.disabled=true;
    try {
      if (!root.TokenAI.isSolanaAddress(address)) throw new Error('A valid Solana address is required.');
      const config=await root.TokenAI.requestJson('/api/research-config');
      const partner=config.bubblemapsPartnerId;
      if (!partner || (partner === 'demo' && !['localhost','0.0.0.0'].includes(root.location.hostname))) throw new Error('Use http://localhost:8000 for demo maps, or configure a registered BUBBLEMAPS_PARTNER_ID.');
      const frame=el('iframe','bubble-frame');frame.title='Bubblemaps holder-transfer network';frame.referrerPolicy='strict-origin-when-cross-origin';
      frame.src='https://iframe.bubblemaps.io/map?chain=solana&address='+encodeURIComponent(address)+'&partnerId='+encodeURIComponent(partner);
      frame.allow='clipboard-write';mapHost.replaceChildren(frame);
      // The cross-origin provider owns its loading/error display; keep an independent fallback link.
    } catch(error) {mapState.textContent=error.message;load.disabled=false;}
  });
  function display(metric) {
    if (metric.value === null) return '—';
    if (metric.unit === 'bool') return metric.value ? 'Yes' : 'No';
    if (metric.unit === 'USD') return root.TokenAI.formatUsd(metric.value);
    return new Intl.NumberFormat('en-US',{maximumFractionDigits:2}).format(metric.value)+metric.unit;
  }
  function row(metric,index) {
    const node=el('div','lens-reading');node.dataset.known=String(metric.value !== null);
    node.dataset.unit=metric.unit;
    node.append(el('dt',null,String(index+1).padStart(2,'0')+' / '+metric.label),el('dd',null,display(metric)));
    const source=el('small',null,metric.source+(metric.value === null ? ' · No data':' · Observed'));
    node.append(source);node.title=metric.detail;
    const detail=el('p','lens-detail',metric.detail);node.append(detail);return node;
  }
  let generation=0;
  async function calculateNative(revision = generation) {
    nativeButton.disabled=true;nativeValues.replaceChildren();nativeStatus.textContent='Reading finalized mint state and the largest token accounts…';
    try {
      if (!root.TokenAI.isSolanaAddress(address)) throw new Error('Invalid Solana address.');
      const base=await root.TokenAI.apiBase();
      const raw=await root.TokenAI.requestJson(base+'/api/tokens/'+encodeURIComponent(address)+'/local-research');
      if (revision !== generation) return;
      nativeStatus.textContent=(raw.status || 'unavailable').toUpperCase()+' / '+raw.methodology+' / '+(raw.reason || 'Locally calculated from RPC facts.');
      const fact=(key,label,value,unit,detail)=>({key,label,value,unit,detail,source:'Local math / Solana RPC'});
      nativeValues.replaceChildren(...[
        fact('accounts','Top 10 token accounts',number(raw.top10_accounts_pct,true),'%','Accounts, not owners. Includes pool vaults; at most 20 accounts sampled.'),
        fact('sample','Sample accounts',number(raw.sample_accounts),'','Does not represent total holder count.'),
        fact('mint','Mint Auth.',typeof raw.mint_authority_active === 'boolean' ? raw.mint_authority_active : null,'bool','Active mint permission from parsed on-chain mint state.'),
        fact('freeze','Freeze Auth.',typeof raw.freeze_authority_active === 'boolean' ? raw.freeze_authority_active : null,'bool','Active freeze permission from parsed on-chain mint state.'),
      ].map(row));
    } catch(error) {if(revision === generation)nativeStatus.textContent='LOCAL DATA UNAVAILABLE / '+error.message+' A working RPC endpoint may be required; missing data is not zero.';}
    finally {if(revision === generation)nativeButton.disabled=false;}
  }
  nativeButton.addEventListener('click',()=>calculateNative());
  root.TokenLens={render(result,loading=false) {
    const revision=++generation;
    nativeButton.disabled=loading;nativeValues.replaceChildren();nativeStatus.textContent='Independent Solana calculations. No provider metrics copied.';
    const data=metrics(result);const top=data[0];
    ringValue.textContent=display(top);ring.style.setProperty('--concentration',(top.value ?? 0)+'%');ring.dataset.known=String(top.value !== null);
    annotation.textContent=top.value === null ? 'Concentration unavailable. No distribution is inferred.' : top.source+' / '+top.detail;
    rail.replaceChildren(...data.slice(1,6).map((m,i)=>row(m,i+1)));
    remaining.replaceChildren(...data.map(row));
    listing.textContent=loading ? 'DEX PROFILE / Checking source…' : 'DEX PROFILE / No result yet';
    if (!result || loading) return;
    if (top.value === null) calculateNative(revision);
    root.TokenAI.apiBase().then(base=>root.TokenAI.requestJson(base+'/api/tokens/'+encodeURIComponent(address)+'/listing')).then(data=>{
      if (revision !== generation) return;
      listing.replaceChildren(el('small',null,'DEX SCREENER / PROFILE ORDERS'),el('strong',null,data.dex_paid === true ? 'Approved profile' : data.dex_paid === false ? 'No approved profile' : 'Unknown'),el('p',null,'Historical approved tokenProfile order. Ads and boosts do not count; not a safety check. Retrieved: '+root.TokenAI.formatUpdatedAt(data.updated_at)));
    }).catch(()=>{if(revision===generation)listing.textContent='DEX PROFILE / Source unavailable — payment status unknown';});
  }};
})(typeof window === 'undefined' ? {} : window);
