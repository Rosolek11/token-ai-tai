const test = require('node:test');
const assert = require('node:assert/strict');
const {warningModel,flagValue} = require('../frontend/report-workspace.js');
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
