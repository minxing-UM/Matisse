/* Separate editor: never sends the user's persona through the demo API. */
(() => {
  const tr = (text) => window.MatisseI18n?.t(text) ?? text;
  const dialog = document.querySelector('#personality-dialog');
  const backdrop = document.querySelector('#personality-backdrop');
  const content = document.querySelector('#personality-content');
  const feedback = document.querySelector('#personality-feedback');
  const save = document.querySelector('#save-personality');
  const reload = document.querySelector('#reload-personality');
  let revision = null;
  let original = '';
  let epoch = 0;
  let saving = false;

  async function request(options) {
    const response = await fetch('/api/personality', options);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '请求失败，请重试。');
    return data;
  }

  async function load() {
    const current = ++epoch;
    revision = null; content.disabled = true; save.disabled = true;
    feedback.textContent = tr('正在读取角色设定…');
    try {
      const data = await request();
      if (current !== epoch) return;
      content.value = data.content; original = content.value; revision = data.revision;
      feedback.textContent = data.restart_required
        ? tr('角色设定有尚未生效的修改，请重启后端；刷新网页不会生效。')
        : data.configured ? '' : tr('开始聊天前，请先填写并保存角色设定，再重启后端。');
    } catch (error) {
      if (current === epoch) feedback.textContent = tr(error.message);
    } finally {
      if (current === epoch) { content.disabled = revision === null; save.disabled = revision === null; }
    }
  }

  function open() {
    window.setSettingsOpen?.(false);
    dialog.hidden = false; backdrop.hidden = false;
    load();
  }

  function close() {
    if (saving) return;
    if (revision !== null && content.value !== original && !window.confirm(tr('角色设定尚未保存，确定关闭吗？'))) return;
    epoch++; dialog.hidden = true; backdrop.hidden = true;
    document.querySelector('#settings-toggle')?.focus();
  }

  document.querySelector('#edit-personality').addEventListener('click', open);
  document.querySelector('#close-personality').addEventListener('click', close);
  backdrop.addEventListener('click', close);
  dialog.addEventListener('keydown', (event) => { if (event.key === 'Escape') close(); });
  reload.addEventListener('click', () => {
    if (saving) return;
    if (revision !== null && content.value !== original && !window.confirm(tr('重新载入会放弃未保存的修改，确定继续吗？'))) return;
    load();
  });
  document.querySelector('#personality-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    if (saving || revision === null) return;
    saving = true; save.disabled = true; reload.disabled = true; content.disabled = true;
    feedback.textContent = tr('正在保存…');
    try {
      const data = await request({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content: content.value, revision }) });
      revision = data.revision; original = data.content;
      feedback.textContent = data.restart_required
        ? tr('角色设定已保存。请关闭后端，再重新运行 Start.cmd 后生效；刷新网页不会生效。')
        : tr('角色设定已保存，与当前生效版本一致。');
    } catch (error) { feedback.textContent = tr(error.message); }
    finally { saving = false; save.disabled = false; reload.disabled = false; content.disabled = false; }
  });
  Promise.resolve(window.MatisseI18n?.ready).then(() => request()).then((data) => {
    if (data.required && !(data.active_configured ?? data.configured) && dialog.hidden) open();
  }).catch(() => {});
})();
