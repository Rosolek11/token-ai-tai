const {test}=require('node:test');
const assert=require('node:assert/strict');
const {createMotion}=require('../frontend/screen-motion.js');
function node(){const attrs=new Map();return {hasAttribute:k=>attrs.has(k),setAttribute:(k,v)=>attrs.set(k,v),removeAttribute:k=>attrs.delete(k)};}
function harness(){
  let now=0,id=0,phase;const timers=new Map(),animations=[];
  const controller=createMotion({setTimeout:(cb,ms)=>{timers.set(++id,{cb,at:now+ms});return id;},clearTimeout:id=>timers.delete(id),
    animate:(target,frames,options)=>{const a={target,frames,options,cancelled:false,cancel(){this.cancelled=true;}};animations.push(a);return a;},
    visible:()=>true,state:value=>{phase=value;},parts:()=>Array.from({length:12},node),layers:[node(),node(),node()]});
  function tick(ms){const end=now+ms;while(true){const next=[...timers].sort((a,b)=>a[1].at-b[1].at)[0];if(!next||next[1].at>end)break;now=next[1].at;timers.delete(next[0]);next[1].cb();}now=end;}
  return {controller,animations,tick,pending:()=>timers.size,phase:()=>phase};
}
test('exit commits once at 90ms; all layers clear before half a second',()=>{
  const h=harness(),from=node(),to=node();let commits=0;
  h.controller.transition(from,to,()=>commits++);
  assert.equal(h.phase(),'exit');assert.equal(from.hasAttribute('inert'),true);
  h.tick(89);assert.equal(commits,0);
  h.tick(1);assert.equal(commits,1);assert.equal(h.phase(),'enter');assert.equal(from.hasAttribute('inert'),false);
  assert.equal(h.animations.length,11); // exit + pane + bounded six parts + three overlays
  h.tick(400);assert.equal(h.phase(),'idle');assert.equal(h.pending(),0);assert.ok(h.animations.every(a=>a.cancelled));
});
test('rapid navigation never commits a stale intermediate destination',()=>{
  const h=harness(),from=node();const commits=[];
  h.controller.transition(from,node(),()=>commits.push('A'));h.tick(30);
  h.controller.transition(from,node(),()=>commits.push('B'));h.tick(30);
  h.controller.transition(from,node(),()=>commits.push('C'));h.tick(90);
  assert.deepEqual(commits,['C']);h.tick(400);assert.equal(h.pending(),0);
});
test('interrupting an entry cancels all previous transforms',()=>{
  const h=harness();h.controller.transition(node(),node(),()=>{});h.tick(140);
  const previous=[...h.animations];h.controller.transition(node(),node(),()=>{});
  assert.ok(previous.every(a=>a.cancelled));h.tick(490);assert.equal(h.phase(),'idle');
});
test('calm mode commits the pending target immediately and disables choreography',()=>{
  const h=harness(),from=node();let count=0;
  h.controller.transition(from,node(),()=>count++);h.tick(20);h.controller.setFull(false);
  assert.equal(count,1);assert.equal(from.hasAttribute('inert'),false);assert.equal(h.pending(),0);
  const amount=h.animations.length;h.controller.transition(node(),node(),()=>count++);
  assert.equal(count,2);assert.equal(h.animations.length,amount);
});
test('page cleanup removes timers and restores focusability without navigation',()=>{
  const h=harness(),from=node();let commits=0;
  h.controller.transition(from,node(),()=>commits++);h.controller.cancel();h.tick(2000);
  assert.equal(commits,0);assert.equal(h.pending(),0);assert.equal(from.hasAttribute('inert'),false);
});
test('same screen selection cancels pending navigation without playing an exit',()=>{
  const h=harness(),from=node();const commits=[];
  h.controller.transition(from,node(),()=>commits.push('stale'));h.tick(20);
  h.controller.transition(from,from,()=>commits.push('current'));h.tick(1000);
  assert.deepEqual(commits,['current']);assert.equal(h.phase(),'idle');
});
test('pre-existing inert state is preserved',()=>{
  const h=harness(),from=node();from.setAttribute('inert','');
  h.controller.transition(from,node(),()=>{});h.controller.cancel();assert.equal(from.hasAttribute('inert'),true);
});
test('missing Web Animations support degrades to immediate navigation',()=>{
  let commits=0;
  const controller=createMotion({setTimeout,clearTimeout,animate(){throw Error('unsupported');},visible:()=>true,state(){},parts:()=>[],layers:[]});
  const from=node();controller.transition(from,node(),()=>commits++);
  assert.equal(commits,1);assert.equal(from.hasAttribute('inert'),false);
});
