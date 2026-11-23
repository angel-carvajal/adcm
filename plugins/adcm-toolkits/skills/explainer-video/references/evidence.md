# MR evidence (`mr-evidence`)

`scripts/launchers/mr-evidence` runs `skills/explainer-video/scripts/evidence.mjs` (Node 20+, same nvm shim as `explainer-record`).
It captures screenshots and a silent captioned mp4 of the branch's LOCAL dev server and uploads them to a GitLab MR. The model writes the spec; the script records, uploads and edits the MR. Requirements: Node >= 20, playwright-core >= 1.61, Chrome, ffmpeg + ffprobe, glab (`mr-evidence doctor`).

## Commands
`mr-evidence doctor|check|capture|attach|run --spec <path> [--mode screenshots|video|both|none] [--note] [--out <dir>] [--mr <iid>] [--forge gitlab|github] [--dry] [--env-file .env.local] [--max-mb 10] [--repo <dir>] [--json]`
- `doctor`: tools only, no spec. `check`: validates spec, loopback hosts, tools and credentials; starts nothing.
- `capture`: starts `serve`, logs in, writes `<out>/shots/<name>-{d,m}.png` (width >= 768 is `d`), `<out>/video/<spec.name>.mp4`, `<out>/manifest.json`. `--out` defaults to `$TMPDIR/mr-evidence/<spec.name>` and must be outside the repo (evidence is never committed).
- `attach`: uploads and prints the block. `--files <dir>` uploads every png/mp4 of a directory with no spec (dependency-renovate); without `--mr` it only uploads and prints (`--md-out <file>` also writes the block, for `glab mr create -d`). With `--mr N`: by default the region between the markers in the description is replaced (appended if absent, all other text untouched, idempotent); `--note` posts `glab mr note create N -m` headed `## Evidencia (refrescada tras arreglos del gate)`.
- `run`: capture + attach. `--mode screenshots|video|both|none` picks the media (default `both`; media without a matching spec section are skipped); `--note` picks the placement (note instead of description region; media from the spec). `--mode body|note` is rejected with exit 64. `--dry` captures but uploads nothing (the block lists local paths).
- `--env-file` is forwarded by the launcher as `--creds-file` because Node itself loads `--env-file` from argv.

## Spec (`qa/evidence/<wave>.json`, unknown keys are exit 64)
```json
{
  "name": "W3",
  "serve": {"cmd": "npm run dev -- --port 3111", "ready": "http://127.0.0.1:3111/", "timeoutS": 60, "cwd": "."},
  "baseUrl": "http://127.0.0.1:3111",
  "allowHosts": ["127.0.0.1", "localhost"],
  "routes": [{"path": "/orders", "name": "orders", "waitFor": "[data-ready]", "mask": [".avatar"]}],
  "widths": [1280, 375],
  "auth": {"loginPath": "/login", "userSelector": "#email", "passSelector": "#password", "submitSelector": "button[type=submit]", "successSelector": "#welcome", "userEnv": "EVIDENCE_USER", "passEnv": "EVIDENCE_PASS"},
  "video": {"steps": [{"action": "goto", "value": "/orders", "caption": "Lista de pedidos", "hold": 1.5}]}
}
```
- `serve` is optional (without it the server must already answer at `baseUrl`). `ready` must answer 2xx/3xx. The port must be free: a busy port is exit 3 and the other process is never reused. The server runs in its own process group and is killed at exit.
- `routes`: `name` lowercase `[a-z0-9-]`, unique. `widths` default `[1280, 375]` (height 800 / 812). `mask` selectors are painted over (PII).
- `auth`: all five selectors required; `userEnv`/`passEnv` default `EVIDENCE_USER`/`EVIDENCE_PASS`. The login runs in each context before any shot and BEFORE the video starts, so credentials never show in media.
- `video.steps`: at most 25, each with `action` (goto|click|fill|select|press|scroll|wait), a required `caption` (<= 80 chars, shown as the subtitle), optional `hold` seconds (default 1.5). Estimated duration (holds + `wait` values) must be <= 60 s or the spec is exit 64. 1280x720, h264, silent, no TTS. `{{...}}` placeholders are refused: secrets only come from `auth`.

## Markers
The MR description region is exactly `<!-- evidence:start -->` ... `<!-- evidence:end -->`, with `## Evidencia` inside. Everything outside is preserved byte for byte. The region is replaced only when the start and end marker each appear exactly once and in order; otherwise a fresh region is appended after the existing text and a `WARN:` line is printed (stderr), so hand-written text is never eaten. A note carries no markers.

## stdout
`EVIDENCE: ok <n> shots[ video][ (<note>)]` or `EVIDENCE: failed(<code>) <reason>`; `MEDIA: unsent: <abs paths>` (send them to the phone with SendUserFile); then the markdown block. `--json` prints one JSON object instead. GitHub forge: the block says `Evidencia: adjuntar a mano (GitHub no admite subida por API)`, exit 0, glab never runs.

## Exit codes
0 ok (also `--mode none`; also a video dropped for size while the shots uploaded) · 1 capture failed · 2 environment (Node < 20, playwright, Chrome, ffmpeg, glab, missing credentials) · 3 server will not start, ready never answers, port busy · 4 login failed · 5 upload or MR write failed (a 413 re-encodes the mp4 once with `-crf 32 -vf scale=-2:540`, then drops the video and keeps the shots) · 6 a host is not loopback (also printed as `failed(6)` when a page request is blocked at runtime) · 64 invalid spec or arguments (also `check`/`capture --mode video` without `video.steps`, `--mode screenshots` without `routes`) · 130 SIGINT · 143 SIGTERM/SIGHUP (the dev server's process group is killed on all three).
A failure never blocks the MR: open it with `## Evidencia: pendiente (<reason>)` and put the reason in the handoff.

## Env and security
- Credentials: `EVIDENCE_USER` / `EVIDENCE_PASS` (names configurable in `spec.auth`), read by the script from `--env-file` (default `<repo>/.env.local`), then the process environment. Agents never read `.env*`. Values and their URL-encoded forms are scrubbed from every printed line, `manifest.json` and glab arguments logged; `manifest.json` holds no auth data. The dev server does not inherit them (the credential variables are removed from its environment even when they were exported in the shell).
- Only loopback hosts (`localhost`, `127.0.0.1`, `::1`) in `baseUrl`, `allowHosts` and `serve.ready` (exit 6; `baseUrl` and `serve.ready` must be `http:` or `https:`, `allowHosts` a non-empty list, `hold` a number: otherwise exit 64); at runtime every request outside `allowHosts` ends the run with exit 6.
- Uploads: `glab api projects/:id/uploads --form file=@<path>` with cwd = `--repo`; the `.markdown` field of the JSON is what goes in the block. `--max-mb` (default 10) re-encodes a larger mp4 before uploading.
- REC_CHANNEL (default `chrome`) and PW_CORE_DIR work as in `explainer-record`.

## WARNING: production data
The script cannot tell where the dev server's own `.env.local` points. If it targets a production database, the shots and the video will show real data and they are uploaded to the MR. Check the server's env first, use seed data, and add `mask` selectors for anything personal.
