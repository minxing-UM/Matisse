const assert = require('node:assert/strict');
const fs = require('node:fs');
const { harness } = require('./test_frontend_thoughts.cjs');

// The shared harness stubs rendering for queue tests; restore the actual function.
const source = fs.readFileSync('app/frontend/app.js', 'utf8');
const render = source.slice(source.indexOf('function renderMood('), source.indexOf('async function refreshMood('));
const h = harness();
h.node('#portrait-stage').dataset = {};
h.run(render);
h.run('renderMood({values: {sadness: 63.5, happiness: 10}})');
const rows = h.node('#mood-values').children;
const sadness = rows.find(row => row.children[0].textContent === '悲伤');
assert.ok(sadness);
assert.equal(sadness.children[1].textContent, '63.5');
assert.equal(sadness.children[2].children[0].style.width, '63.5%');
assert.equal(h.node('#portrait-stage').dataset.mood, 'sad');
console.log('PASS: sadness appears in the mood panel and selects the sad portrait state.');

h.run('renderMood({values: {happiness: 20}})');
const legacySadness = h.node('#mood-values').children.find(row => row.children[0].textContent === '悲伤');
assert.equal(legacySadness.children[1].textContent, '0.0');
assert.equal(h.node('#portrait-stage').dataset.mood, 'calm');
console.log('PASS: legacy mood payloads without sadness display safely as zero.');
