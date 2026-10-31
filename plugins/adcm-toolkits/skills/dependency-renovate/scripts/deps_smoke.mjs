#!/usr/bin/env node
// Visual smoke for dependency runs: shoot a set of routes to PNG files, then compare two sets with a deterministic pixel diff.
//
// usage: deps_smoke.mjs doctor
//        deps_smoke.mjs shoot --base URL --routes /a,/b --out DIR [--serve CMD --ready URL] [--with "CMD {url} {out}"] [options]
//        deps_smoke.mjs diff BEFORE_DIR AFTER_DIR [--threshold 0.002] [--tolerance 16] [--noise DIR] [--out DIR] [--json]
//   --help lists every option.
// Files: <out>/<slug>.png (the route "/" is root, every other run of non-alphanumerics becomes "-") and <out>/manifest.json, without timestamps.
// Env: SMOKE_CHANNEL (default chrome) · PW_CORE_DIR (a playwright-core directory).
// Exit: shoot 0 every route shot · 1 some route failed · 2 environment (Node < 20, playwright-core, Chrome, busy port, server never ready) · 64 usage.
//       diff  0 every route same · 1 changed, resized, missing or unstable · 2 unsupported PNG · 64 usage.
// Output: at most 40 lines ending `SMOKE: …` (`DOCTOR: …` for doctor); --json prints one JSON line instead.
// --serve runs the server in its own process group: <out>/.serve.pid names it, <out>/.serve.log keeps its output, the group is killed on every
// way out, and a pidfile left by a run that died is reaped at the start of the next shoot.
// A pixel is changed when its largest channel delta (RGBA) exceeds --tolerance; a route is changed when the changed share exceeds --threshold.
// For an unstable route, ratio and bbox describe the baseline against its own second shot, the comparison that decided the verdict.
import fs from 'node:fs';
import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';
import { spawn, spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';

const SYNOPSIS = [
  'usage: deps-smoke doctor',
  '       deps-smoke shoot --base URL --routes /a,/b --out DIR [--serve CMD --ready URL] [--with "CMD {url} {out}"] [options]',
  '       deps-smoke diff BEFORE_DIR AFTER_DIR [--threshold 0.002] [--tolerance 16] [--noise DIR] [--out DIR] [--json]',
];
const HELP = [
  ...SYNOPSIS,
  '',
  'doctor  checks Node 20+, playwright-core and the Chrome channel; the last line is DOCTOR: ready|not ready',
  'shoot   one PNG per route plus manifest.json in DIR; the last line is SMOKE: shot(n) [failed(/x, ...)]',
  '  --serve CMD         start the app in its own process group; the group is killed on every exit. Needs --ready',
  '  --ready URL         polled up to --ready-timeout seconds (120): a TCP accept plus an HTTP answer below 500',
  '  --ready-status S    2xx demands a 2xx answer, any accepts any HTTP answer',
  '  --env K=V           environment of the server, repeatable; most apps need PORT and HOST',
  '  --cwd DIR           working directory of the server and of --with',
  '  --node-pin VER      puts that nvm Node first on the server PATH (20, 20.11 or 20.11.0)',
  '  --with "CMD {url} {out}"  capture with your own command; {url} and {out} are shell-quoted for you',
  '  --width 1440 --height 900 --full   viewport and full-page shots (built-in shooter)',
  '  --mask "/route=sel,sel"  paints those elements over, repeatable (built-in shooter)',
  '  --cookie name=value      sent with every request, repeatable (built-in shooter)',
  '  --timeout 45        seconds per route · --json prints one JSON line instead of text',
  'diff    pixel comparison of two shot sets; the last line is',
  '        SMOKE: same(n) | changed(/a 0.84%, ...) resized(/c) missing(/d) unstable(/e) unparsed(/f)',
  '  --threshold 0.002   share of changed pixels above which a route is changed',
  '  --tolerance 16      channel delta above which a pixel counts as changed',
  '  --noise DIR         a second shot of BEFORE_DIR: a route that differs from it is unstable',
  '  --out DIR           writes diff-<route>.png (changed and resized routes) and diff.json; without it nothing is written',
  'Exit: 0 ok · 1 changed, resized, missing, unstable or a route failed · 2 environment or unsupported PNG · 64 usage',
  'Env: SMOKE_CHANNEL (default chrome) · PW_CORE_DIR (a playwright-core directory)',
];

const MAX_LINES = 40;
const PIDFILE = '.serve.pid';
const LOGFILE = '.serve.log';
const DEFAULTS = { width: 1440, height: 900, timeout: 45, readyTimeout: 120, threshold: 0.002, tolerance: 16 };

class EnvError extends Error {}
class Unparsed extends Error {}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const channel = () => process.env.SMOKE_CHANNEL || 'chrome';
const nodeMajor = () => Number(process.versions.node.split('.')[0]);
const firstLine = (s) => String(s).split('\n')[0].slice(0, 160);

function exitAfterFlush(text, code) {
  setTimeout(() => process.exit(code), 3000);
  process.stdout.write(`${text}\n`, () => process.exit(code));
}

function helpExit() {
  try {
    fs.writeSync(1, `${HELP.join('\n')}\n`);
  } catch {
    console.log(HELP.join('\n'));
  }
  process.exit(0);
}

function usageExit(msg) {
  if (msg) console.error(msg);
  console.error(SYNOPSIS.join('\n'));
  process.exit(64);
}

// ───────────────────────── args ─────────────────────────

const FLAGS = {
  doctor: { value: [], repeat: [], bool: [] },
  shoot: {
    value: ['--base', '--routes', '--out', '--serve', '--ready', '--ready-status', '--ready-timeout', '--cwd', '--node-pin', '--with', '--width', '--height', '--timeout'],
    repeat: ['--env', '--mask', '--cookie'],
    bool: ['--full', '--json'],
  },
  diff: { value: ['--threshold', '--tolerance', '--noise', '--out'], repeat: [], bool: ['--json'] },
};

const camel = (flag) => flag.slice(2).replace(/-([a-z])/g, (_, c) => c.toUpperCase());

function parseFlags(sub, argv) {
  const spec = FLAGS[sub];
  const o = { _: [], given: new Set() };
  for (const flag of spec.repeat) o[camel(flag)] = [];
  for (let i = 0; i < argv.length; i++) {
    let a = argv[i];
    let inline = null;
    if (a === '--help' || a === '-h') helpExit();
    if (a.startsWith('--') && a.includes('=')) {
      inline = a.slice(a.indexOf('=') + 1);
      a = a.slice(0, a.indexOf('='));
    }
    if (spec.bool.includes(a)) {
      if (inline !== null) usageExit(`${a} takes no value`);
      o[camel(a)] = true;
    } else if (spec.value.includes(a) || spec.repeat.includes(a)) {
      let v = inline;
      if (v === null) {
        if (i + 1 >= argv.length || argv[i + 1].startsWith('--')) usageExit(`${a} needs a value`);
        v = argv[++i];
      }
      if (spec.repeat.includes(a)) o[camel(a)].push(v);
      else o[camel(a)] = v;
    } else if (a.startsWith('-') && a.length > 1) {
      usageExit(`unknown argument: ${a}`);
    } else {
      o._.push(a);
      continue;
    }
    o.given.add(a);
  }
  return o;
}

function number(value, flag, { min, max, int = false }) {
  const n = Number(value);
  if (String(value).trim() === '' || !Number.isFinite(n) || n < min || n > max || (int && !Number.isInteger(n))) {
    usageExit(`${flag} must be ${int ? 'an integer' : 'a number'} from ${min} to ${max}`);
  }
  return n;
}

const slugOf = (route) => route.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 80).replace(/-+$/, '') || 'root';

// ───────────────────────── png ─────────────────────────

const PNG_SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
const CHANNELS = { 0: 1, 2: 3, 3: 1, 4: 2, 6: 4 };
const MAX_PIXELS = 120e6;

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(buf) {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) c = CRC_TABLE[(c ^ buf[i]) & 255] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

const paeth = (a, b, c) => {
  const p = a + b - c;
  const pa = Math.abs(p - a);
  const pb = Math.abs(p - b);
  const pc = Math.abs(p - c);
  return pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
};

// Reverses the five PNG row filters in place; raw holds h rows of (1 filter byte + w * bpp bytes).
function unfilter(raw, w, h, bpp) {
  const stride = w * bpp;
  for (let y = 0; y < h; y++) {
    const at = y * (stride + 1);
    const type = raw[at];
    const row = at + 1;
    const up = y ? row - (stride + 1) : -1;
    if (type === 1) {
      for (let i = bpp; i < stride; i++) raw[row + i] += raw[row + i - bpp];
    } else if (type === 2) {
      if (up >= 0) for (let i = 0; i < stride; i++) raw[row + i] += raw[up + i];
    } else if (type === 3) {
      for (let i = 0; i < stride; i++) {
        const left = i >= bpp ? raw[row + i - bpp] : 0;
        raw[row + i] += (left + (up >= 0 ? raw[up + i] : 0)) >> 1;
      }
    } else if (type === 4) {
      for (let i = 0; i < stride; i++) {
        const left = i >= bpp ? raw[row + i - bpp] : 0;
        const above = up >= 0 ? raw[up + i] : 0;
        const corner = up >= 0 && i >= bpp ? raw[up + i - bpp] : 0;
        raw[row + i] += paeth(left, above, corner);
      }
    } else if (type !== 0) {
      throw new Unparsed(`bad filter type ${type}`);
    }
  }
}

function toRgba(raw, head, palette, alpha) {
  const { w, h, color } = head;
  const stride = w * CHANNELS[color];
  const out = new Uint8Array(w * h * 4);
  for (let y = 0; y < h; y++) {
    let i = y * (stride + 1) + 1;
    let o = y * w * 4;
    if (color === 6) {
      out.set(raw.subarray(i, i + stride), o);
      continue;
    }
    for (let x = 0; x < w; x++, o += 4) {
      if (color === 2) {
        out[o] = raw[i++];
        out[o + 1] = raw[i++];
        out[o + 2] = raw[i++];
        out[o + 3] = 255;
      } else if (color === 0) {
        out[o] = out[o + 1] = out[o + 2] = raw[i++];
        out[o + 3] = 255;
      } else if (color === 4) {
        out[o] = out[o + 1] = out[o + 2] = raw[i++];
        out[o + 3] = raw[i++];
      } else {
        const idx = raw[i++];
        if (idx * 3 + 2 >= palette.length) throw new Unparsed('palette index out of range');
        out[o] = palette[idx * 3];
        out[o + 1] = palette[idx * 3 + 1];
        out[o + 2] = palette[idx * 3 + 2];
        out[o + 3] = alpha && idx < alpha.length ? alpha[idx] : 255;
      }
    }
  }
  return out;
}

function checkHeader(data) {
  if (data.length !== 13) throw new Unparsed('bad IHDR');
  const head = { w: data.readUInt32BE(0), h: data.readUInt32BE(4), depth: data[8], color: data[9], compression: data[10], filter: data[11], interlace: data[12] };
  if (!(head.color in CHANNELS)) throw new Unparsed(`colour type ${head.color} is not supported (0, 2, 3, 4 and 6 are)`);
  if (head.depth !== 8) throw new Unparsed(`${head.depth}-bit samples are not supported (8-bit only)`);
  if (head.interlace !== 0) throw new Unparsed('interlaced PNGs are not supported');
  if (head.compression !== 0 || head.filter !== 0) throw new Unparsed('unknown compression or filter method');
  if (!head.w || !head.h || head.w * head.h > MAX_PIXELS) throw new Unparsed(`image size ${head.w}x${head.h} is out of range`);
  return head;
}

// 8-bit, non-interlaced PNGs of colour type 0, 2, 3, 4 and 6, returned as RGBA.
function decodePng(buf) {
  if (buf.length < 8 || !buf.subarray(0, 8).equals(PNG_SIGNATURE)) throw new Unparsed('not a PNG file');
  let pos = 8;
  let head = null;
  let palette = null;
  let alpha = null;
  const idat = [];
  while (pos + 12 <= buf.length) {
    const len = buf.readUInt32BE(pos);
    const type = buf.toString('latin1', pos + 4, pos + 8);
    const end = pos + 8 + len;
    if (end + 4 > buf.length) throw new Unparsed(`truncated ${type} chunk`);
    if (crc32(buf.subarray(pos + 4, end)) !== buf.readUInt32BE(end)) throw new Unparsed(`bad checksum in ${type}`);
    const data = buf.subarray(pos + 8, end);
    if (type === 'IHDR') head = checkHeader(data);
    else if (type === 'PLTE') palette = data;
    else if (type === 'tRNS') alpha = data;
    else if (type === 'IDAT') idat.push(data);
    else if (type === 'IEND') break;
    pos = end + 4;
  }
  if (!head) throw new Unparsed('missing IHDR');
  if (!idat.length) throw new Unparsed('missing image data');
  if (head.color === 3 && !palette) throw new Unparsed('missing palette');
  let raw;
  try {
    raw = zlib.inflateSync(Buffer.concat(idat));
  } catch {
    throw new Unparsed('corrupt image data');
  }
  if (raw.length < head.h * (head.w * CHANNELS[head.color] + 1)) throw new Unparsed('truncated image data');
  unfilter(raw, head.w, head.h, CHANNELS[head.color]);
  return { w: head.w, h: head.h, rgba: toRgba(raw, head, palette, alpha) };
}

function pngChunk(type, data) {
  const body = Buffer.concat([Buffer.from(type, 'latin1'), data]);
  const out = Buffer.alloc(body.length + 8);
  out.writeUInt32BE(data.length, 0);
  body.copy(out, 4);
  out.writeUInt32BE(crc32(body), body.length + 4);
  return out;
}

// 8-bit RGB, filter 0 on every row.
function encodePng(w, h, rgb) {
  const stride = w * 3;
  const raw = Buffer.alloc(h * (stride + 1));
  for (let y = 0; y < h; y++) Buffer.from(rgb.buffer, rgb.byteOffset + y * stride, stride).copy(raw, y * (stride + 1) + 1);
  const header = Buffer.alloc(13);
  header.writeUInt32BE(w, 0);
  header.writeUInt32BE(h, 4);
  header[8] = 8;
  header[9] = 2;
  return Buffer.concat([PNG_SIGNATURE, pngChunk('IHDR', header), pngChunk('IDAT', zlib.deflateSync(raw, { level: 6 })), pngChunk('IEND', Buffer.alloc(0))]);
}

const isPngFile = (file) => {
  try {
    const fd = fs.openSync(file, 'r');
    const head = Buffer.alloc(8);
    fs.readSync(fd, head, 0, 8, 0);
    fs.closeSync(fd);
    return head.equals(PNG_SIGNATURE);
  } catch {
    return false;
  }
};

// ───────────────────────── diff ─────────────────────────

const DIM = Uint8Array.from({ length: 256 }, (_, v) => Math.round(v * 0.3));
const ORDER = ['changed', 'resized', 'missing', 'unstable', 'unparsed'];
const round6 = (n) => Math.round(n * 1e6) / 1e6;
const percent = (ratio) => (ratio > 0 && ratio < 0.0001 ? '<0.01%' : `${(ratio * 100).toFixed(2)}%`);
const sizeText = (size) => (size ? `${size[0]}x${size[1]}` : '?');

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return null;
  }
}

// A shot set is a manifest (the routes and whether each was shot) or, without one, the PNG files themselves.
function loadSet(dir) {
  const manifest = readJson(path.join(dir, 'manifest.json'));
  const routes = new Map();
  if (manifest && Array.isArray(manifest.routes)) {
    for (const r of manifest.routes) {
      if (!r || typeof r.route !== 'string') continue;
      const file = path.join(dir, typeof r.file === 'string' ? path.basename(r.file) : `${slugOf(r.route)}.png`);
      routes.set(r.route, r.ok !== false && fs.existsSync(file) ? file : null);
    }
  } else {
    for (const name of fs.readdirSync(dir).filter((n) => n.endsWith('.png') && !n.startsWith('diff-')).sort()) {
      const stem = name.slice(0, -4);
      routes.set(stem === 'root' ? '/' : `/${stem}`, path.join(dir, name));
    }
  }
  return { dir, manifest, routes };
}

function manifestWarnings(before, after) {
  if (!before.manifest || !after.manifest) return [];
  const diffs = [];
  for (const key of ['tool', 'playwright', 'channel', 'viewport', 'full']) {
    const x = JSON.stringify(before.manifest[key] ?? null);
    const y = JSON.stringify(after.manifest[key] ?? null);
    if (x !== y) diffs.push(`${key} ${x} -> ${y}`);
  }
  return diffs.length ? [`WARN manifest mismatch (before -> after): ${diffs.join(', ')}`] : [];
}

function comparePixels(a, b, tolerance, wantMask) {
  const w = Math.min(a.w, b.w);
  const h = Math.min(a.h, b.h);
  const mask = wantMask ? new Uint8Array(w * h) : null;
  const a32 = new Uint32Array(a.rgba.buffer, a.rgba.byteOffset, a.w * a.h);
  const b32 = new Uint32Array(b.rgba.buffer, b.rgba.byteOffset, b.w * b.h);
  let changed = 0;
  let x0 = w;
  let y0 = h;
  let x1 = -1;
  let y1 = -1;
  for (let y = 0; y < h; y++) {
    let pa = y * a.w;
    let pb = y * b.w;
    for (let x = 0; x < w; x++, pa++, pb++) {
      if (a32[pa] === b32[pb]) continue;
      const ia = pa * 4;
      const ib = pb * 4;
      const delta = Math.max(
        Math.abs(a.rgba[ia] - b.rgba[ib]),
        Math.abs(a.rgba[ia + 1] - b.rgba[ib + 1]),
        Math.abs(a.rgba[ia + 2] - b.rgba[ib + 2]),
        Math.abs(a.rgba[ia + 3] - b.rgba[ib + 3]),
      );
      if (delta <= tolerance) continue;
      changed++;
      if (x < x0) x0 = x;
      if (x > x1) x1 = x;
      if (y < y0) y0 = y;
      if (y > y1) y1 = y;
      if (mask) mask[y * w + x] = 1;
    }
  }
  const total = w * h;
  return { ow: w, oh: h, ratio: changed / total, bbox: changed ? { x: x0, y: y0, w: x1 - x0 + 1, h: y1 - y0 + 1 } : null, mask };
}

// The after image dimmed to 30%, changed pixels in red.
function writeDiffPng(file, after, cmp) {
  const rgb = new Uint8Array(after.w * after.h * 3);
  let o = 0;
  for (let y = 0; y < after.h; y++) {
    let i = y * after.w * 4;
    for (let x = 0; x < after.w; x++, i += 4, o += 3) {
      if (y < cmp.oh && x < cmp.ow && cmp.mask[y * cmp.ow + x]) {
        rgb[o] = 255;
      } else {
        rgb[o] = DIM[after.rgba[i]];
        rgb[o + 1] = DIM[after.rgba[i + 1]];
        rgb[o + 2] = DIM[after.rgba[i + 2]];
      }
    }
  }
  fs.writeFileSync(file, encodePng(after.w, after.h, rgb));
}

function judgeRoute(route, sets, opts) {
  const res = { route, verdict: 'same', ratio: null, bbox: null, size_before: null, size_after: null, note: '' };
  const file = { before: sets.before.routes.get(route) || null, after: sets.after.routes.get(route) || null };
  const absent = ['before', 'after'].filter((side) => !file[side]);
  if (absent.length) return { ...res, verdict: 'missing', note: `(${absent.join(', ')})` };
  const unparsed = (side, e) => {
    if (!(e instanceof Unparsed)) throw e;
    return { ...res, verdict: 'unparsed', note: `${side}: ${e.message}` };
  };
  const img = {};
  for (const side of ['before', 'after']) {
    try {
      img[side] = decodePng(fs.readFileSync(file[side]));
      res[`size_${side}`] = [img[side].w, img[side].h];
    } catch (e) {
      return unparsed(side, e);
    }
  }
  const noiseFile = opts.noise ? opts.noise.routes.get(route) || null : null;
  if (opts.noise && !noiseFile) opts.noiseGaps.push(route);
  if (noiseFile) {
    let again;
    try {
      again = decodePng(fs.readFileSync(noiseFile));
    } catch (e) {
      return unparsed('noise', e);
    }
    const sameSize = again.w === img.before.w && again.h === img.before.h;
    const self = sameSize ? comparePixels(img.before, again, opts.tolerance, false) : null;
    if (!self || self.ratio > opts.threshold) {
      const note = self ? `noise ${percent(self.ratio)}` : `noise sizes ${sizeText([img.before.w, img.before.h])} vs ${sizeText([again.w, again.h])}`;
      return { ...res, verdict: 'unstable', ratio: self ? round6(self.ratio) : null, bbox: self ? self.bbox : null, note };
    }
  }
  const cmp = comparePixels(img.before, img.after, opts.tolerance, Boolean(opts.out));
  const resized = img.before.w !== img.after.w || img.before.h !== img.after.h;
  res.ratio = round6(cmp.ratio);
  res.bbox = cmp.bbox;
  res.verdict = resized ? 'resized' : cmp.ratio > opts.threshold ? 'changed' : 'same';
  if (opts.out && (res.verdict === 'changed' || res.verdict === 'resized')) writeDiffPng(path.join(opts.out, `diff-${slugOf(route)}.png`), img.after, cmp);
  return res;
}

const diffLine = (r) => {
  const box = r.bbox ? ` bbox ${r.bbox.x},${r.bbox.y} ${r.bbox.w}x${r.bbox.h}` : '';
  if (r.verdict === 'changed') return `changed ${r.route} ${percent(r.ratio)}${box}`;
  if (r.verdict === 'resized') return `resized ${r.route} ${sizeText(r.size_before)} -> ${sizeText(r.size_after)} overlap ${percent(r.ratio)}${box}`;
  return `${r.verdict} ${r.route} ${r.note}`;
};

const names = (items, limit = 8) => (items.length > limit ? `${items.slice(0, limit).join(', ')}, +${items.length - limit}` : items.join(', '));

// Capped at MAX_LINES: the detail lines give way first, the verdict line is always last.
function printReport(o, { head, warnings, detail, verdict, exit, json }) {
  if (o.json) return exitAfterFlush(JSON.stringify({ verdict, exit, ...json, warnings }), exit);
  const room = Math.max(MAX_LINES - 1 - head.length - warnings.length, 1);
  const shown = detail.length > room ? [...detail.slice(0, room - 1), `... +${detail.length - (room - 1)} more lines (--json lists them all)`] : detail;
  return exitAfterFlush([...head, ...warnings, ...shown, verdict].join('\n'), exit);
}

async function diffMain(o) {
  if (o._.length !== 2) usageExit('diff needs BEFORE_DIR and AFTER_DIR');
  const threshold = o.threshold === undefined ? DEFAULTS.threshold : number(o.threshold, '--threshold', { min: 0, max: 1 });
  const tolerance = o.tolerance === undefined ? DEFAULTS.tolerance : number(o.tolerance, '--tolerance', { min: 0, max: 255, int: true });
  const dirs = { before: path.resolve(o._[0]), after: path.resolve(o._[1]) };
  if (o.noise) dirs.noise = path.resolve(o.noise);
  for (const [label, dir] of Object.entries(dirs)) {
    if (!fs.existsSync(dir) || !fs.statSync(dir).isDirectory()) usageExit(`${label} directory not found: ${dir}`);
  }
  const sets = { before: loadSet(dirs.before), after: loadSet(dirs.after) };
  const routes = [...new Set([...sets.before.routes.keys(), ...sets.after.routes.keys()])];
  if (!routes.length) usageExit(`no routes found in ${dirs.before} or ${dirs.after}`);
  const out = o.out ? path.resolve(o.out) : null;
  if (out) {
    fs.mkdirSync(out, { recursive: true });
    for (const name of fs.readdirSync(out)) if (/^diff-.*\.png$/.test(name)) fs.rmSync(path.join(out, name));
  }
  const opts = { threshold, tolerance, out, noise: dirs.noise ? loadSet(dirs.noise) : null, noiseGaps: [] };
  const results = routes.map((route) => judgeRoute(route, sets, opts));
  const bad = results.filter((r) => r.verdict !== 'same');
  const pub = results.map((r) => ({ route: r.route, verdict: r.verdict, ratio: r.ratio, bbox: r.bbox, size_before: r.size_before, size_after: r.size_after, ...(r.verdict === 'unparsed' ? { reason: r.note } : {}) }));
  const written = out ? results.filter((r) => r.verdict === 'changed' || r.verdict === 'resized').length : 0;
  if (out) fs.writeFileSync(path.join(out, 'diff.json'), `${JSON.stringify({ routes: pub, threshold, tolerance }, null, 2)}\n`);

  const warnings = manifestWarnings(sets.before, sets.after);
  if (opts.noiseGaps.length) warnings.push(`WARN noise set has no shot of ${names(opts.noiseGaps, 4)}`);
  const parts = ORDER.map((verdict) => {
    const hits = bad.filter((r) => r.verdict === verdict);
    return hits.length ? `${verdict}(${names(hits.map((r) => (verdict === 'changed' ? `${r.route} ${percent(r.ratio)}` : r.route)))})` : null;
  }).filter(Boolean);
  const detail = bad.map(diffLine);
  if (bad.length && results.length > bad.length) detail.push(`same ${results.length - bad.length}`);
  const head = [`diff · ${results.length} routes · tolerance ${tolerance} · threshold ${(threshold * 100).toFixed(2)}%`];
  if (out) head.push(`wrote diff.json and ${written} diff image${written === 1 ? '' : 's'} to ${out}`);
  const exit = results.some((r) => r.verdict === 'unparsed') ? 2 : bad.length ? 1 : 0;
  return printReport(o, { head, warnings, detail, verdict: `SMOKE: ${bad.length ? parts.join(' ') : `same(${results.length})`}`, exit, json: { routes: pub, threshold, tolerance } });
}

// ───────────────────────── playwright ─────────────────────────
// keep in sync: capture.mjs, record.mjs

const PLAYWRIGHT_RECIPE = 'npx -y -p playwright-core@1.63 node -e 0';

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

// Order: PW_CORE_DIR → the npx cache (newest stable first) → the project's node_modules (playwright-core, then playwright).
function resolvePlaywright(projectDir) {
  if (process.env.PW_CORE_DIR) return tryLoad(expandHome(process.env.PW_CORE_DIR));
  const cache = path.join(os.homedir(), '.npm', '_npx');
  const dirs = fs.existsSync(cache) ? fs.readdirSync(cache).map((d) => path.join(cache, d, 'node_modules', 'playwright-core')) : [];
  const found = dirs.filter((d) => fs.existsSync(path.join(d, 'package.json'))).map(tryLoad).filter(Boolean);
  found.sort((a, b) => isStable(b.version) - isStable(a.version) || compareVersions(b.version, a.version));
  if (found[0]) return found[0];
  const local = createRequire(path.join(projectDir, 'noop.js'));
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
  return null;
}

function needCore(projectDir) {
  const core = resolvePlaywright(projectDir);
  if (core) return core;
  if (process.env.PW_CORE_DIR) throw new EnvError(`PW_CORE_DIR does not hold a playwright-core: ${process.env.PW_CORE_DIR}`);
  throw new EnvError(`playwright-core not found: run ${PLAYWRIGHT_RECIPE} once, set PW_CORE_DIR, or install it in the project`);
}

async function launch(core) {
  try {
    return await core.chromium.launch({ headless: true, channel: channel() });
  } catch (e) {
    throw new EnvError(`cannot launch Chrome (channel ${channel()}): ${firstLine(e.message)}`);
  }
}

// ───────────────────────── doctor ─────────────────────────

const hasCommand = (cmd, args) => spawnSync(cmd, args, { stdio: 'ignore' }).status === 0;

async function doctorMain() {
  const lines = [];
  const required = [];
  const add = (ok, label, detail, mustPass = true) => {
    lines.push(`${ok ? 'ok' : mustPass ? 'missing' : 'info'} ${label}${detail ? ` (${detail})` : ''}`);
    if (mustPass) required.push(ok);
  };
  const nodeOk = nodeMajor() >= 20;
  add(nodeOk, 'node>=20', process.version);
  const core = nodeOk ? resolvePlaywright(process.cwd()) : null;
  const coreOk = Boolean(core) && compareVersions(core.version, '1.61.0') >= 0;
  add(coreOk, 'playwright-core>=1.61', core ? `${core.version} at ${core.dir}` : nodeOk ? `not found; run ${PLAYWRIGHT_RECIPE} once or set PW_CORE_DIR` : 'not looked for on this Node');
  let chromeOk = false;
  if (coreOk) {
    try {
      const browser = await core.chromium.launch({ headless: true, channel: channel() });
      await browser.close();
      chromeOk = true;
    } catch {}
  }
  add(chromeOk, `chrome channel ${channel()}`);
  add(hasCommand('git', ['--version']), 'git', 'for the manifest head and branch', false);
  const ready = required.every(Boolean);
  lines.push(`DOCTOR: ${ready ? 'ready' : 'not ready'}`);
  return exitAfterFlush(lines.join('\n'), ready ? 0 : 2);
}

// ───────────────────────── server ─────────────────────────

// Every process group started here is in state.groups and is killed on any way out of the process.
const state = { groups: new Set(), server: null };

function killGroup(pid, signal, alone = false) {
  try {
    process.kill(-pid, signal);
  } catch (e) {
    if (alone && e.code === 'ESRCH') {
      try {
        process.kill(pid, signal);
      } catch {}
    }
  }
}

const probeSignal = (target) => {
  try {
    process.kill(target, 0);
    return true;
  } catch (e) {
    return e.code === 'EPERM';
  }
};
const groupAlive = (pid) => probeSignal(-pid);
const pidAlive = (pid) => probeSignal(pid);

const psField = (field, pid) => {
  const r = spawnSync('ps', ['-o', `${field}=`, '-p', String(pid)], { encoding: 'utf8' });
  return r.status === 0 ? r.stdout.trim() : '';
};

function killAllNow() {
  for (const pid of state.groups) killGroup(pid, 'SIGKILL');
  state.groups.clear();
  if (state.server) {
    try {
      fs.rmSync(state.server.pidfile, { force: true });
    } catch {}
    state.server = null;
  }
}
process.on('exit', killAllNow);
for (const [name, code] of [['SIGINT', 130], ['SIGTERM', 143], ['SIGHUP', 129]]) {
  process.on(name, () => {
    killAllNow();
    process.exit(code);
  });
}

async function waitGone(pid, ms) {
  const until = Date.now() + ms;
  while (Date.now() < until && (groupAlive(pid) || pidAlive(pid))) await sleep(40);
  return !(groupAlive(pid) || pidAlive(pid));
}

async function stopServer() {
  const server = state.server;
  if (!server) return;
  killGroup(server.pid, 'SIGTERM');
  if (!(await waitGone(server.pid, 3000))) {
    killGroup(server.pid, 'SIGKILL');
    await waitGone(server.pid, 2000);
  }
  state.groups.delete(server.pid);
  state.server = null;
  fs.rmSync(server.pidfile, { force: true });
}

// Kills the server group named by a pidfile that an earlier run left behind. The group dies only when the recorded start time
// matches the live process; a pidfile without a start time needs a pid that leads its own group.
async function reapStale(out) {
  const file = path.join(out, PIDFILE);
  let raw;
  try {
    raw = fs.readFileSync(file, 'utf8');
  } catch {
    return null;
  }
  fs.rmSync(file, { force: true });
  const [pidText, started = ''] = raw.split('\n');
  const pid = Number(pidText);
  if (!Number.isInteger(pid) || pid <= 1 || pid === process.pid || !pidAlive(pid)) return null;
  const ours = started.trim() ? psField('lstart', pid) === started.trim() : psField('pgid', pid) === String(pid);
  if (!ours) return null;
  killGroup(pid, 'SIGTERM', true);
  if (!(await waitGone(pid, 2000))) {
    killGroup(pid, 'SIGKILL', true);
    await waitGone(pid, 2000);
  }
  return `reaped the server group ${pid} left by an earlier run`;
}

const probeConnect = (host, port) =>
  new Promise((resolve) => {
    const socket = net.connect({ host, port });
    socket.setTimeout(1000);
    socket.once('connect', () => {
      socket.destroy();
      resolve(true);
    });
    socket.once('timeout', () => {
      socket.destroy();
      resolve(false);
    });
    socket.once('error', () => resolve(false));
  });

async function busyHost(port) {
  for (const host of ['127.0.0.1', '::1']) if (await probeConnect(host, port)) return host;
  return null;
}

function httpStatus(url, timeoutMs) {
  return new Promise((resolve) => {
    const client = url.startsWith('https:') ? https : http;
    const req = client.get(url, { agent: false, timeout: timeoutMs, rejectUnauthorized: false }, (res) => {
      res.resume();
      resolve(res.statusCode);
    });
    req.once('timeout', () => {
      req.destroy();
      resolve(null);
    });
    req.once('error', () => resolve(null));
  });
}

const READY = {
  default: (status) => status !== null && status < 500,
  '2xx': (status) => status !== null && status >= 200 && status < 300,
  any: (status) => status !== null,
};

function logTail(out) {
  try {
    const lines = fs.readFileSync(path.join(out, LOGFILE), 'utf8').split('\n').filter(Boolean).slice(-3);
    return lines.length ? `\n  server log: ${lines.map((l) => l.slice(0, 160)).join(' | ')}` : '';
  } catch {
    return '';
  }
}

async function waitReady(cfg, server) {
  const accepts = READY[cfg.readyStatus];
  const deadline = Date.now() + cfg.readyTimeout * 1000;
  let last = null;
  for (;;) {
    const gone = server.exited;
    if (gone && (gone.code !== 0 || !groupAlive(server.pid))) {
      throw new EnvError(`the server exited (${gone.signal || `code ${gone.code}`}) before it was ready${logTail(cfg.out)}`);
    }
    last = await httpStatus(cfg.ready, 2000);
    if (accepts(last)) return last;
    if (Date.now() >= deadline) break;
    await sleep(250);
  }
  const answer = last === null ? 'no HTTP answer' : `last answer HTTP ${last}`;
  throw new EnvError(`the server was not ready after ${cfg.readyTimeout}s at ${cfg.ready} (${answer})${logTail(cfg.out)}`);
}

function pinBin(version) {
  const root = path.join(process.env.NVM_DIR || path.join(os.homedir(), '.nvm'), 'versions', 'node');
  const want = version.replace(/^v/, '');
  let names = [];
  try {
    names = fs.readdirSync(root);
  } catch {}
  const hits = names.filter((n) => /^v\d+\.\d+\.\d+$/.test(n) && (n.slice(1) === want || n.slice(1).startsWith(`${want}.`)));
  hits.sort((a, b) => compareVersions(a.slice(1), b.slice(1)));
  const bin = hits.length ? path.join(root, hits[hits.length - 1], 'bin') : null;
  if (!bin || !fs.existsSync(path.join(bin, 'node'))) throw new EnvError(`Node ${version} is not installed under ${root}`);
  return bin;
}

async function startServer(cfg) {
  const url = new URL(cfg.ready);
  const port = Number(url.port) || (url.protocol === 'https:' ? 443 : 80);
  const busy = await busyHost(port);
  if (busy) throw new EnvError(`port ${port} is busy on ${busy}: stop the server running there or use another port`);
  const env = { ...process.env };
  if (cfg.nodePin) env.PATH = `${pinBin(cfg.nodePin)}${path.delimiter}${env.PATH || ''}`;
  for (const [key, value] of cfg.env) env[key] = value;
  const log = fs.openSync(path.join(cfg.out, LOGFILE), 'w');
  const child = spawn(cfg.serve, { shell: true, detached: true, cwd: cfg.cwd, env, stdio: ['ignore', log, log] });
  fs.closeSync(log);
  if (!child.pid) throw new EnvError(`cannot start the server: ${cfg.serve}`);
  const server = { pid: child.pid, pidfile: path.join(cfg.out, PIDFILE), exited: null };
  state.server = server;
  state.groups.add(server.pid);
  child.once('exit', (code, signal) => {
    server.exited = { code, signal };
  });
  child.once('error', (e) => {
    server.exited = { code: 1, signal: null, error: e.message };
  });
  fs.writeFileSync(server.pidfile, `${server.pid}\n${psField('lstart', server.pid)}\n`);
  return waitReady(cfg, server);
}

// ───────────────────────── shoot ─────────────────────────

function shootConfig(o) {
  if (o._.length) usageExit(`unexpected argument: ${o._[0]}`);
  if (!o.base) usageExit('--base is required');
  let url;
  try {
    url = new URL(o.base);
  } catch {
    usageExit(`--base is not a URL: ${o.base}`);
  }
  if (!/^https?:$/.test(url.protocol)) usageExit('--base must be an http or https URL');
  if (!o.routes) usageExit('--routes is required, for example --routes /,/about');
  if (!o.out) usageExit('--out is required');
  const routes = o.routes.split(',').map((r) => r.trim()).filter(Boolean);
  if (!routes.length) usageExit('--routes lists no route');
  const slugs = new Map();
  for (const route of routes) {
    if (!route.startsWith('/')) usageExit(`route ${route} must start with /`);
    const slug = slugOf(route);
    if (slugs.has(slug)) usageExit(`routes ${slugs.get(slug)} and ${route} share the file name ${slug}.png`);
    slugs.set(slug, route);
  }

  if (o.serve !== undefined && o.ready === undefined) usageExit('--serve needs --ready URL');
  for (const [flag, given] of [['--ready', o.ready], ['--ready-status', o.readyStatus], ['--ready-timeout', o.readyTimeout], ['--node-pin', o.nodePin], ['--env', o.env.length || undefined]]) {
    if (given !== undefined && o.serve === undefined) usageExit(`${flag} belongs with --serve`);
  }
  if (o.ready !== undefined && !/^https?:\/\//.test(o.ready)) usageExit(`--ready is not an http(s) URL: ${o.ready}`);
  if (o.readyStatus !== undefined && !['2xx', 'any'].includes(o.readyStatus)) usageExit('--ready-status is 2xx or any');
  const readyStatus = o.readyStatus === undefined ? 'default' : o.readyStatus;
  if (o.nodePin !== undefined && !/^v?\d+(\.\d+){0,2}$/.test(o.nodePin)) usageExit(`--node-pin is a version such as 20, 20.11 or 20.11.0: ${o.nodePin}`);
  if (o.cwd !== undefined && !(fs.existsSync(o.cwd) && fs.statSync(o.cwd).isDirectory())) usageExit(`--cwd is not a directory: ${o.cwd}`);

  const pairs = (list, flag, namePattern) =>
    list.map((text) => {
      const at = text.indexOf('=');
      const name = at < 0 ? '' : text.slice(0, at);
      if (!namePattern.test(name)) usageExit(`${flag} expects name=value: ${text}`);
      return [name, text.slice(at + 1)];
    });
  const env = pairs(o.env, '--env', /^[A-Za-z_][A-Za-z0-9_]*$/);
  const cookies = pairs(o.cookie, '--cookie', /^[^\s=;,]+$/);
  const masks = new Map();
  for (const text of o.mask) {
    const at = text.indexOf('=');
    const route = at < 0 ? '' : text.slice(0, at);
    const selectors = text.slice(at + 1).split(',').map((s) => s.trim()).filter(Boolean);
    if (!routes.includes(route) || !selectors.length) usageExit(`--mask expects "/route=selector,selector" for a route of --routes: ${text}`);
    masks.set(route, [...(masks.get(route) || []), ...selectors]);
  }

  const delegated = o.with !== undefined;
  if (delegated && (cookies.length || masks.size)) usageExit('--mask and --cookie belong to the built-in shooter, not to --with');
  if (delegated && !(o.with.includes('{url}') && o.with.includes('{out}'))) usageExit('--with needs both {url} and {out}');
  return {
    base: o.base.replace(/\/+$/, ''),
    routes,
    out: path.resolve(o.out),
    serve: o.serve,
    ready: o.ready,
    readyStatus,
    readyTimeout: o.readyTimeout === undefined ? DEFAULTS.readyTimeout : number(o.readyTimeout, '--ready-timeout', { min: 1, max: 3600 }),
    env,
    cwd: o.cwd === undefined ? undefined : path.resolve(o.cwd),
    nodePin: o.nodePin,
    with: o.with,
    ignored: delegated ? ['--width', '--height', '--full'].filter((f) => o.given.has(f)) : [],
    width: o.width === undefined ? DEFAULTS.width : number(o.width, '--width', { min: 100, max: 10000, int: true }),
    height: o.height === undefined ? DEFAULTS.height : number(o.height, '--height', { min: 100, max: 10000, int: true }),
    full: Boolean(o.full),
    timeout: o.timeout === undefined ? DEFAULTS.timeout : number(o.timeout, '--timeout', { min: 1, max: 3600 }),
    cookies,
    masks,
    json: Boolean(o.json),
  };
}

const urlOf = (cfg, route) => `${cfg.base}${route}`;
const shellQuote = (s) => (/^[A-Za-z0-9_@%+=:,./-]+$/.test(s) ? s : `'${s.replace(/'/g, `'\\''`)}'`);

const errorLabel = (e) => {
  if (e && e.http) return `HTTP ${e.http}`;
  if (e && e.name === 'TimeoutError') return 'timeout';
  return firstLine((e && e.message) || e).replace(/^page\.\w+: /, '');
};

function httpError(status) {
  const err = new Error(`HTTP ${status}`);
  err.http = status;
  return err;
}

async function shootRoute(browser, cfg, route) {
  const file = `${slugOf(route)}.png`;
  const target = path.join(cfg.out, file);
  fs.rmSync(target, { force: true });
  const timeoutMs = cfg.timeout * 1000;
  let context = null;
  try {
    context = await browser.newContext({ viewport: { width: cfg.width, height: cfg.height }, deviceScaleFactor: 1, reducedMotion: 'reduce', ignoreHTTPSErrors: true });
    if (cfg.cookies.length) await context.addCookies(cfg.cookies.map(([name, value]) => ({ name, value, url: cfg.base })));
    const page = await context.newPage();
    const response = await page.goto(urlOf(cfg, route), { waitUntil: 'load', timeout: timeoutMs });
    if (response && response.status() >= 400) throw httpError(response.status());
    await page.waitForLoadState('networkidle', { timeout: Math.min(timeoutMs, 5000) }).catch(() => {});
    await page.evaluate(() => document.fonts.ready.then(() => true));
    const mask = (cfg.masks.get(route) || []).map((selector) => page.locator(selector));
    const png = await page.screenshot({ type: 'png', fullPage: cfg.full, animations: 'disabled', caret: 'hide', scale: 'css', mask, timeout: timeoutMs });
    fs.writeFileSync(`${target}.tmp`, png);
    fs.renameSync(`${target}.tmp`, target);
    return { route, file, ok: true, error: null };
  } catch (e) {
    return { route, file: null, ok: false, error: errorLabel(e) };
  } finally {
    if (context) await context.close().catch(() => {});
  }
}

async function shootBuiltin(core, cfg) {
  const browser = await launch(core);
  const results = [];
  try {
    for (const route of cfg.routes) results.push(await shootRoute(browser, cfg, route));
  } finally {
    await browser.close().catch(() => {});
  }
  return results;
}

// Runs one shell command in its own process group; the group is killed when the command ends or after timeoutMs.
function runCommand(cmd, cwd, timeoutMs) {
  return new Promise((resolve) => {
    const child = spawn(cmd, { shell: true, detached: true, cwd, stdio: ['ignore', 'ignore', 'pipe'] });
    let tail = '';
    let timedOut = false;
    const done = (code) => {
      clearTimeout(timer);
      if (child.pid) {
        killGroup(child.pid, 'SIGKILL');
        state.groups.delete(child.pid);
      }
      resolve({ code, timedOut, tail });
    };
    const timer = setTimeout(() => {
      timedOut = true;
      killGroup(child.pid, 'SIGKILL');
    }, timeoutMs);
    if (child.pid) state.groups.add(child.pid);
    child.stderr.on('data', (chunk) => {
      tail = `${tail}${chunk}`.slice(-400);
    });
    child.once('error', (e) => {
      tail = e.message;
      done(1);
    });
    child.once('exit', (code) => done(code));
  });
}

async function shootWith(cfg) {
  const results = [];
  for (const route of cfg.routes) {
    const file = `${slugOf(route)}.png`;
    const target = path.join(cfg.out, file);
    fs.rmSync(target, { force: true });
    const cmd = cfg.with.replaceAll('{url}', () => shellQuote(urlOf(cfg, route))).replaceAll('{out}', () => shellQuote(target));
    const run = await runCommand(cmd, cfg.cwd, cfg.timeout * 1000);
    let error = null;
    if (run.timedOut) error = 'timeout';
    else if (run.code !== 0) error = `exit ${run.code}${run.tail.trim() ? `: ${firstLine(run.tail.trim().split('\n').pop())}` : ''}`;
    else if (!fs.existsSync(target)) error = 'no PNG written';
    else if (!isPngFile(target)) error = 'not a PNG';
    results.push({ route, file: error ? null : file, ok: !error, error });
  }
  return results;
}

function gitInfo(cwd) {
  const run = (...args) => {
    const r = spawnSync('git', args, { cwd, encoding: 'utf8' });
    return r.status === 0 ? r.stdout.trim() : null;
  };
  const head = run('rev-parse', 'HEAD');
  return head ? { head, branch: run('rev-parse', '--abbrev-ref', 'HEAD') } : null;
}

async function shootMain(o) {
  const cfg = shootConfig(o);
  const warnings = cfg.ignored.length ? [`WARN ${cfg.ignored.join(', ')} ignored: --with does its own capture`] : [];
  let outcome;
  try {
    if (nodeMajor() < 20) throw new EnvError(`Node 20+ required (found ${process.version})`);
    try {
      fs.mkdirSync(cfg.out, { recursive: true });
    } catch (e) {
      throw new EnvError(`cannot create ${cfg.out}: ${firstLine(e.message)}`);
    }
    const reaped = await reapStale(cfg.out);
    if (reaped) warnings.push(`WARN ${reaped}`);
    const core = cfg.with ? null : needCore(cfg.cwd || process.cwd());
    const ready = cfg.serve ? await startServer(cfg) : null;
    const results = cfg.with ? await shootWith(cfg) : await shootBuiltin(core, cfg);
    outcome = { core, ready, results };
  } catch (e) {
    if (!(e instanceof EnvError)) throw e;
    outcome = { env: e.message };
  } finally {
    await stopServer();
  }
  if (outcome.env) {
    console.error(outcome.env);
    return printReport(cfg, { head: [], warnings, detail: [], verdict: `SMOKE: env(${firstLine(outcome.env)})`, exit: 2, json: { error: outcome.env } });
  }

  const { core, ready, results } = outcome;
  const failed = results.filter((r) => !r.ok);
  const manifest = {
    tool: cfg.with ? 'deps-smoke/with' : 'deps-smoke/builtin',
    playwright: core ? core.version : null,
    channel: core ? channel() : null,
    viewport: cfg.with ? null : { width: cfg.width, height: cfg.height },
    full: cfg.with ? null : cfg.full,
    base: cfg.base,
    routes: results,
    git: gitInfo(cfg.cwd),
  };
  fs.writeFileSync(path.join(cfg.out, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
  const how = core ? `builtin · playwright ${core.version} · ${channel()} · ${cfg.width}x${cfg.height}${cfg.full ? ' full' : ''}` : 'with';
  const head = [`shoot ${cfg.base} · ${results.length} routes · ${how}`];
  if (ready !== null) head.push(`server ready (HTTP ${ready})`);
  const detail = [...failed.map((r) => `failed ${r.route} ${r.error}`), ...results.filter((r) => r.ok).map((r) => `shot ${r.route} -> ${r.file}`)];
  const verdict = `SMOKE: shot(${results.length - failed.length})${failed.length ? ` failed(${names(failed.map((r) => r.route))})` : ''}`;
  return printReport(cfg, { head, warnings, detail, verdict, exit: failed.length ? 1 : 0, json: { base: cfg.base, routes: results } });
}

// ───────────────────────── main ─────────────────────────

async function main() {
  const [sub, ...rest] = process.argv.slice(2);
  if (!sub) usageExit('missing subcommand');
  if (sub === '--help' || sub === '-h' || sub === 'help') helpExit();
  if (!Object.hasOwn(FLAGS, sub)) usageExit(`unknown subcommand: ${sub}`);
  const o = parseFlags(sub, rest);
  if (sub === 'doctor') {
    if (o._.length) usageExit(`doctor takes no argument: ${o._[0]}`);
    return doctorMain();
  }
  return sub === 'diff' ? diffMain(o) : shootMain(o);
}

main().catch((e) => {
  console.error(`internal error: ${(e && e.stack) || e}`);
  process.exit(2);
});
