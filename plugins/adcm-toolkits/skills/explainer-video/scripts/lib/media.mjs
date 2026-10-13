// Media for the recorder: voice (edge-tts, piper or say), ffprobe/ffmpeg, subtitles and mp4 verification.
// Everything runs through execFile (no shell): guion text never reaches an interpreter.
import { execFile } from 'node:child_process';
import { promisify, stripVTControlCharacters } from 'node:util';
import { lookup } from 'node:dns/promises';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const run = promisify(execFile);
const MAX_BUFFER = 64 * 1024 * 1024;
const LINE_CHARS = 42;
const TTS_TIMEOUT = 120000;
const PROBE_TIMEOUT = 20000;
const EDGE_HOST = 'speech.platform.bing.com';

// Without a shell nobody expands a leading "~": it is resolved here, and path.resolve keeps messages absolute.
export const expand = (p) => path.resolve(p === '~' || p.startsWith('~/') ? path.join(os.homedir(), p.slice(1)) : p);
export const ttsHome = () => expand(process.env.REC_TTS_HOME || '~/.local/share/adcm-voz');

// msPerChar is each engine's pace at its default rate and only feeds the duration estimate (and --mute).
// fix is what the doctor suggests when the engine is installed but cannot synthesize.
export const ENGINES = {
  edge: { bin: 'edge-tts', ext: 'mp3', msPerChar: 70, voice: () => 'es-MX-DaliaNeural', fix: 'pip install -U edge-tts in the voice venv' },
  piper: { bin: 'piper', ext: 'wav', msPerChar: 74, voice: () => path.join(ttsHome(), 'voces', 'es_MX-claude-high.onnx'), fix: 'pip install -U piper-tts in the voice venv' },
  say: { bin: 'say', ext: 'aiff', msPerChar: 68, voice: () => 'Paulina', fix: 'download the voice in System Settings > Accessibility > Spoken Content' },
};

export const VOICE_RECIPE =
  'python3 -m venv ~/.local/share/adcm-voz/venv && ~/.local/share/adcm-voz/venv/bin/pip install -U edge-tts piper-tts==1.8.0 (or point REC_TTS_HOME at an existing voice home)';

const isExecutable = (file) => {
  try {
    fs.accessSync(file, fs.constants.X_OK);
    return fs.statSync(file).isFile();
  } catch {
    return false;
  }
};

export const which = (name) =>
  (process.env.PATH || '').split(path.delimiter).filter(Boolean).map((d) => path.join(d, name)).find(isExecutable) || null;

// Engines live in the voice home first ($REC_TTS_HOME/venv/bin, then $REC_TTS_HOME/bin), then on PATH.
export function findBin(name) {
  const home = ttsHome();
  const local = [path.join(home, 'venv', 'bin', name), path.join(home, 'bin', name)].find(isExecutable);
  return local || which(name);
}

// The engine to use: REC_TTS / REC_VOICE / REC_RATE override the config; a config voice id or rate only applies to
// the engine it was written for.
export function resolveVoice(voiceCfg) {
  const name = process.env.REC_TTS || voiceCfg.engine;
  const spec = Object.hasOwn(ENGINES, name) ? ENGINES[name] : null;
  const own = name === voiceCfg.engine;
  const rawVoice = process.env.REC_VOICE || (own && voiceCfg.id) || spec?.voice() || '';
  const voice = name === 'piper' && rawVoice ? expand(rawVoice) : rawVoice;
  const rate = process.env.REC_RATE || (own && voiceCfg.rate != null ? String(voiceCfg.rate) : '');
  const label = `${name}:${name === 'piper' ? path.basename(voice, '.onnx') : voice}`;
  return { name, spec, voice, rate, label, msPerChar: spec ? spec.msPerChar : ENGINES.edge.msPerChar };
}

const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

// What the voice reads: sayAs over say, plus the pronunciation map. It only changes what is HEARD, never the subtitle.
export function voiceText(step, pronunciation = {}) {
  let text = String(step.sayAs ?? step.say).replace(/\s+/g, ' ').trim();
  for (const [from, to] of Object.entries(pronunciation)) {
    text = text.replace(new RegExp(`(?<![\\p{L}\\p{N}])${escapeRe(from)}(?![\\p{L}\\p{N}])`, 'giu'), to);
  }
  return text;
}

const SAY_VOICE = /^(.+?)\s+[a-z]{2,3}_[A-Za-z0-9]{2,4}\s+#/;
const EDGE_VOICE = /^[a-z]{2,3}-[A-Z]{2}-\w+Neural$/;

// null when the engine and its voice are installed; otherwise the reason. Does not touch the network.
async function voiceProblem(v) {
  if (!v.spec) return `unsupported engine "${v.name}": REC_TTS must be ${Object.keys(ENGINES).join(' | ')}`;
  const bin = findBin(v.spec.bin);
  if (!bin) return `${v.spec.bin} not found in ${ttsHome()}/venv/bin, ${ttsHome()}/bin or PATH`;
  try {
    if (v.name === 'say') {
      // say -v with a missing voice exits 0: only the voice list tells.
      const { stdout } = await run(bin, ['-v', '?'], { timeout: 15000 });
      if (!stdout.split('\n').some((l) => l.match(SAY_VOICE)?.[1] === v.voice)) return `say voice "${v.voice}" is not installed (say -v '?' lists them)`;
    } else if (v.name === 'piper') {
      const missing = [v.voice, `${v.voice}.json`].filter((f) => !fs.existsSync(f));
      if (missing.length) return `piper model missing: ${missing.join(' and ')}`;
    } else {
      await run(bin, ['--version'], { timeout: 15000 });
      if (!EDGE_VOICE.test(v.voice)) return `edge voice "${v.voice}" does not look like es-MX-DaliaNeural (edge-tts -l lists them)`;
    }
  } catch (e) {
    return `${v.name} does not respond (${e.code || String(e.message).split('\n')[0]})`;
  }
  return null;
}

// edge needs the network; a DNS answer is the cheapest honest signal before synthesizing.
async function edgeReachable() {
  try {
    await Promise.race([lookup(EDGE_HOST), new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 4000))]);
    return true;
  } catch {
    return false;
  }
}

// An engine error is shown to the operator and may end up in a pasted log: no URLs (edge's carry a client token),
// no long ids and no local paths. Known secrets and token= values are already masked where the recorder prints.
function scrub(text) {
  const home = os.homedir();
  const noHome = home.length > 1 ? text.replaceAll(home, '~') : text;
  return noHome
    .replaceAll(os.tmpdir(), '<tmp>')
    .replace(/\b[a-z][a-z0-9+.-]*:\/\/[^\s'"<>)]+/gi, '<url>')
    .replace(/\b[A-Fa-f0-9]{16,}\b/g, '<id>')
    .slice(0, 200);
}

// An engine can be installed and still unable to synthesize (edge answers 403 to an outdated client): a real
// one-word take is the only honest check. The scratch dir is removed whatever happens.
async function synthesisProblem(v) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rec-voice-probe-'));
  const txt = path.join(dir, 'probe.txt');
  const raw = path.join(dir, `probe.${v.spec.ext}`);
  try {
    fs.writeFileSync(txt, 'Hola\n');
    await run(findBin(v.spec.bin), engineArgs(v, txt, raw), { timeout: PROBE_TIMEOUT, maxBuffer: MAX_BUFFER });
    return nonEmpty(raw) ? null : 'the take came out empty';
  } catch (e) {
    return scrub(failure(e, PROBE_TIMEOUT));
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

// What --doctor and the recording path both ask before spending a take: null when the voice is ready, otherwise
// { problem } (engine or voice absent) or { problem, fix } (installed but it cannot synthesize).
export async function voiceCheck(v) {
  const problem = await voiceProblem(v);
  if (problem) return { problem };
  if (v.name === 'edge' && !(await edgeReachable())) return { problem: 'no network to the edge endpoint' };
  const failed = await synthesisProblem(v);
  if (!failed) return null;
  const others = Object.keys(ENGINES).filter((n) => n !== v.name).join('|');
  return { problem: `${v.name} is installed but synthesis failed (${failed})`, fix: `${v.spec.fix}, or set REC_TTS=${others}` };
}

// edge leaves ~0.2 s of silence at the start and ~0.9 s at the end: both ends are trimmed down to 0.1 s
// (areverse lets the tail be cleaned with the start parameters).
const EDGE_TRIM = 'silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.1';
const EDGE_CLEAN = [EDGE_TRIM, 'areverse', EDGE_TRIM, 'areverse'];

const LOUDNESS = -17;
const MAX_GAIN = 6;
const ABS_GATE = -70;
// Short phrases come out 4-5 dB low: without a limiter the peak would win over the level (ceiling -1.5 dBFS).
const LIMITER = 'alimiter=limit=0.841:attack=5:release=50:level=0:latency=1';

// Every clip ends as a 48 kHz mono wav at -17 LUFS: one ebur128 pass measures it and the final pass applies the gain
// (max ±6 dB). With no measurable block (silence or under 0.4 s) ebur128 reports its -70 LUFS floor: no gain.
async function normalize(raw, wav, clean = []) {
  const chain = [...clean, 'aresample=48000'];
  const { stderr } = await run('ffmpeg', ['-hide_banner', '-nostats', '-i', raw, '-af', [...chain, 'ebur128=framelog=quiet'].join(','), '-f', 'null', '-'], { maxBuffer: MAX_BUFFER });
  const loudness = Number(stderr.slice(stderr.lastIndexOf('Summary:')).match(/\bI:\s+(-?[\d.]+) LUFS/)?.[1]);
  const audible = loudness > ABS_GATE;
  const gain = audible ? Math.min(Math.max(LOUDNESS - loudness, -MAX_GAIN), MAX_GAIN) : 0;
  await run('ffmpeg', ['-y', '-v', 'error', '-i', raw, '-af', [...chain, `volume=${gain.toFixed(2)}dB`, LIMITER].join(','), '-ac', '1', '-ar', '48000', '-c:a', 'pcm_s16le', wav], { maxBuffer: MAX_BUFFER });
  if (!audible && (await duration(wav)) > 0.4) throw new Error('clip has no audible voice');
  return wav;
}

const failure = (e, timeout = TTS_TIMEOUT) =>
  e.killed ? `exceeded ${timeout / 1000} s` : stripVTControlCharacters(String(e.stderr || e.message)).trim().split('\n').pop().trim();

function engineArgs(v, txt, raw) {
  if (v.name === 'say') return ['-v', v.voice, ...(v.rate ? ['-r', v.rate] : []), '-o', raw, '-f', txt];
  if (v.name === 'piper') return ['-m', v.voice, '-i', txt, '-f', raw, '--sentence_silence', '0.3', '--volume', '0.8', ...(v.rate ? ['--length_scale', v.rate] : [])];
  // --rate=-10% with "=": otherwise a negative value would be read as another option.
  return ['-v', v.voice, '-f', txt, ...(v.rate ? [`--rate=${v.rate}`] : []), '--write-media', raw];
}

// Text goes through a file (-f / -i): one starting with "-" would be read as an engine option. Returns the
// normalized wav that mux consumes; the engine's raw audio stays next to it as <base>.raw.<ext>.
export async function tts(text, outBase, v) {
  const txt = `${outBase}.txt`;
  const raw = `${outBase}.raw.${v.spec.ext}`;
  fs.writeFileSync(txt, text + '\n');
  try {
    await run(findBin(v.spec.bin), engineArgs(v, txt, raw), { timeout: TTS_TIMEOUT, maxBuffer: MAX_BUFFER });
    if (!nonEmpty(raw)) throw new Error(`${path.basename(raw)} is empty`);
    const out = await normalize(raw, `${outBase}.wav`, v.name === 'edge' ? EDGE_CLEAN : []);
    if (!nonEmpty(out)) throw new Error(`${path.basename(out)} is empty`);
    return out;
  } catch (e) {
    throw new Error(`${v.label} could not synthesize: ${failure(e)}${v.name === 'edge' ? ' (edge needs the network and an existing voice)' : ''}`);
  }
}

export async function silence(seconds, wav) {
  await run('ffmpeg', ['-y', '-v', 'error', '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=mono', '-t', seconds.toFixed(3), '-c:a', 'pcm_s16le', wav], { maxBuffer: MAX_BUFFER });
  return wav;
}

// First line of `<bin> -version`, or null when the tool is missing.
export const toolVersion = (bin) =>
  run(bin, ['-version'], { timeout: 15000 }).then(({ stdout }) => stdout.split('\n')[0].trim(), () => null);

export async function probe(file) {
  const { stdout } = await run('ffprobe', ['-v', 'error', '-print_format', 'json', '-show_format', '-show_streams', file], { maxBuffer: MAX_BUFFER });
  return JSON.parse(stdout);
}

export const duration = async (file) => Number((await probe(file)).format.duration);

const lineLen = (words) => words.join(' ').length;
const SENTENCE_END = /[.?!]["»”')\]]*$/;
const PAUSE = /[,;:…]["»”')\]]*$/;
const SHORT_SENTENCE = 14;

function breakBonus(word) {
  if (SENTENCE_END.test(word)) return 15;
  if (PAUSE.test(word)) return 5;
  return 0;
}

// 1 or 2 lines of <=42 characters, as even as possible (a break after punctuation wins ties); null if it does not fit.
function wrapTwo(words) {
  if (lineLen(words) <= LINE_CHARS) return [words.join(' ')];
  let best = null;
  for (let j = 1; j < words.length; j++) {
    const a = lineLen(words.slice(0, j));
    const b = lineLen(words.slice(j));
    if (a > LINE_CHARS || b > LINE_CHARS) continue;
    const score = Math.abs(a - b) - breakBonus(words[j - 1]);
    if (!best || score < best.score) best = { j, score };
  }
  return best && [words.slice(0, best.j).join(' '), words.slice(best.j).join(' ')];
}

// A sentence that does not fit one cue is split as close to its middle as possible, preferring a pause.
function chunk(words) {
  if (words.length < 2 || wrapTwo(words)) return [words];
  let best = { j: 1, score: Infinity };
  for (let j = 1; j < words.length; j++) {
    const score = Math.abs(lineLen(words.slice(0, j)) - lineLen(words.slice(j))) - (PAUSE.test(words[j - 1]) ? 8 : 0);
    if (score < best.score) best = { j, score };
  }
  return [...chunk(words.slice(0, best.j)), ...chunk(words.slice(best.j))];
}

function sentencesOf(words) {
  const sentences = [];
  let sentence = [];
  for (const w of words) {
    sentence.push(w);
    if (SENTENCE_END.test(w)) {
      sentences.push(sentence);
      sentence = [];
    }
  }
  if (sentence.length) sentences.push(sentence);
  return sentences;
}

// A one- or two-word sentence lasts under half a second: it joins the next one, or the previous one if last.
function mergeShort(sentences) {
  const merged = [];
  for (let i = 0; i < sentences.length; i++) {
    let s = sentences[i];
    while (lineLen(s) < SHORT_SENTENCE && i + 1 < sentences.length) s = [...s, ...sentences[++i]];
    merged.push(s);
  }
  if (merged.length > 1 && lineLen(merged.at(-1)) < SHORT_SENTENCE) {
    const last = merged.pop();
    merged.at(-1).push(...last);
  }
  return merged;
}

// Breaks fall at sentence ends: each sentence that fits a cue goes whole, short ones share a cue while they fit,
// and only a sentence too long for one cue is split inside.
function segment(words) {
  if (wrapTwo(words)) return [words];
  const cues = [];
  let open = [];
  for (const s of mergeShort(sentencesOf(words))) {
    if (open.length && wrapTwo([...open, ...s])) {
      open = [...open, ...s];
      continue;
    }
    if (open.length) cues.push(open);
    open = [];
    if (wrapTwo(s)) open = s;
    else cues.push(...chunk(s));
  }
  if (open.length) cues.push(open);
  return cues;
}

// Each cue fits <=2 lines x 42 characters, broken by word, and lasts what its characters weigh inside `dur`
// (the step's voice): the page subtitle and the .srt share times and text.
export function splitCues(text, dur) {
  const chunks = segment(text.replace(/\s+/g, ' ').trim().split(' '));
  const total = chunks.reduce((n, c) => n + lineLen(c), 0);
  let seen = 0;
  return chunks.map((c) => {
    const start = (dur * seen) / total;
    seen += lineLen(c);
    return { text: (wrapTwo(c) || [c.join(' ')]).join('\n'), start, end: (dur * seen) / total };
  });
}

function srtTime(seconds) {
  const ms = Math.round(seconds * 1000);
  const pad = (n, w = 2) => String(n).padStart(w, '0');
  return `${pad(Math.floor(ms / 3600000))}:${pad(Math.floor(ms / 60000) % 60)}:${pad(Math.floor(ms / 1000) % 60)},${pad(ms % 1000, 3)}`;
}

export const toSrt = (cues) => cues.map((c, i) => `${i + 1}\n${srtTime(c.start)} --> ${srtTime(c.end)}\n${c.text}\n`).join('\n');

const ISO639_2 = { es: 'spa', en: 'eng', pt: 'por', fr: 'fra', de: 'deu', it: 'ita' };
export const subtitleLanguage = (locale) => ISO639_2[String(locale).slice(0, 2).toLowerCase()] || 'und';

// clips: [{ file, at }] with `at` in seconds since the first frame. The container lasts as long as its longest
// track: the video, which always outlasts the last clip.
export async function mux({ video, clips, srt, out, language }) {
  const args = ['-y', '-v', 'error', '-i', video];
  for (const c of clips) args.push('-i', c.file);
  args.push('-i', srt);
  const delayed = clips.map((c, k) => `[${k + 1}:a]aresample=48000,adelay=${Math.round(c.at * 1000)}:all=1[a${k}]`);
  const mix = `${clips.map((_, k) => `[a${k}]`).join('')}amix=inputs=${clips.length}:duration=longest:dropout_transition=0:normalize=0[aout]`;
  args.push(
    '-filter_complex', [...delayed, mix].join(';'),
    '-map', '0:v:0', '-map', '[aout]', '-map', `${clips.length + 1}:0`,
    '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p', '-fps_mode', 'cfr', '-r', '25',
    '-c:a', 'aac', '-b:a', '96k',
    '-c:s', 'mov_text', '-metadata:s:s:0', `language=${language}`,
    '-movflags', '+faststart',
    out,
  );
  await run('ffmpeg', args, { maxBuffer: MAX_BUFFER });
}

export const poster = (mp4, png) => run('ffmpeg', ['-y', '-v', 'error', '-ss', '2', '-i', mp4, '-frames:v', '1', png], { maxBuffer: MAX_BUFFER });

export async function contactSheet(mp4, png, bg) {
  const dur = await duration(mp4);
  const color = `0x${String(bg).replace(/^#/, '')}`;
  await run('ffmpeg', ['-y', '-v', 'error', '-i', mp4, '-vf', `fps=12/${dur},scale=320:-1,tile=4x3:padding=4:margin=4:color=${color}`, '-frames:v', '1', png], { maxBuffer: MAX_BUFFER });
}

export const sha256 = (file) => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');

export const nonEmpty = (file) => fs.existsSync(file) && fs.statSync(file).size > 0;

// Container and tracks against the video contract: h264 + aac + mov_text at the viewport size and 25 fps, audio no
// longer than the video and duration inside the window.
export async function verifyMp4(mp4, { viewport, window: [min, max] }) {
  const info = await probe(mp4);
  const pick = (type) => info.streams.find((s) => s.codec_type === type);
  const v = pick('video');
  const a = pick('audio');
  const s = pick('subtitle');
  const dur = Number(info.format.duration);
  const problems = [];
  if (!v || v.codec_name !== 'h264') problems.push('video is not h264');
  if (!a || a.codec_name !== 'aac') problems.push('audio is not aac');
  if (!s || s.codec_name !== 'mov_text') problems.push('mov_text track missing');
  if (v && (v.width !== viewport.width || v.height !== viewport.height)) problems.push(`size ${v.width}x${v.height}`);
  if (v && v.r_frame_rate !== '25/1') problems.push(`fps ${v.r_frame_rate}`);
  if (dur < min || dur > max) problems.push(`duration ${dur.toFixed(1)}s outside ${min}-${max}s`);
  if (v && a && Number(a.duration) > Number(v.duration) + 0.05) problems.push('audio is longer than video');
  return { problems, duration: dur, codecs: [v?.codec_name, a?.codec_name, s?.codec_name].filter(Boolean).join('+') };
}

// Valid deny-list shape: no comments or blank lines, and `grep -r -i -f` (the one-liner `grep -rfi` parses as
// `-f i` and gives a false green). Returns "file:line" for each hit, never the matched text.
export async function denyHits(listFile, files, scratchDir) {
  const patterns = fs.readFileSync(listFile, 'utf8').split('\n').filter((l) => !/^\s*(#|$)/.test(l));
  if (!patterns.length) throw new Error('the filtered deny-list is empty');
  const filtered = path.join(scratchDir, 'deny-list.filtered.txt');
  fs.writeFileSync(filtered, patterns.join('\n') + '\n');
  try {
    const { stdout } = await run('grep', ['-r', '-i', '-n', '-f', filtered, ...files], { maxBuffer: MAX_BUFFER });
    return stdout.split('\n').filter(Boolean).map((l) => l.split(':').slice(0, 2).join(':'));
  } catch (e) {
    if (e.code === 1) return [];
    throw new Error(`deny-list grep failed (${e.code})`);
  } finally {
    fs.rmSync(filtered, { force: true });
  }
}
