const tr = (source, variables = {}) => window.MatisseI18n?.t(source, variables) ?? source.replace(/\{(\w+)\}/g, (match, key) => variables[key] === undefined ? match : String(variables[key]));
'use strict';

const tierForm = document.querySelector('#tier-form');
const tierPicker = document.querySelector('#tier-picker');
const tierOptions = document.querySelector('#tier-options');
const tierPassword = document.querySelector('#tier-password');
const tierStart = document.querySelector('#tier-start');
const tierError = document.querySelector('#tier-error');
const demoWorkspace = document.querySelector('#demo-workspace');
const demoMessages = document.querySelector('#demo-messages');
const demoInput = document.querySelector('#demo-input');
const demoStatus = document.querySelector('#demo-status');
const demoNew = document.querySelector('#demo-new');
let demoChat = null;
let demoBusy = false;
let demoEpoch = 0;

async function demoRequest(path, body) {
  const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(tr(data.error || '暂时无法连接，请稍后重试。'));
    error.status = response.status;
    throw error;
  }
  return data;
}

function selectedTier() { return tierForm.querySelector('input[name="tier"]:checked')?.value || null; }

function updateTierChoice() {
  const tier = selectedTier();
  document.querySelector('#tier-password-wrap').hidden = tier !== 'T0';
  tierPassword.required = tier === 'T0';
  tierPassword.value = '';
  tierError.textContent = '';
  tierStart.disabled = !tier || demoBusy;
  tierStart.textContent = tier ? tr('以 {tier} 开始对话 →', { tier }) : tr('选择关系后开始 →');
  if (tier === 'T0') tierPassword.focus();
}

function setDemoBusy(busy) {
  demoBusy = busy;
  demoNew.disabled = busy;
  tierOptions.disabled = busy;
  tierStart.disabled = busy || !selectedTier();
  tierPassword.disabled = busy;
  document.querySelector('#demo-send').disabled = busy || !demoChat;
  demoInput.disabled = busy || !demoChat;
}

function renderDemoMessages(pending = null) {
  demoMessages.replaceChildren();
  const messages = [...(demoChat?.messages || [])];
  if (pending) messages.push({ role: 'user', content: pending, pending: true });
  if (!messages.length) {
    const empty = document.createElement('div'); empty.className = 'demo-empty';
    const title = document.createElement('strong'); title.textContent = tr('对话的第一句话，交给你。');
    const text = document.createElement('span'); text.textContent = tr('可以聊今天的心情，也可以带来一个具体的问题。');
    empty.append(title, text); demoMessages.append(empty);
  }
  messages.forEach((message) => {
    const row = document.createElement('article'); row.className = `demo-message ${message.role}${message.pending ? ' pending' : ''}`;
    const name = document.createElement('span'); name.className = 'demo-message-name'; name.textContent = message.role === 'user' ? tr('你') : 'MATISSE';
    const text = document.createElement('div'); text.className = 'demo-message-text'; text.textContent = message.content;
    row.append(name, text); demoMessages.append(row);
  });
  demoMessages.scrollTop = demoMessages.scrollHeight;
}

function renderDemoMood(mood) {
  const labels = { calm: tr('平静'), happy: tr('开心'), excited: tr('兴奋'), annoyed: tr('烦闷'), hurt: tr('受伤'), sad: tr('悲伤'), sleepy: tr('困倦'), mixed: tr('心绪交织'), warm: tr('温暖'), lonely: tr('孤独') };
  document.querySelector('#demo-mood-label').textContent = labels[mood.label] || tr(mood.label);
  const container = document.querySelector('#demo-emotions'); container.replaceChildren();
  const emotions = { happiness: tr('开心'), sadness: tr('悲伤'), excitement: tr('兴奋'), loneliness: tr('孤独'), hurt: tr('受伤'), anger: tr('生气') };
  Object.entries(emotions).forEach(([key, label]) => {
    const value = mood.current[key] || 0;
    const delta = mood.delta[key] || 0;
    const row = document.createElement('div'); row.className = 'emotion-row';
    const heading = document.createElement('div'); heading.className = 'emotion-heading';
    const name = document.createElement('span'); name.textContent = label;
    const number = document.createElement('span'); number.className = 'emotion-number'; number.textContent = value.toFixed(1);
    const change = document.createElement('small'); change.textContent = `${delta > 0 ? '+' : ''}${delta.toFixed(2)}`; number.append(change);
    heading.append(name, number);
    const track = document.createElement('div'); track.className = 'emotion-track';
    track.setAttribute('role', 'meter'); track.setAttribute('aria-label', label); track.setAttribute('aria-valuemin', '0'); track.setAttribute('aria-valuemax', '100'); track.setAttribute('aria-valuenow', String(value));
    const fill = document.createElement('span'); fill.className = 'emotion-fill'; fill.style.width = `${Math.max(0, Math.min(100, value))}%`;
    track.append(fill); row.append(heading, track); container.append(row);
  });
}

async function startDemo(event) {
  event.preventDefault();
  const tier = selectedTier();
  if (demoBusy || !tier) return;
  const body = { tier };
  if (tier === 'T0') body.password = tierPassword.value;
  setDemoBusy(true); tierError.textContent = ''; tierStart.textContent = tr('正在开始…');
  const epoch = demoEpoch;
  try {
    const created = await demoRequest('/api/demo/chats', body);
    if (epoch !== demoEpoch) { discardChatId(created.id); return; }
    demoChat = created;
    tierPassword.value = '';
    document.querySelector('#demo-tier-label').textContent = `${demoChat.tier} · ${tr(demoChat.tier_label)}`;
    tierPicker.hidden = true; demoWorkspace.hidden = false;
    demoStatus.textContent = tr('关系已确定，可以开始聊天了。'); demoStatus.classList.remove('error');
    renderDemoMessages(); renderDemoMood(demoChat.mood);
  } catch (error) {
    if (epoch !== demoEpoch) return;
    tierError.textContent = tr(error.message);
    tierPassword.value = '';
    if (tier === 'T0') tierPassword.focus();
  } finally {
    if (epoch === demoEpoch) {
      setDemoBusy(false); tierStart.textContent = tr('以 {tier} 开始对话 →', { tier });
      if (demoChat) demoInput.focus(); else if (tier === 'T0') tierPassword.focus();
    }
  }
}

function discardChatId(chatId) {
  navigator.sendBeacon('/api/demo/discard', new Blob([JSON.stringify({ chat_id: chatId })], { type: 'application/json' }));
}

function discardDemo() {
  demoEpoch += 1;
  if (!demoChat) return;
  const chatId = demoChat.id; demoChat = null;
  // This also works when navigating away, without keeping a private history.
  discardChatId(chatId);
}

function newDemo() {
  if (demoBusy) return;
  discardDemo();
  tierForm.reset(); tierPassword.value = ''; demoInput.value = '';
  demoWorkspace.hidden = true; tierPicker.hidden = false;
  demoMessages.replaceChildren();
  updateTierChoice();
  tierForm.querySelector('input[name="tier"]').focus();
}

async function sendDemoMessage(event) {
  event.preventDefault();
  const content = demoInput.value.trim();
  if (!demoChat || !content || demoBusy) return;
  const epoch = demoEpoch;
  setDemoBusy(true); demoStatus.classList.remove('error');
  demoStatus.textContent = tr('马蒂斯正在思考…'); renderDemoMessages(content);
  try {
    const updated = await demoRequest('/api/demo/messages', { chat_id: demoChat.id, content });
    if (epoch !== demoEpoch) return;
    demoChat = updated; demoInput.value = ''; demoInput.style.height = 'auto';
    renderDemoMessages(); renderDemoMood(demoChat.mood);
    demoStatus.textContent = tr('心情已更新，并会带入下一次回答。');
  } catch (error) {
    if (epoch !== demoEpoch) return;
    renderDemoMessages();
    demoStatus.textContent = tr(error.message); demoStatus.classList.add('error');
    if (error.status === 404) {
      newDemoAfterExpiry(error.message);
    }
  } finally { if (epoch === demoEpoch) { setDemoBusy(false); if (demoChat) demoInput.focus(); } }
}

function newDemoAfterExpiry(message) {
  demoChat = null; tierForm.reset(); tierPassword.value = '';
  demoWorkspace.hidden = true; tierPicker.hidden = false;
  updateTierChoice(); tierError.textContent = message;
}

tierOptions.addEventListener('change', updateTierChoice);
tierForm.addEventListener('submit', startDemo);
demoNew.addEventListener('click', newDemo);
document.querySelector('#demo-composer').addEventListener('submit', sendDemoMessage);
demoInput.addEventListener('keydown', (event) => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); document.querySelector('#demo-composer').requestSubmit(); } });
demoInput.addEventListener('input', () => { demoInput.style.height = 'auto'; demoInput.style.height = `${Math.min(demoInput.scrollHeight, 150)}px`; });
window.addEventListener('pagehide', discardDemo);
window.addEventListener('matisse-language-change', () => {
  if (demoChat) {
    const position = demoMessages.scrollTop;
    renderDemoMessages(demoBusy ? demoInput.value.trim() : null); demoMessages.scrollTop = position;
    renderDemoMood(demoChat.mood);
    document.querySelector('#demo-tier-label').textContent = `${demoChat.tier} · ${tr(demoChat.tier_label)}`;
  }
});
window.addEventListener('pageshow', (event) => { if (event.persisted) { setDemoBusy(false); newDemo(); } });
setDemoBusy(true);
Promise.resolve(window.MatisseI18n?.ready).then(() => demoRequest('/api/demo/enter', {})).then(() => setDemoBusy(false)).catch((error) => {
  tierError.textContent = tr(error.message); setDemoBusy(false);
});
