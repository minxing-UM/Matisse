// Verify the actual demo controller, especially tier resets and stale replies.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app/frontend/demo.js', 'utf8');

function harness() {
  const nodes = new Map();
  const listeners = new Map();
  const element = () => ({
    value: '', textContent: '', disabled: false, hidden: false, style: {}, children: [], events: {},
    focus() {}, setAttribute() {}, append(...items) { this.children.push(...items); },
    replaceChildren(...items) { this.children = items; },
    addEventListener(name, callback) { this.events[name] = callback; },
    classList: { add() {}, remove() {} }
  });
  const node = (selector) => { if (!nodes.has(selector)) nodes.set(selector, element()); return nodes.get(selector); };
  let selected = null;
  node('#tier-form').querySelector = (selector) => selector.includes(':checked') ? (selected ? { value: selected } : null) : node('#tier-first');
  node('#tier-form').reset = () => { selected = null; node('#tier-password').value = ''; };
  const discarded = [];
  const requests = [];
  const context = vm.createContext({
    document: { querySelector: node, createElement: element },
    window: { addEventListener: (name, callback) => listeners.set(name, callback) },
    navigator: { sendBeacon: (url, blob) => { discarded.push({ url, blob }); return true; } },
    Blob, console,
    fetch: async (url, options) => {
      requests.push({ url, body: JSON.parse(options.body) });
      return { ok: true, json: async () => ({ mode: 'demo' }) };
    }
  });
  vm.runInContext(source, context);
  return { node, context, listeners, discarded, requests, select: (tier) => { selected = tier; }, run: (code) => vm.runInContext(code, context) };
}

const mood = { label: 'calm', current: { happiness: 20, sadness: 0 }, delta: { happiness: 0, sadness: 0 } };
const chat = (tier = 'T3', id = 'demo_test') => ({ id, tier, tier_label: '初次认识', messages: [], mood: structuredClone(mood) });
const submit = '({preventDefault() {}})';

async function main() {
  const h = harness();
  await new Promise(setImmediate);
  assert.equal(h.requests.length, 1);
  assert.equal(h.requests[0].url, '/api/demo/enter');
  assert.equal(h.node('#tier-start').disabled, true);
  assert.equal(h.node('#demo-input').disabled, true);
  await h.run(`startDemo${submit}`);
  assert.equal(h.requests.length, 1);
  console.log('PASS: no implicit tier or conversation; initial requests use only the demo API.');

  h.select('T0'); h.node('#tier-options').events.change();
  assert.equal(h.node('#tier-password-wrap').hidden, false);
  assert.equal(h.node('#tier-password').required, true);
  assert.equal(h.node('#tier-form').events.change, undefined);
  h.node('#tier-password').value = 'wrong';
  h.context.requestStub = async (url, body) => { h.context.sent = body; throw new Error('密码不正确'); };
  h.run('demoRequest = (...args) => requestStub(...args)');
  await h.run(`startDemo${submit}`);
  assert.equal(h.run('demoChat'), null);
  assert.equal(h.node('#tier-password').value, '');
  assert.equal(h.node('#tier-error').textContent, '密码不正确');
  h.context.requestStub = async (url, body) => { h.context.sent = body; return chat('T0'); };
  h.node('#tier-password').value = '0423';
  await h.run(`startDemo${submit}`);
  assert.equal(h.context.sent.password, '0423');
  assert.equal(h.node('#tier-password').value, '');
  assert.equal(h.node('#demo-workspace').hidden, false);
  assert.equal(h.node('#tier-picker').hidden, true);
  h.run('newDemo()');
  assert.equal(h.run('selectedTier()'), null);
  assert.equal(h.node('#tier-start').disabled, true);
  assert.equal(h.node('#tier-password-wrap').hidden, true);
  assert.equal(h.node('#demo-workspace').hidden, true);
  assert.equal(h.discarded.length, 1);
  console.log('PASS: T0 requires a password, failures remain at selection, and a new chat clears the tier and password.');

  h.context.requestStub = async () => chat();
  h.select('T3'); h.run('updateTierChoice()');
  await h.run(`startDemo${submit}`);
  let finishReply;
  h.context.requestStub = () => new Promise((resolve) => { finishReply = resolve; });
  h.node('#demo-input').value = '你好';
  const sending = h.run(`sendDemoMessage${submit}`);
  assert.equal(h.node('#demo-new').disabled, true);
  assert.equal(h.node('#demo-input').disabled, true);
  assert.equal(h.run('demoChat.messages.length'), 0);
  h.listeners.get('pagehide')();
  h.listeners.get('pageshow')({ persisted: true });
  finishReply({ ...chat(), messages: [{ role: 'assistant', content: '迟到的回复' }] });
  await sending;
  assert.equal(h.run('demoChat'), null);
  assert.equal(h.node('#demo-workspace').hidden, true);
  assert.equal(h.run('selectedTier()'), null);
  console.log('PASS: navigating back requires a fresh tier; a late answer cannot restore a previous demo.');

  h.context.requestStub = async () => chat();
  h.select('T3'); h.run('updateTierChoice()'); await h.run(`startDemo${submit}`);
  h.context.requestStub = async () => { throw new Error('网络错误'); };
  h.node('#demo-input').value = '重试消息';
  await h.run(`sendDemoMessage${submit}`);
  assert.equal(h.node('#demo-input').value, '重试消息');
  assert.equal(h.run('demoChat.messages.length'), 0);
  assert.equal(h.node('#demo-input').disabled, false);
  console.log('PASS: a failed reply preserves the draft for retry and restores the composer.');
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
