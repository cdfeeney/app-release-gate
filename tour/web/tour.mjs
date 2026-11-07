#!/usr/bin/env node
// app-release-gate: generic screenshot tour for any web app (Playwright).
//
// The web twin of tour/ios/Tour.swift. Runs from the kit (nothing is copied into the app), follows the app's
// Gate/tour.json, and writes the SAME output: NNN-<fixture>-<flow>-<name>.png + .tree.txt per stop, index.json,
// taps.json, summary.json. The .tree.txt is written in XCUITest's debugDescription shape so rules/rules.py and
// reader/run.py read web and iOS tours alike. Deterministic: no LLM; Playwright clicks real DOM controls.
//
//   TOUR_PATH=<Gate/tour.json> TOUR_OUT=<dir> BASE_URL=http://localhost:3000 node tour.mjs
//
// Playwright is resolved from the app's own node_modules (the current directory), so the app pins its version.
// Schema: tour/web/SCHEMA.md.
import { createRequire } from 'node:module';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';

const require = createRequire(join(process.cwd(), 'package.json'));
const { chromium, devices } = require('@playwright/test');

const MAX_SCROLL_STOPS = 25;
const MAX_CANDIDATES = 3;
const SETTLE_DELAY_MS = 800;
const CHANGE_POLLS = 12;
const CHANGE_POLL_MS = 250;
const WAIT_FOR_MS = 15_000;

const manifestPath = resolve(process.env.TOUR_PATH ?? 'Gate/tour.json');
const outDir = resolve(process.env.TOUR_OUT ?? join(dirname(manifestPath), 'out'));
const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
const baseURL = process.env.BASE_URL || manifest.baseURL;
mkdirSync(outDir, { recursive: true });

const index = [];
const taps = [];
const problems = [];
let shotIndex = 0;
let seen = [];

const note = (problem, optional) => { if (optional !== true) problems.push(problem); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const normalized = (tree) => tree;   // the web dump carries no addresses or pids

// The DOM as an XCUITest-shaped tree. Runs in the page. Types follow XCUIElement.ElementType names the rules know:
// Button, Link, Switch, TextField, PopUpButton, Image, Cell, StaticText, Other. Frames are viewport points, as in
// the screenshot. Hidden elements are left out; elements scrolled off screen stay in, with their real frames.
function domTree() {
  const lines = [];
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim().slice(0, 300);
  // Hidden: nothing under it is drawn. Zero-size (a wrapper): not drawn itself, but its children may be.
  const hidden = (el) => {
    const s = getComputedStyle(el);
    return s.display === 'none' || s.visibility === 'hidden' || Number(s.opacity) === 0 || el.getAttribute('aria-hidden') === 'true';
  };
  const sized = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const typeOf = (el) => {
    const role = el.getAttribute('role');
    const tag = el.tagName.toLowerCase();
    const inputType = (el.getAttribute('type') || '').toLowerCase();
    if (role === 'switch' || role === 'checkbox' || role === 'radio' || (tag === 'input' && ['checkbox', 'radio'].includes(inputType))) return 'Switch';
    if (tag === 'button' || role === 'button' || role === 'tab' || role === 'menuitem' || role === 'option' || (tag === 'input' && ['button', 'submit', 'reset'].includes(inputType))) return 'Button';
    if ((tag === 'a' && el.hasAttribute('href')) || role === 'link') return 'Link';
    if (tag === 'input' || tag === 'textarea' || role === 'textbox' || role === 'searchbox' || el.isContentEditable) return 'TextField';
    if (tag === 'select' || role === 'combobox') return 'PopUpButton';
    if (tag === 'img' || tag === 'svg' || role === 'img') return 'Image';
    if (tag === 'li' || role === 'listitem' || role === 'row') return 'Cell';
    return null;
  };
  const ownText = (el) => clean([...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join(' '));
  const frame = (el) => {
    const r = el.getBoundingClientRect();
    return `{{${r.x.toFixed(1)}, ${r.y.toFixed(1)}}, {${r.width.toFixed(1)}, ${r.height.toFixed(1)}}}`;
  };
  let n = 0;
  const emit = (depth, type, el, attrs) => {
    n += 1;
    let line = `${'  '.repeat(depth)}${type}, 0x${n.toString(16)}, ${frame(el)}`;
    for (const [k, v] of Object.entries(attrs)) if (v) line += `, ${k}: '${v}'`;
    if (el.matches?.('[aria-selected="true"],[aria-pressed="true"],[aria-current]:not([aria-current="false"]),:checked')) line += ', Selected';
    if (el.matches?.(':disabled,[aria-disabled="true"]')) line += ', Disabled';
    lines.push(line);
  };
  const walk = (el, depth) => {
    if (!(el instanceof Element) || ['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE'].includes(el.tagName)) return;
    if (hidden(el)) return;
    if (!sized(el)) { for (const child of el.children) walk(child, depth); return; }
    const type = typeOf(el);
    const identifier = el.getAttribute('data-testid') || el.id || '';
    let childDepth = depth;
    if (type) {
      const label = clean(el.getAttribute('aria-label') || el.getAttribute('alt') || (type === 'TextField' ? '' : el.innerText));
      const value = type === 'TextField' || type === 'PopUpButton' ? clean(el.value ?? el.textContent) : '';
      emit(depth, type, el, { identifier, label, value, placeholderValue: clean(el.getAttribute('placeholder')) });
      childDepth = depth + 1;
      if (type === 'Image') return;
    } else if (identifier) {
      emit(depth, 'Other', el, { identifier, label: clean(el.getAttribute('aria-label')) });
      childDepth = depth + 1;
    }
    // Text drawn directly by this element is a StaticText, as SwiftUI's Text is. Controls already carry it as label.
    const text = ownText(el);
    if (text && !type) emit(childDepth, 'StaticText', el, { label: text });
    for (const child of el.children) walk(child, childDepth);
  };
  for (const child of document.body.children) walk(child, 2);
  const w = window.innerWidth, h = window.innerHeight;
  return `Attributes: Application, title: '${clean(document.title)}'\nElement subtree:\n →Application, 0x0, {{0.0, 0.0}, {${w}.0, ${h}.0}}, label: '${clean(document.title)}'\n${lines.join('\n')}\n`;
}

const tree = (page) => page.evaluate(domTree);
const identifiersIn = (text) => [...text.matchAll(/identifier: '([^']*)'/g)].map((m) => m[1]);
const remember = (ids) => { for (const id of ids) if (!seen.includes(id)) seen.push(id); };

// An identifier is a data-testid, an id, or an accessible name (iOS tours tap tabs by label).
function locate(page, id) {
  const esc = JSON.stringify(id);
  return page.locator(`[data-testid=${esc}], [id=${esc}], [aria-label=${esc}]`)
    .or(page.getByRole('button', { name: id, exact: true }))
    .or(page.getByRole('link', { name: id, exact: true }))
    .or(page.getByRole('tab', { name: id, exact: true }))
    .filter({ visible: true }).first();
}

async function capture(page, fixture, flow, screen, name) {
  shotIndex += 1;
  const base = `${String(shotIndex).padStart(3, '0')}-${fixture}-${flow}-${name}`;
  try {
    const png = await page.screenshot();
    const text = await tree(page);
    remember(identifiersIn(text));
    writeFileSync(join(outDir, `${base}.png`), png);
    writeFileSync(join(outDir, `${base}.tree.txt`), text);
    if (!png.length || !text) note(`capture ${base} is empty`, false);
  } catch (error) {
    note(`capture ${base} failed: ${error.message}`, false);
  }
  const vp = page.viewportSize();
  index.push({ n: shotIndex, fixture, flow, screen, name, png: `${base}.png`, tree: `${base}.tree.txt`, window: { width: vp.width, height: vp.height } });
}

// Wheel at the centre scrolls whichever container is under it (body or an inner scroll view), as a swipe would.
async function swipe(page, direction) {
  const vp = page.viewportSize();
  await page.mouse.move(vp.width / 2, vp.height / 2);
  await page.mouse.wheel(0, (direction === 'down' ? -1 : 1) * vp.height * 0.7);
  await sleep(400);
}

async function scrollToBottom(page, fixture, flow, screen, label) {
  let last = '';
  for (let position = 1; position <= MAX_SCROLL_STOPS; position += 1) {
    await capture(page, fixture, flow, screen, `${screen}-${String(position).padStart(2, '0')}`);
    const now = normalized(await tree(page));
    if (now === last) return;
    last = now;
    await swipe(page, 'up');
  }
  note(`${label}: ${screen} never stopped scrolling after ${MAX_SCROLL_STOPS} swipes; bottom not captured`, false);
}

// The main thread's answer 0.8 s after the tap: a frame plus a task. Work deferred past the tap (a debounced
// write, a long task) delays it, as XCUITest's idle wait does on iOS.
async function settle(page) {
  await sleep(SETTLE_DELAY_MS);
  const started = Date.now();
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0))));
  return Date.now() - started;
}

async function tap(page, id, label, expectChange, optional) {
  const target = locate(page, id);
  try {
    await target.scrollIntoViewIfNeeded({ timeout: 5_000 });
  } catch {
    if (optional !== true) taps.push({ identifier: id, step: label, changed: false, expected: expectChange, revealed: false });
    note(`${label}: ${id} not tappable (exists=${(await target.count()) > 0})`, optional);
    return;
  }
  const before = normalized(await tree(page));
  const started = Date.now();
  try {
    await target.click({ timeout: 10_000 });
  } catch (error) {
    taps.push({ identifier: id, step: label, changed: false, expected: expectChange, revealed: true });
    note(`${label}: tapping ${id} failed: ${error.message.split('\n')[0]}`, optional);
    return;
  }
  const idleMs = Date.now() - started;
  const settleMs = await settle(page);
  let changed = false;
  for (let i = 0; i < (expectChange ? CHANGE_POLLS : 1); i += 1) {
    if (normalized(await tree(page)) !== before) { changed = true; break; }
    if (expectChange) await sleep(CHANGE_POLL_MS);
  }
  const entry = { identifier: id, step: label, changed, expected: expectChange, ms: Date.now() - started, idleMs, settleMs };
  const perf = await appTimings(page);
  if (perf) entry.app = perf;
  taps.push(entry);
  if (expectChange && !changed) note(`${label}: tapping ${id} changed nothing on screen`, optional);
}

async function appTimings(page) {
  const text = await page.locator('[data-testid="gate-perf"]').first()
    .evaluate((el) => el.getAttribute('aria-valuetext') || el.getAttribute('aria-label') || el.textContent, null, { timeout: 200 })
    .catch(() => null);
  if (!text) return null;
  const values = Object.fromEntries([...text.matchAll(/(\w+)=(\d+)/g)].map((m) => [m[1], Number(m[2])]));
  return Object.keys(values).length ? values : null;
}

async function matching(page, pattern) {
  const regex = new RegExp(pattern);
  return [...new Set([...identifiersIn(await tree(page)), ...seen])].filter((id) => regex.test(id));
}

async function runFlow(page, flow, fixture) {
  seen = [];
  for (const [i, step] of flow.steps.entries()) {
    const label = `${fixture}/${flow.name}/step${i}`;
    if (step.background !== undefined) note(`${label}: background steps are iOS-only`, false);
    if (step.goto) {
      try { await page.goto(step.goto, { waitUntil: 'load' }); } catch (error) { note(`${label}: goto ${step.goto} failed: ${error.message.split('\n')[0]}`, step.optional); }
    }
    if (step.waitFor) {
      try { await locate(page, step.waitFor).waitFor({ state: 'visible', timeout: WAIT_FOR_MS }); } catch { note(`${label}: ${step.waitFor} never appeared`, step.optional); }
    }
    if (step.sleep) await sleep(step.sleep * 1000);
    if (step.swipe) await swipe(page, step.swipe);
    let target = step.tap;
    let optional = step.optional;
    if (!target && step.tapMatching) {
      const candidates = (await matching(page, step.tapMatching)).slice(0, MAX_CANDIDATES);
      if (!candidates.length) note(`${label}: no element matches ${step.tapMatching}`, step.optional);
      else {
        optional = false;   // the element exists in this app: from here on nothing about this step is optional
        for (const id of candidates) if ((await locate(page, id).count()) > 0) { target = id; break; }
        if (!target) {
          taps.push({ identifier: candidates[0], step: label, changed: false, expected: step.expectChange ?? true, revealed: false });
          note(`${label}: ${candidates.length} identifier(s) match ${step.tapMatching} but none could be revealed: ${candidates}`, false);
        }
      }
    }
    if (target) await tap(page, target, label, step.expectChange ?? true, optional);
    if (step.typeText) await page.keyboard.type(step.typeText);
    const screen = step.shot ?? `step${i}`;
    if (step.scrollToBottom) await scrollToBottom(page, fixture, flow.name, screen, label);
    else if (step.shot) await capture(page, fixture, flow.name, screen, screen);
  }
}

async function contextFor(browser, fixture) {
  const device = devices[manifest.device ?? 'iPhone 13'];
  if (!device) throw new Error(`unknown Playwright device ${manifest.device}`);
  const geo = fixture?.geolocation ?? manifest.geolocation;
  const context = await browser.newContext({
    ...device, baseURL, locale: manifest.locale ?? 'en-US', timezoneId: manifest.timezoneId ?? 'America/New_York',
    ...(geo ? { geolocation: geo, permissions: ['geolocation'] } : {}),
  });
  const storage = { ...(manifest.localStorage ?? {}), ...(fixture?.localStorage ?? {}) };
  await context.addInitScript((pairs) => {
    for (const [k, v] of Object.entries(pairs)) if (localStorage.getItem(k) === null) localStorage.setItem(k, v);
  }, storage);
  // Fixtures for the web are recorded API answers: each route serves a scrubbed JSON file instead of the network.
  for (const route of [...(manifest.routes ?? []), ...(fixture?.routes ?? [])]) {
    const body = readFileSync(join(dirname(manifestPath), route.file), 'utf8');
    await context.route(route.url, (r) => r.fulfill({ status: route.status ?? 200, contentType: 'application/json', body }));
  }
  return context;
}

async function main() {
  if (!baseURL) throw new Error('no BASE_URL and no baseURL in tour.json');
  const browser = await chromium.launch();
  const fixtures = manifest.fixtures?.length ? manifest.fixtures : [null];
  try {
    for (const fixture of fixtures) {
      const name = fixture?.name ?? 'default';
      const context = await contextFor(browser, fixture);
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      try {
        await page.goto(manifest.start ?? '/', { waitUntil: 'load' });
        for (const flow of manifest.flows) await runFlow(page, flow, name);
      } catch (error) {
        problems.push(`${name}: the tour stopped: ${error.message.split('\n')[0]}`);
      }
      // An uncaught page error is a crash the user would see as a dead screen.
      for (const e of [...new Set(errors)]) problems.push(`${name}: uncaught page error: ${e.split('\n')[0]}`);
      await context.close();
    }
  } finally {
    await browser.close();
  }
  if (!index.length) problems.push('the tour captured no screens');
  const write = (name, value) => writeFileSync(join(outDir, name), JSON.stringify(value, null, 2));
  write('index.json', index);
  write('taps.json', taps);
  write('summary.json', { problems, fixtures: fixtures.map((f) => f?.name ?? 'default'), screens: index.length });
  for (const p of problems) console.log('TOUR PROBLEM:', p);
  console.log(`${index.length} screens, ${taps.length} taps, ${problems.length} problems`);
  process.exit(problems.length ? 1 : 0);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
