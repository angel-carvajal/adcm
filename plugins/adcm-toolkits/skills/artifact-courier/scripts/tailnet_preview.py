#!/usr/bin/env python3
"""tailnet_preview - keep a project's dev server alive after the session and map it to a tailnet-only HTTPS URL.

Stdlib only, Python 3.9+. `bin/tailnet-preview` runs it; `--help` prints the grammar.

  doctor   python, lsof, caffeinate, LAN IP, state dir and Tailscale (version, login, MagicDNS, HTTPS
           certificates, serve status); `ready` means `up` can map a tailnet URL.
  up       starts the profile's command detached (own session, stdio to the log, kept awake by caffeinate),
           waits for its health path, maps it with `tailscale serve`, prints the localhost / lan / tailnet URLs.
  status   one state word: up, lan-only, unmapped, unhealthy, starting, stale, stopped, foreign-port.
  url      the three URLs from the run state (no requests; the pid identity is still checked).
  down     stops the process group and caffeinate and removes the serve mapping.
  list     one line per profile.

Read-only by default: `--apply` (up and down only) is the one write flag; without it up and down print the
plan (would-start | would-reuse | would-restart | would-stop), write nothing and exit 1.

Exits: 0 done · 1 needed or partial (dry run, lan-only, mapped but not answering yet, not running) · 2 blocked,
failed, unreadable state, missing or invalid profile, ambiguous slug · 64 usage (bad flag or value, secret-like
env name). Text output is at most 40 lines with `~`-relative paths and always ends with the verdict line
`TAILNET-PREVIEW: <word> ...`; callers dispatch on that word, never on the exit code. `--json` prints one object.

Safety: a process is signalled only after its identity matches the run state (pgid plus `ps -o lstart` read
under LC_ALL=C and compared as an epoch), so a reused pid is never touched. A port held by anyone else is
reported with its holder and the next free port before anything is spawned: never killed, never shifted.
The child gets an allowlisted environment (PATH HOME USER LOGNAME SHELL TMPDIR LANG LC_* TERM NVM_DIR) plus the
profile's env and its --inherit-env names; CLAUDE*/ANTHROPIC_* never pass and secret-like names are refused.
`tailscale serve` only maps an https port (8443-8499 unless pinned) to http://127.0.0.1:<port>: never 443,
never --set-path, never funnel, never `serve reset`.

Hooks: TAILNET_PREVIEW_TAILSCALE=<path>|none (none = absent), TAILNET_PREVIEW_LAN_IP=<ip>|none,
TAILNET_PREVIEW_HOME (state dir), NVM_DIR (default ~/.nvm). Runbook: references/tailnet-preview.md.
"""
import argparse
import contextlib
import fcntl
import http.client
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

SCHEMA = 1
VERDICT = "TAILNET-PREVIEW:"
COMMANDS = ("doctor", "up", "status", "url", "down", "list")
HTTPS_POOL = range(8443, 8500)
WAIT_CAP = 420
DEFAULT_TIMEOUT = 120
MAX_LINES = 40
ROTATE_BYTES = 5 * 1024 * 1024
MIN_TAILSCALE = (1, 52)
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
SECRET_TOKENS = frozenset(("SECRET", "TOKEN", "PASSWORD", "PASS", "KEY", "AUTH", "COOKIE"))
RESERVED = ("CLAUDE", "ANTHROPIC_")
ENV_ALLOW = frozenset(("PATH", "HOME", "USER", "LOGNAME", "SHELL", "TMPDIR", "LANG", "TERM", "NVM_DIR"))
PROCESS_KEYS = ("cwd", "cmd", "env", "inherit_env", "port")
RUNNING = frozenset(("starting", "up", "mapped", "lan-only", "unmapped"))
FAILED = frozenset(("exited", "unhealthy", "blocked"))
APP_CLI = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
INSTALL = "references/tailnet-preview.md §1"
MONTHS = {m: i for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}

HELP = """\
tailnet-preview - keep a project's dev server alive after the session and map it to a tailnet-only HTTPS URL

  tailnet-preview doctor                               [--json] [--state-dir DIR]
  tailnet-preview up [SLUG] [--cwd DIR] [--port N] [--health PATH] [--https-port N] [--timeout S]
                     [--env KEY=VAL]... [--inherit-env NAME]... [--title T] [--reuse|--no-reuse] [--restart]
                     [--no-serve] [--path P] [--apply] [--json] [--state-dir DIR] [-- CMD ARG...]
  tailnet-preview status [SLUG]                        [--json] [--state-dir DIR]
  tailnet-preview url [SLUG] [--path P]                [--json] [--state-dir DIR]
  tailnet-preview down [SLUG | --all] [--keep-serve] [--apply] [--json] [--state-dir DIR]
  tailnet-preview list                                 [--json] [--state-dir DIR]
  tailnet-preview --version | --help

--apply (up and down only) is the one write flag: without it up and down print the plan and exit 1.
up: --port is the service port (1024-65535, never shifted) · --health the path that must answer 200-399 ·
--https-port pins the tailnet port (default: the first free one in 8443-8499, kept per slug) · --timeout 1-1800 s
(the wait is capped at 420) · --env KEY=VAL and --inherit-env NAME add to the child's allowlisted environment
(secret-like names are refused) · --no-reuse restarts on every up, --restart once · --no-serve skips the
tailscale mapping · -- CMD ARG... is the command, run without a shell. --env, --inherit-env and the command
replace the saved values when given. SLUG defaults to the one profile whose cwd is the current directory or one
of its ancestors.
down: --all stops every profile · --keep-serve leaves the tailscale mapping in place.
Exits 0 done · 1 needed or partial · 2 blocked, failed or unreadable · 64 usage. The last line is the verdict
`TAILNET-PREVIEW: <word> ...`: dispatch on the word (ready, up, mapped, lan-only, blocked, unhealthy,
exited (N), down, would-start, ...), never on the exit code.
State: --state-dir, else $TAILNET_PREVIEW_HOME, else ${XDG_STATE_HOME:-~/.local/state}/adcm-toolkits/tailnet-preview.
Setup and lifecycle: skills/artifact-courier/references/tailnet-preview.md"""

USAGE = "usage: tailnet-preview {doctor|up|status|url|down|list} [options]  (tailnet-preview --help)"


class Usage(Exception):
    """A usage error: exit 64."""


class Done(Exception):
    """Ends a command with its exit code, the verdict word and the verdict tail."""

    def __init__(self, code, word, tail=""):
        super().__init__(f"{word} {tail}".strip())
        self.code, self.word, self.tail = code, word, tail


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Usage(message)


# ------------------------------------------------------------------ small helpers
def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def homes():
    found = []
    for home in (os.path.expanduser("~"), os.path.realpath(os.path.expanduser("~"))):
        home = home.rstrip("/")
        if home and home not in found:
            found.append(home)
    return found


def tilde(path):
    """`path` with the home directory written as `~`."""
    if not path:
        return path
    text = str(path)
    for home in homes():
        if text == home:
            return "~"
        if text.startswith(home + "/"):
            return "~/" + text[len(home) + 1:]
    return text


def tilde_text(text):
    for home in homes():
        text = text.replace(home + "/", "~/")
    return text


def first_line(text):
    lines = (text or "").strip().splitlines()
    return lines[0].strip()[:120] if lines else ""


def within(child, parent):
    parent = parent.rstrip("/")
    return not parent or child == parent or child.startswith(parent + "/")


def display_cmd(cmd):
    return " ".join(repr(tilde(x)) if not x or any(c.isspace() for c in x) else tilde(x) for x in cmd)


def clean_path(path):
    return (path or "").lstrip("/")


def target(port):
    return f"http://127.0.0.1:{port}"


def healthy(code):
    return 200 <= code < 400


def as_dict(value):
    return value if isinstance(value, dict) else {}


def tool(name):
    """A system tool: PATH first, then the usual macOS folders (launchd shells may lack /usr/sbin)."""
    found = shutil.which(name)
    if found:
        return found
    for folder in ("/usr/sbin", "/usr/bin", "/bin", "/sbin"):
        cand = os.path.join(folder, name)
        if os.access(cand, os.X_OK):
            return cand
    return None


def run(argv, timeout=20, env=None):
    """(returncode, stdout, stderr) of a command run without a shell; returncode None when it could not run."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=timeout, env=env,
                           stdin=subprocess.DEVNULL)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return None, "", str(exc)
    return p.returncode, p.stdout, p.stderr


# ------------------------------------------------------------------ process identity
def c_locale():
    env = dict(os.environ)
    env.update(LC_ALL="C", LANG="C")
    return env


def lstart_epoch(text):
    """Epoch of a C-locale `ps -o lstart` string ('Wed Oct 28 08:48:27 2026'); None when it does not parse."""
    try:
        _, month, day, hms, year = text.split()
        hour, minute, second = (int(x) for x in hms.split(":"))
        return int(time.mktime((int(year), MONTHS[month], int(day), hour, minute, second, 0, 0, -1)))
    except (ValueError, KeyError, OverflowError):
        return None


def proc_info(pid):
    """pgid, state, lstart (always read under LC_ALL=C), its epoch and args of `pid`; None when it is gone."""
    ps = tool("ps")
    if not ps or not is_int(pid) or pid <= 0:
        return None
    rc, out, _ = run([ps, "-o", "pgid=", "-o", "stat=", "-o", "lstart=", "-o", "args=", "-p", str(pid)],
                     env=c_locale())
    parts = out.split() if rc == 0 else []
    if len(parts) < 7 or not parts[0].isdigit():
        return None
    lstart = " ".join(parts[2:7])
    return {"pgid": int(parts[0]), "stat": parts[1], "lstart": lstart, "epoch": lstart_epoch(lstart),
            "args": " ".join(parts[7:])}


def alive(info):
    return info is not None and not info["stat"].startswith("Z")


def is_ours(state):
    """The recorded service still runs with the recorded pgid and start time; a reused pid fails this."""
    info = proc_info(state.get("pid")) if state else None
    return (alive(info) and info["pgid"] == state.get("pgid") and info["epoch"] is not None
            and info["epoch"] == state.get("lstart_epoch"))


def caffeinate_ours(state):
    info = proc_info(state.get("caffeinate_pid")) if state else None
    return (alive(info) and info["pgid"] == state.get("caffeinate_pid") and info["epoch"] is not None
            and info["epoch"] == state.get("caffeinate_lstart_epoch") and "caffeinate" in info["args"])


def group_alive(pgid, proc=None):
    if proc is not None:
        proc.poll()
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def stop_group(pgid, proc=None, grace=10.0):
    """TERM the process group, KILL it after `grace` seconds; says how it ended. Callers check identity first."""
    if not is_int(pgid) or pgid <= 1 or pgid == os.getpgrp():
        return "refused"
    for sig, wait, name in ((signal.SIGTERM, grace, "TERM"), (signal.SIGKILL, 3.0, "KILL")):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return "gone" if name == "TERM" else "TERM"
        except PermissionError:
            return "refused"
        end = time.monotonic() + wait
        while group_alive(pgid, proc):
            if time.monotonic() >= end:
                break
            time.sleep(0.1)
        else:
            return name
    return "survived"


def start_caffeinate(pid):
    exe = tool("caffeinate")
    proc = None
    if exe:
        try:
            proc = subprocess.Popen([exe, "-i", "-s", "-w", str(pid)], stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    start_new_session=True, close_fds=True)
        except OSError:
            proc = None
    info = proc_info(proc.pid) if proc else None
    return {"caffeinate_pid": proc.pid if proc else None, "caffeinate_lstart_epoch": info["epoch"] if info else None}


def stop_caffeinate(state):
    if caffeinate_ours(state):
        with contextlib.suppress(ProcessLookupError):
            os.kill(state["caffeinate_pid"], signal.SIGTERM)


# ------------------------------------------------------------------ ports and HTTP
def listeners(port):
    """[{pid, pgid, cmd}] of the TCP listeners on `port` that lsof can see; None when lsof cannot run."""
    lsof = tool("lsof")
    if not lsof:
        return None
    rc, out, _ = run([lsof, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fpcg"])
    if rc is None:
        return None
    found, cur = [], None
    for line in out.splitlines():
        tag, val = line[:1], line[1:]
        if tag == "p" and val.isdigit():
            cur = {"pid": int(val), "pgid": None, "cmd": "?"}
            found.append(cur)
        elif cur is not None and tag == "g" and val.isdigit():
            cur["pgid"] = int(val)
        elif cur is not None and tag == "c":
            cur["cmd"] = val
    return found


def listening_ports():
    lsof = tool("lsof")
    rc, out, _ = run([lsof, "-nP", "-iTCP", "-sTCP:LISTEN", "-Fn"]) if lsof else (None, "", "")
    ports = set()
    for line in out.splitlines():
        tail = line.rsplit(":", 1)[-1]
        if line.startswith("n") and tail.isdigit():
            ports.add(int(tail))
    return ports


def connect_probe(port, timeout=0.5):
    """True when something accepts on 127.0.0.1 or [::1]: catches listeners lsof cannot see (root)."""
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                if sock.connect_ex((host, port)) == 0:
                    return True
        except OSError:
            continue
    return False


def proc_cwd(pid):
    lsof = tool("lsof")
    rc, out, _ = run([lsof, "-a", "-p", str(pid), "-d", "cwd", "-Fn"]) if lsof else (None, "", "")
    return next((line[1:] for line in out.splitlines() if line.startswith("n/")), None)


def next_free_port(port):
    taken = listening_ports()
    return next((p for p in range(port + 1, 65536) if p not in taken and not connect_probe(p, 0.2)), None)


def port_holder(port, skip_pgid=None):
    """Who holds `port`, as a verdict fragment; None when it is free. Never touches the holder."""
    held = listeners(port)
    if held is None:
        raise Done(2, "error", "· lsof missing or failing: the port cannot be checked (run doctor)")
    held = [h for h in held if skip_pgid is None or h["pgid"] != skip_pgid]
    if held:
        h = held[0]
        who = f"pid {h['pid']} ({h['cmd']}, {tilde(proc_cwd(h['pid']) or '?')})"
    elif skip_pgid is None and connect_probe(port):
        who = "an unlisted (root?) process"
    else:
        return None
    return f"port {port} held by {who} · free: {next_free_port(port) or 'none'}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def http_code(url, timeout=2.0):
    """Status of one GET, no redirects and no proxy; 0 when nothing answers."""
    try:
        with _OPENER.open(url, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        return 0


def lan_ip():
    hook = os.environ.get("TAILNET_PREVIEW_LAN_IP")
    if hook:
        return None if hook == "none" else hook
    ipconfig = tool("ipconfig")
    for iface in ("en0", "en1"):
        rc, out, _ = run([ipconfig, "getifaddr", iface], timeout=5) if ipconfig else (None, "", "")
        if rc == 0 and out.strip():
            return out.strip()
    return None


# ------------------------------------------------------------------ tailscale
def find_tailscale():
    hook = os.environ.get("TAILNET_PREVIEW_TAILSCALE")
    if hook:
        if hook == "none":
            return None, "TAILNET_PREVIEW_TAILSCALE=none"
        if os.access(hook, os.X_OK):
            return hook, "TAILNET_PREVIEW_TAILSCALE"
        return None, f"{tilde(hook)} is not executable"
    found = shutil.which("tailscale")
    if found:
        return found, "PATH"
    if os.access(APP_CLI, os.X_OK):
        return APP_CLI, "app bundle"
    return None, "not on PATH nor in /Applications"


def ts_call(ts, args, timeout=20):
    env = dict(os.environ)
    env["TAILSCALE_BE_CLI"] = "1"
    return run([ts["path"]] + list(args), timeout=timeout, env=env)


def probe_tailscale():
    """Tailscale facts; `ready` only with version >= 1.52, Running, MagicDNS, HTTPS certificates and a DNS name."""
    ts = {"path": None, "source": "", "version": None, "version_ok": False, "ready": False, "absent": False,
          "unparsed": False, "reason": "", "host": "", "status": None}
    ts["path"], ts["source"] = find_tailscale()
    if not ts["path"]:
        ts.update(absent=True, reason=f"tailscale absent (install: {INSTALL})")
        return ts
    rc, out, err = ts_call(ts, ["version"])
    m = re.match(r"\s*(\d+)\.(\d+)(?:\.(\d+))?", out or "")
    if rc != 0 or not m:
        ts["reason"] = f"tailscale version unreadable ({first_line(err or out) or 'no output'})"
        return ts
    ts["version"] = m.group(0).strip()
    ts["version_ok"] = (int(m.group(1)), int(m.group(2))) >= MIN_TAILSCALE
    if not ts["version_ok"]:
        ts["reason"] = f"tailscale {ts['version']} is older than 1.52 (update the app)"
        return ts
    rc, out, err = ts_call(ts, ["status", "--json"])
    if rc is None or (rc != 0 and not out.lstrip().startswith("{")):
        ts["reason"] = f"tailscale not running ({first_line(err or out) or 'no answer'}): open the Tailscale app"
        return ts
    try:
        status = json.loads(out)
    except ValueError:
        status = None
    if not isinstance(status, dict):
        ts.update(unparsed=True, reason="tailscale status --json is not parseable")
        return ts
    ts["status"] = status
    tailnet = as_dict(status.get("CurrentTailnet"))
    certs = status.get("CertDomains") if isinstance(status.get("CertDomains"), list) else []
    ts["host"] = str(as_dict(status.get("Self")).get("DNSName") or "").rstrip(".")
    backend = status.get("BackendState")
    if backend != "Running":
        ts["reason"] = {"NeedsLogin": "tailscale logged out (login: open the Tailscale app and sign in)",
                        "Stopped": "tailscale stopped (connect: open the Tailscale app)"}.get(
            backend, f"tailscale backend {backend or 'unknown'}")
    elif not tailnet.get("MagicDNSEnabled"):
        ts["reason"] = "MagicDNS off (admin console → DNS)"
    elif not certs:
        ts["reason"] = "HTTPS certificates off (admin console → DNS → HTTPS Certificates)"
    elif not ts["host"]:
        ts["reason"] = "no MagicDNS name for this machine"
    else:
        ts["ready"] = True
    return ts


def serve_config(ts):
    """`tailscale serve status --json` as a dict ({} when nothing is served); None when unreadable."""
    rc, out, _ = ts_call(ts, ["serve", "status", "--json"])
    if rc != 0:
        return None
    if not out.strip():
        return {}
    try:
        cfg = json.loads(out)
    except ValueError:
        return None
    return cfg if isinstance(cfg, dict) else None


def proxy_on(cfg, host, https_port):
    handler = as_dict(as_dict(as_dict(as_dict(cfg).get("Web")).get(f"{host}:{https_port}")).get("Handlers")).get("/")
    return as_dict(handler).get("Proxy")


def serve_taken(cfg, https_port):
    return str(https_port) in as_dict(as_dict(cfg).get("TCP"))


def serve_on(ts, https_port, port):
    if not is_int(https_port) or https_port < 1024:
        return 1, "", f"refusing --https={https_port}"
    return ts_call(ts, ["serve", "--bg", "--yes", f"--https={https_port}", target(port)], timeout=45)


def unmap(tn, https_port, port):
    """Removes the mapping on `https_port` when it proxies to our port; True when it is gone afterwards."""
    ts = tn.ts
    if not ts["ready"] or not is_int(https_port) or not is_int(port):
        return False
    cfg = serve_config(ts)
    if cfg is None or proxy_on(cfg, ts["host"], https_port) != target(port):
        return False
    ts_call(ts, ["serve", f"--https={https_port}", "off"], timeout=45)
    cfg = serve_config(ts)
    return cfg is not None and proxy_on(cfg, ts["host"], https_port) is None


def warm_up(url):
    """HTTP code of the tailnet URL through curl (the macOS trust store), allowing 60 s for a new certificate."""
    curl = tool("curl")
    if not curl:
        return "000"
    rc, out, _ = run([curl, "-s", "-o", os.devnull, "-w", "%{http_code}", "--noproxy", "*", "--max-time", "60", url],
                     timeout=75)
    code = (out or "").strip()
    return code if code.isdigit() else "000"


class Tailnet:
    """Tailscale facts probed at most once per command."""

    def __init__(self):
        self._ts = None

    @property
    def ts(self):
        if self._ts is None:
            self._ts = probe_tailscale()
        return self._ts

    def config(self):
        return serve_config(self.ts) if self.ts["ready"] else None


# ------------------------------------------------------------------ node and environment
def nvm_node(cwd):
    """(bin dir, 'vX.Y.Z', note) from <cwd>/.nvmrc: the highest installed version whose leading components equal
    the spec's, compared as integers (20 picks the newest 20.x.y; 20.1 never matches 20.11.0)."""
    try:
        with open(os.path.join(cwd, ".nvmrc"), encoding="utf-8") as fh:
            words = fh.read().split()
    except OSError:
        return None, None, None
    spec = words[0] if words else ""
    digits = spec[1:] if spec[:1] in ("v", "V") else spec
    if not re.fullmatch(r"\d+(\.\d+){0,2}", digits):
        return None, None, f".nvmrc {spec or '(empty)'} ignored (only numeric versions are matched)"
    want = tuple(int(x) for x in digits.split("."))
    root = os.path.join(os.environ.get("NVM_DIR") or os.path.expanduser("~/.nvm"), "versions", "node")
    try:
        names = os.listdir(root)
    except OSError:
        names = []
    best = None
    for name in names:
        m = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", name)
        ver = tuple(int(x) for x in m.groups()) if m else None
        if ver and ver[:len(want)] == want and os.path.isdir(os.path.join(root, name, "bin")) \
                and (best is None or ver > best[0]):
            best = (ver, name)
    if best is None:
        return None, None, f".nvmrc {spec} is not installed under {tilde(root)}"
    return os.path.join(root, best[1], "bin"), "v" + ".".join(str(x) for x in best[0]), None


def env_name_problem(name):
    if not isinstance(name, str) or not ENV_NAME_RE.match(name):
        return f"{name!r} is not an UPPER_CASE environment name"
    if name.startswith(RESERVED):
        return f"{name}: CLAUDE* and ANTHROPIC_* never reach the child"
    if SECRET_TOKENS.intersection(name.split("_")):
        return (f"{name} looks like a secret (a SECRET, TOKEN, PASSWORD, PASS, KEY, AUTH or COOKIE part): "
                "secrets never go in the profile or the child env")
    return None


def child_env(prof, node_bin):
    """Allowlist + --inherit-env names + profile env; nothing else of the session reaches the service."""
    env = {k: v for k, v in os.environ.items() if k in ENV_ALLOW or k.startswith("LC_")}
    env.update((k, os.environ[k]) for k in prof.get("inherit_env") or [] if k in os.environ)
    env.update(prof.get("env") or {})
    env = {k: v for k, v in env.items() if not k.startswith(RESERVED)}
    if node_bin:
        env["PATH"] = node_bin + os.pathsep + env.get("PATH", os.defpath)
    return env


# ------------------------------------------------------------------ state dir and profiles
class StateDir:
    def __init__(self, override):
        base = override or os.environ.get("TAILNET_PREVIEW_HOME") or os.path.join(
            os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "adcm-toolkits", "tailnet-preview")
        self.root = os.path.abspath(os.path.expanduser(base))

    def profile_path(self, slug):
        return os.path.join(self.root, "profiles", f"{slug}.json")

    def run_path(self, slug):
        return os.path.join(self.root, "run", f"{slug}.json")

    def log_path(self, slug):
        return os.path.join(self.root, "logs", f"{slug}.log")

    def read(self, path):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            raise Done(2, "error", f"· unreadable state {tilde(path)} ({exc.__class__.__name__})")
        if not isinstance(data, dict):
            raise Done(2, "error", f"· unreadable state {tilde(path)} (not an object)")
        return data

    def write(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)

    def slugs(self):
        folder = os.path.join(self.root, "profiles")
        try:
            names = os.listdir(folder)
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise Done(2, "error", f"· unreadable state {tilde(folder)} ({exc.strerror})")
        return sorted(n[:-5] for n in names if n.endswith(".json") and SLUG_RE.match(n[:-5]))

    @contextlib.contextmanager
    def lock(self):
        """flock on <state>/.lock around up and down; the spawned children never inherit it (close_fds)."""
        os.makedirs(self.root, mode=0o700, exist_ok=True)
        with open(os.path.join(self.root, ".lock"), "a") as fh:
            deadline = time.monotonic() + 30
            while True:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() > deadline:
                        raise Done(2, "error", f"· another up or down holds {tilde(fh.name)}")
                    time.sleep(0.2)
            yield


def with_defaults(prof, slug):
    prof = dict(prof)
    for key, value in (("slug", slug), ("title", slug), ("env", {}), ("inherit_env", []), ("health", "/"),
                       ("https_port", None), ("https_port_pinned", False), ("timeout", DEFAULT_TIMEOUT),
                       ("reuse", True)):
        prof.setdefault(key, value)
    return prof


def profile_problem(prof, slug, need_cwd):
    cwd, cmd, env, names = prof.get("cwd"), prof.get("cmd"), prof.get("env"), prof.get("inherit_env")
    port, hport, timeout = prof.get("port"), prof.get("https_port"), prof.get("timeout")
    if prof.get("slug") != slug:
        return f"slug {prof.get('slug')!r} is not {slug}"
    if not isinstance(prof.get("title"), str) or not 0 < len(prof["title"]) <= 40:
        return "title must be 1-40 characters"
    if not isinstance(cwd, str) or not os.path.isabs(cwd):
        return "cwd must be an absolute path"
    if need_cwd and not os.path.isdir(cwd):
        return f"cwd {tilde(cwd)} does not exist"
    if not isinstance(cmd, list) or not cmd or not all(isinstance(x, str) for x in cmd) or not cmd[0]:
        return "cmd must be a non-empty argv list (after --)"
    if not isinstance(env, dict) or not all(isinstance(v, str) for v in env.values()):
        return "env must map names to strings"
    if not isinstance(names, list):
        return "inherit_env must be a list of names"
    bad = next((why for why in map(env_name_problem, list(env) + names) if why), None)
    if bad:
        return bad
    if not is_int(port) or not 1024 <= port <= 65535:
        return "port must be 1024-65535"
    if not isinstance(prof.get("health"), str) or not prof["health"].startswith("/"):
        return "health must start with /"
    if hport is not None and (not is_int(hport) or not 1024 <= hport <= 65535 or hport == port):
        return "https_port must be 1024-65535 and differ from port"
    if not is_int(timeout) or not 1 <= timeout <= 1800:
        return "timeout must be 1-1800 seconds"
    if not isinstance(prof.get("reuse"), bool) or not isinstance(prof.get("https_port_pinned"), bool):
        return "reuse and https_port_pinned must be true or false"
    return None


def load_profile(st, slug):
    raw = st.read(st.profile_path(slug))
    if raw is None:
        raise Done(2, "error", f"{slug} · unknown slug (no profile in {tilde(st.root)})")
    prof = with_defaults(raw, slug)
    why = profile_problem(prof, slug, need_cwd=False)
    if why:
        raise Done(2, "error", f"{slug} · invalid profile {tilde(st.profile_path(slug))}: {why}")
    return prof


def merge_profile(slug, saved, a):
    """The saved profile with the CLI flags on top, validated; `changed` when a process-shaping key differs."""
    prof = with_defaults(saved or {}, slug)
    if a.cwd is not None or saved is None:
        prof["cwd"] = a.cwd if a.cwd is not None else os.getcwd()
    if isinstance(prof.get("cwd"), str):
        prof["cwd"] = os.path.realpath(os.path.abspath(os.path.expanduser(prof["cwd"])))
    for key in ("port", "health", "timeout", "title", "reuse"):
        if getattr(a, key) is not None:
            prof[key] = getattr(a, key)
    if a.env:
        prof["env"] = dict(a.env)
    if a.inherit_env:
        prof["inherit_env"] = list(dict.fromkeys(a.inherit_env))
    if a.cmd_argv:
        prof["cmd"] = list(a.cmd_argv)
    if a.https_port is not None:
        prof["https_port"], prof["https_port_pinned"] = a.https_port, True
    missing = [flag for key, flag in (("port", "--port"), ("cmd", "-- CMD")) if not prof.get(key)]
    if missing:
        raise Done(2, "error", f"{slug} · no saved profile: pass {' and '.join(missing)}")
    why = profile_problem(prof, slug, need_cwd=True)
    if why:
        raise Done(2, "error", f"{slug} · invalid profile: {why}")
    base = with_defaults(saved, slug) if saved else None
    return prof, bool(base) and any(base.get(k) != prof.get(k) for k in PROCESS_KEYS)


def shown(prof):
    return dict(prof, cwd=tilde(prof.get("cwd")))


def resolve_slug(st, rep):
    """The one profile whose cwd is the current directory or an ancestor of it."""
    try:
        here = os.path.realpath(os.getcwd())
    except OSError:
        raise Done(2, "error", "· the current directory is gone: pass a SLUG")
    hits = []
    for slug in st.slugs():
        cwd = (st.read(st.profile_path(slug)) or {}).get("cwd")
        if isinstance(cwd, str) and within(here, os.path.realpath(cwd)):
            hits.append((slug, cwd))
    if len(hits) == 1:
        return hits[0][0]
    if not hits:
        rep.add("profiles", ", ".join(st.slugs()) or "none yet")
        raise Done(2, "error", f"· no profile covers {tilde(here)}: pass a SLUG")
    for slug, cwd in hits:
        rep.add("candidate", f"{slug} {tilde(cwd)}")
    raise Done(2, "error", f"· ambiguous slug: {len(hits)} profiles cover {tilde(here)}: pass a SLUG")


def settle_https(st, slug, prof, cfg, host):
    """(https port, note, blocked reason). The profile keeps its port unless the service port, another profile
    or a foreign serve mapping uses it; an auto port then moves to the first free one in 8443-8499 (never one
    that is listened on locally), a pinned one is blocked."""
    others = set()
    for other in st.slugs():
        with contextlib.suppress(Done):
            value = (st.read(st.profile_path(other)) or {}).get("https_port") if other != slug else None
            if is_int(value):
                others.add(value)

    def conflict(n):
        if n == prof["port"]:
            return "equals the service port"
        if n in others:
            return "belongs to another profile"
        proxy = proxy_on(cfg, host, n) if cfg is not None else None
        if proxy is not None and proxy != target(prof["port"]):
            return f"already serves {proxy}"
        if cfg is not None and proxy is None and serve_taken(cfg, n):
            return "is taken by another serve mapping"
        return None

    cur = prof.get("https_port")
    why = conflict(cur) if cur is not None else "unset"
    if why is None:
        return cur, None, None
    if cur is not None and prof["https_port_pinned"]:
        return cur, None, f"https port {cur} {why}"
    local = listening_ports()
    new = next((n for n in HTTPS_POOL if n != cur and n not in local and conflict(n) is None), None)
    if new is None:
        return cur, None, "no free https port in 8443-8499"
    prof["https_port"] = new
    return new, (f"https port {cur} {why}: moved to {new}" if cur is not None else None), None


# ------------------------------------------------------------------ logs
def rotate(log):
    """Rotation happens only here, at up: the running server keeps the file open."""
    with contextlib.suppress(OSError):
        if os.path.getsize(log) > ROTATE_BYTES:
            os.replace(log, log + ".1")


def log_tail(path, count):
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 65536))
            text = fh.read().decode("utf-8", "replace")
    except (OSError, TypeError):
        return []
    lines = text.splitlines()
    start = max((i for i, line in enumerate(lines) if line.startswith("=== up ")), default=-1) + 1
    return [tilde_text(line.rstrip())[:160] for line in lines[start:] if line.strip()][-count:]


# ------------------------------------------------------------------ report
class Report:
    def __init__(self, command, as_json):
        self.as_json = as_json
        self.lines = []
        self.data = {"version": SCHEMA, "command": command, "slug": None, "status": None, "exit": None,
                     "verdict": None, "urls": {"localhost": None, "lan": None, "tailnet": None}, "pid": None,
                     "port": None, "https_port": None, "node": None, "log": None, "problems": [], "profile": None}

    def add(self, label, text=""):
        self.lines.append(f"{label} {text}".rstrip())

    def problem(self, label, text):
        self.add(label, text)
        self.data["problems"].append(text)

    def finish(self, code, word, tail=""):
        verdict = f"{VERDICT} {word}" + (f" {tail}" if tail else "")
        self.data.update(status=word.split(" (")[0], exit=code, verdict=verdict)
        if self.as_json:
            print(json.dumps(self.data, ensure_ascii=False))
        else:
            lines = self.lines
            if len(lines) > MAX_LINES - 1:
                keep = MAX_LINES - 2
                lines = lines[:keep] + [f"… {len(lines) - keep} more lines"]
            print("\n".join(lines + [verdict]))
        return code


# ------------------------------------------------------------------ doctor
def state_dir_check(root):
    """Writability of the state dir, or of its nearest existing parent; creates nothing."""
    probe = root
    while not os.path.exists(probe) and os.path.dirname(probe) != probe:
        probe = os.path.dirname(probe)
    ok = os.path.isdir(probe) and os.access(probe, os.W_OK | os.X_OK)
    where = "exists" if probe == root else f"absent, parent {tilde(probe)}"
    return ok, f"{tilde(root)} ({where}, {'writable' if ok else 'NOT writable'})"


def other_vpns():
    scutil = tool("scutil")
    rc, out, _ = run([scutil, "--nc", "list"], timeout=5) if scutil else (None, "", "")
    names = []
    for line in out.splitlines():
        if "(Connected)" in line and "tailscale" not in line.lower():
            m = re.search(r'"([^"]+)"', line)
            names.append(m.group(1) if m else line.strip()[:60])
    return names


def cmd_doctor(a, rep):
    st = StateDir(a.state_dir)
    checks, fails = [], []

    def check(level, name, detail):
        checks.append({"level": level, "check": name, "detail": detail})
        rep.add(f"{level:<4}", f"{name} {detail}".rstrip())
        if level == "fail":
            fails.append(f"{name} {detail}")

    v = sys.version_info
    check("ok" if v >= (3, 9) else "warn", "python", f"{v.major}.{v.minor}.{v.micro}")
    lsof, caf, ip = tool("lsof"), tool("caffeinate"), lan_ip()
    check("ok" if lsof else "fail", "lsof", tilde(lsof) if lsof else "missing (the port checks need it)")
    check("ok" if caf else "warn", "caffeinate", tilde(caf) if caf else "missing (the Mac may sleep)")
    check("ok" if ip else "warn", "lan ip", ip or "none (no en0/en1 address, or TAILNET_PREVIEW_LAN_IP=none)")
    writable, detail = state_dir_check(st.root)
    check("ok" if writable else "fail", "state dir", detail)
    ts = probe_tailscale()
    if ts["absent"]:
        check("warn", "tailscale", f"absent (install: {INSTALL})")
    else:
        bundle = " (TAILSCALE_BE_CLI=1)" if ts["path"] == APP_CLI else ""
        check("ok", "tailscale", f"{tilde(ts['path'])} ({ts['source']}){bundle}")
        check("ok" if ts["version_ok"] else "warn", "version",
              (ts["version"] + ("" if ts["version_ok"] else " (1.52 or newer needed: update the app)"))
              if ts["version"] else ts["reason"])
    status = ts["status"]
    if ts["unparsed"]:
        check("fail", "status", ts["reason"])
    elif status is None and not ts["absent"] and ts["version"]:
        check("warn", "status", ts["reason"])
    if status is not None:
        tailnet = as_dict(status.get("CurrentTailnet"))
        certs = status.get("CertDomains") if isinstance(status.get("CertDomains"), list) else []
        backend = status.get("BackendState") or "unknown"
        check("ok" if backend == "Running" else "warn", "backend",
              backend + ("" if backend == "Running" else f" · {ts['reason']}"))
        check("ok" if tailnet.get("MagicDNSEnabled") else "warn", "MagicDNS",
              f"on ({tailnet.get('MagicDNSSuffix') or '?'})" if tailnet.get("MagicDNSEnabled") else "off (admin console → DNS)")
        check("ok" if certs else "warn", "HTTPS certificates",
              f"on ({', '.join(str(c) for c in certs[:2])})" if certs else "off (admin console → DNS → HTTPS Certificates)")
        check("ok" if ts["host"] else "warn", "machine", ts["host"] or "no MagicDNS name (Self.DNSName empty)")
        if backend == "Running":
            cfg = serve_config(ts)
            check("ok" if cfg is not None else "fail", "serve status",
                  f"parses ({len(as_dict(cfg.get('Web')))} web mappings)" if cfg is not None else "not parseable")
        peers = [p for p in as_dict(status.get("Peer")).values() if isinstance(p, dict)]
        phones = [p for p in peers if str(p.get("OS", "")).lower() in ("ios", "android")]
        phone = next((p for p in phones if p.get("Online")), phones[0] if phones else None)
        check("info", "phone", f"{phone.get('HostName')} ({phone.get('OS')}, {'online' if phone.get('Online') else 'offline'})"
              if phone else "no iOS or Android device in the tailnet yet")
        for msg in (status.get("Health") if isinstance(status.get("Health"), list) else [])[:3]:
            check("info", "health", str(msg)[:120])
    for name in other_vpns()[:3]:
        check("info", "vpn", f"{name} connected (may compete for 100.64.0.0/10)")
    rep.data["checks"] = checks
    if fails:
        return 2, "error", f"· {fails[0]}"
    if not ts["ready"]:
        return 1, "lan-only", f"· {ts['reason']}"
    if not caf:
        return 1, "lan-only", "· caffeinate missing (the Mac may sleep)"
    return 0, "ready", f"· tailscale {ts['version']} · {ts['host']} · https on"


# ------------------------------------------------------------------ up
def decide(run_state, prof, changed, a):
    if not run_state or not is_ours(run_state):
        return "start"
    if a.restart or not prof["reuse"] or changed:
        return "restart"
    return "reuse" if healthy(http_code(target(prof["port"]) + prof["health"])) else "restart"


def save_run(st, slug, run_state, **changes):
    run_state.update(changes)
    run_state["updated_at"] = now()
    st.write(st.run_path(slug), run_state)


def stop_previous(st, slug, run_state, prof, tn, rep):
    if is_ours(run_state):
        rep.add("stopped", f"previous pid {run_state['pid']} ({stop_group(run_state['pgid'])})")
    elif run_state.get("status") in RUNNING and alive(proc_info(run_state.get("pid"))):
        rep.problem("warn", f"stale pid {run_state['pid']} not ours (not signalled)")
    stop_caffeinate(run_state)
    keep = run_state.get("port") == prof["port"] and run_state.get("https_port") == prof.get("https_port")
    if run_state.get("mapped") and not keep and unmap(tn, run_state.get("https_port"), run_state.get("port")):
        rep.add("note", f"serve :{run_state['https_port']} off (its target changed)")
    save_run(st, slug, run_state, status="stopped", mapped=bool(run_state.get("mapped") and keep))


def spawn(st, slug, prof, node_bin, node_label):
    """Starts the command in its own session with stdio to the log and records `starting` right away, so a
    launcher killed mid-wait still leaves a run state that up and down can match."""
    log = st.log_path(slug)
    os.makedirs(os.path.dirname(log), mode=0o700, exist_ok=True)
    rotate(log)
    with os.fdopen(os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "ab") as fh:
        fh.write(f"=== up {now()} {display_cmd(prof['cmd'])} ===\n".encode("utf-8", "replace"))
        fh.flush()
        try:
            proc = subprocess.Popen(prof["cmd"], cwd=prof["cwd"], env=child_env(prof, node_bin),
                                    stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
                                    start_new_session=True, close_fds=True)
        except OSError as exc:
            fh.write(f"cannot run {prof['cmd'][0]}: {exc}\n".encode("utf-8", "replace"))
            code = 127 if isinstance(exc, FileNotFoundError) else 126
            raise Done(2, f"exited ({code})", f"{slug} · cannot run {prof['cmd'][0]} ({exc.strerror or exc}) · "
                                              f"log {tilde(log)}")
    info = proc_info(proc.pid)
    stamp = now()
    run_state = {"slug": slug, "status": "starting", "pid": proc.pid, "pgid": info["pgid"] if info else proc.pid,
                 "lstart": info["lstart"] if info else None, "lstart_epoch": info["epoch"] if info else None,
                 "caffeinate_pid": None, "caffeinate_lstart_epoch": None, "port": prof["port"],
                 "https_port": prof["https_port"], "tailnet_host": None, "mapped": False, "started_at": stamp,
                 "updated_at": stamp, "log": log, "cmd": prof["cmd"], "cwd": prof["cwd"], "node_bin": node_bin,
                 "node": node_label, "exit_code": None}
    st.write(st.run_path(slug), run_state)
    return proc, run_state


def wait_healthy(proc, prof, wait):
    url = target(prof["port"]) + prof["health"]
    deadline = time.monotonic() + wait
    time.sleep(0.25)
    while True:
        code = proc.poll()
        if code is not None:
            return "exited", code
        if healthy(http_code(url)):
            return "healthy", None
        left = deadline - time.monotonic()
        if left <= 0:
            return "timeout", None
        time.sleep(min(1.0, left))


def failed_start(st, slug, prof, run_state, proc, rep, outcome, code, wait):
    log = run_state["log"]
    hint = outcome == "timeout" and healthy(http_code(f"http://[::1]:{prof['port']}{prof['health']}"))
    stop_group(run_state["pgid"], proc)
    save_run(st, slug, run_state, status="exited" if outcome == "exited" else "unhealthy", exit_code=code)
    if hint:
        rep.add("hint", "answers on ::1 only: bind 127.0.0.1 or 0.0.0.0 (tailscale serve proxies to 127.0.0.1)")
    for line in log_tail(log, 10):
        rep.add("log", line)
    if outcome == "exited":
        raise Done(2, f"exited ({code})", f"{slug} · log {tilde(log)}")
    raise Done(2, "unhealthy", f"{slug} · no answer on 127.0.0.1:{prof['port']}{prof['health']} after {wait}s · "
                               f"log {tilde(log)}")


def map_tailnet(st, slug, prof, run_state, tn, rep, path):
    """(word, tailnet url, reason): makes sure our serve mapping exists, then warms it up."""
    ts = tn.ts
    cfg = serve_config(ts)
    if cfg is None:
        return "lan-only", None, "tailscale serve status unreadable"
    https, note, blocked = settle_https(st, slug, prof, cfg, ts["host"])
    if blocked:
        return "blocked", None, blocked
    if note:
        rep.add("note", note)
        st.write(st.profile_path(slug), prof)
    err = ""
    if proxy_on(cfg, ts["host"], https) != target(prof["port"]):
        rc, out, err = serve_on(ts, https, prof["port"])
        err = first_line(err or out) if rc != 0 else ""
        cfg = serve_config(ts) or {}
    if proxy_on(cfg, ts["host"], https) != target(prof["port"]):
        return "lan-only", None, "tailscale serve failed" + (f": {err}" if err else "")
    old = run_state.get("https_port")
    if run_state.get("mapped") and old != https and unmap(tn, old, prof["port"]):
        rep.add("note", f"serve :{old} off (moved to :{https})")
    run_state.update(mapped=True, tailnet_host=ts["host"], https_port=https)
    code = warm_up(f"https://{ts['host']}:{https}{prof['health']}")
    url = f"https://{ts['host']}:{https}/{path}"
    if code != "200":
        rep.add("note", f"tailnet answered {code}: the first request after a new mapping can take a minute "
                        "while its certificate is issued")
        return "mapped", url, None
    return "up", url, None


def finish_up(st, slug, prof, run_state, a, rep, tn, reused):
    pid, path = run_state["pid"], clean_path(a.path)
    if not caffeinate_ours(run_state):
        run_state.update(start_caffeinate(pid))
    local = f"http://localhost:{prof['port']}/{path}"
    word, url, reason = "lan-only", None, None
    if a.no_serve:
        reason = "--no-serve"
    elif not tn.ts["ready"]:
        reason = f"tailscale absent: install per {INSTALL}" if tn.ts["absent"] else tn.ts["reason"]
    else:
        word, url, reason = map_tailnet(st, slug, prof, run_state, tn, rep, path)
    ip = lan_ip()
    lan = f"http://{ip}:{prof['port']}/{path}" if ip else None
    lan_note = "" if not lan or healthy(http_code(f"http://{ip}:{prof['port']}{prof['health']}")) \
        else " (unreachable: bound to loopback?)"
    save_run(st, slug, run_state, status="unmapped" if word == "blocked" else word)
    caf = run_state.get("caffeinate_pid")
    node = f" · node {run_state['node']} (.nvmrc)" if run_state.get("node") else ""
    log = tilde(run_state.get("log"))
    rep.add("service", f"{slug} · pid {pid}{' · already up' if reused else ''}{node} · log {log}")
    rep.add("awake", f"caffeinate pid {caf} (-i -s -w)" if caf else "caffeinate missing: the Mac may sleep")
    rep.add("localhost", local)
    rep.add("lan", (lan + lan_note) if lan else "-")
    rep.add("tailnet", url or "-")
    rep.data.update(pid=pid, https_port=prof.get("https_port"), log=log, node=tilde(run_state.get("node_bin")),
                    urls={"localhost": local, "lan": lan, "tailnet": url})
    if word == "up":
        return 0, "up", f"{slug} · {url}"
    if word == "mapped":
        return 1, "mapped", f"{slug} · {url} (not answering yet)"
    if word == "blocked":
        return 2, "blocked", f"{slug} · {reason} (the service keeps running: down {slug} --apply stops it)"
    return 1, "lan-only", f"{slug} · {local} ({reason})"


def plan_up(st, slug, prof, changed, a, rep, tn, node_label):
    run_state = st.read(st.run_path(slug))
    decision = decide(run_state, prof, changed, a)
    cfg, host = (None, "") if a.no_serve else (tn.config(), tn.ts["host"])
    https, note, blocked = settle_https(st, slug, prof, cfg, host)
    rep.data.update(https_port=https, urls={"localhost": f"http://localhost:{prof['port']}/", "lan": None,
                                             "tailnet": None})
    rep.add("plan", f"would-{decision} {slug} · cwd {tilde(prof['cwd'])} · port {prof['port']} · health "
                    f"{prof['health']} · https {https} · wait {min(prof['timeout'], WAIT_CAP)}s · "
                    f"reuse {'on' if prof['reuse'] else 'off'}")
    rep.add("cmd", display_cmd(prof["cmd"]))
    if node_label:
        rep.add("node", f"{node_label} (.nvmrc)")
    if note:
        rep.add("note", note)
    if blocked:
        rep.problem("warn", f"{blocked}: --apply would be blocked")
    if decision != "reuse":
        holder = port_holder(prof["port"], run_state.get("pgid") if decision == "restart" else None)
        if holder:
            rep.problem("warn", f"{holder}: --apply would be blocked")
    if a.no_serve or not tn.ts["ready"]:
        rep.add("tailnet", f"- · {'--no-serve' if a.no_serve else tn.ts['reason']}")
    else:
        rep.add("tailnet", f"https://{host}:{https}/")
    return 1, f"would-{decision}", f"{slug} (dry run: add --apply)"


def apply_up(st, slug, prof, changed, a, rep, tn, node_bin, node_label):
    run_state = st.read(st.run_path(slug))
    if decide(run_state, prof, changed, a) == "reuse":
        st.write(st.profile_path(slug), prof)
        return finish_up(st, slug, prof, run_state, a, rep, tn, reused=True)
    if run_state:
        stop_previous(st, slug, run_state, prof, tn, rep)
    holder = port_holder(prof["port"])
    if holder:
        raise Done(2, "blocked", f"{slug} · {holder}")
    cfg, host = (None, "") if a.no_serve else (tn.config(), tn.ts["host"])
    _, note, blocked = settle_https(st, slug, prof, cfg, host)
    if blocked:
        raise Done(2, "blocked", f"{slug} · {blocked}")
    if note:
        rep.add("note", note)
    st.write(st.profile_path(slug), prof)
    proc, run_state = spawn(st, slug, prof, node_bin, node_label)
    rep.data.update(pid=proc.pid, log=tilde(run_state["log"]))
    wait = min(prof["timeout"], WAIT_CAP)
    outcome, code = wait_healthy(proc, prof, wait)
    if outcome != "healthy":
        failed_start(st, slug, prof, run_state, proc, rep, outcome, code, wait)
    held = listeners(prof["port"])
    foreign = [h for h in held or [] if h["pgid"] != run_state["pgid"]]
    if held is None:
        rep.problem("warn", f"lsof failed: the listener on port {prof['port']} could not be matched to our group")
    elif foreign or not held:
        stop_group(run_state["pgid"], proc)
        save_run(st, slug, run_state, status="blocked")
        who = f"pid {foreign[0]['pid']} ({foreign[0]['cmd']})" if foreign else "an unlisted (root?) process"
        raise Done(2, "blocked", f"{slug} · foreign listener: {who} answers on port {prof['port']}, "
                                 "not our process group")
    return finish_up(st, slug, prof, run_state, a, rep, tn, reused=False)


def cmd_up(a, rep):
    st = StateDir(a.state_dir)
    slug = a.slug or resolve_slug(st, rep)
    rep.data["slug"] = slug
    prof, changed = merge_profile(slug, st.read(st.profile_path(slug)), a)
    rep.data.update(port=prof["port"], profile=shown(prof))
    if prof["timeout"] > WAIT_CAP:
        rep.add("note", f"timeout capped at {WAIT_CAP} (Bash tool limit)")
    node_bin, node_label, node_note = nvm_node(prof["cwd"])
    if node_note:
        rep.problem("warn", node_note)
    rep.data["node"] = tilde(node_bin)
    tn = Tailnet()
    if not a.apply:
        return plan_up(st, slug, prof, changed, a, rep, tn, node_label)
    with st.lock():
        return apply_up(st, slug, prof, changed, a, rep, tn, node_bin, node_label)


# ------------------------------------------------------------------ status, url, list
def observe(prof, run_state, tn, listening=None):
    """The state word of one profile: up, lan-only, unmapped, unhealthy, starting, stale, foreign-port, stopped."""
    run_state = run_state or {}
    port = run_state.get("port") or prof["port"]
    https = run_state.get("https_port") or prof.get("https_port")
    o = {"state": "stopped", "pid": None, "port": port, "https_port": https, "tailnet": None, "detail": ""}
    if is_ours(run_state):
        o["pid"] = run_state["pid"]
        if not healthy(http_code(target(port) + prof["health"])):
            o["state"] = "starting" if run_state.get("status") == "starting" else "unhealthy"
            o["detail"] = f"no answer on 127.0.0.1:{port}{prof['health']}"
        elif not tn.ts["ready"]:
            o.update(state="lan-only", detail=tn.ts["reason"])
        elif proxy_on(tn.config() or {}, tn.ts["host"], https) == target(port):
            o.update(state="up", tailnet=f"https://{tn.ts['host']}:{https}/")
        else:
            o.update(state="unmapped", detail=f"no serve mapping on :{https}")
        return o
    recorded = run_state.get("status") in RUNNING or bool(run_state.get("mapped"))
    holder = None
    if recorded and alive(proc_info(run_state.get("pid"))):
        o.update(state="stale", detail=f"pid {run_state['pid']} is not ours any more (pid reused): never signalled")
        return o
    if listening is not None:
        holder = f"port {port} is held by another process" if port in listening else None
    else:
        holder = port_holder(port)
    if holder:
        o.update(state="foreign-port", detail=holder)
    elif recorded:
        o.update(state="stale", detail=f"pid {run_state.get('pid')} is gone"
                                       + (f"; serve :{https} still mapped" if run_state.get("mapped") else ""))
    return o


def cmd_status(a, rep):
    st = StateDir(a.state_dir)
    slug = a.slug or resolve_slug(st, rep)
    rep.data["slug"] = slug
    prof = load_profile(st, slug)
    run_state = st.read(st.run_path(slug)) or {}
    o = observe(prof, run_state, Tailnet())
    live = o["pid"] is not None
    ip = lan_ip() if live else None
    local = f"http://localhost:{o['port']}/" if live else None
    lan = f"http://{ip}:{o['port']}/" if ip else None
    rep.data.update(profile=shown(prof), port=o["port"], https_port=o["https_port"], pid=o["pid"],
                    log=tilde(run_state.get("log")), node=tilde(run_state.get("node_bin")),
                    urls={"localhost": local, "lan": lan, "tailnet": o["tailnet"]})
    if live:
        rep.add("service", f"{slug} · pid {o['pid']} · port {o['port']} → https {o['https_port']} · started "
                           f"{run_state.get('started_at')} · log {tilde(run_state.get('log'))}")
    else:
        rep.add("service", f"{slug} · not running")
    for label, url in (("localhost", local), ("lan", lan), ("tailnet", o["tailnet"])):
        rep.add(label, url or "-")
    if o["detail"]:
        rep.add("note", o["detail"])
    if o["state"] in ("unhealthy", "starting", "stale", "foreign-port") or run_state.get("status") in FAILED:
        for line in log_tail(run_state.get("log"), 5):
            rep.add("log", line)
    shown_url = {"up": o["tailnet"], "lan-only": local, "unmapped": local}.get(o["state"])
    tail = f"{slug} · {shown_url or o['detail']}" if (shown_url or o["detail"]) else slug
    return (0 if o["state"] == "up" else 1), o["state"], tail


def cmd_url(a, rep):
    st = StateDir(a.state_dir)
    slug = a.slug or resolve_slug(st, rep)
    rep.data["slug"] = slug
    prof = load_profile(st, slug)
    run_state = st.read(st.run_path(slug)) or {}
    rep.data.update(profile=shown(prof), port=run_state.get("port") or prof["port"],
                    https_port=run_state.get("https_port") or prof.get("https_port"))
    if not is_ours(run_state):
        for label in ("localhost", "lan", "tailnet"):
            rep.add(label, "-")
        return 1, "stale" if run_state.get("status") in RUNNING else "stopped", f"{slug} · not running"
    port, path, ip = run_state["port"], clean_path(a.path), lan_ip()
    mapped = run_state.get("mapped") and run_state.get("tailnet_host")
    urls = {"localhost": f"http://localhost:{port}/{path}", "lan": f"http://{ip}:{port}/{path}" if ip else None,
            "tailnet": f"https://{run_state['tailnet_host']}:{run_state['https_port']}/{path}" if mapped else None}
    for label, url in urls.items():
        rep.add(label, url or "-")
    rep.data.update(urls=urls, pid=run_state["pid"], log=tilde(run_state.get("log")))
    if urls["tailnet"]:
        return 0, "up", f"{slug} · {urls['tailnet']}"
    return 1, "lan-only", f"{slug} · {urls['localhost']}"


def cmd_list(a, rep):
    st = StateDir(a.state_dir)
    slugs = st.slugs()
    rep.data["profiles"] = []
    if not slugs:
        rep.add("list", "no profiles")
        return 0, "list", "· no profiles"
    tn, listening, bad = Tailnet(), listening_ports(), 0
    for slug in slugs:
        try:
            prof = load_profile(st, slug)
            o = observe(prof, st.read(st.run_path(slug)), tn, listening)
        except Done as exc:
            bad += 1
            rep.add(slug, f"unreadable ({exc.tail.lstrip('· ')})")
            continue
        rep.add(slug, f"{o['state']} {o['port']}→{o['https_port'] or '-'} {tilde(prof['cwd'])}")
        rep.data["profiles"].append({"slug": slug, "state": o["state"], "port": o["port"],
                                     "https_port": o["https_port"], "cwd": tilde(prof["cwd"])})
    if bad:
        return 2, "error", f"· {bad} unreadable profile(s) in {tilde(st.root)}"
    return 0, "list", f"· {len(slugs)} profile{'s' if len(slugs) != 1 else ''}"


# ------------------------------------------------------------------ down
def down_plan(st, slug, keep_serve):
    run_state = st.read(st.run_path(slug)) or {}
    if is_ours(run_state):
        what = f"TERM pgid {run_state['pgid']} (pid {run_state['pid']}), KILL after 10s, stop caffeinate"
    elif run_state.get("status") in RUNNING and alive(proc_info(run_state.get("pid"))):
        what = f"pid {run_state['pid']} is not ours: never signalled"
    else:
        what = "nothing running"
    if run_state.get("mapped"):
        what += f" · serve :{run_state.get('https_port')} " + ("kept" if keep_serve else "off")
    return f"{slug} · {what}"


def down_one(st, slug, keep_serve, tn, rep):
    run_state = st.read(st.run_path(slug))
    if run_state is None:
        return "already stopped"
    if is_ours(run_state):
        how = stop_group(run_state["pgid"])
        left = [h for h in (listeners(run_state.get("port")) or []) if h["pgid"] == run_state["pgid"]]
        if left:
            rep.problem("warn", f"{slug}: a listener of pgid {run_state['pgid']} survived ({how})")
        parts = [f"stopped pid {run_state['pid']}"]
    elif run_state.get("status") in RUNNING and alive(proc_info(run_state.get("pid"))):
        parts = [f"stale pid {run_state['pid']} not ours (not signalled)"]
    else:
        parts = ["already stopped"]
    stop_caffeinate(run_state)
    if keep_serve:
        if run_state.get("mapped"):
            parts.append(f"serve :{run_state.get('https_port')} kept")
    elif unmap(tn, run_state.get("https_port"), run_state.get("port")):
        parts.append(f"serve :{run_state['https_port']} off")
        run_state["mapped"] = False
    save_run(st, slug, run_state, status="stopped")
    return " · ".join(parts)


def cmd_down(a, rep):
    st = StateDir(a.state_dir)
    if a.all and a.slug:
        raise Usage("pass a SLUG or --all, not both")
    slugs = st.slugs() if a.all else [a.slug or resolve_slug(st, rep)]
    name = "all" if a.all else slugs[0]
    rep.data["slug"] = None if a.all else name
    if not a.all and st.read(st.profile_path(name)) is None and st.read(st.run_path(name)) is None:
        raise Done(2, "error", f"{name} · unknown slug (no profile in {tilde(st.root)})")
    if not slugs:
        rep.add("plan" if not a.apply else "down", "no profiles")
        return (0, "down", "all · no profiles") if a.apply else (1, "would-stop", "all (dry run: add --apply)")
    if not a.apply:
        for slug in slugs:
            rep.add("plan", down_plan(st, slug, a.keep_serve))
        return 1, "would-stop", f"{name} (dry run: add --apply)"
    tn = Tailnet()
    with st.lock():
        results = [(slug, down_one(st, slug, a.keep_serve, tn, rep)) for slug in slugs]
    rep.data["results"] = [{"slug": s, "result": r} for s, r in results]
    if not a.all:
        return 0, "down", f"{name} · {results[0][1]}"
    for slug, result in results:
        rep.add("down", f"{slug} · {result}")
    stopped = sum(1 for _, r in results if r.startswith("stopped"))
    return 0, "down", f"all · {len(results)} profile{'s' if len(results) != 1 else ''} · {stopped} stopped"


# ------------------------------------------------------------------ CLI
def _ranged(lo, hi, flag):
    def conv(text):
        try:
            value = int(text, 10)
        except ValueError:
            raise argparse.ArgumentTypeError(f"{flag} wants an integer {lo}-{hi}, got {text!r}")
        if not lo <= value <= hi:
            raise argparse.ArgumentTypeError(f"{flag} must be {lo}-{hi}, got {value}")
        return value
    return conv


def _slug(text):
    if not SLUG_RE.match(text):
        raise argparse.ArgumentTypeError(f"bad slug {text!r} (lowercase letters, digits and dashes, 1-40)")
    return text


def _env(text):
    name, sep, value = text.partition("=")
    if not sep:
        raise argparse.ArgumentTypeError(f"--env wants KEY=VAL, got {text!r}")
    why = env_name_problem(name)
    if why:
        raise argparse.ArgumentTypeError(why)
    return name, value


def _inherit(text):
    why = env_name_problem(text)
    if why:
        raise argparse.ArgumentTypeError(why)
    return text


def _health(text):
    if not text.startswith("/"):
        raise argparse.ArgumentTypeError(f"--health must start with /, got {text!r}")
    return text


def _title(text):
    if not 0 < len(text) <= 40:
        raise argparse.ArgumentTypeError("--title must be 1-40 characters")
    return text


def build_parser():
    root = Parser(prog="tailnet-preview", add_help=False, allow_abbrev=False)
    sub = root.add_subparsers(dest="command", parser_class=Parser)

    def command(name, text):
        sp = sub.add_parser(name, help=text, description=text, allow_abbrev=False)
        sp.add_argument("--json", action="store_true", help="print one JSON object instead of text")
        sp.add_argument("--state-dir", help="state dir (default $TAILNET_PREVIEW_HOME or "
                                            "${XDG_STATE_HOME:-~/.local/state}/adcm-toolkits/tailnet-preview)")
        return sp

    command("doctor", "check python, lsof, caffeinate, the LAN IP, the state dir and Tailscale")
    up = command("up", "start or reuse the preview, detached, and map it with tailscale serve")
    up.add_argument("slug", nargs="?", type=_slug)
    up.add_argument("--cwd", help="project directory (default: the saved one, or the current directory)")
    up.add_argument("--port", type=_ranged(1024, 65535, "--port"), help="service port; never shifted")
    up.add_argument("--health", type=_health, help="path that must answer 200-399 (default /)")
    up.add_argument("--https-port", type=_ranged(1024, 65535, "--https-port"),
                    help="pin the tailnet https port (default: first free in 8443-8499, kept per slug)")
    up.add_argument("--timeout", type=_ranged(1, 1800, "--timeout"), help="health wait in s (capped at 420)")
    up.add_argument("--env", action="append", type=_env, default=[], metavar="KEY=VAL",
                    help="routing env for the child (secret-like names refused)")
    up.add_argument("--inherit-env", action="append", type=_inherit, default=[], metavar="NAME",
                    help="pass this variable of the current environment through")
    up.add_argument("--title", type=_title, help="label for the courier's preview lines (max 40)")
    reuse = up.add_mutually_exclusive_group()
    reuse.add_argument("--reuse", dest="reuse", action="store_true", help="keep a healthy instance (default)")
    reuse.add_argument("--no-reuse", dest="reuse", action="store_false", help="restart on every up")
    up.set_defaults(reuse=None)
    up.add_argument("--restart", action="store_true", help="restart this time")
    up.add_argument("--no-serve", action="store_true", help="do not map it with tailscale serve")
    up.add_argument("--path", default="", help="append this path to the printed URLs")
    up.add_argument("--apply", action="store_true", help="really do it (otherwise print the plan)")
    status = command("status", "state of one profile")
    status.add_argument("slug", nargs="?", type=_slug)
    url = command("url", "the localhost, lan and tailnet URLs of a running profile")
    url.add_argument("slug", nargs="?", type=_slug)
    url.add_argument("--path", default="", help="append this path to the URLs")
    down = command("down", "stop a profile (process group, caffeinate, serve mapping)")
    down.add_argument("slug", nargs="?", type=_slug)
    down.add_argument("--all", action="store_true", help="every profile")
    down.add_argument("--keep-serve", action="store_true", help="leave the tailscale serve mapping")
    down.add_argument("--apply", action="store_true", help="really do it (otherwise print the plan)")
    command("list", "one line per profile")
    return root


HANDLERS = {"doctor": cmd_doctor, "up": cmd_up, "status": cmd_status, "url": cmd_url, "down": cmd_down,
            "list": cmd_list}


def usage_exit(message, command, as_json):
    if as_json:
        return Report(command, True).finish(64, "usage", f"· {message}")
    sys.stderr.write(USAGE + "\n")
    sys.stderr.flush()
    print(f"{VERDICT} usage · {message}")
    return 64


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(encoding="utf-8", errors="replace")
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd_argv, dashdash = [], "--" in argv
    if dashdash:
        cut = argv.index("--")
        argv, cmd_argv = argv[:cut], argv[cut + 1:]
    as_json = "--json" in argv
    if argv[:1] in (["-h"], ["--help"]):
        print(HELP)
        return 0
    if argv == ["--version"]:
        print(f"tailnet_preview.py schema {SCHEMA}")
        return 0
    command = argv[0] if argv and argv[0] in COMMANDS else None
    try:
        args = build_parser().parse_args(argv)
        if args.command is None:
            raise Usage("missing command")
        if dashdash and args.command != "up":
            raise Usage("-- CMD is only for up")
        if dashdash and not cmd_argv:
            raise Usage("nothing after --")
    except Usage as exc:
        return usage_exit(str(exc), command, as_json)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 0
    args.cmd_argv = cmd_argv
    rep = Report(args.command, args.json)
    try:
        code, word, tail = HANDLERS[args.command](args, rep)
    except Usage as exc:
        return usage_exit(str(exc), args.command, as_json)
    except Done as exc:
        code, word, tail = exc.code, exc.word, exc.tail
    except OSError as exc:
        code, word, tail = 2, "error", f"· {exc.__class__.__name__}: {tilde_text(str(exc))}"
    except Exception as exc:  # the verdict stays the last line even on a bug
        code, word, tail = 2, "error", f"· internal error {exc!r}"
    return rep.finish(code, word, tail)


if __name__ == "__main__":
    sys.exit(main())
