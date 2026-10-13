# explainer-video

Narrated screen recordings of a web app, made by a script instead of a model. You write a
short storyboard per feature; `explainer-record` opens the app, performs the steps, speaks
each one with an AI voice and leaves an mp4 with subtitles, a poster and a contact sheet.

## Why

A model that drives a browser while narrating spends tokens on every click, cannot be
re-run with one command and cannot keep its voice in step with the screen. A script can.
Here the model does the two things only it can do: write the storyboard and audit the
result. Recording, mixing and verifying cost machine minutes, not turns, and a re-take of
an unchanged storyboard gives the same video.

## What it does

1. `--doctor` checks the machine, synthesizes one word with the selected voice engine and
   prints a recipe for what is missing.
2. One executor writes `videos/config.json` (once) and `videos/guiones/NN-slug.json`, then
   proves them with `--check` (schema, estimated duration) and `--dry` (the real clicks
   against the local app, no camera, no voice).
3. The owner approves the storyboard table.
4. `explainer-record <ids>|--all` records in the background: the voice of every step is
   synthesized first and the screencast follows its clock, so what is said and what happens
   stay together. It leaves mp4 (h264 + aac + subtitle track), srt, poster, a 4x3 contact
   sheet and a text dump of each screen.
5. `--verify` checks every mp4 and writes `videos/out/manifest.json`. One auditor reviews
   the contact sheets and subtitles.

## What it does not do

It records only local apps (`allowHosts`), never a deployed one. It has one voice. It does
not capture the desktop, upload anywhere or play the video to judge it.

## Requirements

| Needs | Detail |
|---|---|
| Node >= 20 | the launcher picks one installed with nvm; the default Node may be older |
| playwright-core >= 1.61 | in the project's `node_modules` or the npx cache (`npx -y -p playwright-core@1.63 node -e 0`) |
| Chrome or Chromium | Chrome by default; `REC_CHANNEL=chromium` after `npx playwright-core install chromium` |
| ffmpeg and ffprobe | `brew install ffmpeg` or the system package |
| one TTS engine | edge-tts in a venv (needs network), piper (offline) or macOS `say`; `templates/voice-install.md` |
| the app running locally | for `--dry` and recording, not for `--check` |

`explainer-record --doctor` checks all of it.

## Quick start

```bash
explainer-record --doctor                  # 1. the machine; ends in DOCTOR: ready
mkdir -p videos/guiones
cp "${CLAUDE_PLUGIN_ROOT}/skills/explainer-video/templates/config.json.tmpl" videos/config.json   # 2. once per project
# 3. write videos/guiones/01-your-feature.json from templates/guion.json.tmpl
explainer-record --check                   # 4. schema and estimated seconds, no browser
explainer-record 01 --dry                  # 5. real actions against the local app, no camera
explainer-record 01                        # 6. record, about 2 minutes per video
explainer-record --verify 01               # 7. check the mp4, write videos/out/manifest.json
```

Add `videos/out/` to `.gitignore`. Secrets for the sign-in go through `{{env:VAR}}` in the
config and are exported in the shell that runs the recorder. Inside Claude Code the flow
is the one in `SKILL.md`: an executor writes the storyboards, you approve the table, the
main session records in a background Bash.

Voice overrides: `REC_TTS=piper|say`, `REC_VOICE`, `REC_RATE`, `REC_TTS_HOME`. Offline and
deterministic runs (tests): `--mute` records with silence of the estimated length.

## Optional keys

`denyList` and `mail` are absent from `templates/config.json.tmpl` on purpose: they have no JSON default and the recorder rejects an explicit `null`, so add each one only when you use it (`references/pipeline.md`, config keys).

## Files

| Path | What |
|---|---|
| `SKILL.md` | the flow for the main session and the storyboard executor, and the hard rules |
| `scripts/record.mjs`, `scripts/lib/*` | the recorder |
| `scripts/explainer-video-selftest.py` | offline checks of the recorder |
| `references/storyboard-guide.md` | how to write a guion, with a worked example |
| `references/pipeline.md` | the chain, flags, exit codes, config keys, outputs, troubleshooting |
| `templates/config.json.tmpl`, `templates/guion.json.tmpl` | starting points for the two JSON files |
| `templates/videos-index.md.tmpl` | the human index of the videos for the project docs |
| `templates/voice-install.md` | the voice venv, the piper model and its sha256 check |
| `fixtures/demo/` | a generic demo app for smoke recordings |

The launcher lives at the plugin level: `bin/explainer-record`.
