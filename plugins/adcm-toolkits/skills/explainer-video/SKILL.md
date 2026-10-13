---
name: explainer-video
description: >
  Records explainer videos of a local web app with an AI voice-over, on-screen captions
  and subtitles. A deterministic script (the `explainer-record` launcher) drives the
  browser, speaks every step and muxes mp4 + srt + poster + contact sheet, so the model
  only writes storyboards and never records. Delegation rule: the main session briefs ONE
  executor to write the storyboards, the owner approves the storyboard table, the main
  session runs `explainer-record` in a background Bash with zero agents, and ONE auditor
  reviews the contact sheets and subtitles. Triggers on 'video explicativo', 'graba un
  video de la funcionalidad', 'explainer video', 'narración con voz', 'guion del video',
  'screen recording with voice'.
compatibility: >
  Node >= 20, ffmpeg and ffprobe, playwright-core >= 1.61 (npx cache or the project
  node_modules) with Chrome or Chromium, one TTS engine (edge-tts in a venv, piper offline
  or macOS say), network for edge-tts.
---

# explainer-video

A recorded walkthrough costs model tokens only where a model adds judgment: writing the
storyboard and auditing the result. The recording itself is a script. It opens the app,
performs the steps, speaks each one with a synthetic voice, and leaves the same mp4 every
time the storyboard is unchanged. Re-takes cost minutes of machine time, not turns.

`explainer-record` is the plugin's `bin/` launcher (on the Bash PATH while the plugin is
enabled; it picks a Node >= 20 installed with nvm). Run it bare. Voice overrides go in front as
environment assignments (`REC_TTS=piper explainer-record 01`); nothing else precedes it.
Without the plugin on PATH: `node "${CLAUDE_PLUGIN_ROOT:-.}/skills/explainer-video/scripts/record.mjs" <args>`
(from the plugin root when the variable is unset), with Node >= 20 first on PATH.

CLI (the contract): `explainer-record <ids…>|--all [--check|--dry|--verify|--doctor] [--mute] [--config videos/config.json]`.
Exit: `0` ok · `1` failure · `2` config, guard, voice not ready or Node < 20 · `3` configured
fonts not loaded · `4` no `page.screencast` · `64` argument errors · `130` interrupted (Ctrl-C). Every flag, config key
and failure is in `references/pipeline.md`.

## If you are the main session

You orchestrate. You do not write guiones, record in a browser, play the video or publish.

0. **Doctor, zero agents.** `explainer-record --doctor` prints seven lines, `ok <item>` or
   `missing <item> — <recipe>`, then `DOCTOR: ready|not ready` (exit 0 / 2). The voice line
   synthesizes one word with the selected engine, so an engine that is installed but refused
   (edge answering 403) shows as `missing voice engine — … synthesis failed`. A missing voice:
   `templates/voice-install.md`. Edge not ready: ask the owner which fallback to use
   (`REC_TTS=piper` or `REC_TTS=say`); never switch on your own. Also settle with the owner:
   the features to cover, the LOCAL base URL and how to start it, the sign-in env var NAMES
   (never values) and any data-reset command the project has.
1. **One executor writes the storyboards.** `Agent(subagent_type: "adcm-toolkits:executor")`
   (`adcm-toolkits:executor-frontend` for UI-heavy apps; no plugin in this session →
   `general-purpose` + `model: "sonnet"`), with this brief (≤40 lines):

   ```
   TASK: storyboards for <features> of <app>, ids <NN>..<NN>.
   FILES: read the project context for routes and selectors (<context skill or brain map>),
     ${CLAUDE_PLUGIN_ROOT}/skills/explainer-video/references/storyboard-guide.md and pipeline.md.
     Write videos/config.json (first time, from templates/config.json.tmpl) and
     videos/guiones/NN-slug.json (from templates/guion.json.tmpl). The local app runs at <baseUrl>.
   DELIVERABLE: one guion per feature, 3-20 steps, narration in the voice's language.
   DOD-SLICE: explainer-record --check → every guion OK, estimate inside durationWindow;
     explainer-record <ids> --dry → exit 0 (it DOES change the local app data; reset first if documented).
   STOP IF: baseUrl is not local · a sign-in needs a literal secret · a selector is not found after
     2 attempts · the local app is down.
   FORBIDDEN: recording (an id without --dry records), browser tools, secrets as literals,
     any host outside allowHosts, files outside videos/.
   RETURN: the storyboard TABLE per guion (step · action · narration · caption · est s) plus the
     tails of --check and --dry. Never the JSON.
   ```
2. **Owner gate.** Present each table with `AskUserQuestion` (one question per batch of
   guiones: approve · edit narration · change steps · drop). Corrections go back to the
   same executor with the edited table (`SendMessage`), then `--check` again. No recording
   before the owner approves.
3. **Record in the background, zero agents.** `explainer-record 01 02` (or `--all`) as a Bash
   call with `run_in_background: true`; about 2 minutes per video. Wait for the
   completion notice, then `explainer-record --verify 01 02` (or `--all`), which writes
   `videos/out/manifest.json`. A non-zero exit: read the last lines and
   `references/pipeline.md` (troubleshooting); an engine failure goes to the owner.
4. **One auditor reviews.** `Agent(subagent_type: "adcm-toolkits:auditor")` (Opus;
   `model: "sonnet"` once the Opus quota is spent). It reads `videos/out/sheets/*.png`
   (12 frames per video), `videos/out/srt/*.srt` and `videos/out/dom/*.txt`; it never plays
   the video. It looks for blank or wrong screens, error toasts, unblurred personal data,
   subtitles that disagree with what is on screen, and narration that talks about
   something that never appears. RETURN per id: `ship` or `retake: <why>`. Retake only
   the affected ids: the executor fixes the guion, you re-record and re-verify those ids
   (the manifest keeps the others).
5. **Delivery.** `manifest.json` (id · slug · title · duration · sha256 · bytes) and the
   posters are the evidence. The mp4 files go to the owner with `SendUserFile` from the
   main session when asked (sub-agents cannot); the `.srt` travels beside each mp4. An
   executor writes the human index from `templates/videos-index.md.tmpl` into the
   project's docs. If the session closes with registered artifacts, the courier closes
   as usual and its links block is pasted once. `videos/out/` is never committed.

In direct mode (`sin tanto lío`, `modo directo`) you run the whole flow yourself; the
owner gate and the hard rules below still apply.

## If you are the storyboard executor

Read `references/storyboard-guide.md` before writing. Your brief names the files and the
base URL; do not widen either.

1. **Config, first time only.** `videos/config.json` from `templates/config.json.tmpl`:
   `baseUrl` (local), `setup` for the sign-in with `{{env:VAR}}` values, `profiles` when
   roles differ, `brand`, `fonts`, `durationWindow`. Paths inside it are relative to the
   config file: guiones in `videos/guiones/`, outputs in `videos/out/`. Make sure
   `videos/out/` is in `.gitignore`.
2. **Routes and selectors from the project context** and the app source (test ids, aria
   labels, visible text). Never guess a selector: if the context does not give it, read the
   component; if you still cannot find it twice, STOP and report.
3. **One guion per feature**, `videos/guiones/NN-slug.json` (two-digit id, lowercase-dash
   slug, the file name is `<id>-<slug>.json`). 3 to 20 steps; per step `say` <= 240
   characters (the voice and the subtitle), `caption` <= 60, one idea each. `waitFor` after
   any action that changes the screen; `blur` for personal data; `{{env:VAR}}` for
   secrets; `{{today}}` / `{{today+N}}` for dates. Placeholders are accepted only in
   `value`.
4. **Prove it.** `explainer-record --check` (all guiones OK, the estimate inside the
   window), then `explainer-record <ids> --dry` against the LOCAL stack with the app up:
   it runs the real clicks without camera or voice and changes the app data. Fix selectors
   until it exits 0. An id without `--dry` records: do not run it unless the brief says so.
5. **Return the storyboard table**, one per guion, then the command tails:

   | # | action | narration (say) | caption | est s |
   |---|---|---|---|---|

   Never the JSON, never file contents.

## Hard rules

1. **The script records.** No agent uses browser tools (Chrome extension, Playwright MCP,
   gif tools) to record, click for the viewer or narrate. The model writes guiones and
   launches commands.
2. **Never production.** `allowHosts` defaults to `localhost` and `127.0.0.1`; a request
   to any other host aborts the run with exit 2. Never aim `baseUrl` at a deployed
   environment; add a host to `allowHosts` only for another LOCAL service, and only when the
   owner says so.
3. **Secrets only as `{{env:VAR}}`.** No literal password, token or key in a config, guion,
   fixture, brief or RETURN. Values are redacted in console, srt, dom dump and timeline.
4. **One voice.** `edge:es-MX-DaliaNeural`. The fallbacks (`piper`, then `say`) are chosen
   by the owner with `REC_TTS`; the recorder never falls back on its own and neither do
   you. Narration is written in the language of the voice. Changing the voice for good
   needs samples the owner listens to first.
5. **Two phases.** Storyboard, then the owner's approval, then recording.
6. **Outputs are gitignored.** The versioned files are `videos/config.json` and
   `videos/guiones/*.json`. `videos/out/` is never committed.
7. **The manifest is the evidence.** Done means `--verify` exit 0, the ids in
   `manifest.json`, and the auditor's `ship` for each. Say "recorded" for nothing else.
8. **Budget.** One executor for the storyboards (plus one per re-take round), one auditor,
   zero agents for recording and verifying. Delegation tiers follow
   `${CLAUDE_PLUGIN_ROOT}/skills/execution-prompt-architect/references/orchestrator-rule.md`.

## Files

| File | What it is | Read at |
|---|---|---|
| `scripts/record.mjs`, `scripts/lib/*` | the recorder (Node ESM, no dependencies of its own) | never; run it |
| `scripts/explainer-video-selftest.py` | offline checks of the recorder, with a smoke recording of a demo page | after changing the scripts |
| `references/storyboard-guide.md` | narration, captions, selectors, timing, a worked example | the executor, before writing |
| `references/pipeline.md` | the chain, every flag and exit code, config keys, outputs, troubleshooting | on a failure, or to explain |
| `templates/config.json.tmpl`, `templates/guion.json.tmpl` | starting points for the two JSON files | the executor |
| `templates/videos-index.md.tmpl` | the human index of the videos for the project docs | delivery |
| `templates/voice-install.md` | the voice venv recipe, the piper model and the sha256 check | `--doctor` says the voice is missing |
| `fixtures/demo/` | a generic demo app for smoke recordings | selftest |
| `bin/explainer-record` | the launcher (plugin level) | every command above |
