const test = require('node:test');
const assert = require('node:assert/strict');
const {warningModel,flagValue,activityWindowRows,analysisFactLinks,uncertaintyModel,aiSummary} = require('../frontend/report-workspace.js');
const sources = Object.fromEntries(['rugcheck','dexscreener','dextools','gmgn'].map(key => [key,{status:'ok'}]));
test('warning titles omit raw account payloads but retain meaningful scalar values',()=>{
  assert.equal(flagValue('x'.repeat(1000)), '');
  assert.equal(flagValue({data:'raw account'}), '');
  assert.equal(flagValue(0),'0');
  assert.equal(flagValue(false),'Disabled');
  assert.equal(flagValue(79.7633),'79.76');
});
test('missing security is unknown, with four explicit data gaps', () => {
  const model = warningModel({}); assert.equal(model.level,'unknown'); assert.equal(model.missing.length,4); assert.equal(model.complete,false);
});
test('market data alone never produces a low-risk audit verdict', () => {
  const model = warningModel({security_data:{sources:{dexscreener:{status:'ok'}},risk_summary:{risk_level:'low'}}});
  assert.equal(model.level,'unknown'); assert.equal(model.missing.length,3);
});
test('known audit risk preserves provider explanation and complete coverage', () => {
  const model = warningModel({security_data:{sources,risk_summary:{risk_level:'critical',verdict_summary:'Mint authority active'}}});
  assert.equal(model.level,'critical'); assert.equal(model.explanation,'Mint authority active'); assert.equal(model.complete,true);
});
test('partial coverage never suppresses an observed high risk', () => {
  const model = warningModel({security_data:{sources:{rugcheck:{status:'ok'}},risk_summary:{risk_level:'high'}}});
  assert.equal(model.level,'high'); assert.equal(model.complete,false);
});
test('flags are sorted by severity without mutating the API response', () => {
  const flags = [{severity:'ok',source:'rugcheck'},{severity:'critical',source:'gmgn'},{severity:'warn',source:'aggregated'}];
  assert.deepEqual(warningModel({security_data:{flags}}).flags.map(f=>f.severity),['critical','warn','ok']); assert.equal(flags[0].severity,'ok');
});
test('unknown severity and source are not trusted as successful checks', () => {
  const model = warningModel({security_data:{flags:[{severity:'bogus',source:'javascript:alert(1)'}]}});
  assert.equal(model.flags[0].source,'unknown'); assert.equal(model.flags[0].severity,'info');
});
test('a refresh failure clears previous flags and verdict', () => {
  warningModel({security_data:{sources,flags:[{severity:'high'}],risk_summary:{risk_level:'high'}}});
  const model = warningModel(null); assert.equal(model.level,'unknown'); assert.deepEqual(model.flags,[]);
});
test('no-data sources count as missing evidence even with no flags', () => {
  const model = warningModel({security_data:{sources:{rugcheck:{status:'no_data'}},flags:[]}});
  assert.equal(model.complete,false); assert.equal(model.level,'unknown');
});
test('activity windows preserve real zeros and keep each missing field explicit', () => {
  const rows = activityWindowRows({buys_5m:0,sells_5m:null,volume_5m_usd:0,buys_24h:8}, value => `$${value}`);
  assert.deepEqual(rows[0],{window:'5m',buys:'0',sells:'No data',volume:'$0'});
  assert.deepEqual(rows[3],{window:'24h',buys:'8',sells:'No data',volume:'No data'});
});
test('AI fact citations only include available values and verified HTTPS links', () => {
  const facts = analysisFactLinks({price:{price_usd:{value:1,sourceId:'dexscreener',url:'https://example.test/fact',timestamp:'now'},price_native_sol:{value:null,sourceId:'dexscreener',url:'https://example.test'}},flags:{'gmgn:test':{value:true,sourceId:'gmgn',url:'javascript:alert(1)'}}});
  assert.equal(facts.length,2);
  assert.equal(facts[0].url,'https://example.test/fact');
  assert.equal(facts[1].url,null);
});

test('evidence separates incomplete feeds, conflicting observations, and real zero values', () => {
  const model = uncertaintyModel({
    market_data: {status:'ok',liquidity_usd:0},
    onchain_data: {status:'partial',total_supply:100,metadata:{mint_authority:'So11111111111111111111111111111111111111112'}},
    security_data: {
      sources: {rugcheck:{status:'ok'},dextools:{status:'ok'},gmgn:{status:'ok'}},
      market_activity: {total_supply:105},
      flags: [
        {source:'dextools',code:'dextools_honeypot',value:false},
        {source:'gmgn',code:'gmgn_honeypot',value:true},
        {source:'rugcheck',code:'mint_authority',value:'Renounced'},
        {source:'rugcheck',code:'freeze_authority',value:'Renounced'},
      ],
    },
  });
  assert.equal(model.confidence,'limited');
  assert.deepEqual(model.gaps,[['GMGN activity',undefined],['Solscan','partial']]);
  assert.deepEqual(model.conflicts.map(item => item.label),['Honeypot status','Mint authority','Total supply']);
  assert.deepEqual(model.conflicts[0].readings.map(item => item.value),[false,true]);
  assert.equal(model.facts[0].value,0);
  assert.equal(uncertaintyModel({market_data:{status:'no_data'}}).confidence,'unknown');
});

test('only validated completed output supplies an AI score or conclusion', () => {
  const completed = {status:'completed',score:0,summary:'Observed data'};
  assert.deepEqual(aiSummary(completed),{score:0,analysis:'Observed data'});
  assert.equal(aiSummary({...completed,status:'timeout'}),null);
  assert.equal(aiSummary({...completed,rejected:true}),null);
  assert.equal(aiSummary({...completed,score:null}),null);
});
