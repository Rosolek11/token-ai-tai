const {test} = require('node:test');
const assert = require('node:assert/strict');
const {metrics,number} = require('../frontend/token-lens.js');
const find = (result,key) => metrics(result).find(m=>m.key===key);
test('all unavailable metrics stay unknown, not zero or safe',()=>{
  assert.ok(metrics(null).every(m=>m.value===null));
});
test('zero percent remains a real observed zero',()=>{
  assert.equal(find({security_data:{holder_distribution:{bundled_supply_pct:0}}},'bundlers').value,0);
});
test('sniper share is never replaced by a sniper count',()=>{
  assert.equal(find({security_data:{holder_distribution:{sniper_holders_count:12}}},'snipers').value,null);
});
test('mint and blacklist checks invert only explicit booleans',()=>{
  const r={security_data:{authorities:{mint_authority_active:false},verification_and_metadata:{is_blacklisted:false}}};
  assert.equal(find(r,'nomint').value,true);assert.equal(find(r,'blacklist').value,true);
  assert.equal(find({security_data:{authorities:{mint_authority_active:'false'}}},'nomint').value,null);
});
test('sample concentration retains its sample provenance',()=>{
  const m=find({onchain_data:{top_10_share_percent:4.2,sample_description:'10 sampled accounts'}},'top10');
  assert.equal(m.value,4.2);assert.match(m.source,/sample/);assert.equal(m.detail,'10 sampled accounts');
});
test('price changes and risk score never become PnL or rug probabilities',()=>{
  const r={market_data:{price_change_24h_percent:50},security_data:{risk_summary:{risk_score:90}}};
  assert.equal(find(r,'profit').value,null);assert.equal(find(r,'rug').value,null);
});
test('invalid fractions, booleans and infinities are rejected',()=>{
  for(const v of [true,false,'',null,undefined,Infinity,-1]) assert.equal(number(v),null);
  assert.equal(number(101,true),null);assert.equal(number(100,true),100);
});
test('burned and locked LP remain separate observations',()=>{
  const r={security_data:{liquidity_security:{lp_burned_pct:30,lp_locked_pct:20}}};
  assert.equal(find(r,'burned').value,30);assert.equal(find(r,'locked').value,20);
});
test('raw authority permissions are distinct from their inverse checks',()=>{
  const r={security_data:{authorities:{mint_authority_active:false,freeze_authority_active:true}}};
  assert.equal(find(r,'mint_auth').value,false);assert.equal(find(r,'nomint').value,true);
  assert.equal(find(r,'freeze_auth').value,true);
});
test('fresh buying and holding are not inferred from wallet counts',()=>{
  const r={security_data:{holder_distribution:{holder_count:652,sniper_holders_count:19}}};
  assert.equal(find(r,'fresh_buys').value,null);assert.equal(find(r,'fresh_holding').value,null);
  assert.equal(find(r,'sniper_count').value,19);
});
