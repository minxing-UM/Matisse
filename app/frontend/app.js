const tr = (source, variables = {}) => window.MatisseI18n?.t(source, variables) ?? source.replace(/\{(\w+)\}/g, (match, key) => variables[key] === undefined ? match : String(variables[key]));
const appShell = document.querySelector('#app-shell');
const chatList = document.querySelector('#chat-list');
const messages = document.querySelector('#messages');
const chatTitle = document.querySelector('#chat-title');
const chatStatus = document.querySelector('#chat-status');
const composer = document.querySelector('#composer');
const input = document.querySelector('#message-input');
const sendButton = document.querySelector('#send-button');
const moodValues = document.querySelector('#mood-values');
const moodTime = document.querySelector('#mood-time');
const portraitStage = document.querySelector('#portrait-stage');
const portraitImage = document.querySelector('#portrait-image');
const portraitPlaceholder = document.querySelector('#portrait-placeholder');
const portraitInput = document.querySelector('#portrait-input');
const sidebar = document.querySelector('.sidebar');
const quickProfile = document.querySelector('#quick-profile');
const quickProfileLabel = document.querySelector('#quick-profile-label');
const quickProfileHint = document.querySelector('#quick-profile-hint');
const profileOrder = ['flash', 'balanced', 'focused', 'deep'];

let chats = [];
let currentChat = null;
let isSending = false;
let appSettings = null;
let selectedPersonalityTraits = [];
let memoryCategories = [];
let memorySearchTimer = null;
let isPollingThoughts = false;
let uiEpoch = 0;
let pendingMessage = null;

const moodLabels = {
  happiness: tr('愉悦'), anger: tr('愤怒'), hurt: tr('受伤'), sadness: tr('悲伤'), loneliness: tr('孤独'),
  excitement: tr('兴奋'), tiredness: tr('疲惫')
};

async function request(url, options = {}) {
  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || tr('请求失败，请重试。'));
  return payload;
}

function formatDate(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const today = new Date();
  const sameDay = date.toDateString() === today.toDateString();
  return sameDay
    ? date.toLocaleTimeString(window.MatisseI18n?.locale || 'zh-CN', { hour: '2-digit', minute: '2-digit' })
    : date.toLocaleDateString(window.MatisseI18n?.locale || 'zh-CN', { month: 'numeric', day: 'numeric' });
}

function setMoodOpen(open) {
  appShell.classList.toggle('mood-open', open);
  document.querySelector('#mood-toggle').setAttribute('aria-expanded', String(open));
  localStorage.setItem('matisse-mood-open', String(open));
  if (open) refreshMood();
}

function renderMood(mood) {
  const thoughtText = mood.generation?.kind === 'thought'
    ? tr(' · 正在酝酿想法')
    : mood.next_thought_at ? tr(' · 下次想法 {time}', { time: formatDate(mood.next_thought_at) }) : '';
  const timeLabels = { sleepy_morning: '困倦的早晨', energetic: '精神充沛', active_afternoon: '活跃的午后', relaxed_evening: '放松的夜晚', sleepy_night: '困倦的深夜', very_sleepy: '睡意浓重' };
  moodTime.textContent = tr('{time} · 能量 {energy}/100{thought}', { time: tr(timeLabels[mood.time_state] || mood.time_state || '当前'), energy: Math.round(mood.energy || 0), thought: thoughtText });
  moodValues.replaceChildren();
  Object.entries(moodLabels).forEach(([key, label]) => {
    const value = Math.max(0, Math.min(100, Number(mood.values?.[key]) || 0));
    const row = document.createElement('div');
    row.className = 'mood-row';
    const name = document.createElement('span'); name.className = 'mood-label'; name.textContent = tr(label);
    const number = document.createElement('span'); number.className = 'mood-number'; number.textContent = `${value.toFixed(1)}`;
    const track = document.createElement('div'); track.className = 'mood-track';
    const fill = document.createElement('div'); fill.className = 'mood-fill'; fill.style.width = `${value}%`;
    track.append(fill); row.append(name, number, track); moodValues.append(row);
  });
  const values = mood.values || {};
  const moodName = Math.max(Number(values.hurt) || 0, Number(values.anger) || 0) >= 55
    ? 'hurt'
    : (Number(values.sadness) || 0) >= 55
      ? 'sad'
      : (Number(values.tiredness) || 0) >= 60
        ? 'tired'
        : (Number(values.happiness) || 0) + (Number(values.excitement) || 0) >= 90
          ? 'happy' : 'calm';
  portraitStage.dataset.mood = moodName;
}

async function refreshMood() {
  try { renderMood(await request('/api/mood')); } catch (_) { moodTime.textContent = tr('暂时无法读取状态'); }
}

function renderPortrait(imageUrl) {
  if (imageUrl) {
    portraitImage.src = imageUrl;
    portraitImage.hidden = false;
    portraitPlaceholder.hidden = true;
  } else {
    portraitImage.removeAttribute('src');
    portraitImage.hidden = true;
    portraitPlaceholder.hidden = false;
  }
}

async function refreshPortrait() {
  try { renderPortrait((await request('/api/avatar')).image_url); } catch (_) { renderPortrait(null); }
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error(tr('无法读取这张图片。')));
    reader.readAsDataURL(file);
  });
}

async function uploadPortrait() {
  const file = portraitInput.files?.[0];
  if (!file) return;
  if (!['image/png', 'image/jpeg', 'image/webp', 'image/gif'].includes(file.type) || file.size > 5 * 1024 * 1024) {
    chatStatus.textContent = tr('请选择不超过 5 MB 的 PNG、JPG、WebP 或 GIF。'); portraitInput.value = ''; return;
  }
  chatStatus.textContent = tr('正在保存立绘…');
  try {
    const data = await request('/api/avatar', {
      method: 'POST', body: JSON.stringify({ data_url: await readFileAsDataUrl(file) })
    });
    renderPortrait(data.image_url); chatStatus.textContent = tr('立绘已更新');
  } catch (error) { chatStatus.textContent = tr(error.message); }
  finally { portraitInput.value = ''; }
}

function bindPortraitMotion() {
  portraitStage.addEventListener('pointermove', (event) => {
    const rect = portraitStage.getBoundingClientRect();
    const x = Math.max(-1, Math.min(1, (event.clientX - rect.left) / rect.width * 2 - 1));
    const y = Math.max(-1, Math.min(1, (event.clientY - rect.top) / rect.height * 2 - 1));
    portraitStage.style.setProperty('--portrait-x', `${(x * 6).toFixed(1)}px`);
    portraitStage.style.setProperty('--portrait-y', `${(y * 3).toFixed(1)}px`);
    portraitStage.style.setProperty('--portrait-rotate', `${(x * 1.5).toFixed(2)}deg`);
    portraitStage.style.setProperty('--glow-x', `${50 + x * 20}%`);
    portraitStage.style.setProperty('--glow-y', `${42 + y * 13}%`);
  });
  portraitStage.addEventListener('pointerleave', () => {
    portraitStage.style.setProperty('--portrait-x', '0px'); portraitStage.style.setProperty('--portrait-y', '0px');
    portraitStage.style.setProperty('--portrait-rotate', '0deg'); portraitStage.style.setProperty('--glow-x', '50%'); portraitStage.style.setProperty('--glow-y', '42%');
  });
}

function summaryMode() {
  return document.querySelector('input[name="memory-summary-mode"]:checked')?.value || 'automatic';
}

function updateSummaryControls() {
  const isManual = summaryMode() === 'manual';
  document.querySelector('#memory-summary-interval').disabled = isManual;
  document.querySelector('#manual-summary').disabled = !isManual || isSending;
}

function setProfileDescription(profileName) {
  const profile = appSettings?.inference_profiles?.[profileName];
  document.querySelector('#profile-description').textContent = profile
    ? tr(profile.description)
    : tr('使用下方的上下文、回复长度和思考模式设置。');
}

function applyInferenceProfile() {
  const profileName = document.querySelector('#performance-profile').value;
  const profile = appSettings?.inference_profiles?.[profileName];
  if (profile) {
    document.querySelector('#context-length').value = profile.context_length;
    document.querySelector('#max-output-tokens').value = profile.max_output_tokens;
    document.querySelector('#thinking-enabled').checked = Boolean(profile.thinking_enabled);
  }
  setProfileDescription(profileName);
}

function markCustomProfile() {
  document.querySelector('#performance-profile').value = 'custom';
  setProfileDescription('custom');
}

function renderPersonalityTraits(available, selected) {
  selectedPersonalityTraits = [...selected];
  const container = document.querySelector('#trait-options');
  container.replaceChildren();
  available.forEach((trait) => {
    const selectedNow = selectedPersonalityTraits.includes(trait.id);
    const entry = document.createElement('div'); entry.className = 'trait-entry';
    const button = document.createElement('button'); button.type = 'button';
    button.className = `trait-option${selectedNow ? ' selected' : ''}`; button.textContent = trait.custom ? trait.name : tr(trait.name);
    button.title = trait.custom ? trait.instruction : tr(trait.instruction);
    button.disabled = !selectedNow && selectedPersonalityTraits.length >= 3;
    button.addEventListener('click', () => {
      if (selectedPersonalityTraits.includes(trait.id)) {
        selectedPersonalityTraits = selectedPersonalityTraits.filter((item) => item !== trait.id);
      } else if (selectedPersonalityTraits.length < 3) {
        selectedPersonalityTraits = [...selectedPersonalityTraits, trait.id];
      }
      renderPersonalityTraits(available, selectedPersonalityTraits);
    });
    entry.append(button);
    if (trait.custom) {
      const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'trait-remove';
      remove.textContent = '×'; remove.title = tr('删除「{name}」', { name: trait.name });
      remove.addEventListener('click', () => deletePersonalityTrait(trait)); entry.append(remove);
    }
    container.append(entry);
  });
}

async function addPersonalityTrait() {
  const name = document.querySelector('#new-trait-name').value.trim();
  const instruction = document.querySelector('#new-trait-instruction').value.trim();
  const feedback = document.querySelector('#settings-feedback');
  if (!name || !instruction) {
    feedback.textContent = tr('请填写性格名称和表达说明。'); return;
  }
  try {
    const data = await request('/api/personality-traits', {
      method: 'POST', body: JSON.stringify({ name, instruction })
    });
    document.querySelector('#new-trait-name').value = '';
    document.querySelector('#new-trait-instruction').value = '';
    renderSettings(data.settings);
    feedback.textContent = tr('已添加「{name}」，点击标签即可启用。', { name: data.trait.name });
  } catch (error) { feedback.textContent = tr(error.message); }
}

async function deletePersonalityTrait(trait) {
  if (!window.confirm(tr('删除自定义性格「{name}」？', { name: trait.name }))) return;
  const feedback = document.querySelector('#settings-feedback');
  try {
    const data = await request(`/api/personality-traits/${encodeURIComponent(trait.id)}`, { method: 'DELETE' });
    renderSettings(data.settings); feedback.textContent = tr('已删除「{name}」。', { name: trait.name });
  } catch (error) { feedback.textContent = tr(error.message); }
}

function renderSettings(settings) {
  appSettings = settings;
  const profileName = settings.inference_profiles?.[settings.performance_profile]
    ? settings.performance_profile : 'custom';
  document.querySelector('#performance-profile').value = profileName;
  document.querySelector('#context-length').value = settings.context_length;
  document.querySelector('#max-output-tokens').value = settings.max_output_tokens;
  document.querySelector('#thinking-enabled').checked = Boolean(settings.thinking_enabled);
  renderPersonalityTraits(
    settings.available_personality_traits || [],
    settings.personality_traits || []
  );
  document.querySelector('#memory-enabled').checked = Boolean(settings.memory_enabled);
  document.querySelector('#memory-embedding-enabled').checked = Boolean(settings.memory_embedding_enabled);
  const mode = settings.memory_summary_mode === 'manual' ? 'manual' : 'automatic';
  document.querySelector(`input[name="memory-summary-mode"][value="${mode}"]`).checked = true;
  document.querySelector('#memory-summary-interval').value = settings.memory_summary_interval;
  document.querySelector('#pending-memory').textContent = tr('待整理：{count} 轮对话{status}', { count: settings.pending_memory_turns || 0, status: settings.memory_summary_status?.status === 'failed' ? tr(' · 上次整理未完成，内容已保留') : '' });
  const proactive = settings.proactive || {};
  document.querySelector('#proactive-enabled').checked = proactive.enabled !== false;
  document.querySelector('#thought-min-minutes').value = proactive.thought_min_minutes ?? 1;
  document.querySelector('#thought-max-minutes').value = proactive.thought_max_minutes ?? 10;
  document.querySelector('#wake-hour').value = proactive.wake_hour ?? 6;
  document.querySelector('#sleep-hour').value = proactive.sleep_hour ?? 2;
  document.querySelector('#long-term-goal').value = proactive.long_term_goal || '';
  document.querySelector('#quiet-hours-enabled').checked = Boolean(proactive.quiet_hours_enabled);
  document.querySelector('#quiet-start-hour').value = proactive.quiet_start_hour ?? 23;
  document.querySelector('#quiet-end-hour').value = proactive.quiet_end_hour ?? 8;
  document.querySelector('#browser-notifications').checked = localStorage.getItem('matisse-browser-notifications') === 'true';
  setProfileDescription(profileName);
  renderQuickProfile(settings);
  updateSummaryControls();
}

function renderQuickProfile(settings) {
  const profileName = profileOrder.includes(settings.performance_profile)
    ? settings.performance_profile : 'balanced';
  const profile = settings.inference_profiles?.[profileName];
  quickProfile.value = String(profileOrder.indexOf(profileName));
  quickProfileLabel.textContent = tr(profile?.label || '均衡');
  quickProfileHint.textContent = profile
    ? `${Math.round(profile.context_length / 1024)}k · ${profile.max_output_tokens}`
    : '';
}

async function changeQuickProfile() {
  const profileName = profileOrder[Number(quickProfile.value)] || 'balanced';
  chatStatus.textContent = tr('正在切换到{profile}档…', { profile: tr(appSettings?.inference_profiles?.[profileName]?.label || profileName) });
  try {
    const settings = await request('/api/settings', {
      method: 'POST', body: JSON.stringify({ performance_profile: profileName })
    });
    renderSettings(settings);
    chatStatus.textContent = tr('回复档位已切换');
  } catch (error) { chatStatus.textContent = tr(error.message); }
}

function setSettingsOpen(open) {
  const dialog = document.querySelector('#settings-dialog');
  const backdrop = document.querySelector('#settings-backdrop');
  dialog.hidden = !open; backdrop.hidden = !open;
  if (open) {
    request('/api/settings').then(renderSettings).catch((error) => {
      document.querySelector('#settings-feedback').textContent = tr(error.message);
    });
  }
}

function setMemoriesOpen(open) {
  const dialog = document.querySelector('#memories-dialog');
  const backdrop = document.querySelector('#memories-backdrop');
  dialog.hidden = !open; backdrop.hidden = !open;
  if (open) loadMemories();
}

function categoryLabel(category) {
  return tr(memoryCategories.find((item) => item.id === category)?.label || '其他');
}

function populateMemoryCategories() {
  const select = document.querySelector('#memory-category');
  if (select.options.length || !memoryCategories.length) return;
  memoryCategories.forEach((category) => {
    const option = document.createElement('option'); option.value = category.id; option.textContent = tr(category.label);
    select.append(option);
  });
}

function memorySelect(options, value, onChange) {
  const select = document.createElement('select'); select.className = 'memory-select';
  options.forEach(({ value: optionValue, label }) => {
    const option = document.createElement('option'); option.value = String(optionValue); option.textContent = tr(label);
    select.append(option);
  });
  select.value = String(value ?? ''); select.addEventListener('change', () => onChange(select.value));
  return select;
}

function displayedMemoryImportance(current) {
  return typeof current === 'number' && Number.isFinite(current) && current >= 0 && current <= 5
    ? Math.round(current) : '';
}

function memoryImportanceOptions(current) {
  const options = [0, 1, 2, 3, 4, 5].map((value) => ({ value, label: tr('重要度 {value}', { value }) }));
  if (displayedMemoryImportance(current) === '') options.unshift({ value: '', label: tr('待评分') });
  return options;
}

function renderMemories(data) {
  memoryCategories = data.categories || memoryCategories;
  populateMemoryCategories();
  const list = document.querySelector('#memory-list'); list.replaceChildren();
  document.querySelector('#memories-feedback').textContent = data.summary_status?.status === 'failed'
    ? tr('上次记忆整理没有完成，{count} 轮对话已保留，可在设置中重试整理。', { count: data.pending_turns || 0 }) : '';
  const memories = data.memories || [];
  if (!memories.length) {
    const empty = document.createElement('p'); empty.className = 'memory-empty'; empty.textContent = tr('没有找到记忆。'); list.append(empty); return;
  }
  memories.forEach((memory) => {
    const card = document.createElement('article'); card.className = `memory-card${memory.pinned ? ' pinned' : ''}`;
    const body = document.createElement('div');
    const content = document.createElement('p'); content.className = 'memory-content'; content.textContent = memory.content;
    const meta = document.createElement('div'); meta.className = 'memory-meta';
    const updated = document.createElement('span'); updated.className = 'memory-pill'; updated.textContent = tr('更新于 {date}', { date: formatDate(memory.updated_at) });
    const category = memorySelect(memoryCategories.map((item) => ({ value: item.id, label: item.label })), memory.category, (value) => updateMemory(memory.id, { category: value }));
    const importance = memorySelect(memoryImportanceOptions(memory.importance), displayedMemoryImportance(memory.importance), (value) => {
      if (value !== '') updateMemory(memory.id, { importance: Number(value) });
    });
    importance.setAttribute('aria-label', tr('记忆重要度'));
    if (displayedMemoryImportance(memory.importance) !== '') {
      importance.title = tr('实际评分 {score}；显示为四舍五入后的整数，遗忘计算使用实际评分。', { score: memory.importance });
    }
    meta.append(category, importance, updated); body.append(content, meta);
    const tools = document.createElement('div'); tools.className = 'memory-tools';
    const pin = document.createElement('button'); pin.type = 'button'; pin.className = 'memory-tool'; pin.textContent = memory.pinned ? tr('取消置顶') : tr('置顶'); pin.addEventListener('click', () => updateMemory(memory.id, { pinned: !memory.pinned }));
    const edit = document.createElement('button'); edit.type = 'button'; edit.className = 'memory-tool'; edit.textContent = tr('编辑'); edit.addEventListener('click', () => editMemory(memory));
    const rephrase = document.createElement('button'); rephrase.type = 'button'; rephrase.className = 'memory-tool'; rephrase.textContent = tr('整理措辞'); rephrase.addEventListener('click', () => previewMemoryWording(memory, rephrase));
    const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'memory-tool danger'; remove.textContent = tr('删除'); remove.addEventListener('click', () => deleteMemory(memory));
    tools.append(pin, edit, rephrase, remove); card.append(body, tools); list.append(card);
  });
}

async function loadMemories() {
  const query = document.querySelector('#memory-search').value.trim();
  try { renderMemories(await request(`/api/memories?q=${encodeURIComponent(query)}`)); }
  catch (error) { document.querySelector('#memories-feedback').textContent = tr(error.message); }
}

async function updateMemory(id, changes) {
  try {
    await request(`/api/memories/${encodeURIComponent(id)}`, { method: 'POST', body: JSON.stringify(changes) });
    await loadMemories();
  } catch (error) { document.querySelector('#memories-feedback').textContent = tr(error.message); }
}

async function editMemory(memory) {
  const content = window.prompt(tr('编辑记忆：'), memory.content);
  if (content === null || content.trim() === memory.content) return;
  if (content.trim()) await updateMemory(memory.id, { content: content.trim() });
}

async function previewMemoryWording(memory, button) {
  const feedback = document.querySelector('#memories-feedback');
  button.disabled = true;
  feedback.textContent = tr('正在整理这条记忆的措辞…');
  try {
    const data = await request(`/api/memories/${encodeURIComponent(memory.id)}/wording-preview`, {
      method: 'POST', body: JSON.stringify({})
    });
    const content = window.prompt(tr('检查新措辞是否保留原意，可修改后保存：'), data.content);
    if (content === null || !content.trim() || content.trim() === data.original_content) {
      feedback.textContent = tr('记忆保持原样。'); return;
    }
    await request(`/api/memories/${encodeURIComponent(memory.id)}`, {
      method: 'POST', body: JSON.stringify({ content: content.trim(), expected_content: data.original_content })
    });
    await loadMemories();
    feedback.textContent = tr('措辞已更新，重要度和保留期限保持原样。');
  } catch (error) { feedback.textContent = tr(error.message); }
  finally { button.disabled = false; }
}

async function deleteMemory(memory) {
  if (!window.confirm(tr('删除这条记忆？\n\n{content}', { content: memory.content }))) return;
  try {
    await request(`/api/memories/${encodeURIComponent(memory.id)}`, { method: 'DELETE' });
    await loadMemories();
    document.querySelector('#memories-feedback').textContent = tr('记忆已删除。');
  } catch (error) { document.querySelector('#memories-feedback').textContent = tr(error.message); }
}

async function addMemory(event) {
  event.preventDefault();
  const content = document.querySelector('#memory-content').value.trim();
  if (!content) return;
  try {
    await request('/api/memories', {
      method: 'POST', body: JSON.stringify({
        content,
        category: document.querySelector('#memory-category').value,
        importance: Number(document.querySelector('#memory-importance').value)
      })
    });
    document.querySelector('#memory-content').value = '';
    await loadMemories();
    document.querySelector('#memories-feedback').textContent = tr('已手动记住。');
  } catch (error) { document.querySelector('#memories-feedback').textContent = tr(error.message); }
}

function renderPresence(presence) {
  const activity = tr(presence.activity || 'Matisse 正在安静地陪着你');
  document.querySelector('#presence-activity').textContent = presence.quiet_now ? tr('静默时段 · {activity}', { activity }) : activity;
  const topic = presence.active_topic || '';
  document.querySelector('#presence-topic').textContent = topic ? tr('最近在意：{topic}', { topic }) : '';
  if (presence.generation?.kind === 'thought') {
    chatStatus.textContent = pendingMessage
      ? tr('你的消息已排队，Matisse 说完后会接着回答…')
      : tr('Matisse 正在酝酿自己的想法，你可以照常发消息');
  } else if (pendingMessage) {
    chatStatus.textContent = tr('Matisse 正在思考你的问题…');
  }
}

async function refreshPresence() {
  try { renderPresence(await request('/api/presence')); } catch (_) { /* Presence is non-critical. */ }
}

async function requestBrowserNotificationPermission(enabled) {
  localStorage.setItem('matisse-browser-notifications', String(enabled));
  if (enabled && 'Notification' in window && Notification.permission === 'default') {
    await Notification.requestPermission();
  }
}

async function saveSettings(event) {
  event.preventDefault();
  const feedback = document.querySelector('#settings-feedback');
  feedback.textContent = tr('正在保存…');
  try {
    const settings = await request('/api/settings', {
      method: 'POST',
      body: JSON.stringify({
        performance_profile: document.querySelector('#performance-profile').value,
        context_length: Number(document.querySelector('#context-length').value),
        max_output_tokens: Number(document.querySelector('#max-output-tokens').value),
        thinking_enabled: document.querySelector('#thinking-enabled').checked,
        personality_traits: selectedPersonalityTraits,
        memory_enabled: document.querySelector('#memory-enabled').checked,
        memory_embedding_enabled: document.querySelector('#memory-embedding-enabled').checked,
        memory_summary_mode: summaryMode(),
        memory_summary_interval: Number(document.querySelector('#memory-summary-interval').value),
        proactive: {
          enabled: document.querySelector('#proactive-enabled').checked,
          thought_min_minutes: Number(document.querySelector('#thought-min-minutes').value),
          thought_max_minutes: Number(document.querySelector('#thought-max-minutes').value),
          wake_hour: Number(document.querySelector('#wake-hour').value),
          sleep_hour: Number(document.querySelector('#sleep-hour').value),
          long_term_goal: document.querySelector('#long-term-goal').value.trim(),
          quiet_hours_enabled: document.querySelector('#quiet-hours-enabled').checked,
          quiet_start_hour: Number(document.querySelector('#quiet-start-hour').value),
          quiet_end_hour: Number(document.querySelector('#quiet-end-hour').value)
        }
      })
    });
    await requestBrowserNotificationPermission(document.querySelector('#browser-notifications').checked);
    renderSettings(settings); feedback.textContent = tr('设置已保存，将从下一次回复开始生效。');
  } catch (error) { feedback.textContent = tr(error.message); }
}

async function summarizeMemories() {
  if (!currentChat || isSending) return;
  const button = document.querySelector('#manual-summary');
  const feedback = document.querySelector('#settings-feedback');
  button.disabled = true; feedback.textContent = tr('Matisse 正在整理记忆…');
  try {
    const data = await request('/api/memories/summarize', {
      method: 'POST', body: JSON.stringify({ chat_id: currentChat.id })
    });
    currentChat = data.chat; renderMessages(); await loadChats(); renderSettings(data.settings);
    feedback.textContent = tr('已完成整理，保存了 {count} 条记忆。', { count: data.memories_stored });
    chatStatus.textContent = tr('记忆已整理'); scrollToLatest();
  } catch (error) { feedback.textContent = tr(error.message); }
  finally { updateSummaryControls(); }
}

function renderHistory() {
  chatList.replaceChildren();
  if (!chats.length) {
    const empty = document.createElement('p'); empty.className = 'history-empty'; empty.textContent = tr('还没有对话'); chatList.append(empty); return;
  }
  const label = document.createElement('p'); label.className = 'history-label'; label.textContent = tr('最近对话'); chatList.append(label);
  chats.forEach((chat) => {
    const button = document.createElement('button'); button.type = 'button'; button.className = `chat-item${chat.id === currentChat?.id ? ' active' : ''}`;
    const title = document.createElement('div'); title.className = 'chat-item-title'; title.textContent = displayChatTitle(chat.title);
    const date = document.createElement('div'); date.className = 'chat-item-date'; date.textContent = formatDate(chat.updated_at);
    button.append(title, date); button.addEventListener('click', () => openChat(chat.id)); chatList.append(button);
  });
}

async function copyText(value, successMessage = tr('已复制')) {
  try {
    await navigator.clipboard.writeText(value);
    chatStatus.textContent = successMessage;
  } catch (_) { chatStatus.textContent = tr('浏览器未允许复制。'); }
}

async function copyChat() {
  if (!currentChat?.messages?.length) return;
  const transcript = currentChat.messages.map((message) =>
    `${message.role === 'user' ? tr('你') : 'Matisse'}：${message.content}`
  ).join('\n\n');
  await copyText(transcript, tr('整段对话已复制'));
}

async function deleteCurrentChat() {
  if (!currentChat || !window.confirm(tr('确定删除这段对话吗？此操作无法撤销。'))) return;
  try {
    await request(`/api/chats/${encodeURIComponent(currentChat.id)}`, { method: 'DELETE' });
    currentChat = null; await loadChats();
    if (chats.length) await openChat(chats[0].id); else await createChat();
    chatStatus.textContent = tr('对话已删除');
  } catch (error) { chatStatus.textContent = tr(error.message); }
}

async function reviseMessage(message) {
  const content = window.prompt(tr('修改消息后，后续对话会重新生成：'), message.content);
  if (content === null || content.trim() === message.content) return;
  if (!content.trim()) return;
  await runMessageAction(`/api/chats/${encodeURIComponent(currentChat.id)}/messages/${encodeURIComponent(message.id)}/edit`, { content: content.trim() });
}

async function regenerateMessage(message) {
  await runMessageAction(`/api/chats/${encodeURIComponent(currentChat.id)}/messages/${encodeURIComponent(message.id)}/regenerate`, {});
}

async function runMessageAction(url, body) {
  if (isSending || !currentChat) return;
  isSending = true; sendButton.disabled = true; input.disabled = true;
  uiEpoch += 1;
  chatStatus.textContent = tr('Matisse 正在重新回答…'); showTyping();
  try {
    const data = await request(url, { method: 'POST', body: JSON.stringify(body) });
    currentChat = data.chat; renderMessages(); await loadChats(); renderMood(data.mood); scrollToLatest();
    chatStatus.textContent = tr('已重新生成');
  } catch (error) { document.querySelector('#typing')?.remove(); chatStatus.textContent = tr(error.message); }
  finally { isSending = false; sendButton.disabled = false; input.disabled = false; input.focus(); }
}

function scrollToLatest() { messages.scrollTo({ top: messages.scrollHeight, behavior: 'smooth' }); }

function displayChatTitle(title) { return !title || title === 'New Chat' ? tr('新对话') : title; }

function renderMessages() {
  messages.replaceChildren();
  if (!currentChat?.messages?.length) {
    const empty = document.createElement('div'); empty.className = 'empty-state';
    empty.innerHTML = '<div class="empty-mark">M</div><h2></h2><p></p>';
    empty.querySelector('h2').textContent = tr('和 Matisse 聊聊吧');
    empty.querySelector('p').textContent = tr('新的对话会自动保存在左侧历史记录中。');
    messages.append(empty); return;
  }
  currentChat.messages.forEach((message) => {
    const isUser = message.role === 'user';
    const wrapper = document.createElement('article'); wrapper.className = `message ${isUser ? 'user' : 'assistant'}`;
    const avatar = document.createElement('div'); avatar.className = 'avatar'; avatar.textContent = isUser ? tr('你') : 'M';
    const content = document.createElement('div'); content.className = 'message-content';
    const name = document.createElement('div'); name.className = 'message-name'; name.textContent = isUser ? tr('你') : 'Matisse';
    const text = document.createElement('div'); text.className = 'message-text'; text.textContent = message.content;
    const time = document.createElement('div'); time.className = 'message-time'; time.textContent = formatDate(message.timestamp);
    const tools = document.createElement('div'); tools.className = 'message-tools';
    const copy = document.createElement('button'); copy.type = 'button'; copy.className = 'message-tool'; copy.textContent = tr('复制');
    copy.addEventListener('click', () => copyText(message.content, tr('消息已复制')));
    tools.append(copy);
    if (isUser && !message.interaction) {
      const edit = document.createElement('button'); edit.type = 'button'; edit.className = 'message-tool'; edit.textContent = tr('✎ 修改');
      edit.addEventListener('click', () => reviseMessage(message)); tools.append(edit);
    } else if (!isUser && !message.interaction && !message.proactive) {
      const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'message-tool'; retry.textContent = tr('↻ 重答');
      retry.addEventListener('click', () => regenerateMessage(message)); tools.append(retry);
    }
    content.append(name, text, time, tools); wrapper.append(avatar, content); messages.append(wrapper);
  });
}

function showTyping() {
  document.querySelector('#typing')?.remove();
  const typing = document.createElement('div'); typing.className = 'typing'; typing.id = 'typing';
  typing.textContent = tr('Matisse 正在思考');
  for (let index = 0; index < 3; index += 1) { const dot = document.createElement('span'); dot.textContent = '·'; typing.append(dot); }
  messages.append(typing); scrollToLatest();
}

async function loadChats() {
  const data = await request('/api/chats'); chats = data.chats; renderHistory();
}

async function openChat(id) {
  const epoch = ++uiEpoch;
  try {
    const chat = await request(`/api/chats/${encodeURIComponent(id)}`);
    if (epoch !== uiEpoch) return;
    currentChat = chat;
    chatTitle.textContent = displayChatTitle(currentChat.title); chatStatus.textContent = tr('历史对话');
    renderHistory(); renderMessages(); scrollToLatest();
  } catch (error) { chatStatus.textContent = tr(error.message); }
}

async function createChat() {
  const epoch = ++uiEpoch;
  try {
    const chat = await request('/api/chats', { method: 'POST', body: JSON.stringify({}) });
    if (epoch !== uiEpoch) return;
    currentChat = chat;
    chatTitle.textContent = tr('新对话'); chatStatus.textContent = tr('新的对话');
    await loadChats(); renderMessages(); input.focus();
  } catch (error) { chatStatus.textContent = tr(error.message); }
}

function resizeInput() { input.style.height = 'auto'; input.style.height = `${Math.min(input.scrollHeight, 180)}px`; }

function setInteractionButtonsDisabled(disabled) {
  document.querySelectorAll('#interaction-bar button').forEach((button) => { button.disabled = disabled; });
}

async function performInteraction(actionId) {
  if (isSending) return;
  if (!currentChat) await createChat();
  if (!currentChat) return;
  isSending = true; sendButton.disabled = true; input.disabled = true; setInteractionButtonsDisabled(true);
  uiEpoch += 1;
  chatStatus.textContent = tr('Matisse 正在回应你的互动…');
  try {
    const data = await request(`/api/chats/${encodeURIComponent(currentChat.id)}/interactions`, {
      method: 'POST', body: JSON.stringify({ action: actionId })
    });
    currentChat = data.chat; chatTitle.textContent = currentChat.title || 'Matisse';
    renderMessages(); await loadChats(); renderMood(data.mood); scrollToLatest();
    chatStatus.textContent = tr('互动已记录');
  } catch (error) { chatStatus.textContent = tr(error.message); }
  finally { isSending = false; sendButton.disabled = false; input.disabled = false; setInteractionButtonsDisabled(false); input.focus(); }
}

async function sendMessage(event) {
  event.preventDefault();
  const content = input.value.trim();
  if (!content || isSending) return;
  if (!currentChat) await createChat();
  if (!currentChat) return;
  isSending = true; sendButton.disabled = true; input.disabled = true; chatStatus.textContent = tr('Matisse 正在思考…');
  const epoch = ++uiEpoch;
  const chatId = currentChat.id; input.value = ''; resizeInput();
  pendingMessage = {
    chatId, knownIds: new Set(currentChat.messages.map((message) => message.id)),
    message: { id: `pending-${epoch}`, role: 'user', content, timestamp: new Date().toISOString() }
  };
  currentChat.messages.push(pendingMessage.message); renderMessages(); showTyping();
  try {
    const data = await request(`/api/chats/${encodeURIComponent(chatId)}/messages`, { method: 'POST', body: JSON.stringify({ content }) });
    if (epoch !== uiEpoch || currentChat?.id !== chatId) return;
    currentChat = data.chat; chatTitle.textContent = currentChat.title || 'Matisse'; chatStatus.textContent = tr('刚刚更新');
    renderMessages(); await loadChats(); renderMood(data.mood); scrollToLatest();
  } catch (error) {
    if (epoch === uiEpoch) {
      currentChat.messages = currentChat.messages.filter((message) => message.id !== `pending-${epoch}`);
      renderMessages(); chatStatus.textContent = tr(error.message);
    }
  } finally {
    pendingMessage = null;
    if (epoch === uiEpoch) uiEpoch += 1;
    isSending = false; sendButton.disabled = false; input.disabled = false; input.focus();
  }
}

async function claimProactiveMessage() {
  if (!currentChat || (isSending && !pendingMessage) || document.hidden || isPollingThoughts) return;
  const chatId = currentChat.id;
  const epoch = uiEpoch;
  isPollingThoughts = true;
  try {
    const data = await request('/api/proactive/claim', {
      method: 'POST', body: JSON.stringify({ chat_id: chatId })
    });
    if (epoch !== uiEpoch || currentChat?.id !== chatId || !data.chat) return;
    const previousIds = new Set(currentChat.messages.map((message) => message.id));
    const freshThought = data.chat.messages.find((message) => message.proactive && !previousIds.has(message.id));
    if (pendingMessage?.chatId === chatId) {
      const persisted = data.chat.messages.some((message) =>
        message.role === 'user' && !pendingMessage.knownIds.has(message.id)
        && message.content === pendingMessage.message.content
      );
      if (!persisted) data.chat.messages.push(pendingMessage.message);
    }
    const changed = JSON.stringify(data.chat.messages) !== JSON.stringify(currentChat.messages);
    if (!changed) return;
    currentChat = data.chat;
    chatTitle.textContent = currentChat.title || 'Matisse';
    chatStatus.textContent = pendingMessage ? tr('Matisse 正在思考你的问题…') : tr('Matisse 分享了一个想法');
    renderMessages(); await loadChats();
    if (epoch !== uiEpoch || currentChat?.id !== chatId) return;
    scrollToLatest();
    if (pendingMessage?.chatId === chatId) showTyping();
    if (data.mood) renderMood(data.mood);
    if (
      freshThought && document.hidden
      && localStorage.getItem('matisse-browser-notifications') === 'true'
      && 'Notification' in window
      && Notification.permission === 'granted'
    ) {
      new Notification('Matisse', { body: freshThought.content });
    }
    refreshPresence();
  } catch (_) {
    // The regular chat path remains available even if a background poll fails.
  } finally { isPollingThoughts = false; }
}

document.querySelector('#new-chat').addEventListener('click', createChat);
document.querySelector('#mood-toggle').addEventListener('click', () => setMoodOpen(!appShell.classList.contains('mood-open')));
document.querySelector('#close-mood').addEventListener('click', () => setMoodOpen(false));
document.querySelector('#settings-toggle').addEventListener('click', () => setSettingsOpen(true));
document.querySelector('#close-settings').addEventListener('click', () => setSettingsOpen(false));
document.querySelector('#cancel-settings').addEventListener('click', () => setSettingsOpen(false));
document.querySelector('#settings-backdrop').addEventListener('click', () => setSettingsOpen(false));
document.querySelector('#memories-toggle').addEventListener('click', () => setMemoriesOpen(true));
document.querySelector('#close-memories').addEventListener('click', () => setMemoriesOpen(false));
document.querySelector('#memories-backdrop').addEventListener('click', () => setMemoriesOpen(false));
document.querySelector('#memory-add-form').addEventListener('submit', addMemory);
document.querySelector('#memory-search').addEventListener('input', () => {
  clearTimeout(memorySearchTimer); memorySearchTimer = setTimeout(loadMemories, 180);
});
document.querySelector('#settings-form').addEventListener('submit', saveSettings);
document.querySelector('#add-trait').addEventListener('click', addPersonalityTrait);
document.querySelectorAll('input[name="memory-summary-mode"]').forEach((input) => input.addEventListener('change', updateSummaryControls));
document.querySelector('#manual-summary').addEventListener('click', summarizeMemories);
document.querySelector('#performance-profile').addEventListener('change', applyInferenceProfile);
document.querySelector('#context-length').addEventListener('change', markCustomProfile);
document.querySelector('#max-output-tokens').addEventListener('change', markCustomProfile);
document.querySelector('#thinking-enabled').addEventListener('change', markCustomProfile);
document.querySelector('#history-toggle').addEventListener('click', () => {
  const collapsed = sidebar.classList.toggle('history-collapsed');
  document.querySelector('#history-toggle').setAttribute('aria-expanded', String(!collapsed));
  localStorage.setItem('matisse-history-collapsed', String(collapsed));
});
document.querySelector('#copy-chat').addEventListener('click', copyChat);
document.querySelector('#delete-chat').addEventListener('click', deleteCurrentChat);
document.querySelector('#interaction-bar').addEventListener('click', (event) => {
  const button = event.target.closest('button[data-action]');
  if (button) performInteraction(button.dataset.action);
});
quickProfile.addEventListener('change', changeQuickProfile);
composer.addEventListener('submit', sendMessage);
input.addEventListener('input', resizeInput);
input.addEventListener('keydown', (event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); composer.requestSubmit(); } });
portraitInput.addEventListener('change', uploadPortrait);
bindPortraitMotion();
window.addEventListener('matisse-language-change', () => {
  renderHistory();
  if (currentChat) {
    const position = messages.scrollTop;
    renderMessages(); messages.scrollTop = position;
    chatTitle.textContent = displayChatTitle(currentChat.title);
    if (isSending) showTyping();
  }
  if (appSettings) {
    renderPersonalityTraits(appSettings.available_personality_traits || [], selectedPersonalityTraits);
    setProfileDescription(document.querySelector('#performance-profile').value);
    renderQuickProfile(appSettings);
  }
  refreshMood(); refreshPresence();
  chatStatus.textContent = tr('语言已切换，之后的回复将使用中文。');
});
window.addEventListener('pageshow', (event) => {
  if (event.persisted && currentChat) openChat(currentChat.id);
});

(async function initialize() {
  await window.MatisseI18n?.ready;
  setMoodOpen(localStorage.getItem('matisse-mood-open') === 'true');
  const historyCollapsed = localStorage.getItem('matisse-history-collapsed') === 'true';
  sidebar.classList.toggle('history-collapsed', historyCollapsed);
  document.querySelector('#history-toggle').setAttribute('aria-expanded', String(!historyCollapsed));
  try {
    await loadChats();
    if (chats.length) await openChat(chats[0].id); else await createChat();
    await refreshMood();
    await refreshPresence();
    await refreshPortrait();
    renderSettings(await request('/api/settings'));
  } catch (error) { chatStatus.textContent = error.message || tr('无法连接到本地服务'); }
})();

setInterval(() => {
  if (appShell.classList.contains('mood-open')) refreshMood();
  claimProactiveMessage();
  refreshPresence();
}, 5000);
