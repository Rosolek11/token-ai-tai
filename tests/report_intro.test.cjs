const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../frontend/report-intro.js'), 'utf8');
const address = 'So11111111111111111111111111111111111111112';

function node() {
  const classes = new Set();
  return { hidden: false, textContent: '', attributes: {}, offsetWidth: 1440,
    classList: { add: value => classes.add(value), remove: value => classes.delete(value), contains: value => classes.has(value) },
    setAttribute(name, value) { this.attributes[name] = value; },
    removeAttribute(name) { delete this.attributes[name]; },
  };
}
function intro(pathname = '/token/' + address) {
  let now = 0;
  let nextId = 0;
  const timers = new Map();
  const elements = { 'report-intro': node(), 'report-app': node(), 'intro-address': node() };
  const body = node();
  const events = {};
  const context = {
    document: { body, getElementById: name => elements[name] }, location: { pathname },
    setTimeout(callback, delay) { const id = ++nextId; timers.set(id, {callback, at:now + delay}); return id; },
    clearTimeout(id) { timers.delete(id); },
    addEventListener(name, callback) { events[name] = callback; },
  };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(source, context);
  return { elements, body, events, api: context.ReportIntro,
    advance(ms) {
      now += ms;
      for (const [id, timer] of [...timers]) {
        if (timer.at <= now) { timers.delete(id); timer.callback(); }
      }
    },
    pending: () => timers.size,
  };
}

test('introduction covers the report and blocks underlying keyboard interaction', () => {
  const current = intro();
  assert.equal(current.elements['report-intro'].hidden, false);
  assert.equal(current.elements['report-intro'].classList.contains('is-running'), true);
  assert.equal(current.elements['report-app'].attributes.inert, '');
  assert.equal(current.body.classList.contains('intro-active'), true);
  assert.equal(current.elements['intro-address'].textContent, address);
});
test('the full-screen introduction remains present until exactly three seconds', () => {
  const current = intro();
  current.advance(2999);
  assert.equal(current.elements['report-intro'].hidden, false);
  assert.equal(current.elements['report-app'].attributes.inert, '');
  current.advance(1);
  assert.equal(current.elements['report-intro'].hidden, true);
  assert.equal('inert' in current.elements['report-app'].attributes, false);
  assert.equal(current.body.classList.contains('intro-active'), false);
  assert.equal(current.pending(), 0);
});
test('leaving the page removes scroll and focus locks before browser caching', () => {
  const current = intro();
  current.advance(700);
  current.events.pagehide();
  assert.equal(current.elements['report-intro'].hidden, true);
  assert.equal('inert' in current.elements['report-app'].attributes, false);
  assert.equal(current.pending(), 0);
});
test('returning to a cached report replays the full introduction', () => {
  const current = intro();
  current.advance(3000);
  current.events.pagehide();
  current.events.pageshow({persisted:true});
  current.advance(2999);
  assert.equal(current.elements['report-intro'].hidden, false);
  current.advance(1);
  assert.equal(current.elements['report-intro'].hidden, true);
});
test('a normal pageshow event does not restart the introduction clock', () => {
  const current = intro();
  current.advance(1000);
  current.events.pageshow({persisted:false});
  current.advance(2000);
  assert.equal(current.elements['report-intro'].hidden, true);
});
test('restarting cancels the previous timer rather than closing too early', () => {
  const current = intro();
  current.advance(2000);
  current.api.start();
  assert.equal(current.pending(), 1);
  current.advance(1000);
  assert.equal(current.elements['report-intro'].hidden, false);
  current.advance(2000);
  assert.equal(current.elements['report-intro'].hidden, true);
});
test('malformed URL encoding cannot leave the page permanently covered', () => {
  const current = intro('/token/%E0%A4');
  assert.equal(current.elements['intro-address'].textContent, 'SOLANA NETWORK');
  current.advance(3000);
  assert.equal(current.elements['report-intro'].hidden, true);
});
