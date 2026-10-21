// Exercise the actual send/poll functions with controlled network ordering.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('app/frontend/app.js', 'utf8');
const functions = source.slice(0, source.indexOf("document.querySelector('#new-chat').addEventListener"));

function harness() {
  const nodes = new Map();
  const element = () => ({
    value: '', textContent: '', disabled: false, style: {}, children: [], attributes: {},
    get options() { return this.children; },
    focus() {}, remove() {}, scrollTo() {}, addEventListener() {},
    replaceChildren(...items) { this.children = items; },
    append(...items) { this.children.push(...items); },
    setAttribute(name, value) { this.attributes[name] = value; },
    classList: { contains() { return false; }, toggle() {} }
  });
  const node = (selector) => {
    if (!nodes.has(selector)) nodes.set(selector, element());
    return nodes.get(selector);
  };
  const context = vm.createContext({
    document: { hidden: false, querySelector: node, querySelectorAll() { return []; }, createElement: element },
    window: { prompt() { return null; } },
    console, Date, Set, JSON, Math, Number, String, Boolean,
    localStorage: { getItem() { return 'false'; } }
  });
  vm.runInContext(functions, context);
  vm.runInContext(`
    renderMessages = () => {};
    showTyping = () => {};
    scrollToLatest = () => {};
    loadChats = async () => {};
    renderMood = () => {};
    refreshPresence = async () => {};
    resizeInput = () => {};
    currentChat = { id: 'chat_test', title: 'test', messages: [] };
  `, context);
  return { context, node, run: (text) => vm.runInContext(text, context) };
}

async function main() {
  const h = harness();
  const initialThought = { id: 'thought_1', role: 'assistant', content: '一个具体的新想法', proactive: true };
  const user = { id: 'user_1', role: 'user', content: '我有一个问题' };
  const reply = { id: 'reply_1', role: 'assistant', content: '现在回答你的问题' };
  let finishAnswer;
  let snapshot = [];
  h.context.requestStub = (url) => url.endsWith('/messages')
    ? new Promise((resolve) => { finishAnswer = resolve; })
    : Promise.resolve({ chat: { id: 'chat_test', title: 'test', messages: structuredClone(snapshot) } });
  h.run('request = requestStub');
  h.node('#message-input').value = user.content;
  const sending = h.run('sendMessage({ preventDefault() {} })');
  assert.equal(h.run('pendingMessage.message.content'), user.content);

  // The background remark finishes, but the server has not yet appended the user.
  snapshot = [initialThought];
  await h.run('claimProactiveMessage()');
  assert.deepEqual(JSON.parse(h.run('JSON.stringify(currentChat.messages.map(m => m.role))')), ['assistant', 'user']);
  assert.equal(h.run('currentChat.messages[0].content'), initialThought.content);
  assert.equal(h.run('currentChat.messages[1].content'), user.content);

  // The queued question starts; a poll must replace, not duplicate, the optimistic user.
  snapshot = [initialThought, user];
  await h.run('claimProactiveMessage()');
  await h.run('claimProactiveMessage()');
  assert.equal(h.run('currentChat.messages.length'), 2);
  assert.equal(h.run('currentChat.messages[1].id'), user.id);
  finishAnswer({ chat: { id: 'chat_test', messages: [initialThought, user, reply] }, mood: {} });
  await sending;
  assert.equal(h.run('currentChat.messages.length'), 3);
  assert.equal(h.run('pendingMessage'), null);
  assert.equal(h.run('isSending'), false);
  console.log('PASS: background remark appears first; queued user survives polling without duplicates.');

  // A poll that began before a send completed must not roll the chat backwards.
  let finishPoll;
  h.context.requestStub = () => new Promise((resolve) => { finishPoll = resolve; });
  h.run('request = requestStub');
  const stalePoll = h.run('claimProactiveMessage()');
  h.run("uiEpoch += 1; currentChat.messages.push({id: 'newer', role: 'assistant', content: 'newer'})");
  finishPoll({ chat: { id: 'chat_test', messages: [] } });
  await stalePoll;
  assert.equal(h.run('currentChat.messages.at(-1).id'), 'newer');
  console.log('PASS: stale polling responses cannot overwrite a newer turn.');

  // A poll may complete after the user switches conversations.
  const switchedPoll = h.run('claimProactiveMessage()');
  h.run("uiEpoch += 1; currentChat = {id: 'other', messages: []}");
  finishPoll({ chat: { id: 'chat_test', messages: [initialThought] } });
  await switchedPoll;
  assert.equal(h.run('currentChat.id'), 'other');
  assert.equal(h.run('currentChat.messages.length'), 0);
  console.log('PASS: late updates stay out of another conversation.');
}

module.exports = { harness };
if (require.main === module) main().catch((error) => { console.error(error); process.exitCode = 1; });
