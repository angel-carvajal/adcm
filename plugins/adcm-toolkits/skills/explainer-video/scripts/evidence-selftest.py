#!/usr/bin/env python3
"""evidence-selftest - behavioural tests for evidence.mjs and its launcher mr-evidence (stdlib only).

Usage:
  python3 evidence-selftest.py [--script PATH] [--only NAME] [--keep]

Serves a throwaway static site (python3 -m http.server) from a temp dir, puts a fake `glab` on PATH (it logs its argv
and keeps the MR description in a file) and prints `PASS|FAIL|SKIP <case> [- why]`, then
`<n> PASS · <n> FAIL · <n> SKIP (of <n>)`. Exit code 1 when any case FAILs.

Cases that need no browser (spec validation, loopback guard, upload and MR editing through the glab shim) run
with Node >= 20 alone. Cases that capture need playwright-core, Chrome and ffmpeg: the harness asks `evidence.mjs
doctor` and SKIPs (never FAILs) with the doctor's words when one is missing. Without Node >= 20 everything SKIPs.

Contract encoded:
  - exit codes 0 ok · 2 environment · 3 port busy / ready never answers · 4 login · 5 upload · 6 host not loopback · 64 spec;
  - capture --mode both --dry: shots/<route>-d.png (1280) + -m.png (375), an h264 1280x720 mp4 under 60 s, the evidence
    markers in the block, `EVIDENCE: ok` and `MEDIA: unsent:` lines;
  - glab uploads run as `api projects/:id/uploads --form file=@<path>` with cwd = --repo; a 413 re-encodes the mp4 once,
    then drops it and keeps the shots; every upload failing is exit 5;
  - attach --mr N (default body) is idempotent and keeps human text; --note posts the refreshed-evidence heading;
    --forge github prints "adjuntar a mano" and never calls glab;
  - the password never appears in stdout, stderr, manifest.json or the markdown.
"""
import argparse
import glob
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
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SECRET = "Sup3rSecretX"
USER = "demo-user"
START, END = "<!-- evidence:start -->", "<!-- evidence:end -->"

SITE = {
    "index.html": '<!doctype html><title>Home</title><h1 id=home>Home</h1><button id=more onclick="document.getElementById(\'x\').hidden=false">More</button>'
                  '<p id=x hidden>Extra</p><div id=r></div><script>setTimeout(()=>{document.getElementById("r").setAttribute("data-ready","1");document.getElementById("r").textContent="ready"},150)</script>',
    "login.html": '<!doctype html><title>Login</title><input id=u><input id=p type=password><button id=go onclick="'
                  f"if(document.getElementById('u').value==='{USER}'&&document.getElementById('p').value==='{SECRET}')location='/app.html';else document.getElementById('e').textContent='bad'"
                  '">Go</button><p id=e></p>',
    "ext.html": '<!doctype html><title>Ext</title><h1>Ext</h1><img src="http://example.com/x.png">',
    "font.html": '<!doctype html><title>Font</title><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter"><h1 style="font-family:Inter">Font</h1>',
    "fontfetch.html": "<!doctype html><title>FontFetch</title><h1>FontFetch</h1><script>fetch('https://fonts.googleapis.com/x').catch(()=>{})</script>",
    "fonthttp.html": '<!doctype html><title>FontHttp</title><link rel="stylesheet" href="http://fonts.googleapis.com/css2?family=Inter"><h1>FontHttp</h1>',
    "app.html": '<!doctype html><title>App</title><h1 id=welcome>Welcome</h1><div data-ready>app</div><p style="height:2000px">tall</p>',
}

GLAB_SHIM = r'''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
log = os.environ["GLAB_LOG"]; state = os.environ["GLAB_STATE"]; mode = os.environ.get("GLAB_MODE", "ok")
with open(log, "a") as f:
    f.write(json.dumps({"argv": a, "cwd": os.getcwd()}) + "\n")
def load():
    return json.load(open(state)) if os.path.exists(state) else {"description": "", "notes": []}
if a[:1] == ["--version"]:
    print("glab 0.0.0")
elif a[:3] == ["api", "projects/:id/uploads", "--form"]:
    path = a[3][len("file="):].lstrip("@")
    name = os.path.basename(path)
    if mode == "413all" or (mode == "413mp4" and name.endswith(".mp4")) or (mode == "413big" and name.endswith(".mp4") and not name.endswith("-small.mp4")):
        sys.stderr.write("glab: 413 Request Entity Too Large\n"); sys.exit(1)
    if mode == "401mp4" and name.endswith(".mp4"):
        sys.stderr.write("glab: 401 Unauthorized\n"); sys.exit(1)
    print(json.dumps({"alt": name, "url": "/uploads/h/" + name, "markdown": "![" + name + "](/uploads/h/" + name + ")"}))
elif a[:2] == ["api", "projects/:id/merge_requests/" + (a[1].rsplit("/", 1)[-1] if len(a) > 1 else "")] and len(a) == 2:
    print(json.dumps({"description": load()["description"]}))
elif a[:2] == ["mr", "update"] and a[3] == "-d":
    s = load(); s["description"] = a[4]; json.dump(s, open(state, "w"))
elif a[:3] == ["mr", "note", "create"] and a[4] == "-m":
    s = load(); s["notes"].append(a[5]); json.dump(s, open(state, "w"))
else:
    sys.stderr.write("shim: unsupported " + repr(a) + "\n"); sys.exit(2)
'''


class Skip(Exception):
    pass


def fail(msg):
    raise AssertionError(msg)


def check(cond, msg):
    if not cond:
        fail(msg)


def nvm_version(bin_dir):
    m = re.search(r"/v(\d+)\.(\d+)\.(\d+)/bin$", bin_dir)
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def node_major(exe):
    try:
        out = subprocess.run([exe, "-p", "process.versions.node.split('.')[0]"], capture_output=True, text=True, timeout=20).stdout
        return int(out.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def find_node():
    nvm = sorted(glob.glob(os.path.join(os.path.expanduser("~"), ".nvm", "versions", "node", "v2[0-9]*", "bin")), key=nvm_version)
    candidates = [os.path.join(nvm[-1], "node")] if nvm else []
    if shutil.which("node"):
        candidates.append(shutil.which("node"))
    for exe in candidates:
        if os.access(exe, os.X_OK) and node_major(exe) >= 20:
            return exe
    return None


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Env:
    def __init__(self, script, keep):
        self.script, self.keep = script, keep
        self.node = find_node()
        self.root = tempfile.mkdtemp(prefix="evidence-selftest-")
        self.site = os.path.join(self.root, "site")
        os.makedirs(self.site)
        for name, html in SITE.items():
            open(os.path.join(self.site, name), "w").write(html)
        self.bin = os.path.join(self.root, "bin")
        os.makedirs(self.bin)
        shim = os.path.join(self.bin, "glab")
        open(shim, "w").write(GLAB_SHIM)
        os.chmod(shim, 0o755)
        self.repo = os.path.realpath(self.fresh("repo"))
        self.tools = None

    def fresh(self, name):
        d = tempfile.mkdtemp(prefix=name + "-", dir=self.root)
        return d

    def base_env(self, extra=None):
        env = dict(os.environ)
        env["PATH"] = self.bin + os.pathsep + env["PATH"]
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["GLAB_LOG"] = os.path.join(self.root, "glab.log")
        env["GLAB_STATE"] = os.path.join(self.root, "mr-state.json")
        env.pop("EVIDENCE_USER", None)
        env.pop("EVIDENCE_PASS", None)
        env.update(extra or {})
        return env

    def run(self, args, extra_env=None, timeout=180, cwd=None):
        p = subprocess.run([self.node, self.script, *args], capture_output=True, text=True, timeout=timeout,
                           env=self.base_env(extra_env), cwd=cwd or self.repo)
        return p

    def doctor(self):
        if self.tools is None:
            out = self.run(["doctor"]).stdout
            self.tools = {line.split()[1]: line.startswith("ok") for line in out.splitlines() if line.startswith(("ok ", "missing "))}
        return self.tools

    def need_node(self):
        if not self.node:
            raise Skip("Node >= 20 not found")

    def need_browser(self):
        self.need_node()
        t = self.doctor()
        for item in ("playwright-core>=1.61", "browser", "ffmpeg", "ffprobe"):
            if not t.get(item, False):
                raise Skip(f"{item} not ready (run `mr-evidence doctor`)")

    def need_ffmpeg(self):
        if not shutil.which("ffmpeg"):
            raise Skip("ffmpeg not found")

    def write_env(self, password=SECRET):
        f = os.path.join(self.fresh("envdir"), ".env.local")
        open(f, "w").write(f"EVIDENCE_USER={USER}\nEVIDENCE_PASS={password}\n")
        return f

    def spec(self, port, **over):
        d = {
            "name": "wtest",
            "serve": {"cmd": f"python3 -m http.server {port} --bind 127.0.0.1 --directory {self.site}", "ready": f"http://127.0.0.1:{port}/index.html", "timeoutS": 20},
            "baseUrl": f"http://127.0.0.1:{port}",
            "allowHosts": ["127.0.0.1", "localhost"],
            "routes": [{"path": "/", "name": "home", "waitFor": "[data-ready]"}, {"path": "/app.html", "name": "app", "waitFor": "[data-ready]"}],
            "widths": [1280, 375],
            "auth": {"loginPath": "/login.html", "userSelector": "#u", "passSelector": "#p", "submitSelector": "#go", "successSelector": "#welcome"},
            "video": {"steps": [
                {"action": "goto", "value": "/", "caption": "Inicio", "hold": 0.4},
                {"action": "click", "selector": "#more", "caption": "Ver mas", "hold": 0.4},
                {"action": "goto", "value": "/app.html", "caption": "La app", "hold": 0.4},
                {"action": "scroll", "value": 600, "caption": "Abajo", "hold": 0.4},
            ]},
        }
        d.update(over)
        f = os.path.join(self.fresh("spec"), "w.json")
        json.dump(d, open(f, "w"))
        return f

    def files_dir(self, with_video=True, prefix="files"):
        d = self.fresh(prefix)
        for n in ("a-d.png", "a-m.png"):
            open(os.path.join(d, n), "wb").write(b"\x89PNG fake " + n.encode())
        if with_video:
            self.need_ffmpeg()
            r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25", "-t", "1", "-pix_fmt", "yuv420p", os.path.join(d, "demo.mp4")], capture_output=True)
            check(r.returncode == 0, "ffmpeg could not make the fixture mp4")
        return d

    def glab_calls(self):
        f = os.path.join(self.root, "glab.log")
        return [json.loads(l) for l in open(f)] if os.path.exists(f) else []

    def reset_glab(self, description=""):
        for n in ("glab.log", "mr-state.json"):
            p = os.path.join(self.root, n)
            if os.path.exists(p):
                os.remove(p)
        if description is not None:
            json.dump({"description": description, "notes": []}, open(os.path.join(self.root, "mr-state.json"), "w"))

    def state(self):
        return json.load(open(os.path.join(self.root, "mr-state.json")))

    def cleanup(self):
        if not self.keep:
            shutil.rmtree(self.root, ignore_errors=True)


# ---------------------------------------------------------------- cases
def case_usage(e):
    e.need_node()
    check(e.run([]).returncode == 64, "no command should exit 64")
    check(e.run(["capture"]).returncode == 64, "capture without --spec should exit 64")
    check(e.run(["capture", "--spec", "x.json", "--mode", "weird"]).returncode == 64, "bad --mode should exit 64")


def case_host_not_loopback(e):
    e.need_node()
    spec = e.spec(5999, baseUrl="http://example.com", allowHosts=["example.com"])
    p = e.run(["capture", "--spec", spec, "--mode", "screenshots", "--out", e.fresh("out")])
    check(p.returncode == 6, f"expected exit 6, got {p.returncode}\n{p.stdout}{p.stderr}")
    check("failed(6)" in p.stdout, "stdout lacks EVIDENCE: failed(6)")


def case_spec_video_too_long(e):
    e.need_node()
    steps = [{"action": "wait", "value": 100, "caption": f"s{i}", "hold": 3} for i in range(24)]
    p = e.run(["check", "--spec", e.spec(5998, video={"steps": steps})])
    check(p.returncode == 64, f"expected 64 for a 72 s video, got {p.returncode}\n{p.stdout}{p.stderr}")
    p = e.run(["check", "--spec", e.spec(5998, video={"steps": [{"action": "wait", "value": 100}]})])
    check(p.returncode == 64, "a step without caption should be 64")
    p = e.run(["check", "--spec", e.spec(5998, video={"steps": [{"action": "fill", "selector": "#u", "value": "{{env:X}}", "caption": "c"}]})])
    check(p.returncode == 64, "placeholders in video steps should be 64")


def case_check_ok(e):
    e.need_browser()
    p = e.run(["check", "--spec", e.spec(free_port()), "--creds-file", e.write_env()])
    check(p.returncode == 0, f"check should exit 0, got {p.returncode}\n{p.stdout}{p.stderr}")
    p = e.run(["check", "--spec", e.spec(free_port()), "--creds-file", os.path.join(e.root, "missing.env")])
    check(p.returncode == 2, f"missing credentials should be 2, got {p.returncode}")


def case_launcher_env_file(e):
    e.need_node()
    launcher = os.path.join(HERE, "..", "..", "..", "scripts", "launchers", "mr-evidence")
    if not os.path.exists(launcher):
        raise Skip("launcher not found next to the script")
    e.need_browser()
    p = subprocess.run(["sh", launcher, "check", "--spec", e.spec(free_port()), "--env-file", os.path.join(e.root, "nope.env")],
                       capture_output=True, text=True, env=e.base_env(), cwd=e.repo, timeout=120)
    check(p.returncode == 2 and "credentials not found" in p.stdout, f"launcher --env-file: rc {p.returncode}\n{p.stdout}{p.stderr}")


def case_capture_both_dry(e):
    e.need_browser()
    out = e.fresh("out")
    e.reset_glab()
    p = e.run(["capture", "--spec", e.spec(free_port()), "--mode", "both", "--dry", "--out", out, "--creds-file", e.write_env()])
    check(p.returncode == 0, f"capture failed {p.returncode}\n{p.stdout}{p.stderr}")
    for n in ("home-d.png", "home-m.png", "app-d.png", "app-m.png"):
        f = os.path.join(out, "shots", n)
        check(os.path.getsize(f) > 500, f"{n} missing or empty")
    sizes = {n: png_size(os.path.join(out, "shots", n)) for n in ("home-d.png", "home-m.png")}
    check(sizes["home-d.png"][0] == 1280 and sizes["home-m.png"][0] == 375, f"widths {sizes}")
    mp4 = os.path.join(out, "video", "wtest.mp4")
    info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", mp4], capture_output=True, text=True).stdout)
    v = [s for s in info["streams"] if s["codec_type"] == "video"][0]
    check(v["codec_name"] == "h264" and (v["width"], v["height"]) == (1280, 720), f"video stream {v['codec_name']} {v['width']}x{v['height']}")
    check(0 < float(info["format"]["duration"]) < 60, "duration out of range")
    check(p.stdout.startswith("EVIDENCE: ok 4 shots video"), f"first line: {p.stdout.splitlines()[0]}")
    check("MEDIA: unsent: " in p.stdout and os.path.join(out, "shots", "home-d.png") in p.stdout, "MEDIA line missing")
    check(not os.path.exists(os.path.join(e.root, "glab.log")), "dry capture must not call glab")
    # dry run: capture prints no block; run --dry prints the block with both markers
    p = e.run(["run", "--spec", e.spec(free_port()), "--mode", "both", "--dry", "--out", e.fresh("out2"), "--creds-file", e.write_env()])
    check(p.returncode == 0 and START in p.stdout and END in p.stdout, f"markers missing in run --dry\n{p.stdout}{p.stderr}")


def png_size(path):
    d = open(path, "rb").read(32)
    return int.from_bytes(d[16:20], "big"), int.from_bytes(d[20:24], "big")


def case_server_negatives(e):
    e.need_browser()
    spec = e.spec(free_port())
    port = free_port()
    bad = json.load(open(spec))
    bad["serve"]["cmd"] = f"python3 -m http.server {port} --bind 127.0.0.1 --directory {e.site}"
    bad["serve"]["ready"] = f"http://127.0.0.1:{port}/nope"
    bad["serve"]["timeoutS"] = 3
    bad["baseUrl"] = f"http://127.0.0.1:{port}"
    f = os.path.join(e.fresh("spec"), "bad.json")
    json.dump(bad, open(f, "w"))
    p = e.run(["capture", "--spec", f, "--mode", "screenshots", "--out", e.fresh("out"), "--creds-file", e.write_env()])
    check(p.returncode == 3, f"bad ready should be 3, got {p.returncode}\n{p.stdout}{p.stderr}")
    # port busy: another listener already owns the port and must never be reused
    busy = free_port()
    holder = subprocess.Popen([sys.executable, "-m", "http.server", str(busy), "--bind", "127.0.0.1", "--directory", e.site], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{busy}/index.html", timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        p = e.run(["capture", "--spec", e.spec(busy), "--mode", "screenshots", "--out", e.fresh("out"), "--creds-file", e.write_env()])
        check(p.returncode == 3 and "port busy" in p.stdout + p.stderr, f"busy port should be 3 'port busy', got {p.returncode}\n{p.stdout}{p.stderr}")
        check(holder.poll() is None, "the foreign listener was disturbed")
    finally:
        holder.terminate()
        holder.wait()


def case_login_bad(e):
    e.need_browser()
    p = e.run(["capture", "--spec", e.spec(free_port()), "--mode", "screenshots", "--out", e.fresh("out"), "--creds-file", e.write_env("WrongPass123")])
    check(p.returncode == 4, f"bad login should be 4, got {p.returncode}\n{p.stdout}{p.stderr}")
    check("WrongPass123" not in p.stdout + p.stderr, "wrong password echoed")


def case_secret_leak(e):
    e.need_browser()
    e.reset_glab()
    out = e.fresh("out")
    env_file = e.write_env()
    runs = [e.run(["run", "--spec", e.spec(free_port()), "--mode", "both", "--mr", "5", "--out", out, "--creds-file", env_file, "--json"]),
            e.run(["capture", "--spec", e.spec(free_port()), "--mode", "screenshots", "--out", e.fresh("out"), "--creds-file", e.write_env("WrongPass123")]),
            e.run(["check", "--spec", e.spec(free_port()), "--creds-file", env_file])]
    check(runs[0].returncode == 0, f"run failed {runs[0].returncode}\n{runs[0].stdout}{runs[0].stderr}")
    blobs = [r.stdout + r.stderr for r in runs]
    blobs.append(open(os.path.join(out, "manifest.json")).read())
    blobs.append(json.dumps(e.state()))
    blobs.append(json.dumps(e.glab_calls()))
    for b in blobs:
        check(SECRET not in b and "WrongPass123" not in b, "a password reached an output")
    check(USER not in blobs[-3], "the manifest names the user")


def case_glab_upload_argv(e):
    e.need_node()
    e.reset_glab()
    d = e.files_dir(with_video=False)
    p = e.run(["attach", "--files", d, "--repo", e.repo])
    check(p.returncode == 0, f"attach failed\n{p.stdout}{p.stderr}")
    ups = [c for c in e.glab_calls() if c["argv"][:2] == ["api", "projects/:id/uploads"]]
    check(len(ups) == 2, f"expected 2 uploads, got {len(ups)}")
    for c in ups:
        a = c["argv"]
        check(a[:3] == ["api", "projects/:id/uploads", "--form"] and a[3].startswith("file=@") and len(a) == 4, f"argv {a}")
        check(os.path.realpath(c["cwd"]) == e.repo, f"cwd {c['cwd']} != {e.repo}")
    check(not [c for c in e.glab_calls() if c["argv"][:2] == ["mr", "update"]], "no --mr: the MR must stay untouched")
    check("![a-d.png](/uploads/h/a-d.png)" in p.stdout and START in p.stdout, "block lacks the uploaded markdown")
    md = os.path.join(e.fresh("md"), "block.md")
    p = e.run(["attach", "--files", d, "--repo", e.repo, "--md-out", md])
    check(p.returncode == 0 and START in open(md).read(), "--md-out did not write the block")


def case_glab_413(e):
    e.need_node()
    d = e.files_dir()
    e.reset_glab()
    p = e.run(["attach", "--files", d, "--repo", e.repo], extra_env={"GLAB_MODE": "413all"})
    check(p.returncode == 5 and "failed(5)" in p.stdout, f"413 everywhere should be 5, got {p.returncode}\n{p.stdout}{p.stderr}")
    e.reset_glab()
    p = e.run(["attach", "--files", d, "--repo", e.repo], extra_env={"GLAB_MODE": "413big"})
    check(p.returncode == 0 and "![demo-small.mp4]" in p.stdout, f"a 413 on the original should succeed re-encoded\n{p.stdout}{p.stderr}")
    e.reset_glab()
    p = e.run(["attach", "--files", d, "--repo", e.repo], extra_env={"GLAB_MODE": "413mp4"})
    check(p.returncode == 0, f"video 413 with shots ok should be 0, got {p.returncode}\n{p.stdout}{p.stderr}")
    mp4s = [c["argv"][3] for c in e.glab_calls() if c["argv"][:2] == ["api", "projects/:id/uploads"] and c["argv"][3].endswith(".mp4")]
    check(len(mp4s) == 2 and mp4s[1].endswith("-small.mp4"), f"expected one re-encoded retry, got {mp4s}")
    check(".mp4" not in p.stdout.split("MEDIA")[0] and "![demo.mp4]" not in p.stdout, "dropped video still in the block")
    check("a-d.png" in p.stdout and "video dropped" in p.stdout.splitlines()[0], "shots kept and the drop reported")


def case_body_idempotent(e):
    e.need_node()
    d = e.files_dir(with_video=False)
    e.reset_glab("Intro humano\n\nContexto del MR.\n")
    args = ["attach", "--files", d, "--repo", e.repo, "--mr", "7"]
    check(e.run(args).returncode == 0, "first attach failed")
    first = e.state()["description"]
    check(first.count(START) == 1 and first.count(END) == 1, "markers must appear once")
    check(first.startswith("Intro humano\n\nContexto del MR."), "human text before the region lost")
    check(e.run(args).returncode == 0, "second attach failed")
    check(e.state()["description"] == first, "second attach changed the description (not idempotent)")
    edited = "Nuevo titulo humano\n\n" + first + "\n\nPie escrito a mano"
    e.reset_glab(edited)
    check(e.run(args).returncode == 0, "third attach failed")
    after = e.state()["description"]
    check(after.startswith("Nuevo titulo humano") and after.endswith("Pie escrito a mano") and after.count(START) == 1, "human edits around the region were not preserved")
    e.reset_glab("Solo humano")
    e.run(args)
    check(e.state()["description"].startswith("Solo humano\n\n" + START), "region not appended after existing text")


def case_note_mode(e):
    e.need_node()
    d = e.files_dir(with_video=False)
    e.reset_glab("Descripcion")
    p = e.run(["attach", "--files", d, "--repo", e.repo, "--mr", "7", "--note"])
    check(p.returncode == 0, f"note failed\n{p.stdout}{p.stderr}")
    notes = e.state()["notes"]
    check(len(notes) == 1 and notes[0].startswith("## Evidencia (refrescada tras arreglos del gate)"), f"note body: {notes}")
    check(e.state()["description"] == "Descripcion", "note mode must not touch the description")
    p2 = e.run(["attach", "--files", d, "--repo", e.repo, "--mr", "7", "--mode", "note"])
    check(p2.returncode == 64 and "--note" in (p2.stdout + p2.stderr), f"--mode note must exit 64 with a hint: {p2.returncode}")
    check(any(c["argv"][:4] == ["mr", "note", "create", "7"] and c["argv"][4] == "-m" for c in e.glab_calls()), "glab mr note create 7 -m not called")


def case_spec_strictness(e):
    e.need_node()
    for label, over in (("allowHosts string", {"allowHosts": "localhost"}), ("hold string", {"video": {"steps": [{"action": "wait", "value": 100, "caption": "c", "hold": "70"}]}}),
                        ("ftp baseUrl", {"baseUrl": "ftp://localhost/"}), ("ftp ready", {"serve": {"cmd": "true", "ready": "ftp://localhost/"}})):
        p = e.run(["check", "--spec", e.spec(5997, **over)])
        check(p.returncode == 64, f"{label} should be 64, got {p.returncode}\n{p.stdout}{p.stderr}")
    novideo = json.load(open(e.spec(5997)))
    del novideo["video"]
    f = os.path.join(e.fresh("spec"), "nv.json")
    json.dump(novideo, open(f, "w"))
    p = e.run(["check", "--spec", f, "--mode", "video"])
    check(p.returncode == 64, f"check --mode video without video.steps should be 64, got {p.returncode}\n{p.stdout}{p.stderr}")
    p = e.run(["check", "--spec", e.spec(5997, routes=[]), "--mode", "screenshots"])
    check(p.returncode == 64, f"check --mode screenshots without routes should be 64, got {p.returncode}\n{p.stdout}{p.stderr}")


def case_outside_host_runtime(e):
    e.need_browser()
    f = e.spec(free_port(), routes=[{"path": "/ext.html", "name": "ext"}])
    d = json.load(open(f))
    del d["auth"]
    json.dump(d, open(f, "w"))
    p = e.run(["capture", "--spec", f, "--mode", "screenshots", "--out", e.fresh("out")])
    check(p.returncode == 6 and "failed(6)" in p.stdout, f"outside host should be rc 6 with failed(6), got {p.returncode}\n{p.stdout}{p.stderr}")


def _no_auth_capture(e, route):
    f = e.spec(free_port(), routes=[{"path": route, "name": "r"}])
    d = json.load(open(f))
    del d["auth"]
    json.dump(d, open(f, "w"))
    return e.run(["capture", "--spec", f, "--mode", "screenshots", "--out", e.fresh("out")])


def case_font_cdn_link_allowed(e):
    e.need_browser()
    p = _no_auth_capture(e, "/font.html")
    check(p.returncode == 0, f"a Google Fonts <link> should capture with rc 0, got {p.returncode}\n{p.stdout}{p.stderr}")


def case_font_cdn_fetch_blocked(e):
    e.need_browser()
    p = _no_auth_capture(e, "/fontfetch.html")
    check(p.returncode == 6 and "failed(6)" in p.stdout, f"fetch() to a font host should be rc 6 with failed(6), got {p.returncode}\n{p.stdout}{p.stderr}")


def case_font_cdn_http_blocked(e):
    e.need_browser()
    p = _no_auth_capture(e, "/fonthttp.html")
    check(p.returncode == 6 and "failed(6)" in p.stdout, f"an http:// font-host stylesheet should be rc 6 with failed(6), got {p.returncode}\n{p.stdout}{p.stderr}")


def case_font_cdn_redirect_document_blocked(e):
    e.need_browser()
    srv = os.path.join(e.fresh("redir"), "redir.py")
    open(srv, "w").write(
        "import http.server, sys\n"
        "class H(http.server.BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        if self.path == '/go':\n"
        "            self.send_response(302); self.send_header('Location', 'https://fonts.googleapis.com/css2?family=Inter'); self.send_header('Content-Length', '0'); self.end_headers()\n"
        "        else:\n"
        "            self.send_response(200); self.send_header('Content-Type', 'text/html'); self.end_headers(); self.wfile.write(b'<!doctype html><title>R</title>ok')\n"
        "    def log_message(self, *a): pass\n"
        "http.server.ThreadingHTTPServer(('127.0.0.1', int(sys.argv[1])), H).serve_forever()\n")
    port = free_port()
    f = e.spec(port, routes=[{"path": "/go", "name": "go"}])
    d = json.load(open(f))
    del d["auth"]
    d["serve"]["cmd"] = f"python3 {srv} {port}"
    d["serve"]["ready"] = f"http://127.0.0.1:{port}/ok"
    json.dump(d, open(f, "w"))
    p = e.run(["capture", "--spec", f, "--mode", "screenshots", "--out", e.fresh("out")])
    check(p.returncode == 6 and "failed(6)" in p.stdout, f"a loopback 302 to a font-host document should be rc 6 with failed(6), got {p.returncode}\n{p.stdout}{p.stderr}")


def case_sigterm_kills_server(e):
    e.need_browser()
    port = free_port()
    f = e.spec(port)
    d = json.load(open(f))
    d["serve"]["cmd"] = f"sleep 4 && exec python3 -m http.server {port} --bind 127.0.0.1 --directory {e.site}"
    json.dump(d, open(f, "w"))
    proc = subprocess.Popen([e.node, e.script, "capture", "--spec", f, "--mode", "screenshots", "--out", e.fresh("out"), "--creds-file", e.write_env()],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=e.base_env(), cwd=e.repo)
    try:
        time.sleep(1.5)
        proc.send_signal(signal.SIGTERM)
        rc = proc.wait(timeout=30)
        time.sleep(4.5)
        with socket.socket() as s:
            s.settimeout(1)
            check(s.connect_ex(("127.0.0.1", port)) != 0, "the dev server survived SIGTERM (port still listening)")
        check(rc == 143, f"SIGTERM should exit 143, got {rc}")
    finally:
        if proc.poll() is None:
            proc.kill()


def case_413_ignores_paths(e):
    e.need_node()
    d = e.files_dir(prefix="w413")
    e.reset_glab()
    p = e.run(["attach", "--files", d, "--repo", e.repo], extra_env={"GLAB_MODE": "401mp4"})
    check(p.returncode == 5, f"a 401 on a path containing 413 must be 5, got {p.returncode}\n{p.stdout}{p.stderr}")


def case_unbalanced_markers(e):
    e.need_node()
    d = e.files_dir(with_video=False)
    e.reset_glab(f"Texto humano importante\n{START}\nmitad escrita a mano\n")
    args = ["attach", "--files", d, "--repo", e.repo, "--mr", "7"]
    p = e.run(args)
    check(p.returncode == 0 and "WARN:" in p.stdout + p.stderr, f"unbalanced markers should warn, rc {p.returncode}\n{p.stdout}{p.stderr}")
    check(e.run(args).returncode == 0, "second attach failed")
    desc = e.state()["description"]
    check("Texto humano importante" in desc and "mitad escrita a mano" in desc, f"human text lost: {desc}")


def case_github(e):
    e.need_node()
    e.reset_glab()
    p = e.run(["attach", "--files", e.files_dir(with_video=False), "--repo", e.repo, "--forge", "github", "--mr", "3"])
    check(p.returncode == 0 and "adjuntar a mano" in p.stdout, f"github should print the manual line, rc {p.returncode}\n{p.stdout}{p.stderr}")
    check(not e.glab_calls(), "github must never call glab")


def case_run_end_to_end(e):
    e.need_browser()
    e.reset_glab("Cuerpo")
    p = e.run(["run", "--spec", e.spec(free_port()), "--mode", "both", "--mr", "9", "--repo", e.repo, "--out", e.fresh("out"), "--creds-file", e.write_env()])
    check(p.returncode == 0, f"run failed {p.returncode}\n{p.stdout}{p.stderr}")
    d = e.state()["description"]
    check(d.startswith("Cuerpo") and d.count(START) == 1 and "wtest.mp4" in d and "home-d.png" in d, f"description: {d}")
    check(p.stdout.startswith("EVIDENCE: ok 4 shots video"), p.stdout.splitlines()[0])


CASES = [case_usage, case_host_not_loopback, case_spec_video_too_long, case_check_ok, case_launcher_env_file, case_capture_both_dry, case_server_negatives,
         case_login_bad, case_secret_leak, case_glab_upload_argv, case_glab_413, case_body_idempotent, case_note_mode, case_spec_strictness, case_outside_host_runtime, case_font_cdn_link_allowed, case_font_cdn_fetch_blocked, case_font_cdn_http_blocked, case_font_cdn_redirect_document_blocked, case_sigterm_kills_server, case_413_ignores_paths, case_unbalanced_markers, case_github,
         case_run_end_to_end]


def main():
    ap = argparse.ArgumentParser(description="Behavioural tests for evidence.mjs and scripts/launchers/mr-evidence")
    ap.add_argument("--script", default=os.path.join(HERE, "evidence.mjs"))
    ap.add_argument("--only")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()
    env = Env(args.script, args.keep)
    tally = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    cases = [c for c in CASES if not args.only or args.only in c.__name__]
    try:
        for fn in cases:
            name = fn.__name__[5:].replace("_", "-")
            try:
                fn(env)
                status, why = "PASS", ""
            except Skip as s:
                status, why = "SKIP", str(s)
            except subprocess.TimeoutExpired:
                status, why = "FAIL", "timed out"
            except AssertionError as a:
                status, why = "FAIL", str(a)
            except Exception as ex:  # noqa: BLE001
                status, why = "FAIL", f"{type(ex).__name__}: {ex}"
            tally[status] += 1
            print(f"{status} {name}" + (f" - {why}" if why else ""))
    finally:
        env.cleanup()
    print(f"{tally['PASS']} PASS · {tally['FAIL']} FAIL · {tally['SKIP']} SKIP (of {len(cases)})")
    return 1 if tally["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
