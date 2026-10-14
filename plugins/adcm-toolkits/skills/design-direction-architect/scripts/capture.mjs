#!/usr/bin/env node
// Deterministic design captures: screenshots and design metrics of live sites, static shots of the variant pages, and an environment doctor.
//
// usage: capture.mjs (--board <board.json> | --urls <file.txt>) [--ids a,b] [--force] [--quick] [--concurrency 3] [--timeout 45] [--out <.design>]
//        capture.mjs --variants [--out <.design>]
//        capture.mjs --doctor [--out <.design>]
//   --board        board.json plus every board.d/*.json fragment; the references[] and market[] entries with a url are captured
//   --urls         a text file, one URL per line; the id is the slug of host and path
//   --ids          only these ids · --force recaptures what already has captures/{id}-d.jpg · --quick skips the -full.jpg
//   --concurrency  pages in flight (default 3) · --timeout seconds per navigation (default 45)
//   --out          the .design folder (default: the board's folder, else the cwd)
//   --variants     serves <out> over http and shoots variants/{a,b,c}.html into shots/opt-{id}-{d,m}.jpg
//   --doctor       checks node, playwright-core, chrome, an image tool, python3 and prints DOCTOR: ready|not ready
// Env: DDA_CHANNEL (default chrome) · PW_CORE_DIR (a playwright-core directory) · PEXELS_API_KEY (reported, never printed).
// Exit: 0 ok · 1 some capture failed · 2 no playwright-core/Chrome/Node<20 · 64 usage.
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';

const USAGE = [
  'usage: capture.mjs (--board <board.json> | --urls <file.txt>) [--ids a,b] [--force] [--quick] [--concurrency 3] [--timeout 45] [--out <.design>]',
  '       capture.mjs --variants [--out <.design>]',
  '       capture.mjs --doctor [--out <.design>]',
].join('\n');

const DESKTOP = { width: 1440, height: 900 };
const MOBILE = { width: 390, height: 844 };
const VARIANT_IDS = ['a', 'b', 'c'];
const JPEG = { type: 'jpeg', quality: 80, animations: 'disabled', caret: 'hide' };

const usageExit = (msg) => {
  if (msg) console.error(msg);
  console.error(USAGE);
  process.exit(64);
};

// ───────────────────────── args ─────────────────────────

function parseArgs(argv) {
  const o = { force: false, quick: false, variants: false, doctor: false, concurrency: 3, timeout: 45 };
  const value = (i, flag) => {
    if (i + 1 >= argv.length || argv[i + 1].startsWith('--')) usageExit(`${flag} needs a value`);
    return argv[i + 1];
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--help' || a === '-h') {
      console.log(USAGE);
      process.exit(0);
    } else if (a === '--force') o.force = true;
    else if (a === '--quick') o.quick = true;
    else if (a === '--variants') o.variants = true;
    else if (a === '--doctor') o.doctor = true;
    else if (['--board', '--urls', '--ids', '--out', '--concurrency', '--timeout'].includes(a)) o[a.slice(2)] = value(i++, a);
    else usageExit(`unknown argument: ${a}`);
  }
  o.concurrency = Number(o.concurrency);
  o.timeout = Number(o.timeout);
  if (!(o.concurrency >= 1) || !(o.timeout > 0)) usageExit('--concurrency and --timeout must be positive numbers');
  if (o.ids) o.ids = new Set(String(o.ids).split(',').map((s) => s.trim()).filter(Boolean));
  const modes = [o.doctor, o.variants, Boolean(o.board || o.urls)].filter(Boolean).length;
  if (modes !== 1 || (o.board && o.urls)) usageExit('pick one mode: --board/--urls, --variants or --doctor');
  return o;
}

// ───────────────────────── playwright ─────────────────────────
// keep in sync: explainer-video record.mjs

// [major, minor, patch, stable]: a release sorts above its own prereleases.
const versionParts = (v) => {
  const [core, pre] = String(v).split('-');
  return [...core.split('.').map(Number), pre ? 0 : 1];
};
const compareVersions = (a, b) => {
  const [x, y] = [versionParts(a), versionParts(b)];
  const i = x.findIndex((n, k) => n !== y[k]);
  return i < 0 ? 0 : x[i] - y[i];
};
const isStable = (v) => !String(v).includes('-');

function loadCore(dir) {
  const version = JSON.parse(fs.readFileSync(path.join(dir, 'package.json'), 'utf8')).version;
  return { dir, version, chromium: createRequire(import.meta.url)(dir).chromium };
}

const tryLoad = (dir) => {
  try {
    return loadCore(dir);
  } catch {
    return null;
  }
};

const expandHome = (p) => (p === '~' || p.startsWith('~/') ? path.join(os.homedir(), p.slice(1)) : p);

// Order: the project's node_modules (playwright-core, then playwright) → PW_CORE_DIR → the npx cache. The cache
// copy is picked newest stable first.
function resolvePlaywright() {
  const local = createRequire(path.join(process.cwd(), 'noop.js'));
  for (const name of ['playwright-core', 'playwright']) {
    let dir = null;
    try {
      dir = path.dirname(local.resolve(`${name}/package.json`));
    } catch {
      continue;
    }
    const core = tryLoad(dir);
    if (core) return core;
  }
  if (process.env.PW_CORE_DIR) return tryLoad(expandHome(process.env.PW_CORE_DIR));
  const cache = path.join(os.homedir(), '.npm', '_npx');
  const dirs = fs.existsSync(cache) ? fs.readdirSync(cache).map((d) => path.join(cache, d, 'node_modules', 'playwright-core')) : [];
  const found = dirs.filter((d) => fs.existsSync(path.join(d, 'package.json'))).map(tryLoad).filter(Boolean);
  found.sort((a, b) => isStable(b.version) - isStable(a.version) || compareVersions(b.version, a.version));
  return found[0] || null;
}

const channel = () => process.env.DDA_CHANNEL || 'chrome';
const nodeMajor = () => Number(process.versions.node.split('.')[0]);

// ───────────────────────── doctor ─────────────────────────

const hasCommand = (cmd, args) => spawnSync(cmd, args, { stdio: 'ignore' }).status === 0;

async function doctor(outDir) {
  const lines = [];
  const required = [];
  const add = (ok, label, detail, mustPass = true) => {
    lines.push(`${ok ? 'ok' : mustPass ? 'missing' : 'info'} ${label}${detail ? ` (${detail})` : ''}`);
    if (mustPass) required.push(ok);
  };

  add(nodeMajor() >= 20, 'node>=20', process.version);

  const core = resolvePlaywright();
  const coreOk = Boolean(core) && compareVersions(core.version, '1.61.0') >= 0;
  add(coreOk, 'playwright-core>=1.61', core ? core.dir : 'not found');

  let chromeOk = false;
  if (coreOk) {
    try {
      const browser = await core.chromium.launch({ headless: true, channel: channel() });
      await browser.close();
      chromeOk = true;
    } catch {}
  }
  add(chromeOk, 'chrome channel');

  let image = null;
  if (hasCommand('sips', ['--version'])) image = 'sips';
  else if (hasCommand('magick', ['-version'])) image = 'magick';
  add(Boolean(image), 'image tool', image || 'sips|magick');
  add(hasCommand('python3', ['--version']), 'python3');

  lines.push(`${process.env.PEXELS_API_KEY ? 'ok' : 'info'} PEXELS_API_KEY (${process.env.PEXELS_API_KEY ? 'present' : 'absent'})`);
  const insp = path.join(outDir, 'inspiration');
  lines.push(`${fs.existsSync(insp) ? 'ok' : 'info'} inspiration dir (${insp})`);

  const ready = required.every(Boolean);
  console.log([...lines, `DOCTOR: ${ready ? 'ready' : 'not ready'}`].join('\n'));
  process.exit(ready ? 0 : 2);
}

// ───────────────────────── board entries ─────────────────────────

const slugify = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 48).replace(/-+$/, '');

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (e) {
    usageExit(`cannot read ${file}: ${e.message}`);
  }
}

// Entries merge by id: board.d/*.json fragments by name (a later fragment overrides an earlier one), then board.json wins over all of them.
function boardEntries(boardFile) {
  const frag = path.join(path.dirname(boardFile), 'board.d');
  const files = [];
  if (fs.existsSync(frag)) {
    files.push(...fs.readdirSync(frag).filter((f) => f.endsWith('.json')).sort().map((f) => path.join(frag, f)));
  }
  files.push(boardFile);
  const byId = new Map();
  for (const file of files) {
    const doc = readJson(file);
    for (const key of ['references', 'market']) {
      for (const entry of Array.isArray(doc[key]) ? doc[key] : []) {
        if (entry && entry.id) byId.set(entry.id, { ...byId.get(entry.id), ...entry });
      }
    }
  }
  return [...byId.values()].filter((e) => e.url).map((e) => ({ id: String(e.id), url: String(e.url) }));
}

function urlEntries(urlsFile) {
  if (!fs.existsSync(urlsFile)) usageExit(`cannot read ${urlsFile}: no such file`);
  const urls = fs.readFileSync(urlsFile, 'utf8').split(/\r?\n/).map((l) => l.trim()).filter((l) => l && !l.startsWith('#'));
  const seen = new Set();
  const out = [];
  for (const url of urls) {
    let id;
    try {
      const u = new URL(url);
      id = slugify(u.host + u.pathname);
    } catch {
      id = slugify(url);
    }
    if (id && !seen.has(id)) {
      seen.add(id);
      out.push({ id, url });
    }
  }
  return out;
}

// ───────────────────────── page work ─────────────────────────

function httpError(status) {
  const err = new Error(`HTTP ${status}`);
  err.http = status;
  return err;
}

async function settle(page, url, timeoutMs) {
  // networkidle never settles on Framer or analytics-heavy sites: domcontentloaded, scroll to the end to wake lazy sections, then back.
  const response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: timeoutMs });
  if (response && response.status() >= 400) throw httpError(response.status());
  await page.waitForTimeout(4000);
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await page.waitForTimeout(2500);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(800);
}

// Colors are ranked by PAINTED AREA, not by count: the ground is whatever covers the most pixels, which is what the eye reads as the theme.
const extract = () => {
  const seen = { bg: {}, fg: {}, fonts: {}, type: {}, radius: {}, motion: new Set() };
  for (const el of document.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    const s = getComputedStyle(el), area = r.width * r.height;
    if (s.backgroundColor && s.backgroundColor !== 'rgba(0, 0, 0, 0)')
      seen.bg[s.backgroundColor] = (seen.bg[s.backgroundColor] || 0) + area;
    if (s.borderRadius && s.borderRadius !== '0px')
      seen.radius[s.borderRadius] = (seen.radius[s.borderRadius] || 0) + 1;
    if (s.transitionDuration && s.transitionDuration !== '0s')
      seen.motion.add(`${s.transitionProperty} ${s.transitionDuration} ${s.transitionTimingFunction}`);
    if (!el.childElementCount && el.textContent.trim()) {
      seen.fg[s.color] = (seen.fg[s.color] || 0) + area;
      const fam = s.fontFamily.split(',')[0].replace(/["']/g, '').trim();
      seen.fonts[fam] = (seen.fonts[fam] || 0) + 1;
      const k = `${s.fontSize} w${s.fontWeight} lh:${s.lineHeight} tt:${s.textTransform} ls:${s.letterSpacing} [${fam}]`;
      seen.type[k] = (seen.type[k] || 0) + 1;
    }
  }
  const top = (o, n) => Object.entries(o).sort((a, b) => b[1] - a[1]).slice(0, n)
    .map(([k, v]) => ({ value: k, weight: Math.round(v) }));
  const toHex = (c) => {
    const m = c.match(/\d+(\.\d+)?/g);
    return m && m.length >= 3 ? '#' + m.slice(0, 3).map((n) => Math.round(Number(n)).toString(16).padStart(2, '0')).join('') : null;
  };
  const painted = {};
  for (const group of [seen.bg, seen.fg]) {
    for (const [k, v] of Object.entries(group)) {
      const hex = toHex(k);
      if (hex) painted[hex] = (painted[hex] || 0) + v;
    }
  }
  // Framer leaves data-framer-name on sections: a free, human-readable section map.
  const sections = [...document.querySelectorAll('section, [data-framer-name], main > div')]
    .map(el => ({
      name: el.getAttribute('data-framer-name') || el.id || el.tagName.toLowerCase(),
      height: Math.round(el.getBoundingClientRect().height),
      text: (el.innerText || '').trim().slice(0, 90).replace(/\s+/g, ' '),
    }))
    .filter(s => s.height > 300)
    .slice(0, 20);
  return {
    ground: top(seen.bg, 8), ink: top(seen.fg, 6), palette: Object.entries(painted).sort((a, b) => b[1] - a[1]).slice(0, 6).map(([hex]) => hex), fonts: top(seen.fonts, 5),
    typeScale: top(seen.type, 14), radii: top(seen.radius, 5),
    motion: [...seen.motion].slice(0, 12),
    sections,
    docHeight: Math.round(document.body.scrollHeight),
  };
};

const errorLabel = (e) => {
  if (e && e.http) return `HTTP ${e.http}`;
  if (e && e.name === 'TimeoutError') return 'timeout';
  return String((e && e.message) || e).split('\n')[0].slice(0, 160);
};

async function withPage(browser, viewport, fn) {
  const page = await browser.newPage({ viewport });
  try {
    return await fn(page);
  } finally {
    await page.close();
  }
}

async function captureEntry(browser, entry, opts, dir) {
  const timeoutMs = opts.timeout * 1000;
  const base = path.join(dir, entry.id);
  const renames = ['d', 'm', 'full'].map((k) => [`${base}-${k}.jpg.tmp`, `${base}-${k}.jpg`]);
  try {
    const data = await withPage(browser, DESKTOP, async (page) => {
      await settle(page, entry.url, timeoutMs);
      const metrics = await page.evaluate(extract);
      await page.screenshot({ ...JPEG, path: `${base}-d.jpg.tmp` });
      if (!opts.quick) await page.screenshot({ ...JPEG, path: `${base}-full.jpg.tmp`, fullPage: true });
      return metrics;
    });
    await withPage(browser, MOBILE, async (page) => {
      await settle(page, entry.url, timeoutMs);
      await page.screenshot({ ...JPEG, path: `${base}-m.jpg.tmp` });
    });
    for (const [from, to] of renames) if (fs.existsSync(from)) fs.renameSync(from, to);
    fs.writeFileSync(`${base}.json`, JSON.stringify({ url: entry.url, ...data }, null, 1) + '\n');
    return null;
  } catch (e) {
    // A dead demo (4xx/5xx) or a navigation failure must not strand a Chrome process nor stop the run.
    const captureError = errorLabel(e);
    for (const [from, to] of renames) {
      fs.rmSync(from, { force: true });
      fs.rmSync(to, { force: true });
    }
    fs.writeFileSync(`${base}.json`, JSON.stringify({ url: entry.url, captureError }, null, 1) + '\n');
    return captureError;
  }
}

async function runPool(items, size, worker) {
  let next = 0;
  const lane = async () => {
    while (next < items.length) await worker(items[next++]);
  };
  await Promise.all(Array.from({ length: Math.min(size, items.length) }, lane));
}

// ───────────────────────── modes ─────────────────────────

async function launch(core) {
  try {
    return await core.chromium.launch({ headless: true, channel: channel() });
  } catch (e) {
    console.error(`cannot launch Chrome (channel ${channel()}): ${String(e.message).split('\n')[0]}`);
    process.exit(2);
  }
}

function needCore() {
  if (nodeMajor() < 20) {
    console.error(`Node 20+ required (found ${process.version})`);
    process.exit(2);
  }
  const core = resolvePlaywright();
  if (!core) {
    console.error('playwright-core not found: install it in the project, set PW_CORE_DIR, or run capture.mjs --doctor');
    process.exit(2);
  }
  return core;
}

const summary = (ok, failed) => {
  console.log(`CAPTURE: ${ok} ok · ${failed} failed`);
  process.exit(failed ? 1 : 0);
};

async function captureSites(opts, outDir) {
  const boardFile = opts.board ? path.resolve(opts.board) : null;
  let entries = boardFile ? boardEntries(boardFile) : urlEntries(path.resolve(opts.urls));
  if (opts.ids) entries = entries.filter((e) => opts.ids.has(e.id));
  const dir = path.join(outDir, 'captures');
  fs.mkdirSync(dir, { recursive: true });
  let ok = 0, failed = 0;
  const valid = entries.filter((e) => {
    let why = null;
    if (!/^[a-z0-9-]{1,48}$/.test(e.id)) why = 'invalid id';
    else if (!/^https?:\/\//.test(e.url)) why = 'url must be https?://';
    if (why) {
      failed++;
      console.error(`FAIL ${e.id}: ${why}`);
    }
    return !why;
  });
  const todo = valid.filter((e) => opts.force || !fs.existsSync(path.join(dir, `${e.id}-d.jpg`)));
  const core = needCore();
  if (!todo.length) summary(0, failed);
  const browser = await launch(core);
  try {
    await runPool(todo, opts.concurrency, async (entry) => {
      const err = await captureEntry(browser, entry, opts, dir);
      if (err) {
        failed++;
        console.error(`FAIL ${entry.id}: ${err}`);
      } else {
        ok++;
        console.log(`ok ${entry.id}`);
      }
    });
  } finally {
    await browser.close();
  }
  summary(ok, failed);
}

const MIME = {
  '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8', '.json': 'application/json', '.svg': 'image/svg+xml',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp',
  '.woff2': 'font/woff2', '.woff': 'font/woff',
};

// A static server on port 0: file:// gives an opaque origin that breaks the bridge and module scripts.
function serve(root) {
  const base = path.resolve(root);
  const server = http.createServer((req, res) => {
    const rel = decodeURIComponent((req.url || '/').split('?')[0]);
    const file = path.resolve(path.join(base, rel));
    if (file !== base && !file.startsWith(base + path.sep)) {
      res.writeHead(403).end();
      return;
    }
    fs.readFile(file, (err, body) => {
      if (err) {
        res.writeHead(404).end('not found');
        return;
      }
      res.writeHead(200, { 'content-type': MIME[path.extname(file).toLowerCase()] || 'application/octet-stream' });
      res.end(body);
    });
  });
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server)));
}

async function captureVariants(opts, outDir) {
  const core = needCore();
  const shots = path.join(outDir, 'shots');
  fs.mkdirSync(shots, { recursive: true });
  const server = await serve(outDir);
  const origin = `http://127.0.0.1:${server.address().port}`;
  const browser = await launch(core);
  const timeoutMs = opts.timeout * 1000;
  let ok = 0, failed = 0;
  try {
    for (const id of VARIANT_IDS) {
      const marker = path.join(shots, `opt-${id}.json`);
      try {
        for (const [suffix, viewport] of [['d', DESKTOP], ['m', MOBILE]]) {
          await withPage(browser, viewport, async (page) => {
            const response = await page.goto(`${origin}/variants/${id}.html`, { waitUntil: 'load', timeout: timeoutMs });
            if (!response || response.status() >= 400) throw httpError(response ? response.status() : 'none');
            await page.evaluate(() => document.fonts && document.fonts.ready);
            await page.waitForTimeout(500);
            await page.screenshot({ ...JPEG, path: path.join(shots, `opt-${id}-${suffix}.jpg`) });
          });
        }
        fs.rmSync(marker, { force: true });
        ok++;
        console.log(`ok opt-${id}`);
      } catch (e) {
        failed++;
        const captureError = errorLabel(e);
        fs.writeFileSync(marker, JSON.stringify({ captureError }, null, 1) + '\n');
        console.error(`FAIL opt-${id}: ${captureError}`);
      }
    }
  } finally {
    await browser.close();
    server.close();
  }
  summary(ok, failed);
}

// ───────────────────────── main ─────────────────────────

const opts = parseArgs(process.argv.slice(2));
const defaultOut = () => {
  if (opts.board) return path.dirname(path.resolve(opts.board));
  return fs.existsSync(path.resolve('.design')) ? path.resolve('.design') : process.cwd();
};
const outDir = path.resolve(opts.out || defaultOut());
if (opts.doctor) await doctor(outDir);
else if (opts.variants) await captureVariants(opts, outDir);
else await captureSites(opts, outDir);
