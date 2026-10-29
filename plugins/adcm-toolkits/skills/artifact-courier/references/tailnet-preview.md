# tailnet-preview: a preview link that works off the LAN

`tailnet-preview` (`scripts/tailnet_preview.py`, stdlib Python 3.9+, launcher `bin/tailnet-preview`) keeps a project's
local dev server running after the session (detached, the Mac kept awake by `caffeinate`) and maps it with
`tailscale serve` to a tailnet-only HTTPS URL, `https://<machine>.<tailnet>.ts.net:<port>/`, so the owner can open the
preview from the phone on any network. Only devices signed in to the owner's own tailnet reach it: it never runs
`tailscale funnel`. Without Tailscale it still starts the server and falls back to LAN-only.

## 1. One-time setup (the owner, by hand)

Claude cannot do these steps. Sources: Tailscale's [macOS variants](https://tailscale.com/kb/1065/macos-variants),
[CLI](https://tailscale.com/kb/1080/cli), [serve](https://tailscale.com/kb/1242/tailscale-serve),
[Serve overview](https://tailscale.com/kb/1312/serve), [HTTPS](https://tailscale.com/kb/1153/enabling-https),
[key expiry](https://tailscale.com/kb/1028/key-expiry), [machine names](https://tailscale.com/kb/1098/machine-names),
[other VPNs](https://tailscale.com/kb/1105/other-vpns).

1. **Install the Standalone variant**: `brew install --cask tailscale-app` (the cask installs the Standalone .pkg from
   pkgs.tailscale.com; macOS 13+), or download that .pkg. Tailscale recommends starting with Standalone: no Apple ID,
   in-app updates, and it serves ports (the GUI variants cannot serve files or folders; this launcher never asks).
   Do not install the `tailscale` formula (the open-source `tailscaled`, meant for unattended installs run with
   sudo) and never run the App Store app next to it (to switch: delete the app, empty the Trash, reboot).
2. Open Tailscale.app; approve the system extension (System Settings → General → Login Items & Extensions → Network
   Extensions, or Privacy & Security) and the VPN configuration prompt.
3. Log in with the personal account: that is the owner's tailnet, and only the owner's devices join it.
4. Settings → CLI integration → Show me how → Install Now (admin password) puts a launcher at
   `/usr/local/bin/tailscale`. Without it the launcher calls `/Applications/Tailscale.app/Contents/MacOS/Tailscale`
   with `TAILSCALE_BE_CLI=1`, so the bundled binary does not open the GUI.
5. Admin console (login.tailscale.com/admin) → Machines → the Mac:
   - "Edit machine name" → a neutral name such as `acme-mac`, "Auto-generate from OS hostname" unchecked. Do it
     **before** enabling HTTPS: certificates put the machine name in the Certificate Transparency log (public), and
     the default name comes from the OS hostname, which often carries a first name. Renaming changes the URL.
   - Row menu → "Disable Key Expiry" (keys expire after 180 days by default).
6. Admin console → DNS: MagicDNS on, then HTTPS Certificates → Enable. Tailscale warns that the machine names and the
   tailnet DNS name become publicly visible in the Certificate Transparency log (public) once certificates are
   issued. Optional: switch the tailnet DNS name to a randomized one.
7. Phone: install Tailscale, log in with the **same** account, allow the VPN configuration → Connected. iOS and
   Android run one VPN at a time: turn any other VPN off on the phone before opening a preview link.
8. Mac: `tailscale status` lists both devices; `tailnet-preview doctor` ends with `TAILNET-PREVIEW: ready · …`.
9. Do not share the Mac with other tailnet users (shared devices can reach Serve URLs); keep the default ACL.
10. Other VPN clients on the Mac (corporate or commercial) can claim 100.64.0.0/10 too. Keep them disconnected while
    the phone uses a preview; if a link fails while one is up, disconnect it and retry, look for a competing route
    with `netstat -rn | grep 100.64`, and retry curl with `--noproxy '*'`.
11. Optional: the auto-mode exception and the footer badge in `bin/README.md`.

## 2. Commands and profile

```
tailnet-preview doctor                               [--json] [--state-dir DIR]
tailnet-preview up [SLUG] [--cwd DIR] [--port N] [--health PATH] [--https-port N] [--timeout S]
                   [--env KEY=VAL]... [--inherit-env NAME]... [--title T] [--reuse|--no-reuse] [--restart]
                   [--no-serve] [--path P] [--apply] [--json] [--state-dir DIR] [-- CMD ARG...]
tailnet-preview status [SLUG] | url [SLUG] [--path P] [--json] [--state-dir DIR]
tailnet-preview down [SLUG | --all] [--keep-serve] [--apply] [--json] [--state-dir DIR]
tailnet-preview list                                 [--json] [--state-dir DIR]
```

- Read-only by default: `--apply` (up and down only) is the one write flag. Without it up and down print the plan
  (`would-start | would-reuse | would-restart | would-stop`), write nothing and exit 1.
- Exits: 0 done · 1 needed or partial · 2 blocked, failed or unreadable state · 64 usage. At most 40 lines, `~`
  paths, and the last line is always `TAILNET-PREVIEW: <word> …`. `--json` prints one object: `version, command,
  slug, status, exit, verdict, urls{localhost,lan,tailnet}, pid, port, https_port, node, log, problems[], profile`.
- SLUG (`[a-z0-9][a-z0-9-]{0,39}`) defaults to the one profile whose cwd is the current directory or an ancestor of
  it; none or several → exit 2 with the candidates.
- **Profile** (`profiles/<slug>.json`, machine-local; never in a brain or in `artifacts.json`): `cwd`, `cmd` (argv
  after `--`, run without a shell), `env`, `inherit_env`, `port` (1024-65535), `health` (default `/`; 200-399
  counts), `https_port` (first free in 8443-8499, kept per slug; `--https-port` pins it), `timeout` (1-1800 s,
  default 120), `reuse` (default on), `title`. Flags given to `up` override it; `--env`, `--inherit-env` and the
  command replace the saved values. The wave prompt carries the full `up` line, so a wiped state dir comes back.
- **Child environment**: an allowlist (PATH, HOME, USER, LOGNAME, SHELL, TMPDIR, LANG, LC_*, TERM, NVM_DIR) plus `env`
  plus the `--inherit-env` names; `CLAUDE*` and `ANTHROPIC_*` never pass. A name with a `_`-separated part SECRET,
  TOKEN, PASSWORD, PASS, KEY, AUTH or COOKIE is refused (exit 64), through `--inherit-env` too (`API_TOKEN` is
  refused, `MONKEY_MODE` and `AUTHOR` pass): secrets stay in the project's own env files. Pass routing values only
  (`PORT`, `HOST`, `NODE_ENV`).
- **Node**: `<cwd>/.nvmrc` picks the highest installed `$NVM_DIR/versions/node` version whose leading numbers match
  (`20` → the newest 20.x; `20.1` never matches 20.11.0) and puts its `bin` first on PATH; `lts/*` is ignored.
- **State dir**: `--state-dir`, else `$TAILNET_PREVIEW_HOME`, else
  `${XDG_STATE_HOME:-~/.local/state}/adcm-toolkits/tailnet-preview/`: `profiles/`, `run/<slug>.json` (pid, pgid,
  start time and its epoch, caffeinate pid, ports, mapping, status), `logs/<slug>.log` and `.lock`.
- **Hooks** (tests, debugging): `TAILNET_PREVIEW_TAILSCALE=<path>|none` (`none` = absent),
  `TAILNET_PREVIEW_LAN_IP=<ip>|none` (instead of `ipconfig getifaddr en0`, then en1), `NVM_DIR` (default `~/.nvm`).

## 3. Lifecycle

`up --apply`, under the state-dir lock:
1. A running instance whose identity matches (same pgid and start time) is reused when `reuse` is on, the profile
   did not change, `--restart` is absent and its health answers; the mapping is still ensured ("already up").
   Otherwise it is stopped first.
2. **Port check before spawning**: any listener on `port` (lsof, plus a connect() probe for listeners lsof cannot
   see) → exit 2 `blocked … port N held by pid P (command, cwd) · free: M`. The launcher never kills it and never
   shifts the port: bookmarks, `PLAYWRIGHT_BASE_URL` and habits depend on it.
3. The command starts in its own session and process group with stdio appended to the log, so it outlives the
   session; `run/<slug>.json` gets `status: starting` right away, so a launcher cut short leaves a state `up` and
   `down` still recognise.
4. Health: `GET http://127.0.0.1:<port><health>` every second up to the timeout. The command exits → `exited (N)`
   with the log tail; the timeout passes → `unhealthy` (the group gets TERM, then KILL after 10 s).
5. The listener must belong to our process group, else `blocked` (foreign listener).
6. `caffeinate -i -s -w <pid>` keeps the Mac awake (system sleep is blocked only on AC power) until the service ends.
7. `tailscale serve --bg --yes --https=<https_port> http://127.0.0.1:<port>` (it persists across reboots until
   removed), then one warm-up `curl --noproxy '*' --max-time 60`: 200 → `up`, anything else → `mapped … (not
   answering yet)`. Never 443, never `--set-path`, never `funnel`, never `serve reset`.

`down --apply`: identity check, TERM to the process group (KILL after 10 s), caffeinate stopped, `tailscale serve
--https=<https_port> off` unless `--keep-serve`, status `stopped`; the profile stays. A pid whose start time no
longer matches is never signalled (`stale pid … not ours`).

Who stops it: the next wave's `up` reuses or restarts it; after the merge, `tailnet-preview down <slug> --apply`
(the owner can run it with `!`). **Logs** rotate to `<slug>.log.1` above 5 MB, and only at `up`: the running server
keeps the file open, so a chatty server left up for days grows until the next `up`.

## 4. The close

- The orchestrator runs `tailnet-preview up <slug> --apply` before briefing the courier, with a Bash `timeout` of at
  least (profile timeout + 150) s, in ms, and 600000 at most. That is why the health wait is capped at 420 s: a longer
  `--timeout` is kept in the profile but prints `timeout capped at 420 (Bash tool limit)`.
- Dispatch on the verdict word, never on the exit code (exit 1 covers a dry run, `lan-only` and `mapped`):

  | Verdict word | `Preview:` | `Tailnet:` |
  |---|---|---|
  | `up` | the localhost URL | the `tailnet` URL |
  | `mapped` (not answering yet) | the localhost URL | the `tailnet` URL (the courier's curl allows 60 s) |
  | `lan-only` | the localhost URL | `none` |
  | anything else (`blocked`, `unhealthy`, `exited (N)`, `error`, `usage`) | `none` | `none` |

- The tailnet URL is for the owner's phone only: never pass it to screenshot, capture or recording tools; those stay
  on `localhost`.

## 5. Troubleshooting

- `blocked … port N held by pid P`: another server owns the port; stop it yourself or pick another `--port`.
  `held by an unlisted (root?) process`: a root daemon; `sudo lsof -nP -iTCP:N -sTCP:LISTEN` names it.
- `unhealthy`: raise `--timeout` (a production build can take minutes; 420 s at most) or fix the health path. The hint
  `answers on ::1 only` means the server bound the IPv6 loopback: bind 127.0.0.1 or 0.0.0.0 (serve targets 127.0.0.1).
- `exited (N)`: read the log tail; a server that needs `PORT`/`HOST` gets them through `--env`.
- `mapped … (not answering yet)`: the first request after a new certificate can take a minute; check again with
  `tailnet-preview status`. Let's Encrypt rate limits can delay a first certificate by hours.
- `lan-only` with Tailscale installed: `tailnet-preview doctor` names the missing step (login, MagicDNS, HTTPS
  certificates, version ≥ 1.52). Pick a `--health` path that answers 200: the warm-up and the courier need a 200.
- The phone cannot open the link: Tailscale connected on the phone with the same account, no other VPN on; on the
  Mac, disconnect other VPNs and check `netstat -rn | grep 100.64`.
- `stale`: the process died or its pid was reused; the next `up` restarts it, `down --apply` cleans up.
- Project scripts that kill by pattern hit other servers: a `serve-review.sh` that runs `pkill -f "dist/server.js"`
  kills every process whose command line holds that string, other projects' servers included. Narrow it to the
  repo path or the port before the first preview, and never run a `predev` port killer without an explicit `PORT`.

## 6. Limits

| Stack | Through serve | Fix |
|---|---|---|
| Next.js dev | cross-origin dev assets are blocked unless the Origin host is allowed | `allowedDevOrigins: ['**.ts.net']`, or preview `next build && next start` |
| Vite dev | `server.allowedHosts` rejects the ts.net Host; the default host may be `::1` only | `server.allowedHosts: ['.ts.net']` and `--host 127.0.0.1` |
| SPA with a loopback API URL baked in | the phone calls its own loopback | a same-origin proxy for the API |
| Local auth server | non-loopback redirect URLs are rejected | add the ts.net URL to the allowed redirect URLs |
| Host-based multi-tenant routing | the ts.net Host matches no tenant | a dev-only tenant override |

- Serve keeps the original Host (`<machine>.<tailnet>.ts.net`) and sends `X-Forwarded-Proto: https`, so an app that
  redirects plain-HTTP requests to its canonical host stays put and secure cookies work. Never map with `--http`.
- The child outlives the session because Bash runs unsandboxed; under a sandboxed harness it could be reaped.
- `caffeinate` cannot stop lid-close sleep: keep the lid open (or an external display and power) while a link is out.
- Ports only (https 8443-8499 unless pinned, IPv4 loopback targets); no files or folders, one tailnet.
- Run-together names such as `APIKEY` or `SECRETKEY` are not refused by the `_`-token rule: split them (`API_KEY`) or keep them out of the profile.
