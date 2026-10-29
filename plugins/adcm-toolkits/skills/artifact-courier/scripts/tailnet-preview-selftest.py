#!/usr/bin/env python3
"""tailnet-preview-selftest - behavioural tests for tailnet_preview.py and bin/tailnet-preview (stdlib only).

Usage:
  python3 tailnet-preview-selftest.py [--script PATH] [--only NAME] [--keep]

Hermetic: every case gets a throwaway temp root (HOME and TAILNET_PREVIEW_HOME point inside it, the LAN IP hook
is `none`) and a scratch PATH whose first folder holds three fakes written as Python scripts:
  - `tailscale` (selected through TAILNET_PREVIEW_TAILSCALE): reads and writes <root>/ts.json (modes ready,
    logged-out, https-off, magicdns-off, defensive, garbage; Self.DNSName acme-mac.tail0000.ts.net.), implements
    version, status --json, serve status --json, serve --bg --yes --https=N <target> and serve --https=N off, and
    logs every call with its TAILSCALE_BE_CLI value;
  - `curl`: resolves https://acme-mac.tail0000.ts.net:N/... through ts.json to the proxy target and fetches it
    (`warm: false` in ts.json makes it print 000);
  - `caffeinate`: waits on its -w pid.
lsof and ps are the real ones. The service is `python3 -m http.server` on a free loopback port, or a small fixture
server when a case needs the child's environment, a slow start or a crash. No real tailscale call, no network
beyond the loopback. Every case ends with the launcher's own `down --all --apply`; a process it started that is
still alive afterwards (matched by pgid and start time) is a FAIL.

Prints `PASS|FAIL|SKIP <case> [- why]` per case and `N/N passed` last; exit 1 when any case FAILs. Without lsof
(non-macOS) the cases that need it SKIP. --keep leaves the temp roots on disk.
"""
import argparse
import ast
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
PLUGIN = os.path.dirname(os.path.dirname(SKILL))
BIN = os.path.join(PLUGIN, "bin", "tailnet-preview")
TWIN = os.path.join(PLUGIN, "bin", "renovate-check")
DOC = os.path.join(SKILL, "references", "tailnet-preview.md")
HOST = "acme-mac.tail0000.ts.net"
VERDICT = "TAILNET-PREVIEW:"
ABSENT = "TAILNET-PREVIEW: lan-only · tailscale absent (install: references/tailnet-preview.md §1)"
EXEC_LINE = 'exec python3 -B "$root/skills/artifact-courier/scripts/tailnet_preview.py" "$@"'
HELP_FLAGS = ("--apply", "--https-port", "--inherit-env", "--no-serve", "--keep-serve", "--restart")
JSON_KEYS = {"version", "command", "slug", "status", "exit", "verdict", "urls", "pid", "port", "https_port", "node",
             "log", "problems", "profile"}
USERS = re.compile("/Us" + "ers/")
CONFIG_DIR = re.compile(re.escape("claude" + "-" + "personal"), re.I)
CT_WORD = re.compile(r"\b" + "led" + "ger" + r"\b", re.I)
DOTDOT = "." + "./"

FAKE_TAILSCALE = r'''#!@PY@
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST = "acme-mac.tail0000.ts.net"
argv = sys.argv[1:]
with open(os.path.join(ROOT, "ts-calls.jsonl"), "a") as fh:
    fh.write(json.dumps({"argv": argv, "be_cli": os.environ.get("TAILSCALE_BE_CLI")}) + "\n")
with open(os.path.join(ROOT, "ts.json")) as fh:
    st = json.load(fh)
mode = st.get("mode", "ready")


def save():
    with open(os.path.join(ROOT, "ts.json"), "w") as fh:
        json.dump(st, fh)


def status():
    me = {"HostName": "acme-mac", "DNSName": HOST + ".", "OS": "macOS", "Online": True, "TailscaleIPs": ["100.64.0.1"]}
    doc = {"BackendState": "Running", "Self": me, "CertDomains": [HOST], "Health": [],
           "CurrentTailnet": {"Name": "acme.example", "MagicDNSSuffix": "tail0000.ts.net", "MagicDNSEnabled": True},
           "Peer": {"nodekey:1": {"HostName": "acme-phone", "DNSName": "acme-phone.tail0000.ts.net.", "OS": "iOS",
                                  "Online": True}}}
    if mode == "logged-out":
        doc.update(BackendState="NeedsLogin", CurrentTailnet=None, Health=["You are logged out."], Peer={})
        doc["Self"] = dict(me, DNSName="")
        del doc["CertDomains"]
    elif mode == "https-off":
        del doc["CertDomains"]
    elif mode == "magicdns-off":
        doc["CurrentTailnet"]["MagicDNSEnabled"] = False
        del doc["CertDomains"]
    elif mode == "defensive":
        doc["CurrentTailnet"] = None
        doc["Self"] = dict(me, DNSName="")
        del doc["CertDomains"]
    return doc


if argv[:1] == ["version"]:
    print(st.get("version", "1.104.2"))
    print("  tailscale commit: 0000000")
    sys.exit(0)
if argv == ["status", "--json"]:
    print("this is not json" if mode == "garbage" else json.dumps(status()))
    sys.exit(0)
if argv == ["serve", "status", "--json"]:
    print(json.dumps(st.get("serve") or {}))
    sys.exit(0)
if argv[:1] == ["serve"]:
    flags = [a for a in argv[1:] if a.startswith("--")]
    rest = [a for a in argv[1:] if not a.startswith("--")]
    https = [a.split("=", 1)[1] for a in flags if a.startswith("--https=")]
    if len(https) == 1 and https[0].isdigit():
        port, cfg = https[0], st.setdefault("serve", {})
        key = HOST + ":" + port
        if rest == ["off"]:
            cfg.get("TCP", {}).pop(port, None)
            cfg.get("Web", {}).pop(key, None)
            save()
            sys.exit(0)
        if len(rest) == 1 and "--bg" in flags and "--yes" in flags:
            cfg.setdefault("TCP", {})[port] = {"HTTPS": True}
            cfg.setdefault("Web", {})[key] = {"Handlers": {"/": {"Proxy": rest[0]}}}
            save()
            sys.exit(0)
sys.stderr.write("fake tailscale: unsupported call: " + " ".join(argv) + "\n")
sys.exit(1)
'''

FAKE_CURL = r'''#!@PY@
import json, os, re, sys, urllib.error, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
argv = sys.argv[1:]
with open(os.path.join(ROOT, "curl-calls.jsonl"), "a") as fh:
    fh.write(json.dumps(argv) + "\n")
with open(os.path.join(ROOT, "ts.json")) as fh:
    st = json.load(fh)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def code_of(url):
    m = re.match(r"https://acme-mac\.tail0000\.ts\.net:(\d+)(/.*)?$", url)
    if not m or st.get("warm") is False:
        return 0
    web = (st.get("serve") or {}).get("Web") or {}
    site = web.get("acme-mac.tail0000.ts.net:" + m.group(1)) or {}
    proxy = ((site.get("Handlers") or {}).get("/") or {}).get("Proxy")
    if not proxy:
        return 0
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(proxy.rstrip("/") + (m.group(2) or "/"), timeout=5) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, OSError):
        return 0


code = code_of(argv[-1] if argv else "")
sys.stdout.write("%03d" % code)
sys.exit(0 if code else 7)
'''

FAKE_CAFFEINATE = r'''#!@PY@
import json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
argv = sys.argv[1:]
with open(os.path.join(ROOT, "caffeinate-calls.jsonl"), "a") as fh:
    fh.write(json.dumps(argv) + "\n")
pid = int(argv[argv.index("-w") + 1]) if "-w" in argv else 0
end = time.time() + 600
while pid and time.time() < end:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        break
    except PermissionError:
        pass
    time.sleep(0.2)
'''

FIXTURE_SERVER = r'''import http.server, json, os, sys, time
args = sys.argv[1:]
port = int(args[0])
opts = dict(zip(args[1::2], args[2::2]))
if "--env-out" in opts:
    with open(opts["--env-out"], "w") as fh:
        json.dump(dict(os.environ), fh)
print("fixture booting on", port, flush=True)
time.sleep(float(opts.get("--delay", "0")))


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/__exit":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"bye")
            self.wfile.flush()
            os._exit(0)
        return super().do_GET()


http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
'''


class Skip(Exception):
    pass


class Check:
    def __init__(self):
        self.problems = []

    def ok(self, cond, what):
        if not cond:
            self.problems.append(what)
        return cond

    def eq(self, got, want, what):
        if got != want:
            self.problems.append(f"{what}: got {got!r}, want {want!r}")
        return got == want

    def has(self, hay, needle, what):
        if needle not in (hay or ""):
            self.problems.append(f"{what}: {needle!r} not in {(hay or '')[-220:]!r}")


class R:
    def __init__(self, rc, out, err):
        self.rc, self.out, self.err = rc, out, err
        self.lines = out.splitlines()
        self.last = self.lines[-1] if self.lines else ""

    def __repr__(self):
        return f"rc={self.rc} out={self.out[-300:]!r} err={self.err[-200:]!r}"


# ------------------------------------------------------------------ harness helpers
def lsof_present():
    return shutil.which("lsof") or os.access("/usr/sbin/lsof", os.X_OK)


def need_lsof():
    if not lsof_present():
        raise Skip("lsof not available")


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def http_code(port, path="/"):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}{path}", timeout=3) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, OSError):
        return 0


def port_open(port):
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def ps_fields(pid):
    """(pgid, stat, C-locale lstart) of a pid, or None."""
    if not pid:
        return None
    env = dict(os.environ, LC_ALL="C", LANG="C")
    p = subprocess.run(["ps", "-o", "pgid=", "-o", "stat=", "-o", "lstart=", "-p", str(pid)], capture_output=True,
                       text=True, env=env)
    parts = p.stdout.split()
    if p.returncode != 0 or len(parts) < 7:
        return None
    return int(parts[0]), parts[1], " ".join(parts[2:7])


def pid_alive(pid):
    info = ps_fields(pid)
    return info is not None and not info[1].startswith("Z")


def group_alive(pgid):
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def wait_until(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def serve_cmd(port):
    return [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"]


def find_up(*parts):
    d = HERE
    while True:
        cand = os.path.join(d, *parts)
        if os.path.isfile(cand):
            return cand
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def hook_regexes():
    """PRIVATE_CI (case-insensitive) and PRIVATE_CS lists from the repo's pre-push hook, when present."""
    hook = find_up(".git", "hooks", "pre-push")
    if hook is None:
        return []
    try:
        tree = ast.parse(open(hook, encoding="utf-8").read())
    except (OSError, SyntaxError, ValueError):
        return []
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in ("PRIVATE_CI", "PRIVATE_CS")
                                                for t in node.targets):
            name = node.targets[0].id
            for pat in ast.literal_eval(node.value):
                found.append(re.compile(pat, re.I if name == "PRIVATE_CI" else 0))
    return found


class Ctx:
    def __init__(self, root, script):
        self.root, self.script = root, script
        self.bin = os.path.join(root, "bin")
        self.state = os.path.join(root, "state")
        self.site = os.path.join(root, "site")
        self.fixture = os.path.join(root, "fixture_server.py")
        os.makedirs(self.bin)
        os.makedirs(self.site)
        with open(os.path.join(self.site, "index.html"), "w") as fh:
            fh.write("<!doctype html><title>acme</title>ok\n")
        with open(self.fixture, "w") as fh:
            fh.write(FIXTURE_SERVER)
        for name, body in (("tailscale", FAKE_TAILSCALE), ("curl", FAKE_CURL), ("caffeinate", FAKE_CAFFEINATE)):
            path = os.path.join(self.bin, name)
            with open(path, "w") as fh:
                fh.write(body.replace("@PY@", sys.executable))
            os.chmod(path, 0o755)
        self.write_ts({"mode": "ready", "version": "1.104.2", "serve": {}})
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("TAILNET_PREVIEW_")}
        self.env.pop("XDG_STATE_HOME", None)
        self.env.update(PATH=self.bin + os.pathsep + os.environ.get("PATH", os.defpath), HOME=root,
                        TAILNET_PREVIEW_HOME=self.state, TAILNET_PREVIEW_LAN_IP="none",
                        TAILNET_PREVIEW_TAILSCALE=os.path.join(self.bin, "tailscale"), NVM_DIR=os.path.join(root, "nvm"),
                        PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
        self.helpers = []

    # -- running the launcher
    def env_for(self, env=None, tailscale=None):
        e = dict(self.env)
        if tailscale is not None:
            e["TAILNET_PREVIEW_TAILSCALE"] = tailscale
        for key, value in (env or {}).items():
            if value is None:
                e.pop(key, None)
            else:
                e[key] = value
        return e

    def run(self, *args, env=None, cwd=None, tailscale=None, timeout=120):
        p = subprocess.run([sys.executable, "-B", self.script] + [str(a) for a in args], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", env=self.env_for(env, tailscale),
                           cwd=cwd or self.root, timeout=timeout)
        return R(p.returncode, p.stdout, p.stderr)

    def up(self, slug, port, *flags, cmd=None, **kw):
        return self.run("up", slug, "--cwd", self.site, "--port", port, *flags, "--apply", "--",
                        *(cmd or serve_cmd(port)), **kw)

    def dry(self, slug, port, *flags, cmd=None, **kw):
        return self.run("up", slug, "--cwd", self.site, "--port", port, *flags, "--", *(cmd or ["true"]), **kw)

    # -- fake tailscale state
    def ts(self):
        with open(os.path.join(self.root, "ts.json")) as fh:
            return json.load(fh)

    def write_ts(self, data):
        with open(os.path.join(self.root, "ts.json"), "w") as fh:
            json.dump(data, fh)

    def set_ts(self, **changes):
        data = self.ts()
        data.update(changes)
        self.write_ts(data)

    def proxy(self, https_port):
        site = ((self.ts().get("serve") or {}).get("Web") or {}).get(f"{HOST}:{https_port}") or {}
        return ((site.get("Handlers") or {}).get("/") or {}).get("Proxy")

    def jsonl(self, name):
        path = os.path.join(self.root, name)
        if not os.path.exists(path):
            return []
        with open(path) as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def ts_calls(self):
        return self.jsonl("ts-calls.jsonl")

    # -- state files
    def load(self, kind, slug):
        path = os.path.join(self.state, kind, f"{slug}.json")
        if not os.path.exists(path):
            return None
        with open(path) as fh:
            return json.load(fh)

    def write_state(self, kind, slug, data):
        os.makedirs(os.path.join(self.state, kind), exist_ok=True)
        with open(os.path.join(self.state, kind, f"{slug}.json"), "w") as fh:
            json.dump(data, fh)

    def write_profile(self, slug, cwd=None, port=None, **extra):
        data = {"slug": slug, "title": slug, "cwd": cwd or self.site, "cmd": ["true"], "env": {}, "inherit_env": [],
                "port": port or free_port(), "health": "/", "https_port": None, "https_port_pinned": False,
                "timeout": 120, "reuse": True}
        data.update(extra)
        self.write_state("profiles", slug, data)
        return data

    def start_helper(self, argv, **kw):
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                **kw)
        self.helpers.append(proc)
        return proc

    def cleanup(self):
        """The launcher's own down; then any process it started that still runs is reported (and stopped)."""
        problems = []
        for proc in self.helpers:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
        if os.path.isdir(os.path.join(self.state, "profiles")):
            try:
                self.run("down", "--all", "--apply", timeout=120)
            except subprocess.TimeoutExpired:
                problems.append("down --all --apply timed out")
        run_dir = os.path.join(self.state, "run")
        for name in sorted(os.listdir(run_dir)) if os.path.isdir(run_dir) else []:
            try:
                with open(os.path.join(run_dir, name)) as fh:
                    rec = json.load(fh)
            except (OSError, ValueError):
                continue
            info = ps_fields(rec.get("pid"))
            if info and not info[1].startswith("Z") and info[0] == rec.get("pgid") and info[2] == rec.get("lstart"):
                problems.append(f"leftover service pid {rec['pid']} after down --all --apply")
                os.killpg(rec["pgid"], signal.SIGTERM)
            cpid = rec.get("caffeinate_pid")
            if cpid and not wait_until(lambda: not pid_alive(cpid), 2.0):
                args = subprocess.run(["ps", "-o", "args=", "-p", str(cpid)], capture_output=True, text=True).stdout
                if self.bin in args:
                    problems.append(f"leftover caffeinate pid {cpid}")
                    os.kill(cpid, signal.SIGTERM)
        return problems


def forbidden_calls(calls):
    bad = []
    for call in calls:
        argv = call["argv"]
        if any(a in ("funnel", "reset") or a.startswith("--set-path") or a == "--https=443" for a in argv):
            bad.append(argv)
    return bad


def verdict_ok(t, r, what):
    t.ok(len(r.lines) <= 40, f"{what}: {len(r.lines)} lines (max 40)")
    t.ok(r.last.startswith(VERDICT), f"{what}: last line is not the verdict: {r.last!r}")


# ------------------------------------------------------------------ cases
def case_usage_errors(c, t):
    p = str(free_port())
    for args in ([], ["bogus"], ["status", "--apply"], ["url", "x", "--apply"], ["list", "--apply"],
                 ["doctor", "--apply"], ["up", "Bad_Slug", "--cwd", c.site, "--port", p, "--", "true"],
                 ["up", "demo", "--cwd", c.site, "--port", "80", "--", "true"], ["down", "demo", "--all"],
                 ["status", "x" * 41], ["up", "demo", "--port", p, "--"], ["status", "demo", "--", "true"],
                 ["up", "demo", "--cwd", c.site, "--port", p, "--https-port", "443", "--", "true"],
                 ["up", "demo", "--cwd", c.site, "--port", p, "--health", "nope", "--", "true"]):
        r = c.run(*args)
        t.eq(r.rc, 64, f"exit of {args}")
        t.ok(r.last.startswith(f"{VERDICT} usage"), f"verdict of {args}: {r.last!r}")
    t.ok(not os.path.exists(c.state), "a usage error wrote the state dir")


def case_help_version(c, t):
    r = c.run("--help")
    t.eq(r.rc, 0, "--help exit")
    for flag in HELP_FLAGS:
        t.has(r.out, flag, "--help")
    r = c.run("up", "--help")
    t.eq(r.rc, 0, "up --help exit")
    r = c.run("--version")
    t.eq((r.rc, r.out.strip()), (0, "tailnet_preview.py schema 1"), "--version")


def case_doctor_absent(c, t):
    r = c.run("doctor", tailscale="none")
    t.eq(r.rc, 1, f"exit {r!r}")
    t.eq(r.last, ABSENT, "verdict")
    t.ok(not os.path.exists(c.state), "doctor created the state dir")


def case_doctor_ready(c, t):
    r = c.run("doctor")
    t.eq(r.rc, 0, f"exit {r!r}")
    t.ok(r.last.startswith(f"{VERDICT} ready") and HOST in r.last, f"verdict {r.last!r}")
    t.ok(not os.path.exists(c.state), "doctor created the state dir")
    t.ok(all(call["be_cli"] == "1" for call in c.ts_calls()), "a tailscale call ran without TAILSCALE_BE_CLI=1")


def case_doctor_logged_out(c, t):
    c.set_ts(mode="logged-out")
    r = c.run("doctor")
    t.eq(r.rc, 1, f"exit {r!r}")
    t.ok(r.last.startswith(f"{VERDICT} lan-only"), f"verdict {r.last!r}")
    t.has(r.out.lower(), "login", "doctor output")


def case_doctor_https_off(c, t):
    c.set_ts(mode="https-off")
    r = c.run("doctor")
    t.eq(r.rc, 1, f"exit {r!r}")
    t.ok(r.last.startswith(f"{VERDICT} lan-only"), f"verdict {r.last!r}")
    t.has(r.out, "HTTPS certificates", "doctor output")
    c.set_ts(mode="magicdns-off")
    r = c.run("doctor")
    t.eq(r.rc, 1, f"magicdns-off exit {r!r}")
    t.has(r.last, "MagicDNS off", "magicdns-off verdict")


def case_doctor_defensive_json(c, t):
    c.set_ts(mode="defensive")
    r = c.run("doctor")
    t.eq(r.rc, 1, f"null CurrentTailnet, empty DNSName, no CertDomains must be lan-only: {r!r}")
    t.ok(r.last.startswith(f"{VERDICT} lan-only"), f"verdict {r.last!r}")
    c.set_ts(mode="garbage")
    r = c.run("doctor")
    t.eq(r.rc, 2, f"unparseable status --json: {r!r}")
    t.ok(r.last.startswith(f"{VERDICT} error"), f"verdict {r.last!r}")


def case_up_dry_run(c, t):
    p = free_port()
    r = c.run("up", "demo", "--cwd", c.site, "--port", p, "--health", "/", "--", *serve_cmd(p))
    t.eq(r.rc, 1, f"exit {r!r}")
    t.eq(r.last, f"{VERDICT} would-start demo (dry run: add --apply)", "verdict")
    t.ok(not os.path.exists(c.state), "a dry run created the state dir")
    t.ok(not port_open(p), "a dry run started the service")
    t.ok(not [x for x in c.ts_calls() if x["argv"][:1] == ["serve"] and x["argv"][1:2] != ["status"]],
         "a dry run changed the serve config")


def case_up_first(c, t):
    need_lsof()
    p = free_port()
    r = c.up("demo", p)
    t.eq(r.rc, 0, f"exit {r!r}")
    t.eq(http_code(p), 200, "localhost GET")
    t.eq(c.proxy(8443), f"http://127.0.0.1:{p}", "serve mapping on 8443")
    t.eq(r.last, f"{VERDICT} up demo · https://{HOST}:8443/", "verdict")
    t.has(r.out, f"localhost http://localhost:{p}/", "localhost line")
    t.has(r.out, f"tailnet https://{HOST}:8443/", "tailnet line")
    calls = c.ts_calls()
    t.ok(not forbidden_calls(calls), f"forbidden tailscale calls: {forbidden_calls(calls)}")
    t.ok(calls and all(x["be_cli"] == "1" for x in calls), "a tailscale call ran without TAILSCALE_BE_CLI=1")
    curls = c.jsonl("curl-calls.jsonl")
    t.ok(curls and all("--noproxy" in a and "*" in a and "--max-time" in a and "60" in a for a in curls),
         f"warm-up curl flags: {curls}")
    caf = c.jsonl("caffeinate-calls.jsonl")
    run = c.load("run", "demo") or {}
    t.ok(caf and caf[-1] == ["-i", "-s", "-w", str(run.get("pid"))], f"caffeinate args {caf}")
    t.eq(run.get("status"), "up", "run state status")


def case_up_idempotent(c, t):
    need_lsof()
    p = free_port()
    c.up("demo", p)
    first = (c.load("run", "demo") or {}).get("pid")
    r = c.run("up", "demo", "--apply")
    t.eq(r.rc, 0, f"exit {r!r}")
    t.has(r.out, "already up", "second up")
    t.eq((c.load("run", "demo") or {}).get("pid"), first, "pid after the second up")
    t.has(r.out, f"pid {first}", "second up output")


def case_up_no_reuse(c, t):
    need_lsof()
    p = free_port()
    c.up("demo", p, "--no-reuse")
    first = (c.load("run", "demo") or {}).get("pid")
    r = c.run("up", "demo", "--apply")
    second = (c.load("run", "demo") or {}).get("pid")
    t.eq(r.rc, 0, f"exit {r!r}")
    t.ok(second and second != first, f"pid did not change ({first} -> {second})")
    t.ok(wait_until(lambda: not pid_alive(first)), f"old pid {first} still alive")
    t.eq(http_code(p), 200, "localhost GET after the restart")


def case_url_lines(c, t):
    need_lsof()
    p = free_port()
    c.up("demo", p)
    r = c.run("url", "demo", "--path", "/docs/")
    t.eq(r.rc, 0, f"exit {r!r}")
    t.eq(r.lines[:3], [f"localhost http://localhost:{p}/docs/", "lan -", f"tailnet https://{HOST}:8443/docs/"],
         "url lines")
    t.eq(len(r.lines), 4, "url prints three lines and the verdict")


def case_status_json(c, t):
    need_lsof()
    p = free_port()
    c.up("demo", p)
    r = c.run("status", "demo", "--json")
    d = json.loads(r.out)
    t.ok(JSON_KEYS <= set(d), f"missing keys {sorted(JSON_KEYS - set(d))}")
    t.eq((d.get("status"), d.get("exit"), r.rc), ("up", 0, 0), "status, exit")
    t.eq(set(d.get("urls") or {}), {"localhost", "lan", "tailnet"}, "urls keys")
    t.eq((d.get("urls") or {}).get("tailnet"), f"https://{HOST}:8443/", "tailnet url")


def case_port_collision(c, t):
    need_lsof()
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    p = srv.getsockname()[1]
    try:
        marker = os.path.join(c.site, "spawned")
        r = c.up("probe", p, cmd=[sys.executable, "-c", f"open({marker!r}, 'w').write('x')"])
        t.eq(r.rc, 2, f"exit {r!r}")
        t.ok(r.last.startswith(f"{VERDICT} blocked probe · port {p} held by pid {os.getpid()} ("),
             f"verdict {r.last!r}")
        t.has(r.last, "free: ", "verdict")
        t.ok(not os.path.exists(marker), "the command ran although the port was held")
        t.ok(c.load("run", "probe") is None, "run state written for a blocked up")
        srv.settimeout(3)
        with socket.create_connection(("127.0.0.1", p), timeout=3):
            conn, _ = srv.accept()
            conn.close()
    finally:
        srv.close()


def case_https_port_taken(c, t):
    need_lsof()
    c.set_ts(serve={"TCP": {"8443": {"HTTPS": True}},
                    "Web": {f"{HOST}:8443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:9"}}}}})
    pa = free_port()
    r = c.up("auto", pa)
    t.eq(r.rc, 0, f"auto exit {r!r}")
    t.eq(r.last, f"{VERDICT} up auto · https://{HOST}:8444/", "auto verdict")
    t.eq((c.load("profiles", "auto") or {}).get("https_port"), 8444, "persisted https port")
    pb = free_port()
    r = c.up("pinned", pb, "--https-port", "8443")
    t.eq(r.rc, 2, f"pinned exit {r!r}")
    t.ok(r.last.startswith(f"{VERDICT} blocked pinned") and "8443" in r.last, f"pinned verdict {r.last!r}")
    t.ok(not port_open(pb), "the pinned service was started although its https port is taken")
    t.eq(c.proxy(8443), "http://127.0.0.1:9", "the foreign mapping was touched")


def case_health_timeout(c, t):
    need_lsof()
    p = free_port()
    sleeper = [sys.executable, "-c", "import time; print('sleeper up', flush=True); time.sleep(60)"]
    r = c.up("sleepy", p, "--timeout", "2", cmd=sleeper)
    t.eq(r.rc, 2, f"exit {r!r}")
    t.ok(r.last.startswith(f"{VERDICT} unhealthy sleepy"), f"verdict {r.last!r}")
    t.has(r.out, "sleeper up", "log tail")
    run = c.load("run", "sleepy") or {}
    t.eq(run.get("status"), "unhealthy", "run state status")
    t.ok(run.get("pgid") and wait_until(lambda: not group_alive(run["pgid"])), "the process group survived")


def case_cmd_exits(c, t):
    need_lsof()
    p = free_port()
    r = c.up("boom", p, cmd=[sys.executable, "-c", "import sys; print('boom happened'); sys.exit(3)"])
    t.eq(r.rc, 2, f"exit {r!r}")
    t.ok(r.last.startswith(f"{VERDICT} exited (3) boom"), f"verdict {r.last!r}")
    t.has(r.out, "boom happened", "log tail")


def case_lan_only_up(c, t):
    need_lsof()
    p = free_port()
    r = c.up("demo", p, tailscale="none")
    t.eq(r.rc, 1, f"exit {r!r}")
    t.ok(r.last.startswith(f"{VERDICT} lan-only demo · http://localhost:{p}/"), f"verdict {r.last!r}")
    t.has(r.out, "tailnet -", "tailnet line")
    t.eq(http_code(p), 200, "service alive")
    t.eq(c.ts_calls(), [], "tailscale was called although it is absent")


def case_down_dry(c, t):
    need_lsof()
    p = free_port()
    c.up("demo", p)
    pid = (c.load("run", "demo") or {}).get("pid")
    r = c.run("down", "demo")
    t.eq(r.rc, 1, f"exit {r!r}")
    t.eq(r.last, f"{VERDICT} would-stop demo (dry run: add --apply)", "verdict")
    t.ok(pid_alive(pid), "a dry down stopped the service")
    t.eq(c.proxy(8443), f"http://127.0.0.1:{p}", "a dry down removed the mapping")


def case_down_apply(c, t):
    need_lsof()
    p = free_port()
    c.up("demo", p)
    run = c.load("run", "demo") or {}
    r = c.run("down", "demo", "--apply")
    t.eq(r.rc, 0, f"exit {r!r}")
    t.eq(r.last, f"{VERDICT} down demo · stopped pid {run.get('pid')} · serve :8443 off", "verdict")
    t.ok(wait_until(lambda: not pid_alive(run.get("pid"))), "service still alive")
    t.ok(wait_until(lambda: not pid_alive(run.get("caffeinate_pid")), 3), "caffeinate shim still alive")
    t.ok(c.proxy(8443) is None, "mapping still present")
    t.ok(["serve", "--https=8443", "off"] in [x["argv"] for x in c.ts_calls()], "no serve off call")
    t.ok(not forbidden_calls(c.ts_calls()), f"forbidden calls {forbidden_calls(c.ts_calls())}")
    t.eq((c.load("run", "demo") or {}).get("status"), "stopped", "run state status")
    t.ok(c.load("profiles", "demo") is not None, "down removed the profile")
    t.ok(not port_open(p), "port still open")


def case_down_idempotent(c, t):
    need_lsof()
    p = free_port()
    c.up("demo", p)
    c.run("down", "demo", "--apply")
    r = c.run("down", "demo", "--apply")
    t.eq(r.rc, 0, f"exit {r!r}")
    t.eq(r.last, f"{VERDICT} down demo · already stopped", "verdict")


def case_stale_after_kill(c, t):
    need_lsof()
    p = free_port()
    r = c.up("demo", p, cmd=[sys.executable, c.fixture, str(p)])
    t.eq(r.rc, 0, f"up {r!r}")
    old = (c.load("run", "demo") or {}).get("pid")
    http_code(p, "/__exit")
    t.ok(wait_until(lambda: not pid_alive(old)), "fixture did not exit")
    r = c.run("status", "demo")
    t.eq(r.rc, 1, f"status exit {r!r}")
    t.ok(r.last.startswith(f"{VERDICT} stale demo"), f"status verdict {r.last!r}")
    r = c.run("up", "demo", "--apply")
    new = (c.load("run", "demo") or {}).get("pid")
    t.eq(r.rc, 0, f"restart {r!r}")
    t.ok(new and new != old, "up did not restart the stale profile")
    t.eq(http_code(p), 200, "service after the restart")


def case_pid_reuse_guard(c, t):
    need_lsof()
    dummy = c.start_helper([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    t.ok(wait_until(lambda: pid_alive(dummy.pid)), "dummy did not start")
    p = free_port()
    c.write_profile("demo", port=p, cmd=serve_cmd(p))
    c.write_state("run", "demo", {"slug": "demo", "status": "up", "pid": dummy.pid, "pgid": dummy.pid,
                                  "lstart": "Thu Jan  1 00:00:00 1970", "lstart_epoch": 0, "port": p,
                                  "https_port": 8443, "mapped": False, "caffeinate_pid": None, "log": None})
    r = c.run("status", "demo")
    t.eq(r.rc, 1, f"status exit {r!r}")
    t.ok(r.last.startswith(f"{VERDICT} stale demo"), f"status verdict {r.last!r}")
    r = c.run("down", "demo", "--apply")
    t.eq(r.rc, 0, f"down exit {r!r}")
    t.has(r.last, "not ours", "down verdict")
    time.sleep(0.3)
    t.ok(dummy.poll() is None, "down signalled a pid whose start time does not match")


def case_secret_env_refused(c, t):
    p = free_port()
    for flags in (["--env", "API_TOKEN=x"], ["--env", "DB_PASSWORD=x"], ["--env", "SESSION_COOKIE=x"],
                  ["--env", "NEXT_PUBLIC_ANON_KEY=x"], ["--inherit-env", "API_TOKEN"], ["--env", "lower=x"],
                  ["--env", "NOEQUALS"], ["--env", "CLAUDE_X=1"]):
        r = c.run("up", "demo", "--cwd", c.site, "--port", p, *flags, "--apply", "--", "true")
        t.eq(r.rc, 64, f"exit of {flags}")
    t.ok(not os.path.exists(c.state), "a refused env wrote the state dir")
    for flags in (["--env", "MONKEY_MODE=1"], ["--env", "AUTHOR=acme"], ["--env", "PORT=3000"]):
        r = c.dry("demo", p, *flags)
        t.eq(r.rc, 1, f"dry run with {flags}: {r!r}")


def case_nvmrc_node(c, t):
    need_lsof()
    versions = os.path.join(c.root, "nvm", "versions", "node")
    for v in ("v20.8.1", "v20.11.0", "v20.19.2", "v18.20.4"):
        os.makedirs(os.path.join(versions, v, "bin"))

    def nvmrc(text):
        with open(os.path.join(c.site, ".nvmrc"), "w") as fh:
            fh.write(text + "\n")

    p, out = free_port(), os.path.join(c.root, "child-env.json")
    nvmrc("20")
    r = c.up("node", p, "--json", cmd=[sys.executable, c.fixture, str(p), "--env-out", out])
    d = json.loads(r.out)
    t.eq(d.get("node"), "~/nvm/versions/node/v20.19.2/bin", f"20 -> highest 20.x ({r.rc})")
    with open(out) as fh:
        path = json.load(fh).get("PATH", "")
    t.ok(path.startswith(os.path.join(versions, "v20.19.2", "bin") + os.pathsep), f"child PATH {path[:120]!r}")
    for text, want in (("20.1", None), ("v20.11", "~/nvm/versions/node/v20.11.0/bin"),
                       ("20.8.1", "~/nvm/versions/node/v20.8.1/bin"), ("lts/*", None), ("21", None)):
        nvmrc(text)
        d = json.loads(c.run("up", "node", "--json").out)
        t.eq(d.get("node"), want, f".nvmrc {text}")
        if text in ("20.1", "21"):
            t.ok(any(text in x for x in d.get("problems") or []), f".nvmrc {text}: no warning")


def case_slug_from_cwd(c, t):
    sub = os.path.join(c.site, "sub", "deeper")
    os.makedirs(sub)
    c.write_profile("a")
    r = c.run("status", cwd=sub)
    t.eq(r.rc, 1, f"single match exit {r!r}")
    t.ok(r.last.startswith(f"{VERDICT} stopped a"), f"single match verdict {r.last!r}")
    c.write_profile("b", cwd=c.root)
    r = c.run("status", cwd=sub)
    t.eq(r.rc, 2, f"two matches exit {r!r}")
    t.ok("a ~/site" in r.out and "b ~" in r.out, f"candidates not listed: {r.out!r}")
    other = os.path.join(c.root, "elsewhere")
    os.makedirs(other)
    r = c.run("url", cwd=other)
    t.ok(r.rc == 1 and r.last.startswith(f"{VERDICT} stopped b"), f"ancestor match {r!r}")
    r = c.run("status", cwd=tempfile.gettempdir())
    t.eq(r.rc, 2, f"no match exit {r!r}")


def case_caps_and_verdict(c, t):
    need_lsof()
    p = free_port()
    steps = (("doctor",), ("list",), ("up", "demo", "--cwd", c.site, "--port", p, "--", *serve_cmd(p)),
             ("up", "demo", "--cwd", c.site, "--port", p, "--apply", "--", *serve_cmd(p)), ("status", "demo"),
             ("url", "demo"), ("list",), ("down", "demo"), ("down", "demo", "--apply"), ("status", "demo"),
             ("down", "--all", "--apply"), ("up", "nope", "--apply"))
    for args in steps:
        r = c.run(*args)
        verdict_ok(t, r, " ".join(map(str, args[:2])))
        t.ok(c.root not in r.out, f"{args[:2]}: an absolute path under HOME was printed: {r.out[:200]!r}")
    for n in range(45):
        c.write_profile(f"p{n:02d}")
    r = c.run("list")
    verdict_ok(t, r, "list of 45")
    t.eq(r.rc, 0, "list exit")


def case_json_one_object(c, t):
    need_lsof()
    p, conf = free_port(), os.path.join(c.root, "conf.json")
    cmd = (sys.executable, c.fixture, str(p))
    flags = ("--cwd", c.site, "--port", p, "--env", f"APP_CONFIG={conf}")
    steps = (("doctor", "--json"), ("up", "demo", *flags, "--json", "--", *cmd),
             ("up", "demo", *flags, "--apply", "--json", "--", *cmd),
             ("status", "demo", "--json"), ("url", "demo", "--json"), ("list", "--json"), ("down", "demo", "--json"),
             ("down", "demo", "--apply", "--json"), ("up", "Bad_Slug", "--json"), ("status", "ghost", "--json"))
    for args in steps:
        r = c.run(*args)
        try:
            d = json.loads(r.out)
        except ValueError:
            t.ok(False, f"{args[:2]}: stdout is not one JSON object: {r.out[:160]!r}")
            continue
        t.ok(isinstance(d, dict) and JSON_KEYS <= set(d), f"{args[:2]}: keys {sorted(d) if isinstance(d, dict) else d}")
        t.eq(d.get("exit"), r.rc, f"{args[:2]}: exit field")
        t.ok(str(d.get("verdict", "")).startswith(VERDICT), f"{args[:2]}: verdict field")
        t.ok(c.root not in r.out, f"{args[:2]}: an absolute home path in the JSON: {r.out[:200]!r}")
        prof = d.get("profile") if isinstance(d, dict) and isinstance(d.get("profile"), dict) else None
        if prof is not None and args[1] == "demo":
            t.eq(prof.get("cmd"), [sys.executable, "~/fixture_server.py", str(p)], f"{args[:2]}: profile.cmd")
            t.eq((prof.get("env") or {}).get("APP_CONFIG"), "~/conf.json", f"{args[:2]}: profile.env")
    stored = c.load("profiles", "demo") or {}
    t.eq((stored.get("cmd"), stored.get("env")), (list(cmd), {"APP_CONFIG": conf}),
         "the stored profile keeps absolute paths (the ~ form is display only)")


def case_no_private_strings(c, t):
    hook = hook_regexes()
    files = [os.path.abspath(c.script), os.path.abspath(__file__), DOC, BIN]
    for path in files:
        if not t.ok(os.path.isfile(path), f"missing {os.path.basename(path)}"):
            continue
        with open(path, encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
        name = os.path.basename(path)
        for n, line in enumerate(text.splitlines(), 1):
            hit = next((h.pattern for h in hook if h.search(line)), None)
            if hit:
                t.ok(False, f"pre-push pattern {hit} in {name}:{n}")
            for rx, what in ((USERS, "home path"), (CONFIG_DIR, "config-dir name"), (CT_WORD, "the CT-log word")):
                if rx.search(line):
                    t.ok(False, f"{what} in {name}:{n}")
            if DOTDOT in line:
                t.ok(False, f"parent-dir path in {name}:{n}")


def case_launcher_wrapper(c, t):
    if not t.ok(os.path.isfile(BIN) and os.path.isfile(TWIN), "bin/tailnet-preview or bin/renovate-check missing"):
        return
    p = subprocess.run([BIN, "--help"], capture_output=True, text=True, env=c.env, timeout=60)
    t.eq(p.returncode, 0, "bin/tailnet-preview --help exit")
    t.ok(os.access(BIN, os.X_OK), "bin/tailnet-preview is not executable")
    with open(TWIN, "rb") as fh:
        twin = fh.read().decode("utf-8").split("\n")
    with open(BIN, "rb") as fh:
        mine = fh.read().decode("utf-8").split("\n")
    t.eq(mine[:-2], twin[:-2], "wrapper lines other than the exec line")
    t.eq(mine[-2:], [EXEC_LINE, ""], "exec line (and the trailing newline)")
    t.eq(len(mine), len(twin), "line count")


def case_timeout_range_and_cap(c, t):
    p = free_port()
    for bad in ("0", "1801", "-5", "abc", "2.5"):
        r = c.dry("demo", p, "--timeout", bad)
        t.eq(r.rc, 64, f"--timeout {bad}")
    r = c.dry("demo", p, "--timeout", "1")
    t.eq(r.rc, 1, f"--timeout 1: {r!r}")
    t.ok("capped" not in r.out, "--timeout 1 printed the cap note")
    r = c.dry("demo", p, "--timeout", "1800")
    t.eq(r.rc, 1, f"--timeout 1800: {r!r}")
    t.has(r.out, "timeout capped at 420 (Bash tool limit)", "--timeout 1800")
    t.has(r.out, "wait 420s", "--timeout 1800 plan")
    need_lsof()
    r = c.up("demo", p, "--timeout", "1800")
    t.eq(r.rc, 0, f"--timeout 1800 --apply: {r!r}")
    t.has(r.out, "timeout capped at 420 (Bash tool limit)", "--apply output")
    t.eq((c.load("profiles", "demo") or {}).get("timeout"), 1800, "stored timeout")


def case_locale_independent_identity(c, t):
    need_lsof()
    p = free_port()
    r = c.up("demo", p, env={"LANG": "en_AU.UTF-8", "LC_ALL": None, "LC_TIME": "en_AU.UTF-8"})
    t.eq(r.rc, 0, f"up under en_AU: {r!r}")
    run = c.load("run", "demo") or {}
    t.ok(isinstance(run.get("lstart_epoch"), int), f"run state lacks the lstart epoch: {run}")
    c_env = {"LC_ALL": "C", "LANG": "C", "LC_TIME": None}
    r = c.run("status", "demo", env=c_env)
    t.eq((r.rc, r.last.split(" · ")[0]), (0, f"{VERDICT} up demo"), f"status under C: {r!r}")
    r = c.run("down", "demo", "--apply", env=c_env)
    t.eq(r.rc, 0, f"down under C: {r!r}")
    t.ok(f"stopped pid {run.get('pid')}" in r.last and "not ours" not in r.out, f"down verdict {r.last!r}")
    t.ok(wait_until(lambda: not pid_alive(run.get("pid"))), "service survived down")


def case_child_env_allowlist(c, t):
    need_lsof()
    p, out = free_port(), os.path.join(c.root, "child-env.json")
    parent = {"FOO_TOKEN": "leak", "CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli", "ANTHROPIC_BASE_URL": "x",
              "RANDOM_VAR": "kept", "OTHER_VAR": "dropped", "MONKEY_MODE": "parent"}
    r = c.up("envy", p, "--env", "MONKEY_MODE=on", "--env", "AUTHOR=acme", "--inherit-env", "RANDOM_VAR",
             cmd=[sys.executable, c.fixture, str(p), "--env-out", out], env=parent)
    t.eq(r.rc, 0, f"exit {r!r}")
    with open(out) as fh:
        child = json.load(fh)
    t.eq((child.get("MONKEY_MODE"), child.get("AUTHOR"), child.get("RANDOM_VAR")), ("on", "acme", "kept"),
         "profile env and --inherit-env")
    for gone in ("FOO_TOKEN", "OTHER_VAR", "TAILNET_PREVIEW_HOME", "PYTHONIOENCODING"):
        t.ok(gone not in child, f"{gone} reached the child")
    t.ok(not [k for k in child if k.startswith(("CLAUDE", "ANTHROPIC_"))], "CLAUDE*/ANTHROPIC_* reached the child")
    t.ok(child.get("HOME") == c.root and child.get("PATH"), "HOME/PATH missing in the child")
    for flags in (["--inherit-env", "FOO_TOKEN"], ["--inherit-env", "CLAUDECODE"], ["--env", "API_TOKEN=x"]):
        r = c.run("up", "envy2", "--cwd", c.site, "--port", free_port(), *flags, "--apply", "--", "true", env=parent)
        t.eq(r.rc, 64, f"exit of {flags}")


def case_up_writes_starting_state(c, t):
    need_lsof()
    p = free_port()
    argv = [sys.executable, "-B", c.script, "up", "slow", "--cwd", c.site, "--port", str(p), "--apply", "--",
            sys.executable, c.fixture, str(p), "--delay", "2.5"]
    proc = c.start_helper(argv, env=c.env, cwd=c.root)
    seen = None
    end = time.monotonic() + 15
    while seen is None and time.monotonic() < end and proc.poll() is None:
        try:
            rec = c.load("run", "slow")
        except (OSError, ValueError):
            rec = None
        if rec and rec.get("status") == "starting":
            seen = rec
        time.sleep(0.05)
    t.ok(seen is not None, "no run state with status starting while up was still waiting for health")
    t.ok(not seen or proc.poll() is None, "up had already finished when starting was seen")
    t.eq(proc.wait(timeout=60), 0, "up exit")
    if seen:
        for key in ("pid", "pgid", "lstart_epoch"):
            t.ok(isinstance(seen.get(key), int), f"starting state lacks {key}")
        t.eq(seen.get("pgid"), seen.get("pid"), "the service leads its own process group")
    final = c.load("run", "slow") or {}
    t.eq(final.get("status"), "up", "final run state status")
    t.eq(final.get("pid"), (seen or {}).get("pid"), "final pid")


def case_mapped_verdict_not_answering(c, t):
    need_lsof()
    c.set_ts(warm=False)
    p = free_port()
    r = c.up("demo", p)
    t.eq(r.rc, 1, f"exit {r!r}")
    t.eq(r.last, f"{VERDICT} mapped demo · https://{HOST}:8443/ (not answering yet)", "verdict")
    t.eq((c.load("run", "demo") or {}).get("status"), "mapped", "run state status")
    t.eq(c.proxy(8443), f"http://127.0.0.1:{p}", "mapping")


CASES = [
    ("usage-errors", case_usage_errors), ("help-version", case_help_version), ("doctor-absent", case_doctor_absent),
    ("doctor-ready", case_doctor_ready), ("doctor-logged-out", case_doctor_logged_out),
    ("doctor-https-off", case_doctor_https_off), ("doctor-defensive-json", case_doctor_defensive_json),
    ("up-dry-run", case_up_dry_run), ("up-first", case_up_first), ("up-idempotent", case_up_idempotent),
    ("up-no-reuse", case_up_no_reuse), ("url-lines", case_url_lines), ("status-json", case_status_json),
    ("port-collision", case_port_collision), ("https-port-taken", case_https_port_taken),
    ("health-timeout", case_health_timeout), ("cmd-exits", case_cmd_exits), ("lan-only-up", case_lan_only_up),
    ("down-dry", case_down_dry), ("down-apply", case_down_apply), ("down-idempotent", case_down_idempotent),
    ("stale-after-kill", case_stale_after_kill), ("pid-reuse-guard", case_pid_reuse_guard),
    ("secret-env-refused", case_secret_env_refused), ("nvmrc-node", case_nvmrc_node),
    ("slug-from-cwd", case_slug_from_cwd), ("caps-and-verdict", case_caps_and_verdict),
    ("json-one-object", case_json_one_object), ("no-private-strings", case_no_private_strings),
    ("launcher-wrapper", case_launcher_wrapper), ("timeout-range-and-cap", case_timeout_range_and_cap),
    ("locale-independent-identity", case_locale_independent_identity),
    ("child-env-allowlist", case_child_env_allowlist), ("up-writes-starting-state", case_up_writes_starting_state),
    ("mapped-verdict-not-answering", case_mapped_verdict_not_answering)]


def run_case(fn, script, keep):
    root = os.path.realpath(tempfile.mkdtemp(prefix="tailnet-preview-selftest-"))
    t, ctx, skip = Check(), None, None
    try:
        ctx = Ctx(root, script)
        fn(ctx, t)
    except Skip as exc:
        skip = str(exc)
    except Exception as exc:  # a crashing launcher or harness is a failure, not a crash
        t.problems.append(f"harness error: {exc!r}")
    finally:
        if ctx is not None:
            t.problems.extend(ctx.cleanup())
        if keep:
            print(f"  kept {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)
    if t.problems:
        return "FAIL", "; ".join(p[:260] for p in t.problems[:6])
    return ("SKIP", skip) if skip else ("PASS", "")


def main():
    ap = argparse.ArgumentParser(description="Behavioural tests for tailnet_preview.py and bin/tailnet-preview")
    ap.add_argument("--script", default=os.path.join(HERE, "tailnet_preview.py"), help="the tailnet_preview.py to test")
    ap.add_argument("--only", help="run a single case by name")
    ap.add_argument("--keep", action="store_true", help="leave the temp roots on disk")
    args = ap.parse_args()
    script = os.path.abspath(os.path.expanduser(args.script))
    if not os.path.isfile(script):
        print(f"script not found: {script}")
        return 2
    cases = [c for c in CASES if not args.only or c[0] == args.only]
    if not cases:
        print(f"unknown case {args.only!r}; known: {', '.join(n for n, _ in CASES)}")
        return 2
    tally = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    for name, fn in cases:
        verdict, why = run_case(fn, script, args.keep)
        tally[verdict] += 1
        print(f"{verdict} {name}" + (f" - {why}" if why else ""), flush=True)
    skipped = f" · {tally['SKIP']} skipped" if tally["SKIP"] else ""
    print(f"{tally['PASS']}/{len(cases)} passed{skipped}")
    return 1 if tally["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
