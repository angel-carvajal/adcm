#!/usr/bin/env node
// Deterministic explainer-video recorder: runs a guion over a local web app with a synthetic voice, subtitles and
// an overlay, and leaves mp4 + srt + poster + contact sheet + dom dump under the config's outDir.
//
// usage: record.mjs <ids...>|--all [--check|--dry|--verify|--doctor] [--mute] [--config <path>]
//   <ids...>  guiones by id (01, 02, ...) · --all every guion in guionesDir
//   --check   validates the guiones against the strict schema and prints the estimated duration (no ids = all)
//   --dry     runs the actions with no camera or voice (validates selectors; it DOES change the local app's data)
//   --verify  checks every mp4 and writes <outDir>/manifest.json
//   --doctor  checks node, playwright-core, browser, ffmpeg, ffprobe and the voice (one real word is synthesized); prints a recipe for what is missing
//   --mute    records with silence of the estimated durations instead of a voice (offline, deterministic)
//   --config  config file, relative to the cwd (default videos/config.json); every path inside it is relative to it
// Env: REC_TTS (edge|piper|say) · REC_VOICE · REC_RATE · REC_TTS_HOME (default ~/.local/share/adcm-voz) ·
//      REC_CHANNEL (default chrome) · PW_CORE_DIR (a playwright-core directory).
// Exit: 0 ok · 1 failure · 2 config/guard/voice not ready/Node<20 · 3 configured fonts not loaded ·
//       4 no page.screencast · 64 argument errors · 130 interrupted (Ctrl-C).
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { stripVTControlCharacters } from 'node:util';
import { Fail, fillPlaceholders, hostAllowed, isFail, loadConfig, redact } from './lib/config.mjs';
import * as media from './lib/media.mjs';
import { TARGETS, estimate, loadGuiones, validateGuion } from './lib/schema.mjs';
import { fontsLoaded, guardHosts, installOverlay, runSetup, setupFor } from './lib/setup.mjs';
import { NAV, absoluteUrl, runStep, sleep, stepFail } from './lib/steps.mjs';

const OVERLAY = path.join(path.dirname(fileURLToPath(import.meta.url)), 'lib', 'overlay.js');
const USAGE = 'usage: record.mjs <ids...>|--all [--check|--dry|--verify|--doctor] [--mute] [--config <path>]';
const MODES = ['--check', '--dry', '--verify', '--doctor'];
const MIN_PLAYWRIGHT = '1.61.0';
const PLAYWRIGHT_ITEM = `playwright-core>=${MIN_PLAYWRIGHT.replace(/\.0$/, '')}`;
const PLAYWRIGHT_RECIPE = 'npx -y -p playwright-core@1.63 node -e 0 (or set PW_CORE_DIR)';
const NEEDS_NODE = 'not checked: needs node>=20';
const KINDS = {
  mp4: { dir: 'mp4', ext: 'mp4' },
  srt: { dir: 'srt', ext: 'srt' },
  poster: { dir: 'posters', ext: 'png' },
  sheet: { dir: 'sheets', ext: 'png' },
  dom: { dir: 'dom', ext: 'txt' },
};

const log = (text) => console.log(redact(text));
const offList = (config) => `outside allowHosts (${config.allowHosts.join(', ')}): recordings only run against a local stack`;
const rel = (p) => path.relative(process.cwd(), p) || '.';
const nodeMajor = () => Number(process.versions.node.split('.')[0]);
const ceilTenth = (s) => Math.ceil(s * 10 - 1e-9) / 10;

// The first exit wins: closing the browser during cleanup makes the main flow fail, and that must not override the code.
const cleanups = [];
let exiting = false;
async function die(code, message) {
  if (exiting) return new Promise(() => {});
  exiting = true;
  if (message) console.error(redact(message));
  for (const fn of cleanups.splice(0).reverse()) await Promise.race([Promise.resolve(fn()).catch(() => {}), sleep(5000)]);
  // With stdout on a pipe, exit can cut the last thing printed.
  await Promise.all([process.stdout, process.stderr].map((out) => new Promise((resolve) => out.write('', resolve))));
  process.exit(code);
}

// ───────────────────────── CLI ─────────────────────────

const argError = (message) => {
  throw new Fail(64, `${USAGE}\nrecord.mjs: error: ${message}`);
};

function parseArgs(argv) {
  const o = { ids: [], all: false, mode: 'record', mute: false, config: 'videos/config.json', help: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--help' || a === '-h') o.help = true;
    else if (a === '--all') o.all = true;
    else if (a === '--mute') o.mute = true;
    else if (a === '--config') o.config = argv[++i] ?? argError('--config needs a path');
    else if (a.startsWith('--config=')) o.config = a.slice('--config='.length) || argError('--config needs a path');
    else if (MODES.includes(a)) {
      if (o.mode !== 'record') argError(`${MODES.join(', ')} are mutually exclusive`);
      o.mode = a.slice(2);
    } else if (/^\d{1,2}$/.test(a)) o.ids.push(a.padStart(2, '0'));
    else argError(`unrecognized argument "${a}"`);
  }
  if (o.help) return o;
  if (o.mute && o.mode !== 'record') argError('--mute only applies to recording');
  if (o.mode === 'doctor' && (o.ids.length || o.all)) argError('--doctor takes no ids');
  if (o.all && o.ids.length) argError('give ids or --all, not both');
  if (!['check', 'doctor'].includes(o.mode) && !o.all && !o.ids.length) argError('give ids or --all');
  return o;
}

// --help prints the usage block of this file's header, so the two never drift apart.
function helpText() {
  const lines = fs.readFileSync(fileURLToPath(import.meta.url), 'utf8').split('\n');
  const from = lines.findIndex((l) => l.startsWith('// usage:'));
  const to = lines.findIndex((l, i) => i > from && !l.startsWith('//'));
  return lines.slice(from, to).map((l) => l.replace(/^\/\/ ?/, '')).join('\n');
}

// ───────────────────────── playwright ─────────────────────────

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
  if (process.env.PW_CORE_DIR) return tryLoad(media.expand(process.env.PW_CORE_DIR));
  const cache = path.join(os.homedir(), '.npm', '_npx');
  const dirs = fs.existsSync(cache) ? fs.readdirSync(cache).map((d) => path.join(cache, d, 'node_modules', 'playwright-core')) : [];
  const found = dirs.filter((d) => fs.existsSync(path.join(d, 'package.json'))).map(tryLoad).filter(Boolean);
  found.sort((a, b) => isStable(b.version) - isStable(a.version) || compareVersions(b.version, a.version));
  return found[0] || null;
}

const channel = () => process.env.REC_CHANNEL || 'chrome';

async function launch(pw, view) {
  const args = channel() === 'chrome' ? [`--window-size=${view.width},${view.height}`] : [];
  return pw.chromium.launch({ channel: channel(), headless: true, args });
}

// ───────────────────────── doctor ─────────────────────────

async function probeBrowser(pw, view) {
  try {
    const browser = await launch(pw, view);
    const page = await browser.newPage();
    const screencast = typeof page.screencast?.start === 'function';
    await browser.close();
    return { screencast };
  } catch (e) {
    return { error: stripVTControlCharacters(String(e.message)).split('\n')[0] };
  }
}

function playwrightLine(pw, probe) {
  if (!pw) return [false, PLAYWRIGHT_ITEM, `not found: ${PLAYWRIGHT_RECIPE}`];
  if (compareVersions(pw.version, MIN_PLAYWRIGHT) < 0) return [false, PLAYWRIGHT_ITEM, `found ${pw.version}: ${PLAYWRIGHT_RECIPE}`];
  if (probe.screencast === false) return [false, PLAYWRIGHT_ITEM, `${pw.version} has no page.screencast: ${PLAYWRIGHT_RECIPE}`];
  return [true, PLAYWRIGHT_ITEM, `${pw.version}, ${probe.screencast ? 'screencast' : 'screencast unverified'}`];
}

const browserLine = (probe) =>
  probe.error
    ? [false, 'browser channel', `${channel()}: ${probe.error}; install Google Chrome, or set REC_CHANNEL=chromium after npx playwright-core install chromium`]
    : [true, 'browser channel', channel()];

async function voiceLines(config) {
  const v = media.resolveVoice(config.voice);
  const home = media.ttsHome();
  const homeOk = v.name === 'say' || fs.existsSync(home);
  const bad = await media.voiceCheck(v);
  const others = config.fallbacks.filter((e) => e !== v.name);
  const fallback = others.length ? ` (or set REC_TTS=${others.join('|')})` : '';
  return [
    bad ? [false, 'voice engine', `${bad.problem}: ${bad.fix || `${media.VOICE_RECIPE}${fallback}`}`] : [true, 'voice engine', v.label],
    homeOk ? [true, 'voice home', v.name === 'say' ? 'not needed for say' : home] : [false, 'voice home', `${home} does not exist: ${media.VOICE_RECIPE}`],
  ];
}

async function toolLine(bin) {
  const version = await media.toolVersion(bin);
  return version ? [true, bin, version.replace(/^\S+ version /, '').split(' ')[0]] : [false, bin, 'brew install ffmpeg (or your package manager)'];
}

async function runDoctor(config) {
  // playwright-core ends the process when loaded under Node < 20: neither it nor the browser is touched then.
  const oldNode = nodeMajor() < 20;
  const pw = oldNode ? null : resolvePlaywright();
  const probe = pw ? await probeBrowser(pw, config.viewport) : { error: 'playwright-core not resolved' };
  const lines = [
    oldNode ? [false, 'node>=20', `found ${process.versions.node}: install Node 20+ (nvm install 22) and put it first on PATH`] : [true, 'node>=20', process.versions.node],
    oldNode ? [false, PLAYWRIGHT_ITEM, NEEDS_NODE] : playwrightLine(pw, probe),
    oldNode ? [false, 'browser channel', NEEDS_NODE] : browserLine(probe),
    await toolLine('ffmpeg'),
    await toolLine('ffprobe'),
    ...(await voiceLines(config)),
  ];
  for (const [ok, item, detail] of lines) log(ok ? `ok ${item} (${detail})` : `missing ${item} — ${detail}`);
  const ready = lines.every(([ok]) => ok);
  log(`DOCTOR: ${ready ? 'ready' : 'not ready'}`);
  return ready ? 0 : 2;
}

// ───────────────────────── selection and check ─────────────────────────

function catalog(config) {
  if (!fs.existsSync(config.guionesDir)) throw new Fail(2, `guionesDir not found: ${config.guionesDir}`);
  const entries = loadGuiones(config.guionesDir);
  const ids = new Map();
  for (const e of entries) if (typeof e.data?.id === 'string') ids.set(e.data.id, [...(ids.get(e.data.id) || []), e.file]);
  const byId = new Map(entries.filter((e) => e.data).map((e) => [e.data.id, e.data]));
  return { entries, byId, ctx: { ids, profiles: config.profiles, mail: config.mail } };
}

function select(o, cat) {
  if (!o.ids.length) return cat.entries;
  return o.ids.map((id) => cat.entries.find((e) => e.data?.id === id) || argError(`no guion with id ${id}`));
}

function runCheck(selected, cat, config) {
  const v = media.resolveVoice(config.voice);
  const [min, max] = config.durationWindow;
  let failed = 0;
  log(`voice: ${v.label} (${v.msPerChar} ms/char)`);
  for (const e of selected) {
    const problems = validateGuion(e, cat.ctx);
    if (problems.length) {
      failed++;
      console.error(`FAIL ${e.file}`);
      for (const p of problems) console.error(`  - ${p}`);
      continue;
    }
    const g = e.data;
    const secs = estimate(g, { msPerChar: v.msPerChar, pronunciation: config.pronunciation, hasNext: cat.byId.has(g.next) });
    log(`OK ${g.id} ${g.slug} ${g.steps.length} steps ~${Math.round(secs)}s`);
    if (secs < min || secs > max) log(`  warning: ~${Math.round(secs)}s outside the ${min}-${max} s window`);
    if (g.next && !cat.byId.has(g.next)) log(`  warning: next "${g.next}" does not exist yet`);
  }
  log(failed ? `${selected.length - failed} OK, ${failed} FAIL` : `${selected.length} OK`);
  return failed ? 1 : 0;
}

function assertValid(selected, cat) {
  const invalid = selected.map((e) => ({ e, bad: validateGuion(e, cat.ctx) })).filter((x) => x.bad.length);
  if (invalid.length) throw new Fail(1, invalid.map(({ e, bad }) => `${e.file}: ${bad.join('; ')}`).join('\n'));
  return selected.map((e) => e.data);
}

// ───────────────────────── guards ─────────────────────────

// Static half of the host guard: everything the run will navigate to or fetch from Node must be an allowed host,
// and every {{env:VAR}} must resolve, before a browser opens.
function assertGuards(guiones, config) {
  const deny = (what, url) => {
    throw new Fail(2, `${what} ${url} is ${offList(config)}`);
  };
  if (!hostAllowed(config.baseUrl, config.allowHosts)) deny('baseUrl', config.baseUrl);
  if (config.mail && !hostAllowed(config.mail.url, config.allowHosts)) deny('mail.url', config.mail.url);
  for (const g of guiones) {
    for (const s of [...setupFor(config, g), ...g.steps]) {
      fillPlaceholders(s.value, config.timezone);
      if (s.action === 'goto' && !hostAllowed(absoluteUrl(s.value, config.baseUrl), config.allowHosts)) deny(`guion ${g.id}: goto`, s.value);
    }
  }
}

async function assertVoice(config) {
  const v = media.resolveVoice(config.voice);
  const bad = await media.voiceCheck(v);
  if (!bad) return v;
  const hint = config.fallbacks.length ? `; fallbacks are never applied silently: set REC_TTS=${config.fallbacks[0]} (or ${config.fallbacks.join('|')}) to use one` : '';
  throw new Fail(2, `voice not ready: ${bad.problem}${hint} (record.mjs --doctor prints the recipe)`);
}

function assertPlaywright(dry) {
  const pw = resolvePlaywright();
  if (!pw) throw new Fail(2, `playwright-core not found: ${PLAYWRIGHT_RECIPE}`);
  if (!dry && compareVersions(pw.version, MIN_PLAYWRIGHT) < 0) throw new Fail(4, `playwright-core ${pw.version} predates page.screencast: ${PLAYWRIGHT_RECIPE}`);
  return pw;
}

async function assertServer(config) {
  const up = await fetch(config.baseUrl, { redirect: 'manual', signal: AbortSignal.timeout(10000) }).then(() => true, () => false);
  if (!up) throw new Fail(2, `the app does not respond at ${config.baseUrl}`);
}

// ───────────────────────── lock ─────────────────────────

const alive = (pid) => {
  try {
    process.kill(pid, 0);
    return true;
  } catch (e) {
    return e.code === 'EPERM';
  }
};

// Who holds the lock, or null. An empty or unreadable pid may be a lock being written: it is re-read 3 times
// (50 ms) and, if still unreadable, counts as busy instead of orphaned.
async function lockHolder(lock) {
  for (let i = 0; i < 3; i++) {
    let raw;
    try {
      raw = fs.readFileSync(lock, 'utf8').trim();
    } catch (e) {
      if (e.code === 'ENOENT') return null;
      throw e;
    }
    const pid = Number(raw);
    if (raw && Number.isInteger(pid) && pid > 0) return { pid, running: alive(pid) };
    await sleep(50);
  }
  return { pid: 0, running: true };
}

const busy = (holder, lock) => `another recorder is running (pid ${holder.pid || '?'}); if it does not exist, delete ${rel(lock)}`;

const releaseOnExit = (lock) =>
  process.on('exit', () => {
    try {
      if (fs.readFileSync(lock, 'utf8').trim() === String(process.pid)) fs.unlinkSync(lock);
    } catch {
      // the lock is already gone
    }
  });

// The lock is born complete: written aside and hard-linked (link fails with EEXIST if it exists), so nobody reads
// it empty between its creation and the pid write.
async function acquireLock(outDir) {
  const lock = path.join(outDir, '.lock');
  fs.mkdirSync(outDir, { recursive: true });
  const mine = `${lock}.${process.pid}`;
  fs.writeFileSync(mine, String(process.pid));
  try {
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        fs.linkSync(mine, lock);
        releaseOnExit(lock);
        return;
      } catch (e) {
        if (e.code !== 'EEXIST') throw e;
      }
      const holder = await lockHolder(lock);
      if (!holder) continue;
      if (holder.running) throw new Fail(2, busy(holder, lock));
      fs.rmSync(lock, { force: true });
    }
    throw new Fail(2, `could not take the lock ${rel(lock)}`);
  } finally {
    fs.rmSync(mine, { force: true });
  }
}

// --verify only reads: it takes no lock, but it does not run over files a recorder is rewriting.
async function assertNotRecording(outDir) {
  const lock = path.join(outDir, '.lock');
  const holder = await lockHolder(lock);
  if (holder?.running) throw new Fail(2, busy(holder, lock));
}

// ───────────────────────── recording ─────────────────────────

const stepLabel = (step, i, total) => `step ${i + 1}/${total} (${step.action}${step.selector ? ' ' + step.selector : ''})`;

// The voice leads: every clip exists (and has a duration) before the camera starts.
async function synthesize(g, work, run) {
  const clips = [];
  for (const [i, step] of g.steps.entries()) {
    const text = media.voiceText(step, run.config.pronunciation);
    const base = path.join(work, `step-${String(i + 1).padStart(2, '0')}`);
    const file = run.mute
      ? await media.silence((text.length * run.voice.msPerChar) / 1000, `${base}.wav`)
      : await media.tts(text, base, run.voice).catch((e) => {
          throw new Fail(1, `step ${i + 1}: ${e.message}`);
        });
    const d = await media.duration(file);
    if (!(d > 0.2)) throw new Fail(1, `step ${i + 1}: the voice came out empty`);
    clips.push({ file, d, chars: text.length });
  }
  return clips;
}

async function openBrowser(run) {
  const { config } = run;
  const browser = await launch(run.pw, config.viewport);
  const close = () => browser.close().catch(() => {});
  cleanups.push(close);
  // clipboard-write: without it a "Copy" button falls back to a manual-copy prompt in headless Chromium.
  const context = await browser.newContext({
    viewport: config.viewport, locale: config.locale, timezoneId: config.timezone, deviceScaleFactor: 1,
    permissions: ['clipboard-write'],
  });
  context.setDefaultTimeout(15000);
  await guardHosts(context, config.allowHosts, (url) => die(2, `the page requested ${url}, ${offList(config)}`));
  const page = await context.newPage();
  const done = async () => {
    await close();
    cleanups.splice(cleanups.indexOf(close), 1);
  };
  return { context, page, done };
}

// Cursor and overlay state of one take.
function stage(page, view, dry) {
  const st = { top: '', sub: '', pos: 'bottom' };
  const mouse = { at: null };
  const apply = () => page.evaluate((s) => window.__rec && window.__rec.set(s), { ...st }).catch(() => {});
  const nearBottom = (box) => Boolean(box) && box.y + box.height > view.height - 150;
  const probeBox = (sel) => page.locator(sel).first().boundingBox({ timeout: 600 }).catch(() => null);
  const clamp = (n, max) => Math.min(Math.max(Math.round(n), 2), max - 2);

  const before = async (sel) => {
    const loc = page.locator(sel).first();
    await loc.scrollIntoViewIfNeeded({ timeout: 3000 }).catch(() => {});
    const box = await loc.boundingBox({ timeout: 1000 }).catch(() => null);
    if (!box || dry) return;
    if (nearBottom(box) && st.pos !== 'top') {
      st.pos = 'top';
      await apply();
    }
    const x = clamp(box.x + box.width / 2, view.width);
    const y = clamp(box.y + box.height / 2, view.height);
    // From the parking corner the synthetic cursor would take a detour: the real mouse goes back first.
    if (mouse.at) await page.mouse.move(mouse.at.x, mouse.at.y);
    await page.mouse.move(x, y, { steps: 20 });
    mouse.at = { x, y };
    await page.waitForTimeout(450);
  };
  const park = () => page.mouse.move(view.width - 4, 4).catch(() => {});

  // A narration-only step with the cursor over the subtitle lifts it out of the way first.
  const liftCursor = async () => {
    if (!mouse.at || mouse.at.y <= view.height - 150) return;
    const y = view.height - 190;
    await page.mouse.move(mouse.at.x, mouse.at.y);
    await page.mouse.move(mouse.at.x, y, { steps: 12 });
    mouse.at = { x: mouse.at.x, y };
  };
  return { st, apply, nearBottom, probeBox, before, park, liftCursor };
}

// Starts the screencast and returns t0 = the first frame's timestamp (ms since epoch), so voice and video share a clock.
async function startCamera(page, webm, view) {
  let firstTs = 0;
  let gotFirst;
  const firstFrame = new Promise((resolve) => {
    gotFirst = resolve;
  });
  await page.screencast.start({
    path: webm,
    size: view,
    onFrame: ({ timestamp }) => {
      if (firstTs) return;
      firstTs = timestamp;
      gotFirst();
    },
  });
  let timer;
  const noFrames = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Fail(1, 'the screencast delivered no frames')), 10000);
  });
  await Promise.race([firstFrame, noFrames]).finally(() => clearTimeout(timer));
  // The frame timestamp arrives in epoch ms; if it ever came in seconds or monotonic, fall back to the local clock.
  if (firstTs > 1e12) return firstTs;
  if (firstTs > 1e9) return firstTs * 1000;
  return Date.now();
}

async function narrate(take, step, n) {
  const { page, stg, clock } = take;
  const d = take.clips[n - 1].d;
  const cues = media.splitCues(step.say, d);
  const vti = take.at;
  await clock.until(vti);
  if (step.caption !== undefined) stg.st.top = step.caption;
  stg.st.sub = cues[0].text;
  stg.st.pos = 'bottom';
  const probe = step.highlight || (TARGETS.has(step.action) && step.selector);
  if (stg.nearBottom(probe ? await stg.probeBox(probe) : null)) stg.st.pos = 'top';
  await stg.apply();
  const highlighted = step.highlight
    ? page.locator(step.highlight).first().evaluate((el) => window.__rec.highlight(el), undefined, { timeout: 10000 })
    : Promise.resolve();
  highlighted.catch(() => {});

  const subtitles = (async () => {
    for (const c of cues.slice(1)) {
      await clock.until(vti + c.start);
      stg.st.sub = c.text;
      await stg.apply();
    }
    await clock.until(vti + d);
    stg.st.sub = '';
    await stg.apply();
  })();
  const action = (async () => {
    await clock.until(vti + Math.min(0.6 * d, 3));
    const began = clock.now();
    if (step.action === 'none') await stg.liftCursor();
    await perform(take, step);
    return { began, ended: clock.now() };
  })();
  const [, ran] = await Promise.all([subtitles, action]);
  await highlighted;

  // A step lasts its voice or its action, whichever ends last, plus 0.4 s and its hold; the next one starts on
  // the next tenth of a second so a re-take with the same timings writes the same srt.
  const end = Math.max(vti + d, ran.ended) + 0.4 + (step.hold || 0) / 1000;
  await clock.until(end);
  if (step.highlight) await page.evaluate(() => window.__rec.highlight(null));
  take.at = ceilTenth(end);
  for (const c of cues) take.cues.push({ text: c.text, start: vti + c.start, end: vti + c.end });
  take.timeline.push({ n, vt: +vti.toFixed(3), d: +d.toFixed(3), actionAt: +ran.began.toFixed(3), actionEnd: +ran.ended.toFixed(3), action: step.action, selector: step.selector, caption: step.caption, say: step.say });
  const text = await page.evaluate(() => document.body.innerText).catch(() => '');
  fs.appendFileSync(take.domFile, `=== step ${n} (vt ${vti.toFixed(1)} s) ===\n${redact(text)}\n\n`);
}

async function perform(take, step) {
  const { page, stg, run } = take;
  const value = fillPlaceholders(step.value, run.config.timezone);
  const allowed = (u) => hostAllowed(u, run.config.allowHosts);
  await runStep(page, { ...step, value }, { before: stg.before, baseUrl: run.config.baseUrl, configDir: run.config.dir, mail: run.config.mail, allowed, since: take.t0 });
  await stg.park();
  if (step.waitFor) await page.locator(step.waitFor).first().waitFor({ state: 'visible', timeout: 10000 });
  if (take.dry && step.highlight) await page.locator(step.highlight).first().waitFor({ state: 'attached', timeout: 10000 });
}

function stagedPaths(work, tag) {
  return Object.fromEntries(Object.entries(KINDS).map(([kind, k]) => [kind, path.join(work, 'out', kind, `${tag}.${k.ext}`)]));
}

const finalPath = (outDir, kind, tag) => path.join(outDir, KINDS[kind].dir, `${tag}.${KINDS[kind].ext}`);

async function openScene(g, run, dry) {
  const { config } = run;
  const browser = await openBrowser(run);
  const { page } = browser;
  if (!dry && typeof page.screencast?.start !== 'function') throw new Fail(4, `playwright-core ${run.pw.version} has no page.screencast: ${PLAYWRIGHT_RECIPE}`);
  // Off-camera pre-roll: session, route and fonts ready before the first frame.
  await runSetup(page, setupFor(config, g), config);
  await page.goto(config.baseUrl + g.route, NAV);
  if (!dry && config.fonts.length && !(await fontsLoaded(page, config.fonts))) {
    throw new Fail(3, `configured fonts did not load: ${config.fonts.join(', ')}`);
  }
  return browser;
}

async function dryRun(g, run) {
  const tag = `${g.id}-${g.slug}`;
  log(`dry ${tag}: runs the real actions against the local app`);
  const { page, done } = await openScene(g, run, true);
  const take = { page, run, dry: true, t0: Date.now(), stg: stage(page, run.config.viewport, true) };
  for (const [i, step] of g.steps.entries()) {
    const where = stepLabel(step, i, g.steps.length);
    log(`dry ${tag}: ${where}`);
    await perform(take, step).catch(stepFail(where));
  }
  await done();
  log(`OK dry ${g.id} ${g.slug} ${g.steps.length} steps`);
}

async function shoot(g, run, work, staged) {
  const { config } = run;
  const clips = await synthesize(g, work, run);
  const secs = clips.reduce((n, c) => n + c.d, 0);
  log(`rec ${g.id}-${g.slug}: ${g.steps.length} steps, voice ${secs.toFixed(1)} s · ${run.mute ? 'muted' : run.voice.label}`);

  const { page, context, done } = await openScene(g, run, false);
  await installOverlay(context, page, OVERLAY, { blur: g.blur || [], brand: config.brand, font: config.fonts[0] || null });
  const stg = stage(page, config.viewport, false);
  // A new document (goto, mail link, reload) is born without the current bar and subtitle.
  page.on('domcontentloaded', stg.apply);
  await page.evaluate((spec) => window.__rec.card(spec, true), { title: g.title });
  await page.waitForTimeout(800);

  const t0 = await startCamera(page, path.join(work, 'video.webm'), config.viewport);
  const clock = { now: () => (Date.now() - t0) / 1000, until: (s) => sleep(t0 + s * 1000 - Date.now()) };
  await clock.until(1.5);
  await page.evaluate(() => window.__rec.card(null));
  const take = { page, run, dry: false, t0, stg, clock, clips, at: 1.75, cues: [], timeline: [], domFile: staged.dom };
  fs.writeFileSync(staged.dom, '');
  const maxSeconds = g.maxSeconds ?? config.durationWindow[1];

  for (const [i, step] of g.steps.entries()) {
    const where = stepLabel(step, i, g.steps.length);
    log(`rec ${g.id}-${g.slug}: ${where}`);
    if (take.at > maxSeconds) throw new Fail(1, `${where}: exceeds maxSeconds (${maxSeconds} s)`);
    await narrate(take, step, i + 1).catch(stepFail(where));
  }

  const next = g.next ? run.byId.get(g.next) : null;
  if (next) {
    const kicker = config.locale.toLowerCase().startsWith('es') ? 'Siguiente' : 'Next';
    await page.evaluate((spec) => window.__rec.card(spec), { kicker, title: next.title });
    await sleep(1500);
  }
  await sleep(500);
  await page.screencast.stop();
  const stopVt = clock.now();
  await context.close();
  await done();
  return { clips, take, t0, stopVt, maxSeconds };
}

async function recordVideo(g, run) {
  const { config } = run;
  const tag = `${g.id}-${g.slug}`;
  const work = path.join(config.outDir, 'work', g.id);
  // Everything a take produces is written under work/<id>/out and only moves into outDir when the take succeeds:
  // a failed take never leaves a partial dom next to the previous mp4.
  const staged = stagedPaths(work, tag);
  fs.rmSync(work, { recursive: true, force: true });
  for (const file of Object.values(staged)) fs.mkdirSync(path.dirname(file), { recursive: true });

  const { clips, take, t0, stopVt, maxSeconds } = await shoot(g, run, work, staged);
  fs.writeFileSync(staged.srt, redact(media.toSrt(take.cues)));
  const language = media.subtitleLanguage(config.locale);
  await media.mux({ video: path.join(work, 'video.webm'), clips: clips.map((c, i) => ({ file: c.file, at: take.timeline[i].vt })), srt: staged.srt, out: staged.mp4, language });
  await media.poster(staged.mp4, staged.poster);
  await media.contactSheet(staged.mp4, staged.sheet, config.brand.bg);

  const dur = await media.duration(staged.mp4);
  const timeline = { id: g.id, slug: g.slug, voice: run.mute ? 'muted' : run.voice.label, t0, stopVt: +stopVt.toFixed(3), mp4Duration: dur, steps: take.timeline };
  fs.writeFileSync(path.join(work, 'timeline.json'), redact(JSON.stringify(timeline, null, 1)));
  if (dur > maxSeconds) throw new Fail(1, `${tag}: the video lasts ${dur.toFixed(1)} s and maxSeconds is ${maxSeconds}`);

  for (const kind of Object.keys(KINDS)) {
    const dest = finalPath(config.outDir, kind, tag);
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.renameSync(staged[kind], dest);
  }
  const mp4 = finalPath(config.outDir, 'mp4', tag);
  log(`OK rec ${g.id} ${g.slug} ${dur.toFixed(1)}s ${(fs.statSync(mp4).size / 1048576).toFixed(2)}MB ${rel(mp4)}`);
}

// ───────────────────────── verify ─────────────────────────

async function verifyOne(g, config) {
  const tag = `${g.id}-${g.slug}`;
  const files = { guion: path.join(config.guionesDir, `${tag}.json`), ...Object.fromEntries(Object.keys(KINDS).map((k) => [k, finalPath(config.outDir, k, tag)])) };
  const missing = Object.entries(files).filter(([, f]) => !media.nonEmpty(f)).map(([what, f]) => `missing ${what} (${rel(f)})`);
  if (missing.length) return { problems: missing };
  const mp4 = await media.verifyMp4(files.mp4, { viewport: config.viewport, window: config.durationWindow });
  const problems = [...mp4.problems];
  const hits = config.denyList ? await media.denyHits(config.denyList, [files.guion, files.srt, files.dom], path.join(config.outDir, 'work')) : [];
  if (hits.length) problems.push(`deny-list: ${hits.length} hit(s) in ${hits.slice(0, 5).map(rel).join(', ')}`);
  return { problems, mp4, hits, files };
}

function readManifest(file) {
  try {
    const list = JSON.parse(fs.readFileSync(file, 'utf8'));
    return Array.isArray(list) ? list : [];
  } catch {
    return [];
  }
}

async function runVerify(guiones, cat, config) {
  if (config.denyList && !fs.existsSync(config.denyList)) throw new Fail(2, `denyList not found: ${config.denyList}`);
  fs.mkdirSync(path.join(config.outDir, 'work'), { recursive: true });
  const verified = [];
  let failed = 0;
  for (const g of guiones) {
    const r = await verifyOne(g, config);
    if (r.problems.length) {
      failed++;
      console.error(redact(`FAIL ${g.id} ${g.slug}: ${r.problems.join('; ')}`));
      continue;
    }
    log(`OK ${g.id} ${r.mp4.codecs} ${r.mp4.duration.toFixed(1)}s srt poster sheet dom deny=${r.hits.length}`);
    verified.push({ id: g.id, slug: g.slug, title: g.title, duration: +r.mp4.duration.toFixed(2), sha256: media.sha256(r.files.mp4), bytes: fs.statSync(r.files.mp4).size });
  }
  // The manifest accumulates: re-verifying one id keeps the others (as long as their guion still exists).
  const manifest = path.join(config.outDir, 'manifest.json');
  const byId = new Map(readManifest(manifest).filter((m) => cat.byId.has(m.id)).map((m) => [m.id, m]));
  for (const m of verified) byId.set(m.id, m);
  fs.writeFileSync(manifest, JSON.stringify([...byId.values()].sort((a, b) => a.id.localeCompare(b.id)), null, 2) + '\n');
  return failed ? 1 : 0;
}

// ───────────────────────── main ─────────────────────────

async function main() {
  const o = parseArgs(process.argv.slice(2));
  if (o.help) {
    console.log(helpText());
    return 0;
  }
  if (o.mode === 'doctor') return runDoctor(loadConfig(o.config, { optional: true }));
  if (nodeMajor() < 20) throw new Fail(2, `Node ${process.versions.node}: the recorder needs Node 20 or newer`);
  const config = loadConfig(o.config);
  const cat = catalog(config);
  const selected = select(o, cat);
  if (!selected.length) throw new Fail(1, `no guiones in ${rel(config.guionesDir)}`);
  if (o.mode === 'check') return runCheck(selected, cat, config);

  const guiones = assertValid(selected, cat);
  if (o.mode === 'verify') {
    await assertNotRecording(config.outDir);
    return runVerify(guiones, cat, config);
  }
  const dry = o.mode === 'dry';
  assertGuards(guiones, config);
  const voice = dry || o.mute ? media.resolveVoice(config.voice) : await assertVoice(config);
  const pw = assertPlaywright(dry);
  await assertServer(config);
  await acquireLock(config.outDir);
  const run = { config, pw, voice, mute: o.mute, byId: cat.byId };
  for (const g of guiones) await (dry ? dryRun(g, run) : recordVideo(g, run));
  return 0;
}

process.on('SIGINT', () => die(130, 'interrupted'));
process.on('unhandledRejection', (e) => die(1, `record failed: ${e && e.message}`));
main().then(
  (code) => die(code),
  (e) => die(isFail(e) ? e.code : 1, isFail(e) ? e.message : `record failed: ${e.message}`),
);
