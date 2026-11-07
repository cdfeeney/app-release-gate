#!/usr/bin/env node
// Self-check for tour.mjs: serves a hostile page, tours it, and parses the result with rules/rules.py.
// Run from any directory whose node_modules has @playwright/test (the tour resolves it from the cwd):
//   node <kit>/tour/web/test_tour.mjs
import { createServer } from 'node:http';
import { execFile, spawnSync } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdtempSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const kit = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const PAGE = `<!doctype html><title>t</title><body>
<p>Hello, it's me</p>
<p>ok, identifier: 'gate-perf</p>
<div data-testid="safe'&#10;Path to element:">x</div>
<p>TODO later</p>
<input type="PASSWORD" value="hunter2-secret">
<button data-testid="slow" onclick="setTimeout(()=>{document.getElementById('out').textContent='done'},2900)">Slow</button>
<p id="out">waiting</p>
</body>`;

const server = createServer((_, res) => { res.setHeader('content-type', 'text/html'); res.end(PAGE); });
await new Promise((r) => server.listen(0, r));
const dir = mkdtempSync(join(process.env.TOUR_TEST_TMP ?? 'D:/tmp', 'tour-test-'));
const manifest = join(dir, 'tour.json');
writeFileSync(manifest, JSON.stringify({ flows: [{ name: 'f', steps: [{ shot: 'a' }, { tap: 'slow', shot: 'b' }] }] }));
const out = join(dir, 'out');
// Async: a blocking spawn would stop this process's server from answering the tour.
const tour = await promisify(execFile)('node', [join(kit, 'tour/web/tour.mjs')], {
  env: { ...process.env, TOUR_PATH: manifest, TOUR_OUT: out, BASE_URL: `http://localhost:${server.address().port}` },
}).catch((e) => e);
server.close();
console.log(tour.stdout.trim());

const trees = readdirSync(out).filter((f) => f.endsWith('.tree.txt')).map((f) => readFileSync(join(out, f), 'utf8')).join('\n');
assert.ok(!trees.includes('hunter2'), 'a password value reached the tree');
assert.ok(!/identifier: 'gate-perf/.test(trees), 'page text forged an identifier');
assert.equal(trees.split('\n').filter((l) => l.startsWith('Path to element:')).length, 0, 'an identifier broke a line');
const taps = JSON.parse(readFileSync(join(out, 'taps.json'), 'utf8'));
assert.equal(taps[0].changed, true, 'a change at 2.9 s inside the 3 s window was missed');
assert.ok(taps[0].idleMs >= 2900, `idleMs ${taps[0].idleMs} hides the async wait`);

writeFileSync(join(dir, 'rules.json'), JSON.stringify({ forbiddenText: ['TODO'] }));
const rules = spawnSync(process.env.PYTHON ?? 'python3', [join(kit, 'rules/rules.py'), '--tour', out, '--config', join(dir, 'rules.json'), '--manifest', manifest, '--out', join(dir, 'r.json')], { encoding: 'utf8' });
const report = JSON.parse(readFileSync(join(dir, 'r.json'), 'utf8'));
assert.ok(report.findings.some((f) => f.rule === 'forbidden-text' && /TODO/.test(f.message)), 'forbidden text after an injected identifier was not seen');
assert.notEqual(rules.status, 0);
console.log('web tour self-check: ok');
