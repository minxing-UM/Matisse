/* UI text only: conversation, memory and editable content are never translated. */
(() => {
  const storageKey = 'matisse-language';
  let language = localStorage.getItem(storageKey) === 'en' ? 'en' : 'zh';
  let catalog = {};
  let reverse = new Map();
  let patterns = [];
  let changing = false;
  const originalText = new WeakMap();
  const originalAttributes = new WeakMap();
  const excluded = 'script, style, textarea, [data-i18n-skip], .message-text, .memory-content, .chat-item-title, #chat-title, #presence-topic, .trait-option, .trait-remove, .demo-message-text';
  const attributes = ['aria-label', 'placeholder', 'title', 'alt'];
  const pageTitle = document.title;

  function interpolate(value, variables = {}) {
    return value.replace(/\{(\w+)\}/g, (match, key) => variables[key] === undefined ? match : String(variables[key]));
  }

  function t(source, variables = {}) {
    if (typeof source !== 'string') return source;
    const key = Object.hasOwn(catalog, source) ? source : reverse.get(source);
    if (key !== undefined) return interpolate(language === 'en' ? catalog[key] : key, variables);
    for (const pattern of patterns) {
      const match = source.match(pattern.regex);
      if (match) {
        const values = Object.fromEntries(pattern.names.map((name, index) => [name, match[index + 1]]));
        return interpolate(language === 'en' ? catalog[pattern.key] : pattern.key, { ...values, ...variables });
      }
    }
    return interpolate(source, variables);
  }

  function buildCatalog(value) {
    catalog = value;
    reverse = new Map(Object.entries(catalog).map(([key, translation]) => [translation, key]));
    patterns = [];
    Object.entries(catalog).forEach(([key, translation]) => {
      for (const template of [key, translation]) {
        const names = [];
        const pieces = template.split(/(\{\w+\})/g).map((piece) => {
          if (/^\{\w+\}$/.test(piece)) { names.push(piece.slice(1, -1)); return '([\\s\\S]*?)'; }
          return piece.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        });
        if (names.length) patterns.push({ key, names, regex: new RegExp(`^${pieces.join('')}$`) });
      }
    });
  }

  function localize(root = document.body) {
    if (!root) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      if (!node.parentElement || node.parentElement.closest(excluded)) continue;
      const cached = originalText.get(node);
      const source = cached && cached.rendered === node.data ? cached.source : node.data;
      const trimmed = source.trim();
      const translated = t(trimmed);
      const rendered = source.replace(trimmed, translated);
      node.data = rendered;
      originalText.set(node, { source, rendered });
    }
    const elements = [root, ...root.querySelectorAll('*')];
    elements.forEach((element) => {
      // Textarea values are user content; their labels/placeholders are UI.
      if (element.closest(excluded.replace('textarea, ', ''))) return;
      const cached = originalAttributes.get(element) || {};
      attributes.forEach((name) => {
        const value = element.getAttribute(name);
        if (value === null) return;
        const source = cached[name]?.rendered === value ? cached[name].source : value;
        const rendered = t(source);
        element.setAttribute(name, rendered); cached[name] = { source, rendered };
      });
      originalAttributes.set(element, cached);
    });
  }

  function apply(value) {
    language = value;
    localStorage.setItem(storageKey, language);
    document.documentElement.lang = language === 'en' ? 'en' : 'zh-CN';
    document.title = t(pageTitle);
    localize();
    const select = document.querySelector('#language-select');
    if (select) select.value = language;
    window.dispatchEvent(new CustomEvent('matisse-language-change', { detail: { language } }));
  }

  async function setLanguage(value) {
    if (changing || !['zh', 'en'].includes(value)) return;
    const select = document.querySelector('#language-select');
    changing = true;
    if (select) { select.disabled = true; select.setAttribute('aria-busy', 'true'); }
    try {
      const response = await fetch('/api/language', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ language: value })
      });
      const data = await response.json();
      if (!response.ok || !['zh', 'en'].includes(data.language)) throw new Error(data.error || t('语言切换失败，请重试。'));
      apply(data.language);
    } catch (error) {
      if (select) select.value = language;
      window.alert(t(error.message));
    } finally {
      changing = false;
      if (select) { select.disabled = false; select.removeAttribute('aria-busy'); }
    }
  }

  const ready = Promise.all([
    fetch('/static/translations.json').then((response) => { if (!response.ok) throw new Error('Translations unavailable'); return response.json(); }),
    fetch('/api/language').then((response) => { if (!response.ok) throw new Error('Language unavailable'); return response.json(); })
  ]).then(([translations, settings]) => {
    buildCatalog(translations);
    apply(['zh', 'en'].includes(settings.language) ? settings.language : 'zh');
  }).catch(() => { apply(language); });
  window.MatisseI18n = { t, localize, ready, setLanguage, get language() { return language; }, get locale() { return language === 'en' ? 'en-US' : 'zh-CN'; } };
  const select = document.querySelector('#language-select');
  if (select) {
    select.value = language; select.disabled = true;
    select.addEventListener('change', () => setLanguage(select.value));
    ready.finally(() => { select.disabled = false; });
  }
  window.addEventListener('storage', (event) => {
    if (event.key === storageKey && ['zh', 'en'].includes(event.newValue) && event.newValue !== language) apply(event.newValue);
  });
  window.addEventListener('pageshow', (event) => {
    if (event.persisted) fetch('/api/language').then((response) => response.json()).then((data) => {
      if (['zh', 'en'].includes(data.language) && data.language !== language) apply(data.language);
    }).catch(() => {});
  });
})();
