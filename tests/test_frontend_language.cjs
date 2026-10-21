// Exercise the real localization engine, including protected user text.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const catalog = JSON.parse(fs.readFileSync('app/frontend/translations.json', 'utf8'));

function harness(initialLanguage = 'zh') {
  const elements = [];
  const textNodes = [];
  function element(tag = 'DIV', protectedContent = false, attributes = {}) {
    const node = {
      tagName: tag, protectedContent, attributes, value: '', disabled: false,
      closest(selector) { return this.protectedContent || (tag === 'TEXTAREA' && selector.includes('textarea')) ? this : null; },
      querySelectorAll() { return elements.filter((entry) => entry !== this); },
      getAttribute(name) { return Object.hasOwn(this.attributes, name) ? this.attributes[name] : null; },
      setAttribute(name, value) { this.attributes[name] = value; },
      removeAttribute(name) { delete this.attributes[name]; },
      addEventListener() {}
    };
    elements.push(node); return node;
  }
  function text(data, parentElement = element()) { const node = { data, parentElement }; textNodes.push(node); return node; }
  const body = element('BODY');
  const select = element('SELECT', false, { 'aria-label': '界面与回复语言' });
  const label = text('  新对话\n');
  const status = text('以 T3 开始对话 →');
  const message = text('删除', element('DIV', true));
  const memory = text('New chat', element('P', true));
  const customTrait = text('开心', element('BUTTON', true));
  const textarea = element('TEXTAREA', false, { placeholder: '给 Matisse 发消息…', 'aria-label': '消息内容' });
  textarea.value = '正在编辑的中文草稿';
  const textareaText = text('用户输入的文字', textarea);
  const store = new Map();
  const events = [];
  const alerts = [];
  let serverLanguage = initialLanguage;
  let failSave = false;
  const requests = [];
  const window = { dispatchEvent(event) { events.push(event); }, addEventListener() {}, alert(message) { alerts.push(message); } };
  const document = {
    body, title: 'Matisse · 工作演示版', documentElement: { lang: 'zh-CN' },
    querySelector: () => select,
    createTreeWalker() { let index = 0; return { nextNode: () => textNodes[index++] || null }; }
  };
  const context = vm.createContext({
    window, document, NodeFilter: { SHOW_TEXT: 4 },
    localStorage: { getItem: (key) => store.get(key) || null, setItem: (key, value) => store.set(key, value) },
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
    fetch: async (url, options) => {
      requests.push({ url, options });
      if (url === '/static/translations.json') return { ok: true, json: async () => catalog };
      if (options?.method === 'POST') {
        if (failSave) return { ok: false, json: async () => ({ error: '语言切换失败，请重试。' }) };
        serverLanguage = JSON.parse(options.body).language;
      }
      return { ok: true, json: async () => ({ language: serverLanguage }) };
    }
  });
  vm.runInContext(fs.readFileSync('app/frontend/i18n.js', 'utf8'), context);
  return { api: window.MatisseI18n, document, label, status, message, memory, customTrait, textarea, textareaText, select, requests, alerts, events, store, fail: () => { failSave = true; } };
}

async function main() {
  const h = harness();
  await h.api.ready;
  await h.api.setLanguage('en');
  assert.equal(h.api.language, 'en');
  assert.equal(h.document.documentElement.lang, 'en');
  assert.equal(h.document.title, 'Matisse · Work demo');
  assert.equal(h.label.data, '  New chat\n');
  assert.equal(h.status.data, 'Start a T3 conversation →');
  assert.equal(h.select.attributes['aria-label'], 'Interface and reply language');
  assert.equal(h.textarea.attributes.placeholder, 'Message Matisse…');
  assert.equal(h.textarea.value, '正在编辑的中文草稿');
  assert.equal(h.textareaText.data, '用户输入的文字');
  assert.equal(h.message.data, '删除');
  assert.equal(h.memory.data, 'New chat');
  assert.equal(h.customTrait.data, '开心');
  const save = h.requests.find((request) => request.options?.method === 'POST');
  assert.equal(save.url, '/api/language');
  assert.equal(JSON.parse(save.options.body).language, 'en');
  console.log('PASS: the selector saves the shared language and translates UI, labels and placeholders without changing user content.');

  assert.equal(h.api.t('已添加「{name}」，点击标签即可启用。', { name: '我自己的性格' }), 'Added “我自己的性格”. Select the trait to enable it.');
  assert.equal(h.api.t('以 {tier} 开始对话 →', { tier: 'T2' }), 'Start a T2 conversation →');
  await h.api.setLanguage('zh');
  assert.equal(h.label.data, '  新对话\n');
  assert.equal(h.status.data, '以 T3 开始对话 →');
  assert.equal(h.textarea.attributes.placeholder, '给 Matisse 发消息…');
  assert.equal(h.api.t('Start a T2 conversation →'), '以 T2 开始对话 →');
  assert.equal(h.document.title, 'Matisse · 工作演示版');
  console.log('PASS: dynamic labels round-trip between languages and preserve template values.');

  const persisted = harness('en');
  await persisted.api.ready;
  assert.equal(persisted.api.language, 'en');
  assert.equal(persisted.select.value, 'en');
  assert.equal(persisted.label.data, '  New chat\n');
  persisted.fail();
  await persisted.api.setLanguage('zh');
  assert.equal(persisted.api.language, 'en');
  assert.equal(persisted.select.value, 'en');
  assert.equal(persisted.select.disabled, false);
  assert.equal(persisted.alerts.length, 1);
  console.log('PASS: reload uses the persisted preference; failed saves keep the interface and reply language aligned.');
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
