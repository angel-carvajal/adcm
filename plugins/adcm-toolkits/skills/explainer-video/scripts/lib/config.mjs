// Recorder config: strict keys, defaults, paths anchored to the config file's directory, placeholders and redaction.
import fs from 'node:fs';
import path from 'node:path';
import { ENGINES } from './media.mjs';
import { PLACEHOLDER, isHttpUrl, isObject, isText, isTextList, validateSetupSteps } from './schema.mjs';

export class Fail extends Error {
  constructor(code, message) {
    super(message);
    this.name = 'Fail';
    this.code = code;
  }
}

export const isFail = (e) => e?.name === 'Fail';

const KEYS = new Set([
  'baseUrl', 'allowHosts', 'guionesDir', 'outDir', 'viewport', 'locale', 'timezone', 'voice', 'fallbacks', 'brand',
  'fonts', 'durationWindow', 'denyList', 'pronunciation', 'mail', 'setup', 'profiles',
]);
const DEFAULTS = {
  allowHosts: ['localhost', '127.0.0.1'],
  viewport: { width: 1280, height: 800 },
  locale: 'es-MX',
  timezone: 'America/Mexico_City',
  voice: { engine: 'edge', id: 'es-MX-DaliaNeural', rate: null },
  fallbacks: ['piper', 'say'],
  brand: { accent: '#3B82F6', bg: '#111318' },
  durationWindow: [55, 125],
};

const engineNames = Object.keys(ENGINES).join('|');
const isPositiveInt = (n) => Number.isInteger(n) && n > 0;
const isColor = (c) => typeof c === 'string' && /^#[0-9a-f]{6}$/i.test(c);
const validTimezone = (tz) => {
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: tz });
    return true;
  } catch {
    return false;
  }
};

function voiceProblems(v) {
  if (v === undefined) return [];
  if (!isObject(v)) return ['voice must be {engine, id, rate}'];
  const bad = Object.keys(v).filter((k) => !['engine', 'id', 'rate'].includes(k)).map((k) => `voice: unknown key "${k}"`);
  if (v.engine !== undefined && !Object.hasOwn(ENGINES, v.engine)) bad.push(`voice.engine must be ${engineNames}`);
  if (v.id !== undefined && !isText(v.id)) bad.push('voice.id must be text');
  if (v.rate !== undefined && v.rate !== null && !['string', 'number'].includes(typeof v.rate)) bad.push('voice.rate must be text or a number');
  return bad;
}

function shapeProblems(c) {
  const bad = [];
  if (c.allowHosts !== undefined && !isTextList(c.allowHosts, 1)) bad.push('allowHosts must be a non-empty list of host names');
  for (const k of ['guionesDir', 'outDir', 'locale', 'denyList']) if (c[k] !== undefined && !isText(c[k])) bad.push(`${k} must be text`);
  if (c.timezone !== undefined && !(isText(c.timezone) && validTimezone(c.timezone))) bad.push('timezone must be an IANA zone');
  if (c.viewport !== undefined && !(isObject(c.viewport) && isPositiveInt(c.viewport.width) && isPositiveInt(c.viewport.height))) bad.push('viewport must be {width, height} in pixels');
  if (c.fallbacks !== undefined && !(Array.isArray(c.fallbacks) && c.fallbacks.every((e) => Object.hasOwn(ENGINES, e)))) bad.push(`fallbacks must be a list of ${engineNames}`);
  if (c.brand !== undefined && !(isObject(c.brand) && Object.entries(c.brand).every(([k, v]) => ['accent', 'bg'].includes(k) && isColor(v)))) bad.push('brand must be {accent, bg} as #rrggbb');
  if (c.fonts !== undefined && !(isTextList(c.fonts) && c.fonts.every((f) => !/["'\\{};<]/.test(f)))) bad.push('fonts must be a list of font family names without quotes, backslashes, braces, semicolons or <');
  const w = c.durationWindow;
  if (w !== undefined && !(Array.isArray(w) && w.length === 2 && w.every(Number.isFinite) && w[0] >= 0 && w[0] < w[1])) bad.push('durationWindow must be [minSeconds, maxSeconds]');
  if (c.pronunciation !== undefined && !(isObject(c.pronunciation) && Object.entries(c.pronunciation).every(([k, v]) => isText(k) && isText(v)))) bad.push('pronunciation must map words to how they are read');
  if (c.mail !== undefined && !(isObject(c.mail) && isHttpUrl(c.mail.url) && Object.keys(c.mail).length === 1)) bad.push('mail must be {url}');
  return bad;
}

function setupProblems(c) {
  const bad = c.setup === undefined ? [] : validateSetupSteps(c.setup, 'setup');
  if (c.profiles === undefined) return bad;
  if (!isObject(c.profiles)) return [...bad, 'profiles must map a name to {setup}'];
  for (const [name, p] of Object.entries(c.profiles)) {
    if (!isObject(p) || Object.keys(p).some((k) => k !== 'setup')) bad.push(`profiles.${name} must be {setup}`);
    else if (p.setup !== undefined) bad.push(...validateSetupSteps(p.setup, `profiles.${name}.setup`));
  }
  return bad;
}

function configProblems(c, { needBaseUrl }) {
  if (!isObject(c)) return ['the config must be a JSON object'];
  const bad = Object.keys(c).filter((k) => !KEYS.has(k)).map((k) => `unknown key "${k}"`);
  if ((c.baseUrl !== undefined || needBaseUrl) && !isHttpUrl(c.baseUrl)) bad.push('baseUrl must be an http(s) URL');
  return [...bad, ...shapeProblems(c), ...voiceProblems(c.voice), ...setupProblems(c)];
}

function normalize(c, dir) {
  const at = (p) => path.resolve(dir, p);
  const engine = c.voice?.engine ?? DEFAULTS.voice.engine;
  const defaultId = engine === DEFAULTS.voice.engine ? DEFAULTS.voice.id : null;
  return {
    dir,
    baseUrl: c.baseUrl ? c.baseUrl.replace(/\/+$/, '') : null,
    allowHosts: (c.allowHosts ?? DEFAULTS.allowHosts).map((h) => h.toLowerCase()),
    guionesDir: at(c.guionesDir ?? 'guiones'),
    outDir: at(c.outDir ?? 'out'),
    viewport: { ...(c.viewport ?? DEFAULTS.viewport) },
    locale: c.locale ?? DEFAULTS.locale,
    timezone: c.timezone ?? DEFAULTS.timezone,
    voice: { engine, id: c.voice?.id ?? defaultId, rate: c.voice?.rate ?? null },
    fallbacks: c.fallbacks ?? DEFAULTS.fallbacks,
    brand: { ...DEFAULTS.brand, ...c.brand },
    fonts: c.fonts ?? [],
    durationWindow: c.durationWindow ?? DEFAULTS.durationWindow,
    denyList: c.denyList ? at(c.denyList) : null,
    pronunciation: c.pronunciation ?? {},
    mail: c.mail ?? null,
    setup: c.setup ?? [],
    profiles: c.profiles ?? {},
  };
}

// --config is relative to the cwd; every path inside the config is relative to the config file's directory.
// optional: a missing file yields the defaults (used by --doctor before any config exists).
export function loadConfig(file, { optional = false } = {}) {
  const abs = path.resolve(file);
  if (!fs.existsSync(abs)) {
    if (optional) return normalize({}, path.dirname(abs));
    throw new Fail(2, `config not found: ${abs}`);
  }
  let raw;
  try {
    raw = JSON.parse(fs.readFileSync(abs, 'utf8'));
  } catch (e) {
    throw new Fail(2, `${abs}: invalid JSON (${e.message})`);
  }
  const problems = configProblems(raw, { needBaseUrl: !optional });
  if (problems.length) throw new Fail(2, `${abs}:\n  - ${problems.join('\n  - ')}`);
  return normalize(raw, path.dirname(abs));
}

export const hostAllowed = (url, allowHosts) => {
  try {
    return allowHosts.includes(new URL(url).hostname.toLowerCase());
  } catch {
    return false;
  }
};

// Every value that came from {{env:VAR}} and every link token is struck from console, dom dumps, srt and written
// files: Playwright quotes the value of a failing fill and the URL of a goto that times out.
const secrets = new Set();
export const redact = (text) =>
  [...secrets].reduce((t, s) => t.replaceAll(s, '***'), String(text)).replace(/(token(?:_hash)?=)[^&\s"')]+/gi, '$1***');

// A page prints the value percent-encoded when it travels in a URL, so every encoding is struck as well.
const encodedForms = (value) => [encodeURIComponent(value), encodeURI(value), encodeURIComponent(value).replaceAll('%20', '+')];

function secretFromEnv(name) {
  const value = process.env[name];
  if (!value) throw new Fail(2, `environment variable ${name} is not set (a {{env:${name}}} placeholder needs it)`);
  for (const form of [value, ...encodedForms(value)]) secrets.add(form);
  return value;
}

// formatToParts and not toLocaleDateString('en-CA'): that locale's order changes with each Node's ICU.
function isoDate(timezone, days) {
  const fmt = new Intl.DateTimeFormat('en-US', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit' });
  const part = Object.fromEntries(fmt.formatToParts(new Date(Date.now() + days * 86400000)).map((x) => [x.type, x.value]));
  return `${part.year}-${part.month}-${part.day}`;
}

export const fillPlaceholders = (value, timezone) =>
  typeof value !== 'string' ? value : value.replace(PLACEHOLDER, (_m, env, offset) => (env ? secretFromEnv(env) : isoDate(timezone, Number(offset || 0))));
