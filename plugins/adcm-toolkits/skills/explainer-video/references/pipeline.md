# Pipeline reference

What `explainer-record` does, every flag and exit code, the config keys, the outputs and what
to do when it fails. Written from the recorder's behavior; `--doctor` and `--check` are the
quickest way to confirm any line of it.

## The chain

```
guion → TTS per step → normalize (-17 LUFS) → screencast → mux → poster + sheet → verify
```

1. **Validate.** The guion is checked against the strict schema; any error stops before a
   browser opens (exit 1).
2. **Guards, before the browser.** `baseUrl`, `mail.url` and every `goto` must be hosts in
   `allowHosts`; every `{{env:VAR}}` must be set; the voice engine must be ready, which
   means one word is synthesized with it (not for `--dry` or `--mute`); `playwright-core >= 1.61`
   (not for `--dry`); the app must answer at `baseUrl` within 10 s, a redirect not followed;
   the `.lock` is taken.
3. **TTS, every step first.** The voice reads `sayAs`, else `say`, after the
   `pronunciation` map. Each clip is written through a text file to the engine (edge-tts,
   piper or say, 120 s timeout), so nothing in the narration reaches a shell. The
   engine's raw audio stays beside the clip as `step-NN.raw.<ext>`.
4. **Normalize.** edge clips lose their lead and tail silence (down to 0.1 s). Every clip is
   resampled to 48 kHz mono and one `ebur128` pass sets its gain to -17 LUFS (at most
   6 dB either way), with a limiter at about -1.5 dBFS so short phrases do not clip. A
   clip with no audible voice fails the take.
5. **Screencast.** Headless Chrome (`REC_CHANNEL`), context with the config's viewport, locale
   and timezone, device scale 1, clipboard write allowed. Every HTTP and WebSocket request
   passes the host guard, and a redirect is checked hop by hop: a 3xx that points outside
   `allowHosts` stops the run before that host is contacted. Setup runs off camera, then the route opens, then the overlay
   (title card, caption bar, subtitle, synthetic cursor, highlight ring, `blur`). The camera
   is `page.screencast`; `t0` is the timestamp of its first frame, which puts voice and
   video on one clock (`recordVideo` drifts by hundreds of milliseconds).
6. **Steps on the voice's clock.** See "The voice leads" in `storyboard-guide.md`. After each
   step the page text is appended to the dom dump.
7. **Mux.** One ffmpeg pass: the webm, every clip delayed to its step's start, and the srt.
   Video `libx264` crf 20, preset medium, yuv420p, constant 25 fps. Audio AAC 96k. Subtitles
   `mov_text` tagged with the language of `locale`, plus a separate `.srt` (some drives
   ignore the embedded track). `+faststart`.
8. **Poster and sheet.** The poster is the frame at 2 s. The contact sheet is 12 frames in a
   4x3 grid at 320 px, padded with `brand.bg`.
9. **Move into place.** Everything a take writes is staged under `work/<id>/out` and moved
   into `outDir` only when the whole take succeeded, so a failed take never leaves half
   a result next to the previous mp4.
10. **Verify** (`--verify`, a separate command). See below.

## CLI

```
explainer-record <ids…>|--all [--check|--dry|--verify|--doctor] [--mute] [--config videos/config.json]
```

`explainer-record` is the plugin launcher; it runs `scripts/record.mjs` with Node >= 20.
Ids are two digits (`1` is read as `01`).

| Flag | Meaning |
|---|---|
| `<ids…>` or `--all` | the guiones to act on; `--all` is every `.json` in `guionesDir`. Required, except for `--check` (no ids means all) and `--doctor` (takes none) |
| *(no mode flag)* | record: voice, screencast, mux, poster, sheet, dom dump |
| `--check` | validate against the strict schema and print the estimated duration; no browser, no app, no voice |
| `--dry` | run the real actions with no camera and no voice, to validate selectors and `waitFor`; it DOES change the local app's data |
| `--verify` | check every mp4 and write `<outDir>/manifest.json` (plus a scratch file under `work/` while the deny-list runs); takes no lock, but refuses to run while a recorder is writing |
| `--doctor` | check the environment and print the recipe for what is missing; takes no ids; the config is optional |
| `--mute` | record with silence of the estimated durations instead of a voice: offline and deterministic; only for recording |
| `--config <path>` | the config file, relative to the cwd (default `videos/config.json`); every path inside it is relative to the config file's directory, never to the cwd |

`--check`, `--dry`, `--verify` and `--doctor` are mutually exclusive.

### What the output looks like

```
$ explainer-record --check
voice: edge:es-MX-DaliaNeural (70 ms/char)
OK 01 crear-factura 5 steps ~25s
1 OK
```

A failing guion prints `FAIL <file>` and one `  - <problem>` line each on stderr, then
`N OK, M FAIL`, exit 1. A recording prints `rec <id>-<slug>: step i/n (<action> <selector>)`
per step and ends with `OK rec <id> <slug> <seconds>s <MB>MB <path>`.

`--doctor` prints seven lines and a verdict:

```
ok node>=20 (<version>)
ok playwright-core>=1.61 (<version>, screencast)
ok browser channel (chrome)
ok ffmpeg (<version>)
ok ffprobe (<version>)
ok voice engine (edge:es-MX-DaliaNeural)
ok voice home (<absolute path of the voice home>)
DOCTOR: ready
```

A failing line reads `missing <item> — <recipe>`; the verdict is `DOCTOR: not ready` and the exit
is 2. The `voice engine` line is a real test: the doctor checks that the engine and its
voice exist (for edge, that `edge-tts` runs, the voice id looks valid and the Microsoft endpoint
resolves in DNS) and then synthesizes one word with the selected engine, 20 s at most. An engine
that is installed but cannot synthesize (edge answering HTTP 403 to an outdated client) reads
`missing voice engine — <engine> is installed but synthesis failed (<reason>): pip install -U edge-tts
in the voice venv, or set REC_TTS=piper|say`. Every voiced run asks the same question before the
browser opens and stops with exit 2, `voice not ready`.
Under Node < 20 the doctor still prints its seven lines: `playwright-core` and the browser read
`not checked: needs node>=20`.

## Exit codes

| Code | Meaning | Typical causes |
|---|---|---|
| `0` | ok | |
| `1` | failure | a guion fails the schema; a step fails (selector timeout, `waitFor`); a take exceeds `maxSeconds`; the TTS engine fails; `--verify` finds a problem; no guiones in `guionesDir` |
| `2` | config, guard, voice not ready or Node < 20 | config missing, invalid JSON or unknown key; `baseUrl`, `mail.url`, a `goto` or a page request outside `allowHosts`; an `{{env:VAR}}` not set; voice engine or model missing; `playwright-core` not found; the app does not answer; another recorder holds the lock; `guionesDir` or `denyList` missing |
| `3` | configured fonts not loaded | a family in `fonts` did not load on the first page |
| `4` | no `page.screencast` | `playwright-core` older than 1.61 |
| `64` | argument errors | unknown flag, two modes at once, `--doctor` with ids, ids with `--all`, `--mute` outside recording, no ids, an id with no guion |
| `130` | interrupted (Ctrl-C) | the operator stopped the run; the lock is released and the browser closed |

## Config keys

All optional except `baseUrl`. Unknown keys are an error. Defaults:

| Key | Default | Meaning |
|---|---|---|
| `baseUrl` | none, required | http(s) URL of the local app; `route` and `goto /path` are joined to it |
| `allowHosts` | `["localhost", "127.0.0.1"]` | the only hostnames the page may reach (HTTP and WebSocket; ports are not compared). The first request outside, a redirect hop included, aborts the run with exit 2 |
| `guionesDir` | `guiones` | folder of the guiones, relative to the config file |
| `outDir` | `out` | output folder, relative to the config file |
| `viewport` | `{"width": 1280, "height": 800}` | video size |
| `locale` | `es-MX` | browser locale, subtitle language tag, "Siguiente" or "Next" on the closing card |
| `timezone` | `America/Mexico_City` | IANA zone of the browser and of `{{today}}` |
| `voice` | `{"engine": "edge", "id": "es-MX-DaliaNeural", "rate": null}` | engine `edge`, `piper` or `say`. `rate`: edge a percent string such as `"-10%"`, say words per minute, piper a length scale (above 1 is slower). An `id` applies only to the engine it was written for |
| `fallbacks` | `["piper", "say"]` | engines named in the "voice not ready" hint; never applied by the recorder itself |
| `brand` | `{"accent": "#3B82F6", "bg": "#111318"}` | `#rrggbb` colors: `accent` for the caption bar edge, cursor ring, highlight and title card, `bg` for the title card background and the sheet padding |
| `fonts` | `[]` | families that must load; the first one is used by the overlay; exit 3 if any does not. A name cannot contain quotes, backslashes, braces, semicolons or `<` |
| `durationWindow` | `[55, 125]` | seconds; `--check` warns outside it, `--verify` fails outside it, and its upper end is the default `maxSeconds` |
| `denyList` | none | file of patterns (grep syntax, one per line, `#` comments and blank lines skipped) searched in each guion, srt and dom dump by `--verify` |
| `pronunciation` | `{}` | word to spoken form, whole word, case-insensitive; voice only |
| `mail` | none | `{"url": "http://localhost:<port>"}` of a local mail catcher with `GET /api/v1/messages` and `GET /api/v1/message/<id>`; without it the `mail` action does not exist |
| `setup` | `[]` | off-camera steps run before every take (sign-in, seed screens) |
| `profiles` | `{}` | `{"<name>": {"setup": [...]}}`; a guion with `profile` runs that setup instead of the default; a profile without `setup` runs none |

## Environment variables

| Variable | Effect |
|---|---|
| `REC_TTS` | `edge`, `piper` or `say`; overrides `voice.engine` for this run |
| `REC_VOICE` | voice id (edge), model path (piper) or voice name (say) |
| `REC_RATE` | overrides `voice.rate` |
| `REC_TTS_HOME` | the voice home (default `~/.local/share/adcm-voz`); engines are looked up in `venv/bin`, then `bin`, then on `PATH`; the piper model is `voces/es_MX-claude-high.onnx` (+ `.onnx.json`) |
| `REC_CHANNEL` | browser channel, default `chrome`; `chromium` after `npx playwright-core install chromium` |
| `PW_CORE_DIR` | a `playwright-core` directory to use when the project has none |
| any `VAR` named by `{{env:VAR}}` | secrets of the guiones and the setup; never printed |

Playwright is resolved in this order: the project's `node_modules` (`playwright-core`,
then `playwright`), then `PW_CORE_DIR`, then the newest stable `playwright-core` in the npx
cache (`~/.npm/_npx`). Version 1.61 is the minimum because `page.screencast` starts there.

## Outputs

With the config at `videos/config.json` and the defaults:

```
videos/
  config.json                 versioned
  guiones/NN-slug.json        versioned
  out/                        gitignored, never committed
    mp4/NN-slug.mp4           h264 + aac + mov_text, 25 fps, viewport size
    srt/NN-slug.srt           the same cues as the embedded track
    posters/NN-slug.png       frame at 2 s
    sheets/NN-slug.png        12 frames, 4x3
    dom/NN-slug.txt           page text after each step (what the auditor reads)
    manifest.json             written by --verify
    work/<id>/                clips, video.webm, timeline.json; rebuilt on each take
    .lock                     the recorder's pid while it runs
```

`manifest.json` is an array ordered by id of `{id, slug, title, duration, sha256, bytes}`.
It accumulates: verifying one id keeps the entries of the others as long as their guion
still exists.

`--verify` checks, per id, that the guion, mp4, srt, poster, sheet and dom files exist and are
not empty; that the mp4 has h264 video, AAC audio and a `mov_text` track at the viewport size
and 25 fps; that the duration is inside `durationWindow`; that the audio is not longer than
the video; and the deny-list hits (`file:line`, never the matched text). Exit 1 if any id fails.

## Re-takes and locks

A re-take of an id replaces only that id's files. With the same narration and timings the
srt is byte-identical (steps start on a tenth of a second). A second recorder on the same
`outDir` stops with exit 2 and the pid of the first; a lock left by a dead process is
removed automatically. Recording stops on Ctrl-C (exit 130) and cleans the browser up.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `missing node>=20` or `the recorder needs Node 20 or newer` | default Node is older | `nvm install 22`; the launcher picks the newest `~/.nvm/versions/node/v2*` by itself; without the launcher put Node >= 20 first on `PATH` |
| `missing playwright-core>=1.61` or `playwright-core not found` | not in the project, `PW_CORE_DIR` or the npx cache | `npx -y -p playwright-core@1.63 node -e 0` fills the cache; or `npm i -D playwright-core`; or set `PW_CORE_DIR` |
| exit 4, `has no page.screencast` | `playwright-core` older than 1.61 | same as above, a newer version |
| `missing browser channel` | no Google Chrome, or an installed build this `playwright-core` cannot drive (the line carries the launch error) | install or update Chrome, update `playwright-core`, or `npx playwright-core install chromium` and `REC_CHANNEL=chromium` |
| `missing ffmpeg` or `ffprobe` | not installed | `brew install ffmpeg`, or the system package |
| exit 2, `voice not ready` or `missing voice engine` | engine or model absent, or installed but one-word synthesis failed | `templates/voice-install.md`; the owner picks a fallback with `REC_TTS=piper` or `say` |
| exit 2, `voice not ready` or `missing voice engine` with `synthesis failed (... 403 ...)` | Microsoft changed the read-aloud handshake and the installed edge-tts is older | upgrade it in the voice venv: `~/.local/share/adcm-voz/venv/bin/pip install -U edge-tts`; if it still fails, the owner chooses `REC_TTS=piper` |
| a take fails with `could not synthesize` | the engine worked at the check and failed on a step (a long text, a dropped connection) | re-run the id; if it repeats, read the reason in the message and apply the row above |
| `no network to the edge endpoint` | offline | connect, or the owner chooses `REC_TTS=piper` or `say` |
| exit 2, `is outside allowHosts` | `baseUrl`, a `goto` or a page request points at another host | aim at the local stack; a CDN, font host or analytics script the app loads in dev also aborts the run: serve it locally or switch it off in dev; add a host only for another LOCAL service |
| exit 2, `the app does not respond` | the local stack is down | start it; `--check` does not need it, `--dry` and recording do |
| exit 2, `environment variable X is not set` | an `{{env:X}}` has no value | export it in the environment that launches the recorder, for example `set -a; . ./.env.local; set +a; explainer-record 01` with the file gitignored |
| exit 2, `another recorder is running` | the lock is held | wait for it; if the pid is dead the lock is removed on the next run |
| exit 3, `configured fonts did not load` | a family in `fonts` is not reachable | serve the font locally or drop it from `fonts`; the check exists so a fallback font is never recorded by accident |
| exit 1, `step i/n (click ...)` times out | wrong selector, or the screen was not ready | `--dry` shows the step; fix the selector or add `waitFor` to the previous step (default timeout 15 s) |
| exit 1, `exceeds maxSeconds` | the take outran its limit | shorten the narration or raise `maxSeconds` (at most 300) |
| `--verify`: `duration ... outside` | the video left `durationWindow` | trim or add steps, or change the window |
| `--verify`: `deny-list: N hit(s)` | forbidden text reached the guion, srt or dom dump | edit the guion or the demo data and re-take that id |
| `--verify`: `missing mp4 (...)` | that id was never recorded | record it first |
| a blur does not apply | the entry is not a CSS selector | `blur` takes CSS only; role and text selectors do nothing there |

Related: `storyboard-guide.md` (writing), `templates/voice-install.md` (voice).
