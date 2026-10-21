// Drive the actual character editor with a fake server and user input.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const flush = () => new Promise(setImmediate);

function harness({ required = false, content = '# My character\n喜欢天文学。' } = {}) {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      hidden: id.includes('dialog') || id.includes('backdrop'), value: '', textContent: '', disabled: false,
      handlers: {}, focused: false,
      addEventListener(name, handler) { this.handlers[name] = handler; },
      focus() { this.focused = true; }
    });
    if (id === '#personality-content' && !elements.get(id).normalizesNewlines) {
      let currentValue = '';
      Object.defineProperty(elements.get(id), 'value', { get() { return currentValue; }, set(value) { currentValue = value.replace(/\r\n?/g, '\n'); } });
      elements.get(id).normalizesNewlines = true;
    }
    return elements.get(id);
  }
  let data = { required, content, revision: 'revision-one', configured: Boolean(content.trim()), active_configured: Boolean(content.trim()), restart_required: false };
  let failSave = false;
  let confirmResult = false;
  const requests = [];
  let settingsClosed = false;
  const context = {
    document: { querySelector: element },
    window: {
      MatisseI18n: { ready: Promise.resolve(), t: (source) => source },
      setSettingsOpen(value) { settingsClosed = !value; },
      confirm() { return confirmResult; }
    },
    fetch: async (url, options) => {
      requests.push({ url, options });
      if (options?.method === 'POST') {
        if (failSave) return { ok: false, json: async () => ({ error: 'The personality file changed. Reload it before saving.' }) };
        const body = JSON.parse(options.body);
        assert.equal(body.revision, data.revision);
        data = { ...data, content: body.content, configured: true, restart_required: true, revision: 'revision-two' };
      }
      return { ok: true, json: async () => ({ ...data }) };
    },
    Promise, Error
  };
  vm.runInNewContext(fs.readFileSync('app/frontend/personality.js', 'utf8'), context);
  return {
    element, requests, get settingsClosed() { return settingsClosed; },
    setServer(value) { data = { ...data, ...value }; },
    setFailSave(value) { failSave = value; }, setConfirm(value) { confirmResult = value; }
  };
}

(async () => {
  const h = harness({ required: true, content: '' });
  await flush();
  assert.equal(h.element('#personality-dialog').hidden, false);
  assert.equal(h.settingsClosed, true);
  assert.match(h.element('#personality-feedback').textContent, /开始聊天前/);
  const draft = '# 自己的角色\n\n有自己的见解，喜欢天文学。';
  h.element('#personality-content').value = draft;
  await h.element('#personality-form').handlers.submit({ preventDefault() {} });
  const post = h.requests.find(({ options }) => options?.method === 'POST');
  assert.equal(post.url, '/api/personality');
  assert.deepEqual(JSON.parse(post.options.body), { content: draft, revision: 'revision-one' });
  assert.match(h.element('#personality-feedback').textContent, /重启|重新运行 Start.cmd/);
  h.element('#close-personality').handlers.click();
  h.element('#edit-personality').handlers.click(); await flush();
  assert.match(h.element('#personality-feedback').textContent, /尚未生效.*重启/);
  console.log('PASS: saving exact Markdown requires a backend restart; reopening preserves the pending-change notice.');

  const existing = harness();
  await flush();
  assert.equal(existing.element('#personality-dialog').hidden, true);
  existing.element('#edit-personality').handlers.click(); await flush();
  assert.equal(existing.element('#personality-content').value, '# My character\n喜欢天文学。');
  existing.element('#personality-content').value = '尚未保存的修改';
  existing.element('#close-personality').handlers.click();
  assert.equal(existing.element('#personality-dialog').hidden, false);
  existing.setFailSave(true);
  await existing.element('#personality-form').handlers.submit({ preventDefault() {} });
  assert.equal(existing.element('#personality-content').value, '尚未保存的修改');
  assert.match(existing.element('#personality-feedback').textContent, /file changed/);
  assert.equal(existing.element('#save-personality').disabled, false);
  assert.equal(existing.element('#personality-content').disabled, false);
  console.log('PASS: existing users are not interrupted; conflicts preserve the draft and restore editing controls.');

  existing.setServer({ content: '外部编辑器的新内容', revision: 'external-edit' });
  existing.element('#reload-personality').handlers.click(); await flush();
  assert.equal(existing.element('#personality-content').value, '尚未保存的修改');
  existing.setConfirm(true);
  existing.element('#reload-personality').handlers.click(); await flush();
  assert.equal(existing.element('#personality-content').value, '外部编辑器的新内容');
  existing.element('#close-personality').handlers.click();
  assert.equal(existing.element('#personality-dialog').hidden, true);
  assert.equal(existing.requests.some(({ url }) => url.includes('/demo')), false);
  console.log('PASS: reload requires discarding a dirty draft and fetches the current external file without calling demo endpoints.');

  const windowsFile = harness({content: '# Character\r\nWindows Markdown\r\n'});
  await flush(); windowsFile.element('#edit-personality').handlers.click(); await flush();
  assert.equal(windowsFile.element('#personality-content').value, '# Character\nWindows Markdown\n');
  windowsFile.element('#close-personality').handlers.click();
  assert.equal(windowsFile.element('#personality-dialog').hidden, true);
  console.log('PASS: Windows line endings do not incorrectly mark an unchanged file as an unsaved draft.');
})().catch((error) => { console.error(error); process.exitCode = 1; });
