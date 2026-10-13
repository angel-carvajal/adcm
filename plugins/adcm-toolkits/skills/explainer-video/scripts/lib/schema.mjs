// Strict schema for guiones and setup steps, plus the duration estimate. Pure: returns problem lists, never throws.
import fs from 'node:fs';
import path from 'node:path';
import { voiceText } from './media.mjs';

export const ACTIONS = ['click', 'fill', 'type', 'select', 'press', 'scroll', 'wait', 'pick', 'goto', 'mail', 'upload', 'drag', 'mock', 'none'];
export const TARGETS = new Set(['click', 'fill', 'type', 'select', 'press', 'scroll', 'pick', 'upload', 'drag']);
const NEEDS_SELECTOR = new Set(['click', 'fill', 'select', 'pick', 'upload', 'drag']);
const NEEDS_VALUE = new Set(['fill', 'type', 'select', 'press', 'pick', 'goto', 'mail', 'upload', 'drag', 'mock']);
const GUION_KEYS = new Set(['id', 'slug', 'title', 'profile', 'route', 'next', 'maxSeconds', 'blur', 'tags', 'steps']);
const STEP_KEYS = new Set(['say', 'sayAs', 'caption', 'action', 'selector', 'value', 'highlight', 'waitFor', 'hold']);
const SETUP_KEYS = new Set(['action', 'selector', 'value', 'waitFor']);
const SETUP_ACTIONS = new Set(['goto', 'click', 'fill', 'type', 'select', 'press', 'wait', 'none']);
const NO_PLACEHOLDERS = ['say', 'sayAs', 'caption', 'selector', 'highlight', 'waitFor'];
const MIN_STEPS = 3;
const MAX_STEPS = 20;

// {{env:VAR}} (a secret from the environment) · {{today}} · {{today+N}} / {{today-N}} (ISO date in the config timezone).
export const PLACEHOLDER = /\{\{\s*(?:env:([A-Za-z_][A-Za-z0-9_]*)|today([+-]\d+)?)\s*\}\}/g;

export const isText = (v) => typeof v === 'string' && v.trim().length > 0;
export const isObject = (v) => Boolean(v) && typeof v === 'object' && !Array.isArray(v);
export const isTextList = (v, min = 0) => Array.isArray(v) && v.length >= min && v.every(isText);
export const isHttpUrl = (v) => {
  try {
    return ['http:', 'https:'].includes(new URL(v).protocol);
  } catch {
    return false;
  }
};

function valueProblems(value, at) {
  if (typeof value !== 'string') return JSON.stringify(value)?.includes('{{') ? [at('placeholders are accepted only in string values')] : [];
  return /\{\{/.test(value.replace(PLACEHOLDER, '')) ? [at('value has an unknown or malformed placeholder: use {{env:VAR}}, {{today}} or {{today±N}}')] : [];
}

function actionProblems(s, at, ctx) {
  const bad = [];
  if (NEEDS_SELECTOR.has(s.action) && !isText(s.selector)) bad.push(at(`${s.action} needs selector`));
  if (s.selector !== undefined && !isText(s.selector)) bad.push(at('selector must be text'));
  if (NEEDS_VALUE.has(s.action) && s.value === undefined) bad.push(at(`${s.action} needs value`));
  if (s.action === 'goto' && !(isText(s.value) && (s.value.startsWith('/') || isHttpUrl(s.value)))) bad.push(at('goto needs a path starting with / or an http(s) URL'));
  if (s.action === 'mail' && !ctx.mail) bad.push(at('mail needs mail.url in the config'));
  if (s.action === 'mail' && !(typeof s.value === 'string' && s.value.includes('@'))) bad.push(at('mail needs the address in value'));
  if (s.action === 'upload' && !(isText(s.value) || isTextList(s.value, 1))) bad.push(at('upload needs file path(s) in value'));
  if (s.action === 'drag' && !isText(s.value)) bad.push(at('drag needs the target selector in value'));
  if (s.action === 'mock' && !(isObject(s.value) && isText(s.value.url) && s.value.body !== undefined)) bad.push(at('mock needs value {url, body}'));
  if ((s.action === 'scroll' || s.action === 'wait') && s.value !== undefined && !Number.isFinite(Number(s.value))) bad.push(at(`${s.action} needs a number in value`));
  return bad;
}

export function validateStep(s, n, ctx) {
  const at = (m) => `step ${n}: ${m}`;
  if (!isObject(s)) return [at('is not an object')];
  const bad = Object.keys(s).filter((k) => !STEP_KEYS.has(k)).map((k) => at(`unknown field "${k}"`));
  if (!isText(s.say)) bad.push(at('say is missing'));
  else if (s.say.length > 240) bad.push(at(`say has ${s.say.length} characters (max 240)`));
  if (s.sayAs !== undefined && (!isText(s.sayAs) || s.sayAs.length > 240)) bad.push(at('sayAs must be text of up to 240 characters'));
  if (s.caption !== undefined && (typeof s.caption !== 'string' || s.caption.length > 60)) bad.push(at('caption must be text of up to 60 characters'));
  for (const k of NO_PLACEHOLDERS) if (typeof s[k] === 'string' && s[k].includes('{{')) bad.push(at(`${k} does not accept placeholders`));
  bad.push(...valueProblems(s.value, at));
  if (!ACTIONS.includes(s.action)) return [...bad, at(`action "${s.action}" is not one of ${ACTIONS.join('|')}`)];
  bad.push(...actionProblems(s, at, ctx));
  if (s.highlight !== undefined && !isText(s.highlight)) bad.push(at('highlight must be a selector'));
  if (s.waitFor !== undefined && !isText(s.waitFor)) bad.push(at('waitFor must be a selector'));
  if (s.hold !== undefined && !(Number.isFinite(s.hold) && s.hold >= 0 && s.hold <= 10000)) bad.push(at('hold must be 0-10000 ms'));
  return bad;
}

// Setup steps run off camera before recording (sign-in, seed screens): a subset of the step actions, no narration.
export function validateSetupSteps(steps, where) {
  if (!Array.isArray(steps)) return [`${where} must be a list of steps`];
  return steps.flatMap((s, i) => {
    const at = (m) => `${where}[${i}]: ${m}`;
    if (!isObject(s)) return [at('is not an object')];
    const bad = Object.keys(s).filter((k) => !SETUP_KEYS.has(k)).map((k) => at(`unknown field "${k}"`));
    if (!SETUP_ACTIONS.has(s.action)) return [...bad, at(`action must be ${[...SETUP_ACTIONS].join('|')}`)];
    bad.push(...valueProblems(s.value, at), ...actionProblems(s, at, {}));
    for (const k of ['selector', 'waitFor']) if (typeof s[k] === 'string' && s[k].includes('{{')) bad.push(at(`${k} does not accept placeholders`));
    if (s.waitFor !== undefined && !isText(s.waitFor)) bad.push(at('waitFor must be a selector'));
    return bad;
  });
}

export function loadGuiones(dir) {
  return fs.readdirSync(dir).filter((f) => f.endsWith('.json')).sort().map((file) => {
    try {
      return { file, data: JSON.parse(fs.readFileSync(path.join(dir, file), 'utf8')) };
    } catch (e) {
      return { file, error: `invalid JSON: ${e.message}` };
    }
  });
}

function headerProblems(file, g, ctx) {
  const bad = Object.keys(g).filter((k) => !GUION_KEYS.has(k)).map((k) => `unknown field "${k}"`);
  if (!/^\d{2}$/.test(g.id ?? '')) bad.push('id must be NN (two digits)');
  if ((ctx.ids.get(g.id) || []).length > 1) bad.push(`id repeated in ${ctx.ids.get(g.id).join(', ')}`);
  if (!/^[a-z0-9][a-z0-9-]*$/.test(g.slug ?? '')) bad.push('slug must be lowercase letters, digits and dashes');
  if (g.id && g.slug && file !== `${g.id}-${g.slug}.json`) bad.push(`file must be named ${g.id}-${g.slug}.json`);
  if (!isText(g.title)) bad.push('title is missing');
  if (g.profile !== undefined && !Object.hasOwn(ctx.profiles, g.profile)) bad.push(`profile "${g.profile}" is not in config.profiles`);
  if (!isText(g.route) || !g.route.startsWith('/')) bad.push('route must start with /');
  if (g.next !== undefined && (!/^\d{2}$/.test(g.next) || g.next === g.id)) bad.push(`next "${g.next}" is invalid`);
  if (g.maxSeconds !== undefined && !(Number.isFinite(g.maxSeconds) && g.maxSeconds >= 10 && g.maxSeconds <= 300)) bad.push('maxSeconds must be 10-300');
  if (g.blur !== undefined && !(isTextList(g.blur) && g.blur.every((sel) => !/[{};]/.test(sel)))) bad.push('blur must be a list of CSS selectors without { } or ;');
  if (g.tags !== undefined && !isTextList(g.tags)) bad.push('tags must be a list of text');
  return bad;
}

// ctx: { ids: Map(id → [files]), profiles, mail }
export function validateGuion({ file, data: g, error }, ctx) {
  if (error) return [error];
  if (!isObject(g)) return ['the guion must be an object'];
  const bad = headerProblems(file, g, ctx);
  if (!Array.isArray(g.steps)) return [...bad, `steps must be a list of ${MIN_STEPS} to ${MAX_STEPS} steps`];
  if (g.steps.length < MIN_STEPS || g.steps.length > MAX_STEPS) bad.push(`steps must have ${MIN_STEPS} to ${MAX_STEPS} steps (has ${g.steps.length})`);
  g.steps.forEach((s, i) => bad.push(...validateStep(s, i + 1, ctx)));
  return bad;
}

const actionSeconds = (s) => {
  const typed = String(s.value ?? '').length * 0.04;
  switch (s.action) {
    case 'none':
    case 'mock':
      return 0;
    case 'wait':
      return (Number(s.value) || 500) / 1000;
    case 'type':
      return 1 + typed;
    case 'pick':
      return 2.5 + typed;
    case 'goto':
    case 'drag':
      return 2;
    case 'mail':
      return 3;
    default:
      return 1;
  }
};

// The voice weighs msPerChar per character; the action starts at 60 % of the voice (max 3 s) and each step breathes
// 0.4 s. 1.75 s of title card before the first step, 0.5 s of tail and 2 s of next card when there is one.
export function estimate(g, { msPerChar, pronunciation, hasNext }) {
  let t = 1.75;
  for (const s of g.steps) {
    const d = (voiceText(s, pronunciation).length * msPerChar) / 1000;
    t += Math.max(d, Math.min(0.6 * d, 3) + actionSeconds(s) + (s.waitFor ? 0.3 : 0)) + 0.4 + (s.hold || 0) / 1000;
  }
  return t + 0.5 + (hasNext ? 2 : 0);
}
