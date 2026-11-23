#!/usr/bin/env node
// Deterministic MR evidence: screenshots (desktop + mobile per route) and a silent captioned mp4 of a LOCAL dev
// server, uploaded to a GitLab merge request. The model writes the spec; this script records and uploads.
//
// usage: evidence.mjs doctor|check|capture|attach|run --spec <path> [--mode screenshots|video|both|none] [--note] [--out <dir>] [--mr <iid>] [--forge gitlab|github] [--dry] [--env-file .env.local] [--max-mb 10] [--repo <dir>] [--json] [--files <dir>] [--md-out <file>]
//   doctor   node, playwright-core, browser, ffmpeg, ffprobe, glab (no spec needed)
//   check    validates the spec, loopback hosts, credentials and tools; touches nothing
//   capture  starts the spec's server, logs in, writes shots/<name>-{d,m}.png, video/<name>.mp4 and manifest.json under --out
//   attach   uploads the captured files (or --files <dir>, no spec) and prints the markdown block; with --mr N it writes it
//            into the MR: by default it replaces the region between the evidence markers, --note posts a comment instead
//   run      capture + attach (--mode screenshots|video|both picks the media, --note the placement; --dry skips the upload)
// Node itself loads (and aborts on a missing) --env-file wherever it appears in argv, so the launcher passes it on as --creds-file.
// Exit: 0 ok · 1 capture failed · 2 environment · 3 server will not start / port busy · 4 login · 5 upload ·
//       6 host not loopback · 64 invalid spec or arguments.
// Stdout: `EVIDENCE: ok <n> shots[ video]` or `EVIDENCE: failed(<code>) <reason>`, `MEDIA: unsent: <abs paths>`, the markdown block.
import fs from 'node:fs';
import os from 'node:os';
import net from 'node:net';
import path from 'node:path';
import { spawn, execFile } from 'node:child_process';
import { promisify, stripVTControlCharacters } from 'node:util';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { Fail, fillPlaceholders, hostAllowed, isFail, redact } from './lib/config.mjs';
import * as media from './lib/media.mjs';
import { isObject, isText } from './lib/schema.mjs';
import { guardHosts, installOverlay } from './lib/setup.mjs';
import { NAV, runStep, sleep, stepFail } from './lib/steps.mjs';

const run = promisify(execFile);
const OVERLAY = path.join(path.dirname(fileURLToPath(import.meta.url)), 'lib', 'overlay.js');
const USAGE = 'usage: evidence.mjs doctor|check|capture|attach|run --spec <path> [--mode screenshots|video|both|none] [--note] [--out <dir>] [--mr <iid>] [--forge gitlab|github] [--dry] [--env-file .env.local] [--max-mb 10] [--repo <dir>] [--json] [--files <dir>] [--md-out <file>]';
const COMMANDS = ['doctor', 'check', 'capture', 'attach', 'run'];
const CAPTURE_MODES = ['screenshots', 'video', 'both', 'none'];
const LOOPBACK = new Set(['localhost', '127.0.0.1', '::1', '[::1]']);
const MIN_PLAYWRIGHT = '1.61.0';
const START = '<!-- evidence:start -->';
const END = '<!-- evidence:end -->';
const HEADING = '## Evidencia';
const NOTE_HEADING = '## Evidencia (refrescada tras arreglos del gate)';
const GITHUB_LINE = 'Evidencia: adjuntar a mano (GitHub no admite subida por API)';
const SPEC_KEYS = new Set(['name', 'serve', 'baseUrl', 'allowHosts', 'routes', 'widths', 'auth', 'video', 'locale', 'timezone']);
const STEP_ACTIONS = new Set(['goto', 'click', 'fill', 'select', 'press', 'scroll', 'wait']);
const MAX_STEPS = 25;
const MAX_SECONDS = 60;
const VIDEO_VIEW = { width: 1280, height: 720 };
const DEFAULT_HOLD = 1.5;

for (const out of [process.stdout, process.stderr]) out.on('error', () => {});
const cleanups = [];
let exiting = false;
let reported = false;
async function die(code, message) {
  if (exiting) return new Promise(() => {});
  exiting = true;
  if (message) console.error(redact(message));
  if (code !== 0 && !reported) {
    reported = true;
    print({ json: process.argv.includes('--json') }, { code, reason: redact(message ?? '').split('\n')[0], media: [], block: null });
  }
  for (const fn of cleanups.splice(0).reverse()) await Promise.race([Promise.resolve(fn()).catch(() => {}), sleep(5000)]);
  await Promise.all([process.stdout, process.stderr].map((out) => new Promise((resolve) => out.write('', resolve))));
  process.exit(code);
}

const argError = (message) => {
  throw new Fail(64, `${message}\n${USAGE}`);
};
const nodeMajor = () => Number(process.versions.node.split('.')[0]);
const firstLine = (e) => redact(stripVTControlCharacters(String(e?.message ?? e)).split('\n')[0]);
const isDesktop = (width) => width >= 768;
// The value of fn(), or null when it throws.
const attempt = (fn) => {
  try {
    return fn();
  } catch {
    return null;
  }
};

// ───────────────────────── arguments ─────────────────────────

const VALUE_FLAGS = { '--spec': 'spec', '--mode': 'mode', '--out': 'out', '--mr': 'mr', '--forge': 'forge', '--env-file': 'envFile', '--creds-file': 'envFile', '--max-mb': 'maxMb', '--repo': 'repo', '--files': 'files', '--md-out': 'mdOut' };

function parseArgs(argv) {
  const o = { cmd: null, forge: 'gitlab', maxMb: 10, repo: process.cwd(), dry: false, note: false, json: false, help: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const eq = a.startsWith('--') ? a.indexOf('=') : -1;
    const [flag, inline] = eq > 0 ? [a.slice(0, eq), a.slice(eq + 1)] : [a, undefined];
    if (a === '--help' || a === '-h') o.help = true;
    else if (a === '--dry') o.dry = true;
    else if (a === '--note') o.note = true;
    else if (a === '--json') o.json = true;
    else if (VALUE_FLAGS[flag]) o[VALUE_FLAGS[flag]] = inline ?? argv[++i] ?? argError(`${flag} needs a value`);
    else if (!o.cmd && COMMANDS.includes(a)) o.cmd = a;
    else argError(`unrecognized argument "${a}"`);
  }
  if (o.help) return o;
  if (!o.cmd) argError('give a command');
  if (!['gitlab', 'github'].includes(o.forge)) argError('--forge must be gitlab or github');
  if (['body', 'note'].includes(o.mode)) argError(`--mode ${o.mode} is gone: --mode is the media (screenshots|video|both|none); add --note to post an MR note instead of replacing the description region`);
  if (o.mode !== undefined && !CAPTURE_MODES.includes(o.mode)) argError('--mode must be screenshots|video|both|none (add --note to post an MR note)');
  o.maxMb = Number(o.maxMb);
  if (!(o.maxMb > 0)) argError('--max-mb must be a positive number');
  if (o.mr !== undefined && !/^\d+$/.test(o.mr)) argError('--mr must be the numeric MR iid');
  if (['check', 'capture', 'run'].includes(o.cmd) && !o.spec) argError(`${o.cmd} needs --spec`);
  if (o.cmd === 'attach' && !o.files && !o.spec && !o.out) argError('attach needs --files <dir>, or --spec / --out to find the captured media');
  o.repo = path.resolve(o.repo);
  return o;
}

const helpText = () => {
  const lines = fs.readFileSync(fileURLToPath(import.meta.url), 'utf8').split('\n');
  const from = lines.findIndex((l) => l.startsWith('// usage:'));
  const to = lines.findIndex((l, i) => i > from && l.startsWith('// Stdout'));
  return lines.slice(from, to + 1).map((l) => l.replace(/^\/\/ ?/, '')).join('\n');
};

// ───────────────────────── spec ─────────────────────────

const hostOf = (url) =>
  attempt(() => {
    const u = new URL(url);
    return /^https?:$/.test(u.protocol) ? u.hostname.toLowerCase() : null;
  });

function stepSeconds(s) {
  return (s.action === 'wait' ? (Number(s.value) || 500) / 1000 : 0) + Number(s.hold ?? DEFAULT_HOLD);
}

// Returns the normalized spec or throws Fail(64 invalid | 6 host not loopback).
function loadSpec(file) {
  let raw;
  try {
    raw = JSON.parse(fs.readFileSync(path.resolve(file), 'utf8'));
  } catch (e) {
    throw new Fail(64, `${file}: cannot read the spec (${firstLine(e)})`);
  }
  const bad = [];
  if (!isObject(raw)) throw new Fail(64, 'the spec must be a JSON object');
  for (const k of Object.keys(raw)) if (!SPEC_KEYS.has(k)) bad.push(`unknown key "${k}"`);
  if (!(isText(raw.name) && /^[A-Za-z0-9._-]+$/.test(raw.name))) bad.push('name must be text of letters, digits, . _ -');
  const base = hostOf(raw.baseUrl);
  if (!base) bad.push('baseUrl must be an http(s) URL');
  const hostList = raw.allowHosts ?? ['localhost', '127.0.0.1'];
  if (!(Array.isArray(hostList) && hostList.length)) bad.push('allowHosts must be a non-empty list');
  const allowHosts = Array.isArray(hostList) ? hostList.map((h) => String(h).toLowerCase()) : [];
  if (raw.serve !== undefined) {
    const s = raw.serve;
    if (!(isObject(s) && isText(s.cmd))) bad.push('serve must be {cmd, ready?, timeoutS?, cwd?}');
    else if (s.timeoutS !== undefined && !(Number(s.timeoutS) > 0)) bad.push('serve.timeoutS must be a positive number');
    else if (s.ready !== undefined && !hostOf(s.ready)) bad.push('serve.ready must be an http(s) URL');
  }
  const widths = raw.widths ?? [1280, 375];
  if (!(Array.isArray(widths) && widths.length && widths.every((w) => Number.isInteger(w) && w >= 200 && w <= 3000))) bad.push('widths must be a list of pixel widths');
  const routes = raw.routes ?? [];
  if (!Array.isArray(routes)) bad.push('routes must be a list');
  else {
    const seen = new Set();
    routes.forEach((r, i) => {
      const at = `routes[${i}]`;
      if (!(isObject(r) && isText(r.path) && r.path.startsWith('/'))) return bad.push(`${at}: path must start with /`);
      if (!(isText(r.name) && /^[a-z0-9-]+$/.test(r.name))) bad.push(`${at}: name must be lowercase letters, digits, -`);
      else if (seen.has(r.name)) bad.push(`${at}: duplicate name "${r.name}"`);
      else seen.add(r.name);
      if (r.waitFor !== undefined && !isText(r.waitFor)) bad.push(`${at}: waitFor must be a selector`);
      if (r.mask !== undefined && !(Array.isArray(r.mask) && r.mask.every(isText))) bad.push(`${at}: mask must be a list of selectors`);
    });
  }
  const auth = raw.auth;
  if (auth !== undefined) {
    const need = ['loginPath', 'userSelector', 'passSelector', 'submitSelector', 'successSelector'];
    if (!isObject(auth) || need.some((k) => !isText(auth[k]))) bad.push(`auth must have ${need.join(', ')} (and optional userEnv, passEnv)`);
    else if (!auth.loginPath.startsWith('/')) bad.push('auth.loginPath must start with /');
  }
  let steps = [];
  if (raw.video !== undefined) {
    if (!(isObject(raw.video) && Array.isArray(raw.video.steps) && raw.video.steps.length)) bad.push('video must be {steps: [...]} with at least one step');
    else {
      steps = raw.video.steps;
      if (steps.length > MAX_STEPS) bad.push(`video has ${steps.length} steps (max ${MAX_STEPS})`);
      steps.forEach((s, i) => {
        const at = `video.steps[${i}]`;
        if (!(isObject(s) && STEP_ACTIONS.has(s.action))) return bad.push(`${at}: action must be ${[...STEP_ACTIONS].join('|')}`);
        if (!isText(s.caption)) bad.push(`${at}: caption is required`);
        else if (s.caption.length > 80) bad.push(`${at}: caption has ${s.caption.length} characters (max 80)`);
        if (['click', 'fill', 'select'].includes(s.action) && !isText(s.selector)) bad.push(`${at}: ${s.action} needs selector`);
        if (['fill', 'select', 'press', 'goto'].includes(s.action) && s.value === undefined) bad.push(`${at}: ${s.action} needs value`);
        if (s.hold !== undefined && !(typeof s.hold === 'number' && s.hold >= 0)) bad.push(`${at}: hold must be seconds`);
        if (JSON.stringify(s).includes('{{')) bad.push(`${at}: placeholders are not accepted (credentials only come from spec.auth)`);
      });
      const total = steps.reduce((n, s) => n + (isObject(s) ? stepSeconds(s) : 0), 0);
      if (total > MAX_SECONDS) bad.push(`video is estimated at ${total.toFixed(0)} s (max ${MAX_SECONDS})`);
    }
  }
  if (!routes.length && !steps.length) bad.push('the spec needs routes or video.steps');
  if (bad.length) throw new Fail(64, `${file}:\n  - ${bad.join('\n  - ')}`);
  // Loopback only, every host the spec names: this is checked before anything starts.
  const hosts = [base, ...allowHosts, raw.serve?.ready ? hostOf(raw.serve.ready) : null].filter(Boolean);
  const outside = hosts.find((h) => !LOOPBACK.has(h));
  if (outside) throw new Fail(6, `host "${outside}" is not loopback (localhost, 127.0.0.1, ::1): evidence only runs against a local server`);
  if (!allowHosts.includes(base)) throw new Fail(64, `baseUrl host "${base}" is not in allowHosts`);
  const url = new URL(raw.baseUrl);
  return {
    name: raw.name,
    serve: raw.serve ? { ...raw.serve, timeoutS: Number(raw.serve.timeoutS ?? 60), ready: raw.serve.ready ?? raw.baseUrl } : null,
    baseUrl: raw.baseUrl.replace(/\/+$/, ''),
    port: Number(url.port || (url.protocol === 'https:' ? 443 : 80)),
    host: url.hostname,
    allowHosts,
    routes,
    widths,
    auth: auth ? { userEnv: 'EVIDENCE_USER', passEnv: 'EVIDENCE_PASS', ...auth } : null,
    steps,
    locale: raw.locale ?? 'es-MX',
    timezone: raw.timezone ?? 'America/Mexico_City',
    dir: path.dirname(path.resolve(file)),
  };
}

// ───────────────────────── environment ─────────────────────────

function parseEnvFile(file) {
  const out = {};
  if (!fs.existsSync(file)) return out;
  for (const line of fs.readFileSync(file, 'utf8').split('\n')) {
    const m = line.match(/^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (!m) continue;
    let v = m[2];
    if (/^(["']).*\1$/.test(v)) v = v.slice(1, -1);
    out[m[1]] = v;
  }
  return out;
}

// Reads the credentials from --env-file (then the process env), registers them with redact(). Returns { user, pass } or null.
function loadCredentials(spec, o) {
  if (!spec.auth) return null;
  const file = path.resolve(o.repo, o.envFile ?? '.env.local');
  const env = parseEnvFile(file);
  const names = [spec.auth.userEnv, spec.auth.passEnv];
  const values = names.map((name) => env[name] ?? process.env[name]);
  const missing = names.filter((_, i) => !values[i]);
  if (missing.length) throw new Fail(2, `credentials not found: ${missing.join(', ')} (looked in ${path.basename(file)} and the environment)`);
  names.forEach((name, i) => {
    process.env[name] = values[i];
    // Filling an {{env:NAME}} placeholder is what registers the value (and its encodings) with redact().
    fillPlaceholders(`{{env:${name}}}`, spec.timezone);
  });
  return { user: values[0], pass: values[1] };
}

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
const tryLoad = (dir) => attempt(() => loadCore(dir));

// Same order as record.mjs: the project's node_modules → PW_CORE_DIR → the npx cache (newest stable first).
function resolvePlaywright() {
  const local = createRequire(path.join(process.cwd(), 'noop.js'));
  for (const name of ['playwright-core', 'playwright']) {
    const core = attempt(() => loadCore(path.dirname(local.resolve(`${name}/package.json`))));
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
const launch = (pw) => pw.chromium.launch({ channel: channel(), headless: true });

async function probeBrowser(pw) {
  try {
    const browser = await launch(pw);
    const page = await browser.newPage();
    const screencast = typeof page.screencast?.start === 'function';
    await browser.close();
    return { screencast };
  } catch (e) {
    return { error: firstLine(e) };
  }
}

const PW_RECIPE = 'npx -y -p playwright-core@1.63 node -e 0 (or set PW_CORE_DIR)';

// Checks what the command needs; throws Fail(2) naming the first gap. Returns the loaded playwright core (or null if not needed).
async function requireTools({ screenshots, video, upload }) {
  if (nodeMajor() < 20) throw new Fail(2, `node ${process.versions.node}: Node 20+ is required (nvm install 22, first on PATH)`);
  let pw = null;
  if (screenshots || video) {
    pw = resolvePlaywright();
    if (!pw) throw new Fail(2, `playwright-core not found: ${PW_RECIPE}`);
    if (video && compareVersions(pw.version, MIN_PLAYWRIGHT) < 0) throw new Fail(2, `playwright-core ${pw.version} has no page.screencast: ${PW_RECIPE}`);
  }
  if (video) for (const bin of ['ffmpeg', 'ffprobe']) if (!(await media.toolVersion(bin))) throw new Fail(2, `${bin} not found: brew install ffmpeg`);
  if (upload && !(await run('glab', ['--version']).then(() => true, () => false))) throw new Fail(2, 'glab not found: brew install glab');
  return pw;
}

// Doctor rows are [ok, item, detail].
function playwrightRow(pw, probe) {
  const item = 'playwright-core>=1.61';
  if (!pw) return [false, item, `not found: ${PW_RECIPE}`];
  if (compareVersions(pw.version, MIN_PLAYWRIGHT) < 0) return [false, item, `found ${pw.version}: ${PW_RECIPE}`];
  if (probe.screencast === false) return [false, item, `${pw.version} has no page.screencast`];
  return [true, item, `${pw.version}${probe.screencast ? ', screencast' : ''}`];
}

async function runDoctor() {
  const old = nodeMajor() < 20;
  const pw = old ? null : resolvePlaywright();
  const probe = pw ? await probeBrowser(pw) : { error: 'playwright-core not resolved' };
  const tool = async (bin) => {
    const v = await media.toolVersion(bin);
    return v ? [true, bin, v.replace(/^\S+ version /, '').split(' ')[0]] : [false, bin, 'brew install ffmpeg (or your package manager)'];
  };
  const glab = await run('glab', ['--version']).then(({ stdout }) => [true, 'glab', stdout.split('\n')[0].trim()], () => [false, 'glab', 'brew install glab (GitLab uploads)']);
  const rows = [
    old ? [false, 'node>=20', `found ${process.versions.node}: install Node 20+ and put it first on PATH`] : [true, 'node>=20', process.versions.node],
    playwrightRow(pw, probe),
    probe.error ? [false, 'browser channel', `${channel()}: ${probe.error}; install Google Chrome, or set REC_CHANNEL=chromium`] : [true, 'browser channel', channel()],
    await tool('ffmpeg'),
    await tool('ffprobe'),
    glab,
  ];
  const ready = rows.every(([ok]) => ok);
  const out = rows.map(([ok, item, detail]) => (ok ? `ok ${item} (${detail})` : `missing ${item} — ${detail}`));
  out.push(`DOCTOR: ${ready ? 'ready' : 'not ready'}`);
  return { text: out.join('\n'), ready };
}

// ───────────────────────── server ─────────────────────────

const portBusy = (host, port) =>
  new Promise((resolve) => {
    const sock = net.connect({ host, port });
    const done = (busy) => {
      sock.destroy();
      resolve(busy);
    };
    sock.setTimeout(800, () => done(false));
    sock.once('connect', () => done(true));
    sock.once('error', () => done(false));
  });

const ready = async (url) => {
  try {
    const r = await fetch(url, { redirect: 'manual', signal: AbortSignal.timeout(3000) });
    return r.status >= 200 && r.status < 400;
  } catch {
    return false;
  }
};

// Starts spec.serve in its own process group and waits for `ready`. A busy port is never reused.
async function startServer(spec, o, env) {
  if (!spec.serve) {
    if (!(await ready(spec.baseUrl))) throw new Fail(3, `no serve.cmd in the spec and ${spec.baseUrl} is not answering`);
    return;
  }
  if (await portBusy(spec.host, spec.port)) throw new Fail(3, `port busy: ${spec.host}:${spec.port} already has a listener (stop it; evidence never reuses another process)`);
  const cwd = path.resolve(o.repo, spec.serve.cwd ?? '.');
  const child = spawn('sh', ['-c', spec.serve.cmd], { cwd, env, detached: true, stdio: ['ignore', 'pipe', 'pipe'] });
  let tail = '';
  let exited = null;
  const lastOutput = () => tail.replace(/\s+/g, ' ').trim().slice(-300);
  for (const s of [child.stdout, child.stderr]) s.on('data', (d) => { tail = (tail + d).slice(-1500); });
  child.on('exit', (code) => { exited = code ?? 'signal'; });
  child.on('error', (e) => { exited = e.message; });
  cleanups.push(async () => {
    for (const sig of ['SIGTERM', 'SIGKILL']) {
      try {
        process.kill(-child.pid, sig);
      } catch {
        return;
      }
      await sleep(sig === 'SIGTERM' ? 1500 : 0);
    }
  });
  const deadline = Date.now() + spec.serve.timeoutS * 1000;
  while (Date.now() < deadline) {
    if (exited !== null) throw new Fail(3, `the server exited (${exited}) before ${spec.serve.ready} answered: ${lastOutput()}`);
    if (await ready(spec.serve.ready)) return;
    await sleep(300);
  }
  throw new Fail(3, `${spec.serve.ready} did not answer 2xx/3xx within ${spec.serve.timeoutS}s: ${lastOutput()}`);
}

// ───────────────────────── capture ─────────────────────────

async function openContext(pw, spec, view) {
  const browser = await launch(pw);
  const close = () => browser.close().catch(() => {});
  cleanups.push(close);
  const context = await browser.newContext({ viewport: view, locale: spec.locale, timezoneId: spec.timezone, deviceScaleFactor: 1 });
  context.setDefaultTimeout(15000);
  await guardHosts(context, spec.allowHosts, (url) => die(6, `the page requested ${url}, outside loopback (${spec.allowHosts.join(', ')})`));
  const page = await context.newPage();
  return { page, context, close: async () => { await close(); cleanups.splice(cleanups.indexOf(close), 1); } };
}

async function login(page, spec, creds) {
  const a = spec.auth;
  try {
    await page.goto(spec.baseUrl + a.loginPath, NAV);
    await page.fill(a.userSelector, creds.user);
    await page.fill(a.passSelector, creds.pass);
    await page.click(a.submitSelector);
    await page.locator(a.successSelector).first().waitFor({ state: 'visible', timeout: 10000 });
  } catch (e) {
    throw new Fail(4, `login failed (${a.successSelector} never appeared): ${firstLine(e)}`);
  }
}

async function shootRoute(page, spec, route, file) {
  try {
    await page.goto(spec.baseUrl + route.path, NAV);
    if (route.waitFor) await page.locator(route.waitFor).first().waitFor({ state: 'visible', timeout: 15000 });
    const mask = (route.mask ?? []).map((s) => page.locator(s));
    await page.screenshot({ path: file, mask, maskColor: '#888888', animations: 'disabled' });
  } catch (e) {
    throw isFail(e) ? e : new Fail(1, `route ${route.path}: ${firstLine(e)}`);
  }
}

async function captureShots(pw, spec, creds, outDir) {
  const shots = [];
  fs.mkdirSync(path.join(outDir, 'shots'), { recursive: true });
  for (const width of spec.widths) {
    const desktop = isDesktop(width);
    const { page, close } = await openContext(pw, spec, { width, height: desktop ? 800 : 812 });
    if (creds) await login(page, spec, creds);
    for (const route of spec.routes) {
      const file = path.join(outDir, 'shots', `${route.name}-${desktop ? 'd' : 'm'}.png`);
      await shootRoute(page, spec, route, file);
      shots.push({ route: route.path, name: route.name, width, file, sha256: media.sha256(file) });
    }
    await close();
  }
  return shots;
}

// The first frame of the screencast must arrive, or the video would be empty.
async function startCamera(page, webm) {
  let got;
  const first = new Promise((r) => { got = r; });
  await page.screencast.start({ path: webm, size: VIDEO_VIEW, onFrame: () => got() });
  let timer;
  const none = new Promise((_, rej) => { timer = setTimeout(() => rej(new Fail(1, 'the screencast delivered no frames')), 10000); });
  await Promise.race([first, none]).finally(() => clearTimeout(timer));
}

async function captureVideo(pw, spec, creds, outDir) {
  fs.mkdirSync(path.join(outDir, 'video'), { recursive: true });
  const webm = path.join(outDir, 'video', `${spec.name}.webm`);
  const mp4 = path.join(outDir, 'video', `${spec.name}.mp4`);
  const { page, context, close } = await openContext(pw, spec, VIDEO_VIEW);
  // The login happens before the camera starts: the credentials never appear in the video.
  if (creds) await login(page, spec, creds);
  await installOverlay(context, page, OVERLAY, { blur: [], brand: { accent: '#3B82F6', bg: '#111318' }, font: null });
  const st = { top: '', sub: '', pos: 'bottom' };
  const apply = () => page.evaluate((s) => window.__rec && window.__rec.set(s), { ...st }).catch(() => {});
  page.on('domcontentloaded', apply);
  await startCamera(page, webm);
  const t0 = Date.now();
  const ctx = { baseUrl: spec.baseUrl, configDir: spec.dir, allowed: (u) => hostAllowed(u, spec.allowHosts) };
  for (const [i, step] of spec.steps.entries()) {
    st.sub = step.caption;
    await apply();
    await runStep(page, step, ctx).catch(stepFail(`video.steps[${i}] (${step.action}${step.selector ? ' ' + step.selector : ''})`));
    await apply();
    await sleep(stepSeconds({ ...step, action: 'none' }) * 1000);
    if ((Date.now() - t0) / 1000 > MAX_SECONDS) throw new Fail(1, `the video ran past ${MAX_SECONDS} s`);
  }
  await page.screencast.stop();
  await close();
  await run('ffmpeg', ['-y', '-v', 'error', '-i', webm, '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-r', '25', '-vf', `scale=${VIDEO_VIEW.width}:${VIDEO_VIEW.height}`, '-movflags', '+faststart', mp4]).catch((e) => {
    throw new Fail(1, `ffmpeg could not encode the video: ${firstLine(e)}`);
  });
  fs.rmSync(webm, { force: true });
  // verifyMp4 expects the narrated contract (aac + mov_text); this video is silent, so the checks are made on ffprobe directly.
  const info = await media.probe(mp4);
  const v = info.streams.find((s) => s.codec_type === 'video');
  const seconds = Number(info.format.duration);
  const problems = [];
  if (!v || v.codec_name !== 'h264') problems.push('not h264');
  if (v && (v.width !== VIDEO_VIEW.width || v.height !== VIDEO_VIEW.height)) problems.push(`size ${v.width}x${v.height}`);
  if (!(seconds > 0 && seconds <= MAX_SECONDS + 2)) problems.push(`duration ${seconds.toFixed(1)}s`);
  if (problems.length) throw new Fail(1, `the video failed its check: ${problems.join(', ')}`);
  return { file: mp4, seconds: Number(seconds.toFixed(1)), sha256: media.sha256(mp4) };
}

// The media a --mode asks for, limited to what the spec can produce.
const wantedMedia = (spec, kind) => ({
  shots: ['screenshots', 'both'].includes(kind) && spec.routes.length > 0,
  video: ['video', 'both'].includes(kind) && spec.steps.length > 0,
});

function needMedia(spec, kind) {
  if (kind === 'video' && !spec.steps.length) throw new Fail(64, 'mode video needs video.steps in the spec');
  if (kind === 'screenshots' && !spec.routes.length) throw new Fail(64, 'mode screenshots needs routes in the spec');
}

async function capture(spec, o, kind, outDir) {
  needMedia(spec, kind);
  const want = wantedMedia(spec, kind);
  const manifest = { name: spec.name, mode: kind, createdAt: new Date().toISOString(), shots: [], video: null };
  if (want.shots || want.video) {
    const pw = await requireTools({ screenshots: true, video: want.video });
    // Children get the environment as it was before the credentials were loaded.
    const childEnv = { ...process.env };
    for (const name of spec.auth ? [spec.auth.userEnv, spec.auth.passEnv] : []) delete childEnv[name];
    const creds = loadCredentials(spec, o);
    await startServer(spec, o, childEnv);
    if (want.shots) manifest.shots = await captureShots(pw, spec, creds, outDir);
    if (want.video) manifest.video = await captureVideo(pw, spec, creds, outDir);
  }
  fs.mkdirSync(outDir, { recursive: true });
  fs.writeFileSync(path.join(outDir, 'manifest.json'), redact(JSON.stringify(manifest, null, 2)));
  return manifest;
}

// ───────────────────────── upload and MR ─────────────────────────

const glab = (args, o) => run('glab', args, { cwd: o.repo, maxBuffer: 20 * 1024 * 1024, env: process.env });
const TOO_BIG = /\b413\b|entity too large/i;

async function uploadOne(file, o) {
  try {
    const { stdout } = await glab(['api', 'projects/:id/uploads', '--form', `file=@${file}`], o);
    const md = JSON.parse(stdout).markdown;
    if (!isText(md)) throw new Error('the response has no markdown field');
    return md;
  } catch (e) {
    const text = `${e.stderr ?? ''} ${e.stdout ?? ''} ${e.message ?? ''}`;
    const err = new Fail(5, `upload of ${path.basename(file)} failed: ${redact(text).replace(/\s+/g, ' ').trim().slice(0, 200)}`);
    err.tooBig = TOO_BIG.test(`${e.stderr ?? ''} ${e.stdout ?? ''}`);
    throw err;
  }
}

async function reencode(mp4) {
  const out = mp4.replace(/\.mp4$/, '-small.mp4');
  await run('ffmpeg', ['-y', '-v', 'error', '-i', mp4, '-an', '-c:v', 'libx264', '-crf', '32', '-vf', 'scale=-2:540', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', out]);
  return out;
}

// A 413 resolves to null; any other upload failure still throws.
const uploadUnless413 = (file, o) =>
  uploadOne(file, o).catch((e) => {
    if (e.tooBig) return null;
    throw e;
  });

// One re-encode (proactive when over --max-mb, reactive on a 413); a video that still does not fit is dropped.
async function uploadVideo(file, o) {
  const limit = o.maxMb * 1024 * 1024;
  let small;
  if (fs.statSync(file).size > limit) {
    small = await reencode(file).catch(() => null);
    if (!small || fs.statSync(small).size > limit) return { dropped: `video over ${o.maxMb} MB even re-encoded` };
  } else {
    const md = await uploadUnless413(file, o);
    if (md) return { md };
    small = await reencode(file).catch(() => null);
  }
  const md = small && (await uploadUnless413(small, o));
  return md ? { md } : { dropped: 'video too large (413) after re-encode' };
}

// The MR block: the description region between the markers, or (--note) a note under its own heading.
function render(lines, note, extra) {
  const body = [note ? NOTE_HEADING : HEADING, '', ...lines, ...(extra ? ['', extra] : [])].join('\n');
  return note ? body : `${START}\n${body}\n${END}`;
}

// Files to publish: the manifest of --out (shots first, then the video), or every png/mp4 of --files.
function collectFiles(o, outDir) {
  if (o.files) {
    const dir = path.resolve(o.files);
    if (!fs.existsSync(dir)) throw new Fail(64, `--files ${dir} does not exist`);
    const all = fs.readdirSync(dir, { recursive: true }).map((f) => path.join(dir, String(f))).filter((f) => fs.statSync(f).isFile()).sort();
    return { shots: all.filter((f) => f.endsWith('.png')).map((file) => ({ name: path.basename(file, '.png'), file })), video: all.find((f) => f.endsWith('.mp4')) ?? null };
  }
  const mf = path.join(outDir, 'manifest.json');
  if (!fs.existsSync(mf)) throw new Fail(64, `no manifest.json under ${outDir}: run capture first`);
  const m = JSON.parse(fs.readFileSync(mf, 'utf8'));
  return { shots: m.shots.map((s) => ({ name: `${s.name} ${isDesktop(s.width) ? 'desktop' : 'mobile'}`, file: s.file })), video: m.video?.file ?? null };
}

async function setBody(o, block) {
  const { stdout } = await glab(['api', `projects/:id/merge_requests/${o.mr}`], o);
  const current = JSON.parse(stdout).description ?? '';
  const region = new RegExp(`${START}[\\s\\S]*?${END}`);
  const count = (marker) => current.split(marker).length - 1;
  const balanced = count(START) === 1 && count(END) === 1 && current.indexOf(START) < current.indexOf(END);
  if (!balanced && (count(START) || count(END))) console.error(`WARN: the MR description has unbalanced evidence markers (${count(START)} start, ${count(END)} end); appended a fresh region and left the existing text untouched`);
  const next = balanced ? current.replace(region, () => block) : `${current.replace(/\s+$/, '')}${current.trim() ? '\n\n' : ''}${block}\n`;
  if (next !== current) await glab(['mr', 'update', o.mr, '-d', next], o);
}

async function attach(files, o) {
  const paths = [...files.shots.map((s) => s.file), ...(files.video ? [files.video] : [])];
  const hasVideo = Boolean(files.video);
  if (o.forge === 'github') {
    return { block: render([], o.note, GITHUB_LINE), media: paths, shots: files.shots.length, video: hasVideo, note: 'GitHub: attach by hand' };
  }
  if (o.dry) {
    const lines = [...files.shots.map((s) => `- ${s.name}: ${s.file}`), ...(hasVideo ? [`- video: ${files.video}`] : [])];
    return { block: render(lines, o.note), media: paths, shots: files.shots.length, video: hasVideo, note: 'dry: nothing uploaded' };
  }
  await requireTools({ upload: true });
  const items = [];
  for (const s of files.shots) items.push(await uploadOne(s.file, o));
  const shots = items.length;
  const { md: videoMd, dropped } = hasVideo ? await uploadVideo(files.video, o) : {};
  if (videoMd) items.push(videoMd);
  if (!items.length) throw new Fail(5, dropped ?? 'nothing to upload');
  const block = render(items, o.note);
  if (o.mr) {
    try {
      if (o.note) await glab(['mr', 'note', 'create', o.mr, '-m', block], o);
      else await setBody(o, block);
    } catch (e) {
      throw isFail(e) ? e : new Fail(5, `could not write the MR: ${firstLine(e)}`);
    }
  }
  return { block, media: paths, shots, video: Boolean(videoMd), note: dropped ? `video dropped: ${dropped}` : null };
}

// attach, then --md-out and the stdout report.
async function attachAndPrint(files, o) {
  const r = await attach(files, o);
  if (o.mdOut) fs.writeFileSync(path.resolve(o.mdOut), `${r.block}\n`);
  print(o, { code: 0, ...r });
  return 0;
}

// ───────────────────────── main ─────────────────────────

function print(o, res) {
  if (o.json) return console.log(redact(JSON.stringify(res)));
  const lines = [];
  if (res.code === 0) lines.push(`EVIDENCE: ok ${res.shots} shots${res.video ? ' video' : ''}${res.note ? ` (${res.note})` : ''}`);
  else lines.push(`EVIDENCE: failed(${res.code}) ${res.reason}`);
  if (res.media?.length) lines.push(`MEDIA: unsent: ${res.media.join(' ')}`);
  if (res.block) lines.push(res.block);
  return console.log(redact(lines.join('\n')));
}

async function main() {
  const o = parseArgs(process.argv.slice(2));
  if (o.help) return console.log(helpText());
  if (o.cmd === 'doctor') {
    const d = await runDoctor();
    console.log(redact(d.text));
    return d.ready ? 0 : 2;
  }
  if (o.cmd === 'attach' && !o.spec) return attachAndPrint(collectFiles(o, path.resolve(o.out ?? '.')), o);
  const spec = loadSpec(o.spec);
  const kind = o.mode ?? 'both';
  const outDir = path.resolve(o.out ?? path.join(os.tmpdir(), 'mr-evidence', spec.name));
  if (outDir === o.repo || outDir.startsWith(o.repo + path.sep)) throw new Fail(64, `--out ${outDir} is inside the repo: evidence is scratch and never committed`);
  if (o.cmd === 'check') {
    needMedia(spec, kind);
    await requireTools({ screenshots: true, video: wantedMedia(spec, kind).video });
    loadCredentials(spec, o);
    const secs = spec.steps.reduce((n, s) => n + stepSeconds(s), 0);
    console.log(redact(`CHECK: ok ${spec.routes.length} routes x ${spec.widths.length} widths, ${spec.steps.length} video steps ~${secs.toFixed(0)}s, loopback ${spec.allowHosts.join(',')}`));
    return 0;
  }
  if (o.cmd === 'attach') return attachAndPrint(collectFiles(o, outDir), o);
  const manifest = await capture(spec, o, kind, outDir);
  if (o.cmd === 'capture' || kind === 'none') {
    const mediaPaths = [...manifest.shots.map((s) => s.file), ...(manifest.video ? [manifest.video.file] : [])];
    print(o, { code: 0, shots: manifest.shots.length, video: Boolean(manifest.video), media: mediaPaths, block: null, note: o.cmd === 'capture' ? null : 'mode none' });
    return 0;
  }
  // run publishes what this capture just wrote, never a --files directory.
  return attachAndPrint(collectFiles({ ...o, files: undefined }, outDir), o);
}

process.on('SIGINT', () => die(130, 'interrupted'));
for (const sig of ['SIGTERM', 'SIGHUP']) process.on(sig, () => die(143, 'terminated'));
process.on('unhandledRejection', (e) => die(1, `evidence failed: ${e && e.message}`));
main().then(
  (code) => die(code),
  (e) => {
    if (exiting) return undefined;
    const code = isFail(e) ? e.code : 1;
    const reason = isFail(e) ? e.message : `evidence failed: ${e.message}`;
    const json = process.argv.includes('--json');
    if (code === 64) console.error(redact(reason));
    reported = true;
    print({ json }, { code, reason: redact(reason).split('\n')[0], media: [], block: null });
    return die(code);
  },
);
