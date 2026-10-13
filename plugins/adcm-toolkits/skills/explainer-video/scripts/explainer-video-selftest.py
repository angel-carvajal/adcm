#!/usr/bin/env python3
"""explainer-video-selftest - behavioural tests for record.mjs and its launcher (stdlib only).

Usage:
  python3 explainer-video-selftest.py [--script PATH] [--only NAME] [--keep]

Builds one throwaway `tempfile` project per case (videos/config.json, videos/guiones/*.json), runs
record.mjs under Node >= 20 as a subprocess (PYTHONDONTWRITEBYTECODE=1) and prints
`PASS|FAIL|SKIP <case> [- why]`. Exit code 1 when any case FAILs.

Node is located the way bin/explainer-record does it: the newest nvm v2x, else the node on PATH. Every
case that runs record.mjs SKIPs without a Node >= 20. Cases that record need playwright-core, a browser, ffmpeg and
ffprobe; the harness asks `record.mjs --doctor` instead of guessing and SKIPs with the doctor's own
words when one is missing. The voiced case needs a piper engine and model under $REC_TTS_HOME and never
uses edge (a network service that can refuse a handshake): every other recording is --mute.

Contract encoded:
  - --check: `voice: <engine:id> (<ms> ms/char)`, `OK <id> <slug> <n> steps ~<s>s` per guion (the
    estimate is recomputed here from msPerChar edge 70 / piper 74 / say 68), warnings for the duration
    window and a missing `next`, `FAIL <file>` + `  - <problem>` lines, `<n> OK` / `<a> OK, <b> FAIL`;
  - config keys are strict (exit 2); guionesDir / outDir / every path inside the config resolve against
    the config file's directory, only --config is relative to the cwd;
  - --doctor prints 7 `ok|missing <item>` lines in a fixed order, then `DOCTOR: ready|not ready`; the voice
    line synthesizes one word, so an installed engine that fails reads `synthesis failed`; under Node < 20
    it still prints the 7 lines (exit 2);
  - exit codes: 64 for argument errors (usage + `record.mjs: error: <msg>` on stderr), 2 for
    config / host guard / lock / unset env var, 1 for an invalid guion, a failed step or a failed verify;
  - {{env:VAR}} values (raw and percent-encoded) and token= query values never reach an output file or the
    console; allowHosts also stops a redirect hop that leaves the list;
  - steps start on a 0.1 s grid: a second --mute take writes the same srt and dom;
  - --verify writes <outDir>/manifest.json (array sorted by id, entries of other ids kept while their
    guion exists) and checks h264 + aac + mov_text, 1280x800, 25 fps.

Fixtures are generic (Acme, Provider/Invoice, example.com, localhost); the demo page is served by
a small `http.server` script on a free port. The script under test defaults to the record.mjs next to this
file; pass --script to test an installed copy. --keep leaves the temp trees on disk.
"""
import argparse
import atexit
import glob
import hashlib
import json
import math
import os
import pathlib
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DOCTOR_ITEMS = ("node>=20", "playwright-core>=1.61", "browser channel", "ffmpeg", "ffprobe", "voice engine", "voice home")
CONTRACT_KEYS = ("baseUrl", "allowHosts", "guionesDir", "outDir", "viewport", "locale", "timezone", "voice", "fallbacks",
                 "brand", "fonts", "durationWindow", "denyList", "pronunciation", "mail", "setup", "profiles")
CONFIG_DEFAULTS = {
    "allowHosts": ["localhost", "127.0.0.1"], "guionesDir": "guiones", "outDir": "out",
    "viewport": {"width": 1280, "height": 800}, "locale": "es-MX", "timezone": "America/Mexico_City",
    "voice": {"engine": "edge", "id": "es-MX-DaliaNeural", "rate": None}, "fallbacks": ["piper", "say"],
    "brand": {"accent": "#3B82F6", "bg": "#111318"}, "fonts": [], "durationWindow": [55, 125],
    "pronunciation": {}, "setup": [], "profiles": {},
}
STEP_KEYS = ("say", "sayAs", "caption", "action", "selector", "value", "highlight", "waitFor", "hold")
CLOSED = {"baseUrl": "http://127.0.0.1:9"}


class Skip(Exception):
    pass


# ------------------------------------------------------------------ machine facts
class Facts:
    """What this machine offers; filled once by main()."""

    def __init__(self):
        self.script = self.skill_dir = self.plugin_root = None
        self.node = self.node_source = self.node_why = None
        self.ffmpeg = self.ffprobe = None
        self._doctor = {}
        self._encoders = None

    def configure(self, script):
        self.script = script
        self.skill_dir = os.path.dirname(os.path.dirname(script))
        skills = os.path.dirname(self.skill_dir)
        self.plugin_root = os.path.dirname(skills) if os.path.basename(skills) == "skills" else None
        self.node, self.node_source, self.node_why = find_node()
        self.ffmpeg, self.ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")

    def env(self, **patch):
        env = dict(os.environ)
        for k in ("REC_TTS", "REC_VOICE", "REC_RATE"):
            env.pop(k, None)
        env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "NO_COLOR": "1"})
        if self.node:
            env["PATH"] = os.path.dirname(self.node) + os.pathsep + env.get("PATH", "")
        for k, v in patch.items():
            if v is None:
                env.pop(k, None)
            else:
                env[k] = v
        return env

    def doctor(self, tts=None):
        """{item: (ok, detail)} of `record.mjs --doctor` with REC_TTS=tts, cached."""
        if tts not in self._doctor:
            scratch = tempfile.mkdtemp(prefix="explainer-video-doctor-")
            try:
                r = spawn([self.node, self.script, "--doctor", "--config", os.path.join(scratch, "none.json")],
                          self.env(REC_TTS=tts), scratch, 180)
            finally:
                shutil.rmtree(scratch, ignore_errors=True)
            found = {}
            for line in r.out.splitlines():
                for item in DOCTOR_ITEMS:
                    if line.startswith(f"ok {item} ("):
                        found[item] = (True, line[len(item) + 5:-1])
                    elif line.startswith(f"missing {item} — "):
                        found[item] = (False, line[len(item) + 11:])
            self._doctor[tts] = found
        return self._doctor[tts]

    def encoders_problem(self):
        if self._encoders is None:
            out = subprocess.run([self.ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
            gone = [e for e in ("libx264", "aac", "mov_text") if not re.search(rf"\b{e}\b", out)]
            self._encoders = f"ffmpeg has no encoder for {', '.join(gone)}" if gone else ""
        return self._encoders or None


F = Facts()


def node_major(exe):
    try:
        out = subprocess.run([exe, "-p", "process.versions.node"], capture_output=True, text=True, timeout=30).stdout
        return int(out.strip().split(".")[0])
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def nvm_version(bin_dir):
    """(major, minor, patch) of the bin directory of an nvm install: the order `sort -V` gives."""
    m = re.search(r"/v(\d+)\.(\d+)\.(\d+)/bin$", bin_dir)
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def find_node():
    """(node, 'nvm'|'PATH', why-not): the newest nvm v2x (version order) first, else PATH's node, as bin/explainer-record does."""
    nvm = sorted(glob.glob(os.path.join(os.path.expanduser("~"), ".nvm", "versions", "node", "v2[0-9]*", "bin")), key=nvm_version)
    candidates = [(os.path.join(nvm[-1], "node"), "nvm")] if nvm else []
    on_path = shutil.which("node")
    if on_path:
        candidates.append((on_path, "PATH"))
    for exe, source in candidates:
        if os.access(exe, os.X_OK) and node_major(exe) >= 20:
            return exe, source, None
    return None, None, "Node >= 20 not found (newest nvm v2x, then node on PATH)"


# ------------------------------------------------------------------ harness
class R:
    """One process run."""

    def __init__(self, rc, out, err, timed_out=False):
        self.rc, self.out, self.err, self.timed_out = rc, out, err, timed_out
        self.text = out + err


def spawn(cmd, env, cwd, timeout):
    """Run in its own process group so a timeout also takes the browser down."""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                         errors="replace", env=env, cwd=cwd, start_new_session=True)
    try:
        out, err = p.communicate(timeout=timeout)
        return R(p.returncode, out, err)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        out, err = p.communicate()
        return R(-9, out or "", err or "", timed_out=True)


class Check:
    def __init__(self):
        self.problems = []

    def ok(self, cond, what):
        if not cond:
            self.problems.append(what)

    def eq(self, got, want, what):
        if got != want:
            self.problems.append(f"{what}: got {got!r}, want {want!r}")

    def has(self, hay, needle, what):
        if needle not in (hay or ""):
            self.problems.append(f"{what}: {needle!r} not in {tail(hay)!r}")

    def lacks(self, hay, needle, what):
        if needle in (hay or ""):
            self.problems.append(f"{what}: {needle!r} must not be present")

    def rc(self, r, want, what):
        if r.rc != want:
            self.problems.append(f"{what}: exit {r.rc}{' (timed out)' if r.timed_out else ''}, want {want} ({tail(r.text)})")


def tail(text, n=170):
    flat = " | ".join(x for x in (text or "").strip().splitlines() if x.strip())
    return flat[-n:]


class Proj:
    """<root>/<name>/videos/{config.json, guiones/, out/}."""

    def __init__(self, root, name):
        self.cwd = os.path.join(root, name)
        self.videos = os.path.join(self.cwd, "videos")
        self.config = os.path.join(self.videos, "config.json")
        self.guiones = os.path.join(self.videos, "guiones")
        self.out = os.path.join(self.videos, "out")

    def write_config(self, cfg, name="config.json"):
        os.makedirs(self.videos, exist_ok=True)
        with open(os.path.join(self.videos, name), "w", encoding="utf-8") as fh:
            fh.write(cfg if isinstance(cfg, str) else json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")

    def add(self, g, file=None, directory=None):
        """A guion dict (or raw text) as <id>-<slug>.json unless `file` names it."""
        directory = directory or self.guiones
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, file or f"{g['id']}-{g['slug']}.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(g if isinstance(g, str) else json.dumps(g, indent=2, ensure_ascii=False) + "\n")
        return path

    def path(self, *parts):
        return os.path.join(self.out, *parts)


class Ctx:
    def __init__(self, root):
        self.root = root

    # ---- requirements: each raises Skip with the reason
    def need_node(self):
        if not F.node:
            raise Skip(F.node_why)

    def need_media(self):
        self.need_node()
        if not (F.ffmpeg and F.ffprobe):
            raise Skip("ffmpeg / ffprobe not found on PATH")
        if F.encoders_problem():
            raise Skip(F.encoders_problem())

    def need_browser(self):
        self.need_media()
        found = F.doctor()
        for item in ("playwright-core>=1.61", "browser channel", "ffmpeg", "ffprobe"):
            ok, detail = found.get(item, (False, "no line in the doctor output"))
            if not ok:
                raise Skip(f"{item}: {detail}")

    def need_piper(self):
        self.need_browser()
        ok, detail = F.doctor("piper").get("voice engine", (False, "no line in the doctor output"))
        if not ok:
            raise Skip(f"piper voice not ready: {detail}")

    # ---- running and fixtures
    def run(self, *args, cwd=None, env=None, timeout=240):
        return spawn([F.node, F.script, *args], F.env(**(env or {})), cwd or self.root, timeout)

    def project(self, config=None, guiones=(), name="proj"):
        p = Proj(self.root, name)
        os.makedirs(p.guiones, exist_ok=True)
        p.write_config(CLOSED if config is None else config)
        for g in guiones:
            p.add(g)
        return p

    def live(self, **extra):
        """A config pointing at the demo server, with a window short enough for the demo guiones."""
        cfg = {"baseUrl": get_demo().url, "durationWindow": [4, 60]}
        cfg.update(extra)
        return cfg

    def record(self, p, *ids, env=None, timeout=300):
        return self.run(*ids, "--mute", cwd=p.cwd, env=env, timeout=timeout)


def step(say, action="none", **kw):
    s = {"say": say, "action": action}
    s.update(kw)
    return s


def guion(id_, slug, steps, **kw):
    g = {"id": id_, "slug": slug, "title": kw.pop("title", f"Acme {slug}"), "route": kw.pop("route", "/index.html")}
    g.update(kw)
    g["steps"] = steps
    return g


def fill_text(n):
    """Exactly n characters of narration."""
    return ("Invoice " * (n // 8 + 1))[:n - 1] + "."


def narration(n):
    return [step(f"Acme step number {i} keeps the provider invoice list easy to follow.") for i in range(1, n + 1)]


SAYS = ["Welcome to Acme, where every provider invoice has a home.",
        "Each row shows the provider, the amount and the due date.",
        "Open one row to review the invoice before you approve it."]
TOUR = [
    step("Welcome to Acme Billing, where every provider invoice lives in one simple and tidy list.", caption="Provider invoices", highlight="#title"),
    step("Type the invoice reference in the field and the draft appears right below it, as you type.", "fill", selector="#ref", value="INV-204"),
    step("Then press add, and the new invoice joins the list with a confirmation message on top.", "click", selector="#add", waitFor="#status"),
]


def js_round(x):
    return int(math.floor(x + 0.5))


def estimate(says, holds, ms_per_char, has_next):
    """The recorder's estimate for guiones made only of `none` steps: no action time, so a step lasts its voice."""
    t = 1.75
    for say, hold in zip(says, holds):
        d = len(say) * ms_per_char / 1000
        t += max(d, min(0.6 * d, 3)) + 0.4 + hold / 1000
    return t + 0.5 + (2 if has_next else 0)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def read_json(path):
    return json.loads(read(path))


def parse_srt(text):
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.split("\n")
        m = re.fullmatch(r"(\d\d):(\d\d):(\d\d),(\d{3}) --> (\d\d):(\d\d):(\d\d),(\d{3})", lines[1]) if len(lines) >= 3 else None
        if not m:
            raise ValueError(f"bad cue block {block[:60]!r}")
        n = [int(x) for x in m.groups()]
        cues.append({"start": n[0] * 3600 + n[1] * 60 + n[2] + n[3] / 1000, "end": n[4] * 3600 + n[5] * 60 + n[6] + n[7] / 1000, "lines": lines[2:]})
    return cues


def ffprobe_json(path):
    p = subprocess.run([F.ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
                       capture_output=True, text=True)
    return json.loads(p.stdout)


def streams_by_type(path):
    return {s["codec_type"]: s for s in ffprobe_json(path)["streams"]}


def mean_volume(path):
    p = subprocess.run([F.ffmpeg, "-hide_banner", "-i", path, "-vn", "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", p.stderr)
    return float(m.group(1)) if m else None


def tree_files(base):
    for dirpath, _dirs, files in os.walk(base):
        for f in files:
            yield os.path.join(dirpath, f)


def scan_for(base, needle):
    """Files under base whose bytes hold the needle."""
    raw = needle.encode("utf-8")
    hits = []
    for f in tree_files(base):
        with open(f, "rb") as fh:
            if raw in fh.read():
                hits.append(os.path.relpath(f, base))
    return hits


# ------------------------------------------------------------------ demo app
PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Acme Billing</title>
<style>
body{margin:0;font:16px/1.5 system-ui,sans-serif;background:#f6f7f9;color:#1c2330}
header{padding:16px 24px;background:#fff;border-bottom:1px solid #d8dde6}
main{max-width:720px;padding:24px}
input,button{font:inherit;padding:8px 12px;margin:4px 0}
ul{padding:0}li{list-style:none;padding:6px 0;border-bottom:1px solid #e3e7ee}
</style></head>
<body>
<header><strong>Acme Billing</strong></header>
<main>
<h1 id="title">Provider invoices</h1>
<label for="ref">Invoice reference</label><br>
<input id="ref" autocomplete="off"> <button id="add" type="button">Add invoice</button>
<p id="draft"></p>
<p id="status" role="status"></p>
<ul id="list"><li>INV-001 - Globex Supplies - Paid</li><li>INV-002 - Initech Parts - Pending</li></ul>
<p id="query"></p>
</main>
<script>
var ref = document.getElementById('ref');
ref.addEventListener('input', function () { document.getElementById('draft').textContent = 'Draft: ' + ref.value; });
document.getElementById('add').addEventListener('click', function () {
  var li = document.createElement('li');
  li.textContent = ref.value + ' - Acme Provider - Pending';
  document.getElementById('list').prepend(li);
  document.getElementById('status').textContent = 'Invoice ' + ref.value + ' added';
});
document.getElementById('query').textContent = 'Query: ' + location.search;
</script></body></html>
"""

# The demo server: static files plus /redir, a 302 to the same app under a host name that allowHosts leaves out.
SERVER = """import functools, http.server, sys
port, root = int(sys.argv[1]), sys.argv[2]


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/redir"):
            self.send_response(302)
            self.send_header("Location", "http://localhost:%d/index.html" % port)
            self.end_headers()
            return
        super().do_GET()

    def log_message(self, *args):
        pass


http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Handler, directory=root)).serve_forever()
"""

# A page that reaches for a host outside allowHosts: the recorder must stop the run.
LEAK_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Acme Billing</title></head>
<body><h1>Provider invoices</h1><script>fetch('http://example.com/ping').catch(function () {});</script></body></html>
"""


class Demo:
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="explainer-video-demo-")
        site = os.path.join(self.dir, "site")
        os.makedirs(site)
        for name, body in (("index.html", PAGE), ("leak.html", LEAK_PAGE)):
            with open(os.path.join(site, name), "w", encoding="utf-8") as fh:
                fh.write(body)
        server = os.path.join(self.dir, "server.py")
        with open(server, "w", encoding="utf-8") as fh:
            fh.write(SERVER)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.proc = subprocess.Popen([sys.executable, "-B", server, str(self.port), site],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.url = f"http://127.0.0.1:{self.port}"
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=1).close()
                return
            except OSError:
                time.sleep(0.1)
        self.stop()
        raise RuntimeError("the demo server did not start")

    def stop(self):
        try:
            os.killpg(self.proc.pid, signal.SIGKILL)
        except OSError:
            pass
        self.proc.wait()
        shutil.rmtree(self.dir, ignore_errors=True)


_demo = None


def get_demo():
    global _demo
    if _demo is None:
        _demo = Demo()
        atexit.register(_demo.stop)
    return _demo


# ------------------------------------------------------------------ cases: schema and config (no browser)
def case_check_valid_guion_estimate(c, t):
    c.need_node()
    holds = [0, 500, 0]
    first = guion("01", "tour", [step(s, hold=h) if h else step(s) for s, h in zip(SAYS, holds)], next="02")
    second = guion("02", "approve", [step(s) for s in SAYS], next="03")
    p = c.project(guiones=[first, second])
    r = c.run("--check", cwd=p.cwd)
    t.rc(r, 0, "--check")
    lines = r.out.splitlines()
    t.eq(lines[0] if lines else None, "voice: edge:es-MX-DaliaNeural (70 ms/char)", "voice line")
    one = js_round(estimate(SAYS, holds, 70, True))
    two = js_round(estimate(SAYS, [0, 0, 0], 70, False))
    t.ok(f"OK 01 tour 3 steps ~{one}s" in lines, f"01 estimate ~{one}s (next exists: +2 s, hold +0.5 s) in {lines[1:2]}")
    t.ok(f"OK 02 approve 3 steps ~{two}s" in lines, f"02 estimate ~{two}s in {lines[1:5]}")
    t.ok(f"  warning: ~{one}s outside the 55-125 s window" in lines, "window warning for 01")
    t.ok('  warning: next "03" does not exist yet' in lines, "missing-next warning for 02")
    t.eq(lines[-1] if lines else None, "2 OK", "tally")
    only = c.run("--check", "1", cwd=p.cwd)
    t.rc(only, 0, "--check 1 (ids are padded to NN)")
    t.has(only.out, "OK 01 tour", "--check 1 selects guion 01")
    t.lacks(only.out, "OK 02", "--check 1 leaves guion 02 out")
    t.eq(only.out.splitlines()[-1] if only.out else None, "1 OK", "--check 1 tally")


def case_check_voice_pace_per_engine(c, t):
    c.need_node()
    p = c.project(guiones=[guion("01", "tour", [step(s) for s in SAYS])])
    for engine, pace, label in (("edge", 70, "edge:es-MX-DaliaNeural"), ("piper", 74, "piper:es_MX-claude-high"), ("say", 68, "say:Paulina")):
        r = c.run("--check", cwd=p.cwd, env={"REC_TTS": engine})
        t.rc(r, 0, f"--check with REC_TTS={engine}")
        lines = r.out.splitlines()
        t.eq(lines[0] if lines else None, f"voice: {label} ({pace} ms/char)", f"{engine} voice line")
        want = js_round(estimate(SAYS, [0, 0, 0], pace, False))
        t.ok(f"OK 01 tour 3 steps ~{want}s" in lines, f"{engine} estimate ~{want}s in {lines[1:2]}")
    r = c.run("--check", cwd=p.cwd, env={"REC_TTS": "say", "REC_VOICE": "Monica"})
    t.eq(r.out.splitlines()[0] if r.out else None, "voice: say:Monica (68 ms/char)", "REC_VOICE picks the voice")
    # a config voice id belongs to the engine it was written for: another engine falls back to its own default
    p.write_config({**CLOSED, "voice": {"engine": "edge", "id": "es-MX-JorgeNeural"}})
    r = c.run("--check", cwd=p.cwd)
    t.eq(r.out.splitlines()[0] if r.out else None, "voice: edge:es-MX-JorgeNeural (70 ms/char)", "config voice id")
    r = c.run("--check", cwd=p.cwd, env={"REC_TTS": "say"})
    t.eq(r.out.splitlines()[0] if r.out else None, "voice: say:Paulina (68 ms/char)", "config voice id is not carried to another engine")


def case_check_invalid_steps_count(c, t):
    c.need_node()
    p = c.project(guiones=[
        guion("01", "short", narration(2)), guion("02", "long", narration(21)),
        guion("03", "min", narration(3)), guion("04", "max", narration(20)),
    ])
    r = c.run("--check", cwd=p.cwd)
    t.rc(r, 1, "--check")
    t.has(r.err, "FAIL 01-short.json", "short guion fails")
    t.has(r.err, "  - steps must have 3 to 20 steps (has 2)", "2 steps")
    t.has(r.err, "FAIL 02-long.json", "long guion fails")
    t.has(r.err, "  - steps must have 3 to 20 steps (has 21)", "21 steps")
    t.lacks(r.err, "03-min.json", "3 steps is valid")
    t.lacks(r.err, "04-max.json", "20 steps is valid")
    t.has(r.out, "OK 03 min 3 steps", "03 reported OK")
    t.has(r.out, "OK 04 max 20 steps", "04 reported OK")
    t.eq(r.out.splitlines()[-1] if r.out else None, "2 OK, 2 FAIL", "tally")


def case_check_invalid_say_length(c, t):
    c.need_node()
    edge = step(fill_text(240), sayAs=fill_text(240), caption="c" * 60)
    p = c.project(guiones=[
        guion("01", "edge", [edge] + narration(2)),
        guion("02", "say", [step(fill_text(241))] + narration(2)),
        guion("03", "sayas", [step(fill_text(40), sayAs=fill_text(241))] + narration(2)),
        guion("04", "caption", [step(fill_text(40), caption="c" * 61)] + narration(2)),
    ])
    r = c.run("--check", cwd=p.cwd)
    t.rc(r, 1, "--check")
    t.has(r.err, "  - step 1: say has 241 characters (max 240)", "say of 241")
    t.has(r.err, "  - step 1: sayAs must be text of up to 240 characters", "sayAs of 241")
    t.has(r.err, "  - step 1: caption must be text of up to 60 characters", "caption of 61")
    t.lacks(r.err, "01-edge.json", "240 / 240 / 60 are valid")
    t.eq(r.out.splitlines()[-1] if r.out else None, "1 OK, 3 FAIL", "tally")


def case_check_strict_fields_and_placeholders(c, t):
    c.need_node()
    ok = narration(2)
    bad = {
        "01-mood.json": (guion("01", "mood", ok + [step("A third step.")], mood="calm"), ['unknown field "mood"']),
        "02-bad_slug.json": (guion("02", "Bad_Slug", narration(3)), ["slug must be lowercase letters, digits and dashes", "file must be named 02-Bad_Slug.json"]),
        "03-a.json": (guion("03", "a", narration(3)), ["id repeated in 03-a.json, 03-b.json"]),
        "03-b.json": (guion("03", "b", narration(3)), []),
        "05-route.json": (guion("05", "route", narration(3), route="invoices"), ["route must start with /"]),
        "06-max.json": (guion("06", "max", narration(3), maxSeconds=5), ["maxSeconds must be 10-300"]),
        "07-profile.json": (guion("07", "profile", narration(3), profile="ghost"), ['profile "ghost" is not in config.profiles']),
        "08-placeholders.json": (guion("08", "placeholders", [step("Today is {{today}}."), step("Fill it.", "fill", selector="#ref", value="{{nope}}"), step("Done.")]),
                                 ["say does not accept placeholders", "unknown or malformed placeholder"]),
        "09-action.json": (guion("09", "action", ok + [step("Beam me up.", "teleport")]), ['action "teleport" is not one of']),
        "10-needs.json": (guion("10", "needs", [step("No selector.", "click"), step("No value.", "fill", selector="#ref"), step("Done.")]),
                          ["click needs selector", "fill needs value"]),
        "11-goto.json": (guion("11", "goto", ok + [step("Go.", "goto", value="pricing")]), ["goto needs a path starting with / or an http(s) URL"]),
        "12-hold.json": (guion("12", "hold", ok + [step("Wait.", hold=10001)]), ["hold must be 0-10000 ms"]),
        "14-next.json": (guion("14", "next", narration(3), next="AA"), ['next "AA" is invalid']),
        "15-title.json": ({k: v for k, v in guion("15", "title", narration(3)).items() if k != "title"}, ["title is missing"]),
        "16-blur.json": (guion("16", "blur", narration(3), blur=["#a{color:red}"]), ["blur must be a list of CSS selectors without { } or ;"]),
        "17-listplaceholder.json": (guion("17", "listplaceholder", ok + [step("Upload.", "upload", selector="#ref", value=["{{env:ACME_FILE}}"])]),
                                    ["placeholders are accepted only in string values"]),
    }
    p = c.project()
    needles = []
    for file, (g, wanted) in bad.items():
        p.add(g, file=file)
        needles += wanted
    p.add("{ nope", file="13-broken.json")
    needles.append("invalid JSON")
    accepted = guion("20", "placeholders", [
        step("Accepted placeholders.", "fill", selector="#ref", value="{{env:ACME_USER}}"),
        step("Dates too.", "fill", selector="#ref", value="{{today}}"), step("Offsets.", "fill", selector="#ref", value="{{today+3}} {{ today-1 }}")])
    p.add(accepted)
    r = c.run("--check", cwd=p.cwd)
    t.rc(r, 1, "--check")
    for needle in needles:
        t.has(r.err, needle, "problem reported")
    t.lacks(r.err, "20-placeholders.json", "{{env:VAR}}, {{today}} and {{today+-N}} are valid in value")
    failed = len(bad) + 1
    t.eq(r.out.splitlines()[-1] if r.out else None, f"1 OK, {failed} FAIL", "tally")


def case_check_mail_requires_url(c, t):
    c.need_node()
    mail = guion("01", "mail", [step("Open the sign-in email.", "mail", value="user@example.com"), step("Done."), step("Really done.")])
    p = c.project(guiones=[mail])
    r = c.run("--check", cwd=p.cwd)
    t.rc(r, 1, "mail action without mail.url")
    t.has(r.err, "mail needs mail.url in the config", "message")
    p.write_config({**CLOSED, "mail": {"url": "http://localhost:1080"}})
    r = c.run("--check", cwd=p.cwd)
    t.rc(r, 0, "mail action with mail.url")
    t.eq(r.out.splitlines()[-1] if r.out else None, "1 OK", "tally")
    p.add(guion("01", "mail", [step("Open the sign-in email.", "mail", value="not-an-address"), step("Done."), step("Really done.")]))
    r = c.run("--check", cwd=p.cwd)
    t.rc(r, 1, "mail address without @")
    t.has(r.err, "mail needs the address in value", "message")
    p.write_config({**CLOSED, "mail": {"url": "mailbox"}})
    r = c.run("--check", cwd=p.cwd)
    t.rc(r, 2, "mail.url that is not a URL")
    t.has(r.err, "mail must be {url}", "message")
    # the mail host is guarded like every other host, before anything opens
    p.add(mail)
    p.write_config({**CLOSED, "mail": {"url": "http://mail.example.com:1080"}})
    r = c.run("--dry", "01", cwd=p.cwd)
    t.rc(r, 2, "mail.url outside allowHosts")
    t.has(r.err, "mail.url http://mail.example.com:1080 is outside allowHosts", "message")


def case_config_defaults_and_overrides(c, t):
    c.need_node()
    # the decoy sits where a cwd-anchored default would look: it must never be read
    decoy = os.path.join(c.root, "guiones")
    os.makedirs(decoy)
    with open(os.path.join(decoy, "99-decoy.json"), "w") as fh:
        fh.write("{ nope")
    p = c.project(guiones=[guion("01", "tour", narration(3))])
    rel_config = os.path.join("proj", "videos", "config.json")
    r = c.run("--check", "--config", rel_config, cwd=c.root)
    t.rc(r, 0, "foreign cwd, --config relative to the cwd")
    t.has(r.out, "OK 01 tour 3 steps", "guionesDir default is anchored to the config directory")
    t.lacks(r.out + r.err, "decoy", "the cwd's guiones/ is never read")
    t.has(r.out, "voice: edge:es-MX-DaliaNeural (70 ms/char)", "default voice")
    t.has(r.out, "outside the 55-125 s window", "default durationWindow")
    r = c.run("--verify", "01", "--config", rel_config, cwd=c.root)
    t.rc(r, 1, "--verify with nothing recorded")
    t.has(r.err, os.path.join("proj", "videos", "out", "mp4", "01-tour.mp4"), "outDir default is anchored to the config directory")
    t.ok(os.path.isfile(p.path("manifest.json")) and read_json(p.path("manifest.json")) == [], "manifest.json written under <config dir>/out")
    t.ok(not os.path.exists(os.path.join(c.root, "out")) and not os.path.exists(os.path.join(c.root, "videos")), "nothing is created under the cwd")
    r = c.run("--check", cwd=p.cwd)
    t.rc(r, 0, "default --config is videos/config.json")
    r = c.run("--check", cwd=c.root)
    t.rc(r, 2, "no config at the default path")
    t.has(r.err, "config not found", "message")
    r = c.run("--check", "--config", "config.json", cwd=p.videos)
    t.rc(r, 0, "--config relative to a cwd inside the project")
    t.has(r.out, "OK 01 tour", "guiones still found next to the config")
    p.write_config({**CLOSED, "guionesDir": "episodes", "outDir": "render", "durationWindow": [30, 40],
                    "voice": {"engine": "edge", "id": "es-MX-JorgeNeural", "rate": "-10%"}}, name="alt.json")
    p.add(guion("07", "alt", narration(3)), directory=os.path.join(p.videos, "episodes"))
    alt = f"--config={os.path.join('proj', 'videos', 'alt.json')}"
    r = c.run("--check", alt, cwd=c.root)
    t.rc(r, 0, "overrides")
    t.has(r.out, "OK 07 alt 3 steps", "guionesDir override")
    t.lacks(r.out, "OK 01", "the default guiones dir is not read when overridden")
    t.has(r.out, "voice: edge:es-MX-JorgeNeural (70 ms/char)", "voice.id override")
    t.has(r.out, "outside the 30-40 s window", "durationWindow override")
    c.run("--verify", "07", alt, cwd=c.root)
    t.ok(os.path.isfile(os.path.join(p.videos, "render", "manifest.json")), "outDir override")


def case_config_strict_keys(c, t):
    c.need_node()
    p = c.project(guiones=[guion("01", "tour", narration(3))])
    base = dict(CLOSED)
    bad = [
        ({**base, "frobnicate": 1}, 'unknown key "frobnicate"'),
        ({}, "baseUrl must be an http(s) URL"),
        ({"baseUrl": "ftp://localhost"}, "baseUrl must be an http(s) URL"),
        ({**base, "brand": {"accent": "red"}}, "brand must be {accent, bg} as #rrggbb"),
        ({**base, "brand": {"accent": "#3B82F6", "fg": "#ffffff"}}, "brand must be {accent, bg} as #rrggbb"),
        ({**base, "voice": {"pitch": 3}}, 'voice: unknown key "pitch"'),
        ({**base, "voice": {"engine": "azure"}}, "voice.engine must be edge|piper|say"),
        ({**base, "timezone": "Mars/Base"}, "timezone must be an IANA zone"),
        ({**base, "allowHosts": []}, "allowHosts must be a non-empty list of host names"),
        ({**base, "durationWindow": [125, 55]}, "durationWindow must be [minSeconds, maxSeconds]"),
        ({**base, "fallbacks": ["azure"]}, "fallbacks must be a list of edge|piper|say"),
        ({**base, "viewport": {"width": 0, "height": 800}}, "viewport must be {width, height} in pixels"),
        ({**base, "mail": {"url": "http://localhost:1080", "extra": 1}}, "mail must be {url}"),
        ({**base, "fonts": ['Acme"}body{x:y']}, "fonts must be a list of font family names without quotes"),
        ({**base, "setup": [{"action": "scroll"}]}, "setup[0]: action must be"),
        ({**base, "profiles": {"admin": {"user": "x"}}}, "profiles.admin must be {setup}"),
        ("{", "invalid JSON"),
        ("[]", "the config must be a JSON object"),
    ]
    for cfg, needle in bad:
        p.write_config(cfg)
        r = c.run("--check", cwd=p.cwd)
        t.rc(r, 2, f"config {needle!r}")
        t.has(r.err, needle, "message")
    # everything optional set at once: accepted (the files it names are only needed when recording / verifying)
    p.write_config({**base, "allowHosts": ["localhost", "127.0.0.1", "app.example.com"], "fonts": ["Acme Sans"], "denyList": "deny.txt",
                    "pronunciation": {"Acme": "Akmee"}, "mail": {"url": "http://localhost:1080"},
                    "setup": [{"action": "goto", "value": "/login"}, {"action": "fill", "selector": "#user", "value": "{{env:ACME_USER}}"}],
                    "profiles": {"admin": {"setup": []}, "anonymous": {}}})
    r = c.run("--check", cwd=p.cwd)
    t.rc(r, 0, "a config with every optional key")


def case_templates_accepted(c, t):
    c.need_node()
    tdir = os.path.join(F.skill_dir, "templates")
    cfg_file, guion_file = os.path.join(tdir, "config.json.tmpl"), os.path.join(tdir, "guion.json.tmpl")
    if not (os.path.isfile(cfg_file) and os.path.isfile(guion_file)):
        raise Skip("templates/ not found next to the script")
    cfg, g = read_json(cfg_file), read_json(guion_file)
    t.eq(sorted(set(cfg) - set(CONTRACT_KEYS)), [], "config template keys outside the contract")
    # denyList and mail have no JSON default: the recorder rejects an explicit null, so the template leaves them out
    t.eq(sorted(set(CONTRACT_KEYS) - set(cfg) - {"denyList", "mail"}), [], "contract keys missing from the config template")
    for key, want in CONFIG_DEFAULTS.items():
        if key in cfg:
            t.eq(cfg[key], want, f"config template default for {key}")
    t.ok(isinstance(cfg.get("baseUrl"), str) and cfg["baseUrl"].startswith("http://localhost"), "baseUrl is a localhost example")
    steps = g.get("steps") or []
    t.eq(len(steps), 4, "guion template steps")
    t.eq(sorted(set(STEP_KEYS) - {k for s in steps for k in s}), [], "step keys the guion template does not show")
    p = c.project(config=cfg)
    p.add(g)
    r = c.run("--check", cwd=p.cwd)
    t.rc(r, 0, "--check on the templates")
    t.has(r.out, f"OK {g['id']} {g['slug']} 4 steps", "template guion is valid")
    t.lacks(r.out, "warning", "the shipped example sits inside the duration window")


def case_doctor_shape(c, t):
    c.need_node()
    r = c.run("--doctor", "--config", os.path.join(c.root, "none.json"))
    lines = r.out.splitlines()
    t.eq(len(lines), 8, f"doctor lines (7 items + DOCTOR): {lines}")
    for item, line in zip(DOCTOR_ITEMS, lines):
        t.ok((line.startswith(f"ok {item} (") and line.endswith(")")) or line.startswith(f"missing {item} — "), f"line for {item}: {line[:90]!r}")
    ready = len(lines) == 8 and all(x.startswith("ok ") for x in lines[:7])
    t.eq(lines[-1] if lines else None, "DOCTOR: ready" if ready else "DOCTOR: not ready", "final line follows the items")
    t.eq(r.rc, 0 if ready else 2, "exit code follows the final line (0 ready, 2 not ready)")
    # the config is read when it exists: its voice engine is the one reported
    path = os.path.join(c.root, "voice.json")
    with open(path, "w") as fh:
        json.dump({"voice": {"engine": "say"}}, fh)
    r = c.run("--doctor", "--config", path)
    voice = next((x for x in r.out.splitlines() if " voice engine " in x), "")
    t.has(voice, "say", "voice engine line from the config")


def case_doctor_voice_missing_recipe(c, t):
    c.need_node()
    config = os.path.join(c.root, "none.json")
    r = c.run("--doctor", "--config", config, env={"REC_TTS_HOME": "/nonexistent", "REC_TTS": "edge"})
    t.rc(r, 2, "--doctor with a voice home that does not exist")
    lines = r.out.splitlines()
    home = next((x for x in lines if x.startswith("missing voice home")), None)
    t.ok(home is not None, f"a `missing voice home` line in {lines[5:7]}")
    if home:
        t.ok(home.startswith("missing voice home — /nonexistent does not exist: "), f"home line: {home[:100]!r}")
        t.has(home, "python3 -m venv", "recipe creates the venv")
        t.has(home, "REC_TTS_HOME", "recipe names REC_TTS_HOME")
        t.has(home, "adcm-voz", "recipe uses the default voice home name")
    t.eq(lines[-1] if lines else None, "DOCTOR: not ready", "final line")
    r = c.run("--doctor", "--config", config, env={"REC_TTS_HOME": "/nonexistent", "REC_TTS": "say"})
    t.ok(any(x.startswith("ok voice home (not needed for say)") for x in r.out.splitlines()), "say needs no voice home")


STUB_ENGINE = """#!/bin/sh
if [ "$1" = "--version" ]; then echo "stub 0.0"; exit 0; fi
echo "stub: handshake refused (403)" >&2
exit 1
"""


def edge_resolves():
    try:
        socket.getaddrinfo("speech.platform.bing.com", 443)
        return True
    except OSError:
        return False


def case_doctor_synthesis_failed(c, t):
    c.need_node()
    home = os.path.join(c.root, "voice-home")
    venv_bin = os.path.join(home, "venv", "bin")
    os.makedirs(venv_bin)
    os.makedirs(os.path.join(home, "voces"))
    for model in ("es_MX-claude-high.onnx", "es_MX-claude-high.onnx.json"):
        open(os.path.join(home, "voces", model), "w").close()
    for engine in ("edge-tts", "piper"):
        stub = os.path.join(venv_bin, engine)
        with open(stub, "w") as fh:
            fh.write(STUB_ENGINE)
        os.chmod(stub, 0o755)
    config = os.path.join(c.root, "none.json")
    p = c.project(guiones=[guion("01", "tour", narration(3))])
    engines = [("piper", "pip install -U piper-tts in the voice venv, or set REC_TTS=edge|say")]
    if edge_resolves():
        engines.insert(0, ("edge", "pip install -U edge-tts in the voice venv, or set REC_TTS=piper|say"))
    for engine, fix in engines:
        env = {"REC_TTS_HOME": home, "REC_TTS": engine}
        r = c.run("--doctor", "--config", config, env=env)
        t.rc(r, 2, f"--doctor with an {engine} that is installed but cannot synthesize")
        lines = r.out.splitlines()
        voice = next((x for x in lines if x.startswith("missing voice engine")), "")
        t.ok(voice.startswith(f"missing voice engine — {engine} is installed but synthesis failed ("), f"{engine} voice line: {voice[:110]!r}")
        t.has(voice, "stub: handshake refused (403)", f"{engine}: the reason is shown")
        t.ok(voice.endswith(f"): {fix}"), f"{engine}: the fix names the upgrade and the other engines: {voice[-90:]!r}")
        t.eq(len(lines), 8, f"{engine}: the doctor still prints 7 items and the verdict")
        t.eq(lines[-1] if lines else None, "DOCTOR: not ready", f"{engine}: final line")
        r = c.run("01", cwd=p.cwd, env=env)
        t.rc(r, 2, f"recording with an {engine} that cannot synthesize")
        t.has(r.err, f"voice not ready: {engine} is installed but synthesis failed", f"{engine}: stops before the browser opens")
        t.ok(not os.path.exists(p.path("mp4")), f"{engine}: no mp4")
    if not any(e == "edge" for e, _ in engines) and not t.problems:
        raise Skip("no DNS answer for the edge endpoint: only the piper stub was exercised")


def old_node():
    """A Node 18 or 19 from nvm, or None: the range the recorder can start in and refuses."""
    found = sorted(glob.glob(os.path.join(os.path.expanduser("~"), ".nvm", "versions", "node", "v1[89].*", "bin")), key=nvm_version)
    return os.path.join(found[-1], "node") if found and os.access(os.path.join(found[-1], "node"), os.X_OK) else None


def case_doctor_old_node(c, t):
    c.need_node()
    exe = old_node()
    if not exe:
        raise Skip("no Node 18 or 19 under ~/.nvm to start the recorder with")
    r = spawn([exe, F.script, "--doctor", "--config", os.path.join(c.root, "none.json")], F.env(), c.root, 180)
    t.rc(r, 2, "--doctor under Node < 20")
    lines = r.out.splitlines()
    t.eq(len(lines), 8, f"doctor lines under Node < 20: {lines}")
    for item, line in zip(DOCTOR_ITEMS, lines):
        t.ok(line.startswith(f"ok {item} (") or line.startswith(f"missing {item} — "), f"line for {item}: {line[:90]!r}")
    t.ok(bool(lines) and lines[0].startswith("missing node>=20 — found "), f"node line: {lines[:1]}")
    t.eq(lines[1] if len(lines) > 1 else None, "missing playwright-core>=1.61 — not checked: needs node>=20", "playwright-core is not loaded")
    t.eq(lines[2] if len(lines) > 2 else None, "missing browser channel — not checked: needs node>=20", "the browser is not probed")
    t.eq(lines[-1] if lines else None, "DOCTOR: not ready", "final line")


def case_usage_exit_64(c, t):
    c.need_node()
    p = c.project(guiones=[guion("01", "tour", narration(3))])
    vectors = [
        ([], "give ids or --all"),
        (["--bogus"], 'unrecognized argument "--bogus"'),
        (["123"], 'unrecognized argument "123"'),
        (["--check", "--dry"], "are mutually exclusive"),
        (["--dry", "--verify", "01"], "are mutually exclusive"),
        (["--mute", "--check"], "--mute only applies to recording"),
        (["--mute", "--verify", "01"], "--mute only applies to recording"),
        (["--doctor", "01"], "--doctor takes no ids"),
        (["--doctor", "--all"], "--doctor takes no ids"),
        (["--all", "01"], "give ids or --all, not both"),
        (["--dry"], "give ids or --all"),
        (["--verify"], "give ids or --all"),
        (["--config"], "--config needs a path"),
        (["--config="], "--config needs a path"),
        (["--check", "99"], "no guion with id 99"),
        (["99", "--mute"], "no guion with id 99"),
    ]
    for args, needle in vectors:
        r = c.run(*args, cwd=p.cwd)
        t.rc(r, 64, f"record.mjs {' '.join(args)}")
        t.ok(r.err.startswith("usage: record.mjs "), f"{args}: stderr starts with the usage line, got {r.err[:50]!r}")
        t.has(r.err, "record.mjs: error: ", f"{args}: error line")
        t.has(r.err, needle, f"{args}: message")
    for flag in ("--help", "-h"):
        r = c.run(flag, cwd=p.cwd)
        t.rc(r, 0, flag)
        t.ok(r.out.startswith("usage: record.mjs "), f"{flag}: usage first, got {r.out[:40]!r}")
        t.has(r.out, "Exit: 0 ok", f"{flag}: exit code legend")


def case_env_placeholder_unset_exit_2(c, t):
    c.need_node()
    g = guion("01", "secret", [step("Open the form.", "none"), step("Fill the field.", "fill", selector="#ref", value="{{env:DEMO_SECRET}}"), step("Done.")])
    p = c.project(guiones=[g])
    for mode in (["--dry", "01"], ["01", "--mute"]):
        for label, env in (("unset", {"DEMO_SECRET": None}), ("empty", {"DEMO_SECRET": ""})):
            r = c.run(*mode, cwd=p.cwd, env=env)
            t.rc(r, 2, f"{' '.join(mode)} with DEMO_SECRET {label}")
            t.has(r.err, "environment variable DEMO_SECRET is not set", f"{label}: message")
    t.ok(not os.path.exists(p.path("mp4")), "no recording before the variable resolves")
    # a setup step is resolved the same way, before any browser opens
    p.write_config({**CLOSED, "setup": [{"action": "fill", "selector": "#user", "value": "{{env:DEMO_SETUP}}"}]})
    p.add(guion("01", "secret", narration(3)))
    r = c.run("--dry", "01", cwd=p.cwd, env={"DEMO_SETUP": None})
    t.rc(r, 2, "config.setup placeholder unset")
    t.has(r.err, "DEMO_SETUP is not set", "message")


def case_allowhosts_blocks_offlist(c, t):
    c.need_node()
    plain = guion("01", "tour", narration(3))
    p = c.project(config={"baseUrl": "http://example.com"}, guiones=[plain])
    r = c.record(p, "01")
    t.rc(r, 2, "baseUrl outside allowHosts")
    t.has(r.err, "baseUrl http://example.com is outside allowHosts (localhost, 127.0.0.1)", "message")
    t.ok(not os.path.exists(p.path("mp4")) and not os.path.exists(p.path(".lock")), "no mp4 and no lock")
    p = c.project(guiones=[guion("01", "tour", [step("Open it.", "none"), step("Go elsewhere.", "goto", value="https://example.com/pricing"), step("Done.")])])
    r = c.record(p, "01")
    t.rc(r, 2, "goto outside allowHosts")
    t.has(r.err, "guion 01: goto https://example.com/pricing is outside allowHosts", "message")
    t.ok(not os.path.exists(p.path("mp4")), "no mp4")
    r = c.run("--dry", "01", cwd=p.cwd)
    t.rc(r, 2, "--dry applies the same guard")
    p = c.project(config={**CLOSED, "setup": [{"action": "goto", "value": "https://example.org/login"}]}, guiones=[plain])
    r = c.record(p, "01")
    t.rc(r, 2, "setup goto outside allowHosts")
    t.has(r.err, "is outside allowHosts", "message")
    # listing the host makes the same goto pass the guard: the run then stops at the closed port, not at the guard
    p = c.project(config={**CLOSED, "allowHosts": ["localhost", "127.0.0.1", "example.com"]},
                  guiones=[guion("01", "tour", [step("Open it.", "none"), step("Go there.", "goto", value="https://example.com/pricing"), step("Done.")])])
    r = c.record(p, "01")
    t.lacks(r.err, "outside allowHosts", "an allowed host passes the guard")
    t.ok(r.rc in (2, 4), f"stops at the closed port or the playwright check, not at the guard: exit {r.rc}")


def case_mux_from_synthetic_inputs(c, t):
    c.need_media()
    mp4 = build_mp4(c, os.path.join(c.root, "mux"))
    info = ffprobe_json(mp4["path"])
    kinds = {s["codec_type"]: s for s in info["streams"]}
    v, a, s = kinds.get("video", {}), kinds.get("audio", {}), kinds.get("subtitle", {})
    t.eq((v.get("codec_name"), v.get("width"), v.get("height"), v.get("r_frame_rate")), ("h264", 1280, 800, "25/1"), "video stream")
    t.eq(a.get("codec_name"), "aac", "audio codec")
    t.eq(s.get("codec_name"), "mov_text", "subtitle codec")
    t.eq((s.get("tags") or {}).get("language"), "spa", "mov_text language from the es-MX locale")
    dur = float(info["format"]["duration"])
    t.ok(5.8 <= dur <= 6.3, f"container lasts the video ({dur:.2f} s)")
    a_dur = float(a.get("duration") or 0)
    t.ok(3.4 <= a_dur <= dur + 0.05, f"audio spans the second clip's delay: {a_dur:.2f} s")
    with open(mp4["path"], "rb") as fh:
        head = fh.read(65536)
    t.ok(0 <= head.find(b"moov") < head.find(b"mdat") or head.find(b"mdat") < 0, "faststart: moov before mdat")
    t.eq(mp4["report"]["problems"], [], "verifyMp4 on the muxed file")
    t.eq(mp4["report"]["langs"], {"es-MX": "spa", "en-US": "eng", "pt-BR": "por", "fr-FR": "fra", "zz": "und"}, "subtitle languages")


def case_verify_manifest_accumulates(c, t):
    c.need_media()
    built = build_mp4(c, os.path.join(c.root, "mux"))
    p = c.project(config={**CLOSED, "durationWindow": [4, 60]}, guiones=[guion(i, s, narration(3)) for i, s in (("01", "alpha"), ("02", "beta"), ("03", "gamma"))])
    for tag in ("01-alpha", "02-beta"):
        place_outputs(p, tag, built["path"])
    manifest = p.path("manifest.json")
    r = c.run("--verify", "02", cwd=p.cwd)
    t.rc(r, 0, "--verify 02")
    t.has(r.out, "OK 02 h264+aac+mov_text", "verify line")
    t.eq([m["id"] for m in read_json(manifest)], ["02"], "manifest after 02")
    r = c.run("--verify", "01", cwd=p.cwd)
    t.rc(r, 0, "--verify 01")
    entries = read_json(manifest)
    t.eq([m["id"] for m in entries], ["01", "02"], "manifest keeps 02 and sorts by id")
    t.eq(sorted(entries[0]), ["bytes", "duration", "id", "sha256", "slug", "title"], "manifest keys")
    mp4 = p.path("mp4", "01-alpha.mp4")
    t.eq(entries[0]["sha256"], hashlib.sha256(open(mp4, "rb").read()).hexdigest(), "sha256 of the mp4")
    t.eq(entries[0]["bytes"], os.path.getsize(mp4), "bytes of the mp4")
    t.eq((entries[0]["slug"], entries[0]["title"]), ("alpha", "Acme alpha"), "slug and title come from the guion")
    t.ok(abs(entries[0]["duration"] - 6.0) < 0.3, f"duration {entries[0]['duration']}")
    os.remove(os.path.join(p.guiones, "02-beta.json"))
    c.run("--verify", "01", cwd=p.cwd)
    t.eq([m["id"] for m in read_json(manifest)], ["01"], "an entry whose guion is gone is dropped")
    r = c.run("--verify", "03", cwd=p.cwd)
    t.rc(r, 1, "--verify of a guion with no outputs")
    t.has(r.err, "FAIL 03 gamma: missing mp4", "message")
    t.eq([m["id"] for m in read_json(manifest)], ["01"], "a failed id never enters the manifest")
    lock = p.path(".lock")
    with open(lock, "w") as fh:
        fh.write(str(os.getpid()))
    r = c.run("--verify", "01", cwd=p.cwd)
    t.rc(r, 2, "--verify while a recorder holds the lock")
    t.has(r.err, f"another recorder is running (pid {os.getpid()})", "message")
    dead = subprocess.Popen([sys.executable, "-B", "-c", "pass"])
    dead.wait()
    with open(lock, "w") as fh:
        fh.write(str(dead.pid))
    r = c.run("--verify", "01", cwd=p.cwd)
    t.rc(r, 0, "--verify with a stale lock")


def case_denylist_hits(c, t):
    c.need_media()
    built = build_mp4(c, os.path.join(c.root, "mux"))
    p = c.project(config={**CLOSED, "durationWindow": [4, 60], "denyList": "deny.txt"}, guiones=[guion("01", "alpha", narration(3))])
    place_outputs(p, "01-alpha", built["path"])
    r = c.run("--verify", "01", cwd=p.cwd)
    t.rc(r, 2, "denyList file missing")
    t.has(r.err, "denyList not found", "message")
    with open(os.path.join(p.videos, "deny.txt"), "w") as fh:
        fh.write("# comments and blank lines are not patterns\n\nforbidden-word\n")
    r = c.run("--verify", "01", cwd=p.cwd)
    t.rc(r, 0, "clean outputs")
    t.has(r.out, "deny=0", "no hits")
    with open(p.path("srt", "01-alpha.srt"), "w") as fh:
        fh.write("1\n00:00:01,000 --> 00:00:03,000\nThis line carries a Forbidden-Word in the subtitle.\n")
    r = c.run("--verify", "01", cwd=p.cwd)
    t.rc(r, 1, "a hit in the srt")
    t.has(r.err, "deny-list: 1 hit(s) in", "message")
    t.ok("forbidden-word" not in r.text.lower(), "the matched text is never printed")


def case_launcher_exec_and_help(c, t):
    c.need_node()
    launcher = os.path.join(F.plugin_root, "bin", "explainer-record") if F.plugin_root else ""
    if not os.path.isfile(launcher):
        raise Skip("no bin/explainer-record next to the script")
    t.ok(os.access(launcher, os.X_OK), "bin/explainer-record is executable")
    head = read(launcher).splitlines()[:2]
    t.eq(head, ["#!/bin/sh", "set -e"], "POSIX sh with set -e")
    env = F.env()
    r = spawn([launcher, "--help"], env, c.root, 60)
    t.rc(r, 0, "launcher --help")
    t.ok(r.out.startswith("usage: record.mjs "), f"--help prints the recorder usage, got {r.out[:40]!r}")
    r = spawn([launcher, "--bogus"], env, c.root, 60)
    t.rc(r, 64, "the launcher passes the recorder's exit code through")
    link = os.path.join(c.root, "linked-record")
    os.symlink(launcher, link)
    r = spawn([link, "--help"], env, c.root, 60)
    t.rc(r, 0, "launcher through a symlink")
    t.ok(r.out.startswith("usage: record.mjs "), "the symlink resolves to the plugin root")
    if F.node_source == "nvm":
        # no node on PATH at all: the shim must find the nvm one
        bare = dict(env, PATH="/usr/bin:/bin")
        r = spawn([launcher, "--help"], bare, c.root, 60)
        t.rc(r, 0, "launcher with a bare PATH finds nvm's node")
    # version order, not text order: v20.10.0 is newer than v20.9.0 (and v100 would beat v99)
    fake = os.path.join(c.root, "fake-home")
    for version in ("v20.9.0", "v20.10.0"):
        node_dir = os.path.join(fake, ".nvm", "versions", "node", version, "bin")
        os.makedirs(node_dir)
        with open(os.path.join(node_dir, "node"), "w") as fh:
            fh.write(f"#!/bin/sh\necho picked-{version}\n")
        os.chmod(os.path.join(node_dir, "node"), 0o755)
    r = spawn([launcher, "--help"], dict(env, HOME=fake, PATH="/usr/bin:/bin"), c.root, 60)
    t.eq(r.out.strip(), "picked-v20.10.0", "the launcher picks the newest nvm v2x by version")


def case_no_package_json(c, t):
    banned = ("package.json", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml")
    roots = [F.skill_dir] + ([F.plugin_root] if F.plugin_root else [])
    found = []
    for base in roots:
        for dirpath, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d != ".git"]
            found += [os.path.join(dirpath, d) for d in dirs if d == "node_modules"]
            found += [os.path.join(dirpath, f) for f in files if f in banned]
    t.eq(sorted(set(found)), [], "dependency manifests in the skill or the plugin")


# ------------------------------------------------------------------ fabricated outputs
MUX_JS = """const [mediaUrl, video, clip, srt, out, locale] = process.argv.slice(2);
const media = await import(mediaUrl);
await media.mux({ video, clips: [{ file: clip, at: 0.5 }, { file: clip, at: 2 }], srt, out, language: media.subtitleLanguage(locale) });
const langs = Object.fromEntries(['es-MX', 'en-US', 'pt-BR', 'fr-FR', 'zz'].map((l) => [l, media.subtitleLanguage(l)]));
const report = await media.verifyMp4(out, { viewport: { width: 1280, height: 800 }, window: [1, 60] });
console.log(JSON.stringify({ langs, problems: report.problems }));
"""


def build_mp4(c, directory, seconds=6):
    """Synthetic video (lavfi testsrc) + a sine clip + a two-cue srt, muxed by the recorder's own mux()."""
    os.makedirs(directory, exist_ok=True)
    video, clip, srt, out = (os.path.join(directory, n) for n in ("video.mkv", "clip.wav", "cues.srt", "out.mp4"))
    quiet = [F.ffmpeg, "-y", "-v", "error"]
    for cmd in (quiet + ["-f", "lavfi", "-i", "testsrc=size=1280x800:rate=25", "-t", str(seconds), "-c:v", "libx264", "-pix_fmt", "yuv420p", video],
                quiet + ["-f", "lavfi", "-i", "sine=frequency=440:duration=1.5:sample_rate=48000", "-ac", "1", clip]):
        subprocess.run(cmd, check=True, capture_output=True)
    with open(srt, "w", encoding="utf-8") as fh:
        fh.write("1\n00:00:01,000 --> 00:00:03,000\nFirst cue\n\n2\n00:00:03,500 --> 00:00:05,000\nSecond cue\n")
    helper = os.path.join(directory, "mux-helper.mjs")
    with open(helper, "w", encoding="utf-8") as fh:
        fh.write(MUX_JS)
    media_url = pathlib.Path(os.path.join(os.path.dirname(F.script), "lib", "media.mjs")).as_uri()
    r = spawn([F.node, helper, media_url, video, clip, srt, out, "es-MX"], F.env(), directory, 180)
    if r.rc != 0:
        raise RuntimeError(f"mux helper failed: {tail(r.text)}")
    return {"path": out, "report": json.loads(r.out)}


def place_outputs(p, tag, mp4):
    """The five files --verify wants for <tag>, with the muxed file as the mp4."""
    files = {"mp4": ("mp4", "mp4"), "srt": ("srt", "srt"), "posters": ("posters", "png"), "sheets": ("sheets", "png"), "dom": ("dom", "txt")}
    for kind, (folder, ext) in files.items():
        os.makedirs(p.path(folder), exist_ok=True)
        dest = p.path(folder, f"{tag}.{ext}")
        if kind == "mp4":
            shutil.copy(mp4, dest)
        else:
            with open(dest, "w", encoding="utf-8") as fh:
                fh.write("1\n00:00:01,000 --> 00:00:03,000\nFirst cue\n" if kind == "srt" else f"{kind} of {tag}\n")


# ------------------------------------------------------------------ cases: recording (browser)
def case_dry_failed_step_exit_1(c, t):
    c.need_browser()
    bad = [step("Open the list.", "none"), step("Press a button that cannot be selected.", "click", selector="css=#a["), step("Never reached.")]
    p = c.project(config=c.live(), guiones=[guion("01", "tour", TOUR), guion("02", "broken", bad)])
    r = c.run("--dry", "01", cwd=p.cwd)
    t.rc(r, 0, "--dry on a good guion")
    t.has(r.out, "OK dry 01 tour 3 steps", "dry result")
    r = c.run("--dry", "02", cwd=p.cwd)
    t.rc(r, 1, "--dry with a step that fails")
    t.has(r.err, "step 2/3 (click css=#a[)", "the failing step is named")
    t.ok(not os.path.exists(p.path(".lock")), "the lock is released after a failure")
    t.ok(not os.path.exists(p.path("mp4")), "no mp4")
    p.write_config(c.live(setup=[{"action": "fill", "selector": "#nope", "value": "x"}]))
    r = c.run("--dry", "01", cwd=p.cwd)
    t.rc(r, 1, "--dry with a setup step that fails")
    t.has(r.err, "setup[0] (fill #nope)", "the failing setup step is named")
    t.lacks(r.err, "\x1b", "no terminal escapes in the message")


def case_allowhosts_blocks_redirect(c, t):
    c.need_browser()
    # allowHosts lists 127.0.0.1 only: /redir answers 302 to the same app under `localhost`
    cfg = c.live(allowHosts=["127.0.0.1"])
    p = c.project(config=cfg, guiones=[guion("01", "bounce", narration(3), route="/redir")])
    r = c.record(p, "01")
    t.rc(r, 2, "a route that redirects outside allowHosts")
    t.has(r.err, "outside allowHosts", "message")
    t.has(r.err, "localhost", "the redirect target is named")
    t.ok(not os.path.isdir(p.path("mp4")) or not os.listdir(p.path("mp4")), "no mp4")
    t.ok(not os.path.exists(p.path(".lock")), "the lock is released")
    steps = [step("Open the list.", "none"), step("Follow a link that bounces elsewhere.", "goto", value="/redir"), step("Done.")]
    p = c.project(config=cfg, guiones=[guion("01", "bounce", steps)])
    r = c.run("--dry", "01", cwd=p.cwd)
    t.rc(r, 2, "--dry: a goto that redirects outside allowHosts")
    t.has(r.err, "outside allowHosts", "message")


def case_allowhosts_blocks_page_request(c, t):
    c.need_browser()
    p = c.project(config=c.live(), guiones=[guion("01", "leak", narration(3), route="/leak.html")])
    r = c.record(p, "01")
    t.rc(r, 2, "a page that requests a host outside allowHosts")
    t.has(r.err, "outside allowHosts", "message")
    t.has(r.err, "example.com", "the blocked host is named")
    t.ok(not os.path.isdir(p.path("mp4")) or not os.listdir(p.path("mp4")), "no mp4")
    t.ok(not os.path.exists(p.path(".lock")), "the lock is released")


def case_lock_busy_exit_2(c, t):
    c.need_browser()
    p = c.project(config=c.live(), guiones=[guion("01", "tour", TOUR)])
    os.makedirs(p.out, exist_ok=True)
    with open(p.path(".lock"), "w") as fh:
        fh.write(str(os.getpid()))
    r = c.record(p, "01")
    t.rc(r, 2, "recording while another recorder holds the lock")
    t.has(r.err, f"another recorder is running (pid {os.getpid()})", "message")
    t.eq(read(p.path(".lock")), str(os.getpid()), "the foreign lock is left alone")
    t.ok(not os.path.exists(p.path("mp4")), "no mp4")


def case_redaction_env_placeholder(c, t):
    c.need_browser()
    secret = "sec" + hashlib.sha256(os.urandom(16)).hexdigest()[:20]
    # a space, an at sign, a slash and a non-ASCII letter: the address bar shows it percent-encoded
    spicy = f"s3c {hashlib.sha256(os.urandom(16)).hexdigest()[:10]} p@ss/ñ"
    spicy_forms = [spicy, urllib.parse.quote(spicy, safe="@/"), urllib.parse.quote(spicy, safe=""), urllib.parse.quote_plus(spicy, safe="")]
    link_value = hashlib.sha256(os.urandom(16)).hexdigest()[:16]
    steps = [
        step("Welcome to Acme Billing, where every provider invoice lives in one simple list.", caption="Provider invoices"),
        step("Now we fill the reference with a value that must never be shown or written down.", "fill", selector="#ref", value="{{env:DEMO_SECRET}}"),
        step("Dates in a guion follow the configured timezone and can move forward or back.", "fill", selector="#ref", value="{{today+3}}"),
        step("A link with an access value in its address is cleaned before it is written anywhere.", "goto", value=f"/index.html?token={link_value}"),
        step("The same goes for a secret that travels percent-encoded in the address of the page.", "goto", value="/index.html?pw={{env:DEMO_SPICY}}"),
    ]
    p = c.project(config=c.live(), guiones=[guion("01", "secret", steps)])
    r = c.record(p, "01", env={"DEMO_SECRET": secret, "DEMO_SPICY": spicy})
    t.rc(r, 0, "recording with {{env:DEMO_SECRET}}")
    t.lacks(r.text, secret, "console output")
    t.lacks(r.text, link_value, "console output (token)")
    t.eq(scan_for(p.out, secret), [], "output files holding the secret")
    t.eq(scan_for(p.out, link_value), [], "output files holding the token value")
    for form in spicy_forms:
        t.lacks(r.text, form, f"console output ({form!r})")
        t.eq(scan_for(p.out, form), [], f"output files holding {form!r}")
    dom_file = p.path("dom", "01-secret.txt")
    if os.path.isfile(dom_file):
        dom = read(dom_file)
        t.has(dom, "Draft: ***", "the secret reads *** in the dom dump")
        t.has(dom, "token=***", "the token reads *** in the dom dump")
        t.has(dom, "pw=***", "the percent-encoded secret reads *** in the dom dump")
        try:
            from zoneinfo import ZoneInfo
            want = (datetime.now(timezone.utc) + timedelta(days=3)).astimezone(ZoneInfo("America/Mexico_City")).strftime("%Y-%m-%d")
            t.has(dom, f"Draft: {want}", "{{today+3}} in the config timezone")
        except (ImportError, KeyError, OSError):
            pass
    else:
        t.ok(False, "no dom dump to inspect")


def case_srt_cue_splitting(c, t):
    c.need_browser()
    first = "Acme keeps every provider invoice in one tidy list. Open an invoice to see the amount, the due date and the status. Then approve it."
    second = ("When the invoice is complete, check the supplier, the tax and the total at the bottom of the page, "
              "and then confirm the payment date with the Acmeville finance team before you approve it.")
    third, third_as = "The reference looks like INV-204 and it never repeats.", "The reference looks like I N V, two zero four, and it never repeats."
    steps = [step(first, caption="Sentences"), step(second, caption="One long sentence"), step(third, sayAs=third_as, caption="Spoken apart")]
    p = c.project(config=c.live(pronunciation={"Acme": "Akmee"}), guiones=[guion("01", "cues", steps)])
    r = c.record(p, "01")
    t.rc(r, 0, "--mute take")
    if r.rc != 0:
        return
    cues = parse_srt(read(p.path("srt", "01-cues.srt")))
    t.eq(cues[0]["lines"][0][:7], "Acme ke", "the first cue shows the narration")
    t.ok(abs(cues[0]["start"] - 1.75) < 0.001, f"the first cue starts after the title card: {cues[0]['start']}")
    for i, cue in enumerate(cues):
        t.ok(1 <= len(cue["lines"]) <= 2, f"cue {i + 1} has {len(cue['lines'])} lines")
        t.ok(all(len(x) <= 42 for x in cue["lines"]), f"cue {i + 1} has a line over 42 characters: {cue['lines']}")
        t.ok(cue["end"] > cue["start"], f"cue {i + 1} ends before it starts")
        if i:
            t.ok(cue["start"] >= cues[i - 1]["end"] - 0.001, f"cue {i + 1} overlaps the previous one")
    shown = " ".join(" ".join(cue["lines"]) for cue in cues)
    t.eq(shown, " ".join([first, second, third]), "the srt carries the narration as written (never sayAs or pronunciation)")
    timeline = read_json(os.path.join(p.out, "work", "01", "timeline.json"))["steps"]
    cuts = [s["vt"] for s in timeline] + [10 ** 6]
    groups = [[cue for cue in cues if cuts[k] - 0.001 <= cue["start"] < cuts[k + 1] - 0.001] for k in range(3)]
    ends = [bool(re.search(r"[.?!]$", " ".join(x["lines"]))) for x in groups[0]]
    t.ok(len(groups[0]) >= 2 and all(ends), f"step 1 splits by sentence: {len(groups[0])} cues, sentence ends {ends}")
    t.ok(len(groups[1]) >= 2 and not re.search(r"[.?!]$", " ".join(groups[1][0]["lines"])), "a sentence too long for one cue is split inside")
    t.ok(len(groups[2]) == 1, f"step 3 fits one cue, got {len(groups[2])}")
    # the voice reads sayAs and the pronunciation map; the clip lasts what that text weighs (70 ms per character)
    voiced = [first.replace("Acme keeps", "Akmee keeps"), second, third_as]
    for k, text in enumerate(voiced):
        want = len(text) * 70 / 1000
        t.ok(abs(timeline[k]["d"] - want) < 0.02, f"step {k + 1} voice lasts {timeline[k]['d']} s, want {want:.2f} s for {len(text)} characters")


def case_smoke_mute_e2e(c, t):
    c.need_browser()
    p = c.project(config=c.live(), guiones=[guion("01", "tour", TOUR)])
    r = c.record(p, "01")
    t.rc(r, 0, "--mute take")
    if r.rc != 0:
        return
    t.has(r.out, "rec 01-tour: 3 steps, voice ", "take header")
    t.has(r.out, "· muted", "muted label")
    t.has(r.out, "OK rec 01 tour", "take result")
    mp4 = p.path("mp4", "01-tour.mp4")
    for folder, ext in (("mp4", "mp4"), ("srt", "srt"), ("posters", "png"), ("sheets", "png"), ("dom", "txt")):
        f = p.path(folder, f"01-tour.{ext}")
        t.ok(os.path.isfile(f) and os.path.getsize(f) > 0, f"{folder}/01-tour.{ext} exists")
    for folder in ("posters", "sheets"):
        with open(p.path(folder, "01-tour.png"), "rb") as fh:
            t.eq(fh.read(4), b"\x89PNG", f"{folder} png signature")
    work = os.path.join(p.out, "work", "01")
    for n in ("step-01.wav", "step-02.wav", "step-03.wav", "video.webm", "timeline.json"):
        t.ok(os.path.isfile(os.path.join(work, n)), f"work/01/{n} is kept")
    t.ok(not os.path.exists(p.path(".lock")), "the lock is released")
    kinds = streams_by_type(mp4)
    v, a, s = kinds.get("video", {}), kinds.get("audio", {}), kinds.get("subtitle", {})
    t.eq((v.get("codec_name"), v.get("width"), v.get("height"), v.get("r_frame_rate")), ("h264", 1280, 800, "25/1"), "video stream")
    t.eq(a.get("codec_name"), "aac", "audio stream")
    t.eq(s.get("codec_name"), "mov_text", "subtitle stream")
    t.eq((s.get("tags") or {}).get("language"), "spa", "mov_text language")
    poster = streams_by_type(p.path("posters", "01-tour.png")).get("video", {})
    t.eq((poster.get("width"), poster.get("height")), (1280, 800), "poster size")
    t.has(read(p.path("dom", "01-tour.txt")), "=== step 1 (vt 1.8 s) ===", "dom dump marks each step")
    v1 = c.run("--verify", "--all", cwd=p.cwd)
    t.rc(v1, 0, "--verify --all")
    t.has(v1.out, "OK 01 h264+aac+mov_text", "verify line")
    manifest = read_json(p.path("manifest.json"))
    t.ok(isinstance(manifest, list) and len(manifest) == 1, f"manifest is an array of one entry: {manifest!r}")
    if manifest:
        m = manifest[0]
        t.eq(sorted(m), ["bytes", "duration", "id", "sha256", "slug", "title"], "manifest keys")
        t.eq((m["id"], m["slug"], m["title"]), ("01", "tour", "Acme tour"), "manifest identity")
        t.eq(m["sha256"], hashlib.sha256(open(mp4, "rb").read()).hexdigest(), "manifest sha256")
        t.eq(m["bytes"], os.path.getsize(mp4), "manifest bytes")


def case_second_run_byte_identical(c, t):
    c.need_browser()
    p = c.project(config=c.live(), guiones=[guion("01", "tour", TOUR)])
    snaps = []
    for n in (1, 2):
        r = c.record(p, "01")
        t.rc(r, 0, f"take {n}")
        v = c.run("--verify", "01", cwd=p.cwd)
        t.rc(v, 0, f"verify {n}")
        if r.rc or v.rc:
            return
        timeline = read_json(os.path.join(p.out, "work", "01", "timeline.json"))["steps"]
        snaps.append({"srt": read(p.path("srt", "01-tour.srt")), "dom": read(p.path("dom", "01-tour.txt")), "manifest": read_json(p.path("manifest.json")),
                      "grid": [(s["vt"], s["d"]) for s in timeline]})
    volatile = ("duration", "sha256", "bytes")
    t.ok(snaps[0]["srt"] == snaps[1]["srt"], "the srt of the second take differs from the first")
    t.ok(snaps[0]["dom"] == snaps[1]["dom"], "the dom dump of the second take differs from the first")
    t.eq(snaps[0]["grid"], snaps[1]["grid"], "step start times and voice durations")
    stable = [[{k: v for k, v in m.items() if k not in volatile} for m in s["manifest"]] for s in snaps]
    t.eq(stable[0], stable[1], "manifest without duration / sha256 / bytes")


def case_smoke_voiced(c, t):
    c.need_piper()
    p = c.project(config=c.live(), guiones=[guion("01", "tour", TOUR)])
    r = c.run("01", cwd=p.cwd, env={"REC_TTS": "piper"}, timeout=300)
    t.rc(r, 0, "take with REC_TTS=piper")
    if r.rc != 0:
        return
    t.has(r.out, "piper:es_MX-claude-high", "the take names the piper voice")
    t.lacks(r.out, "muted", "not a muted take")
    mp4 = p.path("mp4", "01-tour.mp4")
    level = mean_volume(mp4)
    t.ok(level is not None and level > -45, f"the audio carries a voice: mean volume {level} dB")
    t.ok(os.path.isfile(os.path.join(p.out, "work", "01", "step-01.wav")), "step clips are kept")
    v = c.run("--verify", "01", cwd=p.cwd)
    t.rc(v, 0, "--verify of the voiced take")


CASES = [
    ("check_valid_guion_estimate", case_check_valid_guion_estimate),
    ("check_voice_pace_per_engine", case_check_voice_pace_per_engine),
    ("check_invalid_steps_count", case_check_invalid_steps_count),
    ("check_invalid_say_length", case_check_invalid_say_length),
    ("check_strict_fields_and_placeholders", case_check_strict_fields_and_placeholders),
    ("check_mail_requires_url", case_check_mail_requires_url),
    ("config_defaults_and_overrides", case_config_defaults_and_overrides),
    ("config_strict_keys", case_config_strict_keys),
    ("templates_accepted", case_templates_accepted),
    ("doctor_shape", case_doctor_shape),
    ("doctor_voice_missing_recipe", case_doctor_voice_missing_recipe),
    ("doctor_synthesis_failed", case_doctor_synthesis_failed),
    ("doctor_old_node", case_doctor_old_node),
    ("usage_exit_64", case_usage_exit_64),
    ("env_placeholder_unset_exit_2", case_env_placeholder_unset_exit_2),
    ("allowhosts_blocks_offlist", case_allowhosts_blocks_offlist),
    ("mux_from_synthetic_inputs", case_mux_from_synthetic_inputs),
    ("verify_manifest_accumulates", case_verify_manifest_accumulates),
    ("denylist_hits", case_denylist_hits),
    ("launcher_exec_and_help", case_launcher_exec_and_help),
    ("no_package_json", case_no_package_json),
    ("dry_failed_step_exit_1", case_dry_failed_step_exit_1),
    ("allowhosts_blocks_redirect", case_allowhosts_blocks_redirect),
    ("allowhosts_blocks_page_request", case_allowhosts_blocks_page_request),
    ("lock_busy_exit_2", case_lock_busy_exit_2),
    ("redaction_env_placeholder", case_redaction_env_placeholder),
    ("srt_cue_splitting", case_srt_cue_splitting),
    ("smoke_mute_e2e", case_smoke_mute_e2e),
    ("second_run_byte_identical", case_second_run_byte_identical),
    ("smoke_voiced", case_smoke_voiced),
]


def run_case(fn, keep):
    root = os.path.realpath(tempfile.mkdtemp(prefix="explainer-video-selftest-"))
    t = Check()
    try:
        fn(Ctx(root), t)
        verdict, why = ("FAIL", "; ".join(p[:230] for p in t.problems[:8])) if t.problems else ("PASS", "")
    except Skip as s:
        verdict, why = "SKIP", str(s)
    except Exception as exc:  # a broken harness or a crashing recorder is a failure, not a crash
        verdict, why = "FAIL", f"harness error: {exc!r}"
    finally:
        if keep:
            print(f"  kept {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)
    return verdict, why


def main():
    ap = argparse.ArgumentParser(description="Behavioural tests for record.mjs and bin/explainer-record")
    ap.add_argument("--script", default=os.path.join(HERE, "record.mjs"), help="the record.mjs to test")
    ap.add_argument("--only", help="run a single case by name")
    ap.add_argument("--keep", action="store_true", help="leave the temp trees on disk")
    args = ap.parse_args()
    script = os.path.abspath(os.path.expanduser(args.script))
    if not os.path.isfile(script):
        print(f"script not found: {script}")
        return 2
    cases = [c for c in CASES if not args.only or c[0] == args.only]
    if not cases:
        print(f"unknown case {args.only!r}; known: {', '.join(n for n, _ in CASES)}")
        return 2
    F.configure(script)
    tally = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    try:
        for name, fn in cases:
            verdict, why = run_case(fn, args.keep)
            tally[verdict] += 1
            print(f"{verdict} {name}" + (f" — {why}" if why else ""), flush=True)
    finally:
        if _demo is not None:
            _demo.stop()
    print(f"{tally['PASS']} PASS · {tally['FAIL']} FAIL · {tally['SKIP']} SKIP (of {len(cases)})")
    return 1 if tally["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
