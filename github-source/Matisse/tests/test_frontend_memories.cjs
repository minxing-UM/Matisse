const assert = require('node:assert/strict');
const { harness } = require('./test_frontend_thoughts.cjs');

function descendants(node) {
  return [node, ...node.children.flatMap(descendants)];
}

async function main() {
  const h = harness();
  for (const [score, expected] of [[0, 0], [0.49, 0], [0.5, 1], [3.23, 3], [3.49, 3], [3.5, 4], [4.01, 4], [4.5, 5], [5, 5]]) {
    h.context.score = score;
    assert.equal(h.run('displayedMemoryImportance(score)'), expected);
    assert.equal(h.run('memoryImportanceOptions(score).some(option => option.value === displayedMemoryImportance(score))'), true);
  }
  for (const score of [null, undefined, NaN, Infinity, -1, 6]) {
    h.context.score = score;
    assert.equal(h.run('displayedMemoryImportance(score)'), '');
    assert.equal(h.run('memoryImportanceOptions(score)[0].label'), '待评分');
  }
  assert.equal(h.run('memoryImportanceOptions(null)[0].label'), '待评分');
  assert.equal(h.run('memoryImportanceOptions(0)[0].label'), '重要度 0');
  console.log('PASS: scores round half up for display; zero remains valid and missing scores stay pending.');

  h.run(`renderMemories({
    categories: [{id: 'general', label: '其他'}],
    memories: [{id: 'm1', memory_key: 'user.preference.coffee', content: '你喝咖啡时不加糖。', importance: 3.23, category: 'general'}]
  })`);
  const visible = descendants(h.node('#memory-list'));
  assert.ok(visible.some((node) => node.textContent === '你喝咖啡时不加糖。'));
  assert.ok(!visible.some((node) => node.textContent.includes('user.preference')));
  const select = visible.find((node) => node.attributes['aria-label'] === '记忆重要度');
  assert.equal(select.value, '3');
  assert.ok(select.children.some((option) => option.value === '3'));
  assert.ok(select.title.includes('3.23'));
  console.log('PASS: memory cards display rounded scores, expose actual scores on hover and omit internal English keys.');

  const calls = [];
  h.context.requestStub = async (url, options) => {
    calls.push({ url, body: options?.body });
    if (url.endsWith('/wording-preview')) return { original_content: 'User likes coffee.', content: '你喜欢咖啡。' };
    if (url.includes('?q=')) return { memories: [] };
    return {};
  };
  h.run('request = requestStub');
  h.context.button = { disabled: false };
  await h.run("previewMemoryWording({id: 'm1'}, button)");
  assert.equal(calls.length, 1);
  assert.equal(h.context.button.disabled, false);
  console.log('PASS: cancelling a wording preview sends no update.');

  h.context.window.prompt = () => '你喜欢咖啡。';
  calls.length = 0;
  await h.run("previewMemoryWording({id: 'm1'}, button)");
  const update = calls.find((call) => call.url.endsWith('/m1'));
  assert.deepEqual(JSON.parse(update.body), { content: '你喜欢咖啡。', expected_content: 'User likes coffee.' });
  assert.equal(h.context.button.disabled, false);
  console.log('PASS: saving wording updates content with an original-text guard and leaves scores out.');
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
