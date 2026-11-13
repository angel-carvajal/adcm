#!/usr/bin/env python3
"""deps-smoke-selftest - behavioural tests for deps_smoke.mjs and scripts/launchers/deps-smoke (stdlib only).

Usage:
  python3 deps-smoke-selftest.py [--only NAME] [--keep]

Every case works in a throwaway `tempfile` tree: PNG sets written here with zlib + struct, stub servers started by
`scripts/launchers/deps-smoke --serve` on 127.0.0.1 (the only host ever contacted), and `scripts/launchers/deps-smoke` itself run as a subprocess
(PYTHONDONTWRITEBYTECODE=1). It prints `PASS|FAIL|SKIP <case> [- why]`, then the tally
`N PASS · M FAIL · S SKIP (of N)` as the last line. Exit code 1 when any case FAILs.

builtin_shoot_mask and shoot_cookie open Chrome and SKIP unless `deps-smoke doctor` says ready; node_pin_path SKIPs
without nvm Node versions; git_manifest SKIPs without git. --keep leaves the temp trees on disk.
"""
import argparse
import json
import os
import random
import re
import shlex
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
PLUGIN = os.path.dirname(os.path.dirname(SKILL))
BIN = os.path.join(PLUGIN, "scripts", "launchers", "deps-smoke")
SIG = b"\x89PNG\r\n\x1a\n"
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
PY = shlex.quote(sys.executable) + " -B"

STUB = r'''
import http.server, os, shutil, socket

port = int(os.environ["PORT"])
host = os.environ.get("HOST", "127.0.0.1")
status = int(os.environ.get("STATUS", "200"))
mode = os.environ.get("MODE", "fixed")
report = os.environ.get("REPORT")
if report:
    with open(report, "w") as f:
        f.write(str(shutil.which("node")))

if mode == "silent":
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(8)
    held = []
    while True:
        held.append(srv.accept()[0])

RAND = b"""<!doctype html><meta charset="utf-8"><body style="margin:0;background:#fff">
<div style="width:300px;height:200px;background:#226633"></div><div style="height:2400px"></div>
<div id="rand" style="position:absolute;left:400px;top:100px;width:400px;height:300px"></div>
<script>document.getElementById('rand').style.background = 'rgb(' + Array.from(crypto.getRandomValues(new Uint8Array(3))).join(',') + ')'</script></body>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        code, body = status, b"ok"
        if mode == "pages":
            code, body = (404, b"missing") if "missing" in self.path else (200, ("page " + self.path).encode())
        elif mode == "cookie":
            green = "session=abc" in self.headers.get("Cookie", "")
            body = ('<!doctype html><body style="margin:0;background:%s"></body>' % ("#00ff00" if green else "#ff0000")).encode()
        elif mode == "rand":
            body = RAND
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


http.server.ThreadingHTTPServer((host, port), Handler).serve_forever()
'''

FAKE_SHOT = r'''
import hashlib, struct, sys, urllib.request, zlib

url, out = sys.argv[1], sys.argv[2]
body = urllib.request.urlopen(url, timeout=10).read()
r, g, b = hashlib.md5(body).digest()[:3]
w = h = 8
raw = b"".join(b"\x00" + bytes((r, g, b)) * w for _ in range(h))


def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


with open(out, "wb") as f:
    f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
'''


class Skip(Exception):
    pass


class Check:
    def __init__(self):
        self.problems = []

    def ok(self, cond, msg):
        if not cond:
            self.problems.append(msg)
        return cond


# ------------------------------------------------------------------ png writer and reader
def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def predictor(ftype, a, b, c):
    if ftype == 1:
        return a
    if ftype == 2:
        return b
    if ftype == 3:
        return (a + b) // 2
    if ftype == 4:
        p = a + b - c
        pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
        return a if pa <= pb and pa <= pc else b if pb <= pc else c
    return 0


def filter_row(ftype, row, prev, bpp):
    out = bytearray([ftype])
    for i, x in enumerate(row):
        a = row[i - bpp] if i >= bpp else 0
        b = prev[i] if prev is not None else 0
        c = prev[i - bpp] if prev is not None and i >= bpp else 0
        out.append((x - predictor(ftype, a, b, c)) & 255)
    return bytes(out)


def png_bytes(w, h, rows, color=2, depth=8, interlace=0, plte=None, trns=None, filters=(0,)):
    """rows: h byte strings of unfiltered samples; filters: the row filter types, cycled."""
    bpp = max(1, CHANNELS[color] * depth // 8)
    raw, prev = b"", None
    for y, row in enumerate(rows):
        raw += filter_row(filters[y % len(filters)], row, prev, bpp)
        prev = row
    parts = [SIG, chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, depth, color, 0, 0, interlace))]
    if plte is not None:
        parts.append(chunk(b"PLTE", plte))
    if trns is not None:
        parts.append(chunk(b"tRNS", trns))
    parts += [chunk(b"IDAT", zlib.compress(raw, 9)), chunk(b"IEND", b"")]
    return b"".join(parts)


def patch_ihdr(data, index, value):
    ihdr = bytearray(data[16:29])
    ihdr[index] = value
    return data[:16] + bytes(ihdr) + struct.pack(">I", zlib.crc32(b"IHDR" + bytes(ihdr)) & 0xFFFFFFFF) + data[33:]


def encode(pic, kind="t6", filters=(0,)):
    """pic: rows of (r, g, b, a); kind t0|t2|t3|t4|t6 names the PNG colour type."""
    h, w = len(pic), len(pic[0])
    if kind == "t6":
        return png_bytes(w, h, [bytes(v for px in r for v in px) for r in pic], 6, filters=filters)
    if kind == "t2":
        return png_bytes(w, h, [bytes(v for px in r for v in px[:3]) for r in pic], 2, filters=filters)
    if kind == "t0":
        return png_bytes(w, h, [bytes(px[0] for px in r) for r in pic], 0, filters=filters)
    if kind == "t4":
        return png_bytes(w, h, [bytes(v for px in r for v in (px[0], px[3])) for r in pic], 4, filters=filters)
    colors = list(dict.fromkeys(px for r in pic for px in r))
    assert len(colors) <= 256, "too many colours for a palette"
    index = {c: i for i, c in enumerate(colors)}
    plte = bytes(v for c in colors for v in c[:3])
    trns = bytes(c[3] for c in colors) if any(c[3] != 255 for c in colors) else None
    return png_bytes(w, h, [bytes(index[px] for px in r) for r in pic], 3, plte=plte, trns=trns, filters=filters)


def solid(w, h, rgb, alpha=255):
    return [[(rgb[0], rgb[1], rgb[2], alpha) for _ in range(w)] for _ in range(h)]


def paint(pic, x, y, w, h, rgb):
    for yy in range(y, y + h):
        for xx in range(x, x + w):
            pic[yy][xx] = (rgb[0], rgb[1], rgb[2], pic[yy][xx][3])
    return pic


def png_of(pic):
    return encode(pic, "t6")


def read_png(path, upto=None):
    """(w, h, color, rows) of an 8-bit non-interlaced PNG; decodes only the first `upto` rows."""
    with open(path, "rb") as f:
        data = f.read()
    assert data[:8] == SIG, "not a PNG"
    pos, idat, ihdr = 8, b"", None
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        kind, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
        crc = struct.unpack(">I", data[pos + 8 + n:pos + 12 + n])[0]
        assert zlib.crc32(kind + body) & 0xFFFFFFFF == crc, f"bad CRC in {kind!r}"
        if kind == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat += body
        pos += 12 + n
    w, h, depth, color, _, _, interlace = ihdr
    assert depth == 8 and interlace == 0 and color in (2, 6), f"unexpected PNG layout {ihdr}"
    bpp = CHANNELS[color]
    raw = zlib.decompress(idat)
    stride = w * bpp
    rows, prev = [], bytes(stride)
    for y in range(h if upto is None else min(h, upto)):
        ftype = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        if ftype:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                c = prev[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + predictor(ftype, a, prev[i], c)) & 255
        prev = bytes(line)
        rows.append(prev)
    return w, h, color, rows


def pixel(path, x, y):
    w, h, color, rows = read_png(path, y + 1)
    bpp = CHANNELS[color]
    return tuple(rows[y][x * bpp:x * bpp + 3])


def near(a, b, slack=2):
    return all(abs(p - q) <= slack for p, q in zip(a, b))


def slug(route):
    return re.sub(r"[^a-z0-9]+", "-", route.lower()).strip("-")[:80].rstrip("-") or "root"


# ------------------------------------------------------------------ harness
def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def port_open(port, host="127.0.0.1"):
    s = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET)
    s.settimeout(0.5)
    try:
        s.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def wait_until(fn, seconds, step=0.05):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if fn():
            return True
        time.sleep(step)
    return fn()


class Ctx:
    def __init__(self, root):
        self.root = root
        self._doctor = None

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    def mkdir(self, name):
        d = self.path(name)
        os.makedirs(d)
        return d

    def write(self, name, text):
        p = self.path(name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def stub(self):
        return self.path("stub_server.py") if os.path.exists(self.path("stub_server.py")) else self.write("stub_server.py", STUB)

    def fake_shot(self):
        return self.path("fake_shot.py") if os.path.exists(self.path("fake_shot.py")) else self.write("fake_shot.py", FAKE_SHOT)

    def fixture_png(self):
        p = self.path("fixture.png")
        if not os.path.exists(p):
            with open(p, "wb") as f:
                f.write(png_of(solid(8, 8, (30, 90, 150))))
        return p

    def run(self, *args, cwd=None, env=None, timeout=120):
        e = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        if env:
            e.update(env)
        p = subprocess.run([BIN, *[str(a) for a in args]], capture_output=True, text=True, cwd=cwd or self.root, env=e, timeout=timeout)
        return p.returncode, p.stdout, p.stderr

    def diff_json(self, before, after, *extra):
        rc, out, err = self.run("diff", before, after, "--json", *extra)
        try:
            data = json.loads(out.strip())
        except ValueError:
            raise AssertionError(f"diff --json printed no JSON (exit {rc}): {out[:160]!r} {err[:160]!r}")
        return rc, data, {r["route"]: r for r in data["routes"]}

    def doctor_ready(self):
        if self._doctor is None:
            rc, out, err = self.run("doctor", timeout=120)
            lines = out.strip().splitlines()
            self._doctor = (lines[-1] if lines else "") == "DOCTOR: ready"
        return self._doctor

    def need_browser(self):
        if not os.path.isfile(BIN):
            raise Skip("scripts/launchers/deps-smoke not present")
        if not self.doctor_ready():
            raise Skip("deps-smoke doctor is not ready")


def mkset(c, name, items, manifest=None):
    """A shot set: <slug>.png per route (+ manifest.json when given); returns the directory."""
    d = c.mkdir(name)
    for route, data in items.items():
        with open(os.path.join(d, slug(route) + ".png"), "wb") as f:
            f.write(data)
    if manifest is not None:
        with open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f)
    return d


def manifest_of(routes, **fields):
    m = {"tool": "deps-smoke/builtin", "playwright": "1.63.0", "channel": "chrome", "viewport": {"width": 1440, "height": 900}, "full": False,
         "base": "http://127.0.0.1:1", "git": None}
    m.update(fields)
    m["routes"] = [{"route": r, "file": slug(r) + ".png", "ok": True, "error": None} for r in routes]
    return m


def last_line(text):
    lines = text.strip().splitlines()
    return lines[-1] if lines else ""


def stub_args(c, port, wrap=False, **env):
    """--serve/--ready/--env arguments that start the stub server on `port` (PORT and HOST travel through --env).
    With wrap the server is a background child of the shell that leads the group."""
    args = ["--serve", f"{PY} {shlex.quote(c.stub())}" + (" & wait" if wrap else ""), "--ready", f"http://127.0.0.1:{port}/", "--env", f"PORT={port}", "--env", "HOST=127.0.0.1"]
    for key, value in env.items():
        args += ["--env", f"{key}={value}"]
    return args


def cp_template(png):
    return f"cp {shlex.quote(png)} {{out}} # {{url}}"


# ------------------------------------------------------------------ cases: usage and decoding
def case_usage_64(c, t):
    a = mkset(c, "ua", {"/": png_of(solid(4, 4, (9, 9, 9)))})
    b = mkset(c, "ub", {"/": png_of(solid(4, 4, (9, 9, 9)))})
    out = c.path("uo")
    url = "http://127.0.0.1:9"
    shoot = ["shoot", "--base", url, "--routes", "/", "--out", out]
    bad = {
        "no arguments": [],
        "unknown subcommand": ["frobnicate"],
        "doctor with an argument": ["doctor", "extra"],
        "diff without dirs": ["diff"],
        "diff with one dir": ["diff", a],
        "diff unknown flag": ["diff", a, b, "--bogus"],
        "diff bad threshold": ["diff", a, b, "--threshold", "abc"],
        "diff tolerance out of range": ["diff", a, b, "--tolerance", "300"],
        "diff missing dir": ["diff", a, c.path("nope")],
        "diff flag without value": ["diff", a, b, "--threshold"],
        "shoot without flags": ["shoot"],
        "shoot without routes": ["shoot", "--base", url, "--out", out],
        "shoot bad base": ["shoot", "--base", "not-a-url", "--routes", "/", "--out", out],
        "shoot route without slash": ["shoot", "--base", url, "--routes", "no-slash", "--out", out],
        "shoot duplicate routes": ["shoot", "--base", url, "--routes", "/,/", "--out", out],
        "serve without ready": shoot + ["--serve", "true"],
        "ready without serve": shoot + ["--ready", url + "/"],
        "bad ready-status": shoot + ["--serve", "true", "--ready", url + "/", "--ready-status", "weird"],
        "env without equals": shoot + ["--serve", "true", "--ready", url + "/", "--env", "NOEQUALS"],
        "bad node pin": shoot + ["--serve", "true", "--ready", url + "/", "--node-pin", "latest"],
        "mask for an unknown route": shoot + ["--mask", "/zzz=h1"],
        "with lacking placeholders": shoot + ["--with", "true"],
        "with and cookie": shoot + ["--with", "true {url} {out}", "--cookie", "a=b"],
        "tiny width": shoot + ["--width", "10"],
    }
    for label, argv in bad.items():
        rc, so, se = c.run(*argv)
        t.ok(rc == 64, f"{label}: exit {rc}, expected 64")
        t.ok(not so.strip(), f"{label}: usage errors belong on stderr, stdout had {so[:80]!r}")
    rc, so, se = c.run("--help")
    t.ok(rc == 0 and so.startswith("usage: deps-smoke"), f"--help: exit {rc}, output {so[:60]!r}")
    t.ok(len(so.splitlines()) <= 40, "--help runs past 40 lines")
    t.ok(c.run("diff", "--help")[0] == 0, "diff --help must exit 0")


def gray_pic(w, h):
    return [[((x * 20 + y * 7) % 256,) * 3 + (255,) for x in range(w)] for y in range(h)]


def color_pic(w, h):
    return [[((x * 17) % 256, (y * 29) % 256, ((x + y) * 13) % 256, 255) for x in range(w)] for y in range(h)]


def alpha_pic(w, h):
    return [[((x * 21 + y * 5) % 256,) * 3 + ((x * 11 + y * 3) % 256,) for x in range(w)] for y in range(h)]


def shifted(pic, x, y, w, h):
    out = [list(r) for r in pic]
    for yy in range(y, y + h):
        for xx in range(x, x + w):
            r, g, b, a = out[yy][xx]
            out[yy][xx] = ((r + 100) % 256, (g + 100) % 256, (b + 100) % 256, a)
    return out


def case_decode_types_0_2_3_4_6(c, t):
    w, h = 12, 8
    plan = {"gray": (gray_pic(w, h), ["t0", "t2", "t3", "t4", "t6"]),
            "color": (color_pic(w, h), ["t2", "t3", "t6"]),
            "alpha": (alpha_pic(w, h), ["t4", "t3", "t6"])}
    before, same, moved = {}, {}, {}
    for name, (pic, kinds) in plan.items():
        for kind in kinds:
            route = f"/{name}-{kind}"
            before[route] = png_of(pic)
            same[route] = encode(pic, kind)
            moved[route] = encode(shifted(pic, 2, 2, 4, 4), kind)
    b = mkset(c, "dec-before", before)
    rc, data, by = c.diff_json(b, mkset(c, "dec-same", same), "--tolerance", "0", "--threshold", "0")
    t.ok(rc == 0, f"every encoding of one picture must read back identical, exit {rc}")
    t.ok(len(by) == len(before), f"expected {len(before)} routes, got {len(by)}")
    for route, entry in by.items():
        t.ok(entry["verdict"] == "same" and entry["ratio"] == 0 and entry["size_after"] == [w, h], f"{route}: {entry}")
    rc, data, by = c.diff_json(b, mkset(c, "dec-moved", moved), "--tolerance", "0", "--threshold", "0")
    t.ok(rc == 1, f"a moved block must be seen in every encoding, exit {rc}")
    for route, entry in by.items():
        ok = entry["verdict"] == "changed" and abs(entry["ratio"] - 16 / 96) < 1e-5 and entry["bbox"] == {"x": 2, "y": 2, "w": 4, "h": 4}
        t.ok(ok, f"{route}: {entry}")


def case_filters_0_to_4(c, t):
    rng = random.Random(5)
    w, h = 40, 30
    noise = [[tuple(rng.randrange(256) for _ in range(3)) + (255,) for _ in range(w)] for _ in range(h)]
    gray = [[(v, v, v, 255) for v in (rng.randrange(256) for _ in range(w))] for _ in range(h)]
    ga = [[(v, v, v, rng.randrange(256)) for v in (rng.randrange(256) for _ in range(w))] for _ in range(h)]
    pal = [tuple(rng.randrange(256) for _ in range(3)) + (rng.randrange(1, 256),) for _ in range(16)]
    indexed = [[rng.choice(pal) for _ in range(w)] for _ in range(h)]
    pics = {"t2": noise, "t6": noise, "t0": gray, "t4": ga, "t3": indexed}
    schemes = {"f1": (1,), "f2": (2,), "f3": (3,), "f4": (4,), "mixed": (0, 1, 2, 3, 4)}
    before, after = {}, {}
    for kind, pic in pics.items():
        for label, filters in schemes.items():
            before[f"/{kind}-{label}"] = encode(pic, kind, (0,))
            after[f"/{kind}-{label}"] = encode(pic, kind, filters)
    rc, data, by = c.diff_json(mkset(c, "flt-before", before), mkset(c, "flt-after", after), "--tolerance", "0", "--threshold", "0")
    t.ok(rc == 0, f"row filters 1-4 must reverse exactly, exit {rc}: {[r for r, e in by.items() if e['verdict'] != 'same'][:6]}")
    t.ok(len(by) == len(before), f"expected {len(before)} routes, got {len(by)}")


def case_identical_same(c, t):
    p = png_of(color_pic(30, 20))
    items = {"/": p, "/a-b": p, "/c": p}
    rc, so, se = c.run("diff", mkset(c, "id-before", items), mkset(c, "id-after", items))
    t.ok(rc == 0, f"exit {rc}, expected 0: {se[:120]}")
    t.ok(last_line(so) == "SMOKE: same(3)", f"verdict line {last_line(so)!r}")
    rc, data, by = c.diff_json(c.path("id-before"), c.path("id-after"))
    t.ok(all(e["verdict"] == "same" and e["ratio"] == 0 and e["bbox"] is None for e in by.values()), f"{by}")
    t.ok(set(by) == {"/", "/a-b", "/c"}, f"routes {sorted(by)}")


def case_region_changed_ratio_bbox(c, t):
    base = solid(100, 100, (200, 200, 200))
    twin = paint(solid(100, 100, (200, 200, 200)), 10, 10, 5, 5, (100, 200, 200))
    twin = paint(twin, 80, 70, 5, 5, (100, 200, 200))
    after = {
        "/a": png_of(paint(solid(100, 100, (200, 200, 200)), 30, 40, 20, 10, (140, 200, 200))),
        "/two": png_of(twin),
        "/small": png_of(paint(solid(100, 100, (200, 200, 200)), 5, 5, 1, 1, (100, 100, 100))),
        "/edge16": png_of(solid(100, 100, (216, 200, 200))),
        "/edge17": png_of(solid(100, 100, (217, 200, 200))),
    }
    b = mkset(c, "reg-before", {r: png_of(base) for r in after})
    a = mkset(c, "reg-after", after)
    rc, data, by = c.diff_json(b, a)
    t.ok(rc == 1, f"exit {rc}, expected 1")
    t.ok(by["/a"]["verdict"] == "changed" and by["/a"]["ratio"] == 0.02 and by["/a"]["bbox"] == {"x": 30, "y": 40, "w": 20, "h": 10}, f"/a: {by['/a']}")
    t.ok(by["/two"]["verdict"] == "changed" and by["/two"]["ratio"] == 0.005 and by["/two"]["bbox"] == {"x": 10, "y": 10, "w": 75, "h": 65}, f"/two: {by['/two']}")
    t.ok(by["/small"]["verdict"] == "same" and by["/small"]["ratio"] == 0.0001, f"/small: {by['/small']}")
    t.ok(by["/edge16"]["verdict"] == "same" and by["/edge16"]["ratio"] == 0, f"a delta of exactly 16 is not a change: {by['/edge16']}")
    t.ok(by["/edge17"]["verdict"] == "changed" and by["/edge17"]["ratio"] == 1 and by["/edge17"]["bbox"] == {"x": 0, "y": 0, "w": 100, "h": 100}, f"/edge17: {by['/edge17']}")
    rc, so, se = c.run("diff", b, a)
    t.ok("changed /a 2.00% bbox 30,40 20x10" in so, f"text line missing: {so[:300]!r}")
    t.ok(last_line(so) == "SMOKE: changed(/a 2.00%, /edge17 100.00%, /two 0.50%)", f"verdict line {last_line(so)!r}")
    rc, data, by = c.diff_json(b, a, "--threshold", "0.02")
    t.ok(by["/a"]["verdict"] == "same", f"a ratio equal to the threshold is same: {by['/a']}")
    rc, data, by = c.diff_json(b, a, "--tolerance", "100")
    t.ok(rc == 0 and all(e["verdict"] == "same" for e in by.values()), f"tolerance 100 hides every delta here: {by}")


def case_resized(c, t):
    gray = (120, 120, 120)
    over = paint(solid(100, 110, gray), 20, 20, 10, 10, (10, 10, 10))
    b = mkset(c, "rs-before", {"/h": png_of(solid(100, 100, gray)), "/w": png_of(solid(100, 100, gray)), "/o": png_of(solid(100, 100, gray))})
    a = mkset(c, "rs-after", {"/h": png_of(solid(100, 120, gray)), "/w": png_of(solid(120, 100, gray)), "/o": png_of(over)})
    rc, data, by = c.diff_json(b, a)
    t.ok(rc == 1, f"exit {rc}, expected 1")
    t.ok(by["/h"]["verdict"] == "resized" and by["/h"]["size_before"] == [100, 100] and by["/h"]["size_after"] == [100, 120], f"/h: {by['/h']}")
    t.ok(by["/h"]["ratio"] == 0 and by["/h"]["bbox"] is None, f"an identical overlap has ratio 0: {by['/h']}")
    t.ok(by["/w"]["verdict"] == "resized" and by["/w"]["size_after"] == [120, 100], f"/w: {by['/w']}")
    t.ok(by["/o"]["verdict"] == "resized" and by["/o"]["ratio"] == 0.01 and by["/o"]["bbox"] == {"x": 20, "y": 20, "w": 10, "h": 10}, f"the overlap is still compared: {by['/o']}")
    rc, so, se = c.run("diff", b, a)
    t.ok(last_line(so) == "SMOKE: resized(/h, /o, /w)", f"verdict line {last_line(so)!r}")
    o = c.path("rs-out")
    c.run("diff", b, a, "--out", o)
    t.ok(sorted(os.listdir(o)) == ["diff-h.png", "diff-o.png", "diff-w.png", "diff.json"], f"resized routes get a diff image: {sorted(os.listdir(o))}")
    w, h, _, _ = read_png(os.path.join(o, "diff-h.png"))
    t.ok((w, h) == (100, 120), f"the diff image takes the after size, got {w}x{h}")


def case_missing(c, t):
    p = png_of(solid(10, 10, (50, 60, 70)))
    b = mkset(c, "ms-before", {"/a": p, "/b": p})
    a = mkset(c, "ms-after", {"/a": p, "/c": p})
    rc, data, by = c.diff_json(b, a)
    t.ok(rc == 1 and by["/b"]["verdict"] == "missing" and by["/c"]["verdict"] == "missing" and by["/a"]["verdict"] == "same", f"exit {rc}: {by}")
    t.ok(by["/b"]["size_after"] is None and by["/b"]["ratio"] is None, f"/b: {by['/b']}")
    t.ok(last_line(c.run("diff", b, a)[1]) == "SMOKE: missing(/b, /c)", "verdict line for missing routes")
    broken = manifest_of(["/d", "/e"])
    broken["routes"][0].update(file=None, ok=False, error="HTTP 500")
    mb = mkset(c, "ms-mb", {"/d": p, "/e": p}, manifest_of(["/d", "/e"]))
    ma = mkset(c, "ms-ma", {"/e": p}, broken)
    rc, data, by = c.diff_json(mb, ma)
    t.ok(rc == 1 and by["/d"]["verdict"] == "missing" and by["/e"]["verdict"] == "same", f"a route the manifest marks failed is missing: {by}")


def case_noise_unstable(c, t):
    base = solid(100, 100, (100, 100, 100))
    noisy = paint(solid(100, 100, (100, 100, 100)), 10, 10, 10, 10, (250, 250, 250))
    b = mkset(c, "nz-before", {"/a": png_of(base), "/b": png_of(base), "/c": png_of(base), "/d": png_of(base)})
    n = mkset(c, "nz-noise", {"/a": png_of(noisy), "/b": png_of(base), "/c": png_of(solid(100, 110, (100, 100, 100))), "/d": png_of(base)})
    changed = paint(solid(100, 100, (100, 100, 100)), 0, 0, 20, 20, (0, 0, 0))
    a = mkset(c, "nz-after", {"/a": png_of(base), "/b": png_of(changed), "/c": png_of(base), "/d": png_of(base)})
    rc, data, by = c.diff_json(b, a)
    t.ok(by["/a"]["verdict"] == "same" and by["/b"]["verdict"] == "changed", f"without --noise the baseline is trusted: {by}")
    rc, data, by = c.diff_json(b, a, "--noise", n)
    t.ok(rc == 1, f"exit {rc}, expected 1")
    t.ok(by["/a"]["verdict"] == "unstable" and by["/a"]["ratio"] == 0.01 and by["/a"]["bbox"] == {"x": 10, "y": 10, "w": 10, "h": 10}, f"/a: {by['/a']}")
    t.ok(by["/b"]["verdict"] == "changed" and by["/b"]["ratio"] == 0.04, f"a stable baseline keeps its own verdict: {by['/b']}")
    t.ok(by["/c"]["verdict"] == "unstable" and by["/c"]["ratio"] is None, f"a baseline whose size moves is unstable: {by['/c']}")
    t.ok(by["/d"]["verdict"] == "same", f"/d: {by['/d']}")
    rc, so, se = c.run("diff", b, a, "--noise", n)
    t.ok(last_line(so) == "SMOKE: changed(/b 4.00%) unstable(/a, /c)", f"verdict line {last_line(so)!r}")
    t.ok("unstable /a noise 1.00%" in so, f"text line missing: {so[:300]!r}")
    partial = mkset(c, "nz-partial", {"/a": png_of(base)})
    rc, so, se = c.run("diff", b, a, "--noise", partial)
    t.ok("WARN noise set has no shot of" in so, f"a noise set that lacks routes must say so: {so[:300]!r}")


def case_unsupported_16bit_and_interlaced(c, t):
    good = png_of(solid(4, 4, (10, 20, 30)))
    rows = [bytes(12) for _ in range(4)]
    cut = good[:-20]
    flipped = bytearray(good)
    flipped[good.index(b"IDAT") + 6] ^= 0xFF
    text = chunk(b"tEXt", b"Comment\x00acme")
    badtext = good[:-12] + text[:-1] + bytes([text[-1] ^ 0xFF]) + good[-12:]
    after = {
        "/a": png_bytes(4, 4, [bytes(24) for _ in range(4)], 2, depth=16),
        "/b": png_bytes(4, 4, rows, 2, interlace=1),
        "/c": png_bytes(4, 4, [bytes(2) for _ in range(4)], 3, depth=4, plte=bytes(48)),
        "/d": b"not a png at all",
        "/e": bytes(flipped),
        "/f": cut,
        "/g": patch_ihdr(good, 9, 5),
        "/h": badtext,
    }
    b = mkset(c, "un-before", {r: good for r in after})
    rc, data, by = c.diff_json(b, mkset(c, "un-after", after))
    t.ok(rc == 2, f"an unsupported PNG exits 2, got {rc}")
    t.ok(all(e["verdict"] == "unparsed" and e.get("reason") for e in by.values()), f"every route is unparsed with a reason: {by}")
    t.ok("16-bit" in by["/a"]["reason"] and "interlaced" in by["/b"]["reason"] and "4-bit" in by["/c"]["reason"], f"reasons: {[e['reason'] for e in by.values()]}")
    t.ok("checksum" in by["/h"].get("reason", ""), f"a bad CRC on any chunk is unparsed: {by['/h']}")
    rc, so, se = c.run("diff", b, c.path("un-after"))
    t.ok(last_line(so) == "SMOKE: unparsed(/a, /b, /c, /d, /e, /f, /g, /h)", f"verdict line {last_line(so)!r}")
    rc, so, se = c.run("diff", b, mkset(c, "un-good", {r: good for r in after}))
    t.ok(rc == 0, f"control: supported PNGs exit 0, got {rc}")


def case_out_writes_decodable_png(c, t):
    base = solid(64, 48, (100, 100, 100))
    moved = paint(solid(64, 48, (100, 100, 100)), 10, 5, 20, 10, (200, 100, 50))
    b = mkset(c, "ow-before", {"/": png_of(base), "/x": png_of(base)})
    a = mkset(c, "ow-after", {"/": png_of(moved), "/x": png_of(base)})
    o = c.path("ow-out")
    rc, so, se = c.run("diff", b, a, "--out", o)
    t.ok(rc == 1, f"exit {rc}, expected 1")
    t.ok(sorted(os.listdir(o)) == ["diff-root.png", "diff.json"], f"only the changed route gets an image: {sorted(os.listdir(o))}")
    w, h, color, rows = read_png(os.path.join(o, "diff-root.png"))
    t.ok((w, h) == (64, 48), f"diff image size {w}x{h}")
    t.ok(pixel(os.path.join(o, "diff-root.png"), 12, 7) == (255, 0, 0), "a changed pixel must be red")
    t.ok(pixel(os.path.join(o, "diff-root.png"), 50, 40) == (30, 30, 30), "an unchanged pixel must be the after image at 30%")
    doc = json.load(open(os.path.join(o, "diff.json"), encoding="utf-8"))
    t.ok(set(doc) == {"routes", "threshold", "tolerance"} and doc["threshold"] == 0.002 and doc["tolerance"] == 16, f"diff.json keys {sorted(doc)}")
    t.ok(all(set(r) == {"route", "verdict", "ratio", "bbox", "size_before", "size_after"} for r in doc["routes"]), f"route keys {[sorted(r) for r in doc['routes']]}")
    text = json.dumps(doc)
    t.ok(not re.search(r"time|date|stamp|\d{4}-\d{2}-\d{2}", text, re.I), "diff.json must not carry timestamps")
    o2 = c.path("ow-out2")
    c.run("diff", a, a, "--out", o2)
    t.ok(sorted(os.listdir(o2)) == ["diff.json"], f"nothing changed, nothing to draw: {sorted(os.listdir(o2))}")
    shutil.copy(os.path.join(o, "diff-root.png"), os.path.join(o2, "diff-stale.png"))
    c.run("diff", a, a, "--out", o2)
    t.ok(sorted(os.listdir(o2)) == ["diff.json"], f"a stale diff image must be removed: {sorted(os.listdir(o2))}")


def snapshot(root):
    snap = []
    for dirpath, _, files in os.walk(root):
        for name in files:
            st = os.stat(os.path.join(dirpath, name))
            snap.append((os.path.relpath(os.path.join(dirpath, name), root), st.st_size, st.st_mtime_ns))
    return sorted(snap)


def case_no_out_no_writes(c, t):
    base = solid(30, 30, (100, 100, 100))
    b = mkset(c, "nw-before", {"/": png_of(base), "/y": png_of(base)})
    a = mkset(c, "nw-after", {"/": png_of(paint(solid(30, 30, (100, 100, 100)), 0, 0, 15, 15, (0, 0, 0))), "/y": png_of(base)})
    work = c.mkdir("nw-cwd")
    before = snapshot(c.root)
    for extra in ([], ["--json"], ["--noise", b]):
        rc, so, se = c.run("diff", b, a, *extra, cwd=work)
        t.ok(rc == 1, f"diff {extra}: exit {rc}")
    t.ok(snapshot(c.root) == before, "diff without --out must not create or touch any file")


def case_manifest_mismatch_warning(c, t):
    p = png_of(solid(10, 10, (1, 2, 3)))
    mb = manifest_of(["/"], playwright="1.63.0")
    b = mkset(c, "mm-before", {"/": p}, mb)
    a = mkset(c, "mm-after", {"/": p}, manifest_of(["/"], playwright="1.64.0"))
    rc, so, se = c.run("diff", b, a)
    lines = so.strip().splitlines()
    warn = [l for l in lines if l.startswith("WARN")]
    t.ok(rc == 0, f"a manifest mismatch is a warning only, exit {rc}")
    t.ok(len(warn) == 1 and "manifest" in warn[0] and "1.63.0" in warn[0] and "1.64.0" in warn[0], f"warning lines {warn}")
    t.ok(lines[-1] == "SMOKE: same(1)", f"the verdict stays last: {lines[-1]!r}")
    other = mkset(c, "mm-other", {"/": p}, manifest_of(["/"], playwright="1.63.0", tool="deps-smoke/with"))
    rc, so, se = c.run("diff", b, other)
    t.ok(any(l.startswith("WARN") and "tool" in l for l in so.splitlines()), f"a tool mismatch warns too: {so[:200]!r}")
    twin = mkset(c, "mm-twin", {"/": p}, mb)
    rc, so, se = c.run("diff", b, twin)
    t.ok("WARN" not in so, f"matching manifests must stay quiet: {so[:200]!r}")


# ------------------------------------------------------------------ cases: serve and shoot
def case_serve_port_busy(c, t):
    fixture = c.fixture_png()
    holders, spots = [], []
    try:
        v4 = socket.socket()
        v4.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        v4.bind(("127.0.0.1", 0))
        v4.listen(4)
        holders.append(v4)
        spots.append(("127.0.0.1", v4.getsockname()[1], "http://127.0.0.1:%d"))
        try:
            v6 = socket.socket(socket.AF_INET6)
            v6.bind(("::1", 0))
            v6.listen(4)
            holders.append(v6)
            spots.append(("::1", v6.getsockname()[1], "http://[::1]:%d"))
        except OSError:
            pass
        for host, port, fmt in spots:
            marker, out, base = c.path(f"started-{port}"), c.path(f"busy-{port}"), fmt % port
            serve = f"touch {shlex.quote(marker)}; sleep 30"
            rc, so, se = c.run("shoot", "--base", base, "--routes", "/", "--out", out, "--serve", serve, "--ready", base + "/", "--with", cp_template(fixture))
            t.ok(rc == 2, f"{host}: a busy port exits 2, got {rc}")
            t.ok("busy" in se and host in se, f"{host}: stderr must name the busy host: {se[:160]!r}")
            t.ok(last_line(so).startswith("SMOKE: env("), f"{host}: verdict line {last_line(so)!r}")
            t.ok(not os.path.exists(marker), f"{host}: a busy port must refuse before the server is started")
            t.ok(not os.path.exists(os.path.join(out, ".serve.pid")), f"{host}: a refused start leaves no pidfile")
            t.ok(not os.path.exists(os.path.join(out, "manifest.json")), f"{host}: a refused start writes no manifest")
    finally:
        for s in holders:
            s.close()


def case_shoot_with_template(c, t):
    fake = c.fake_shot()
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    template = f"{PY} {shlex.quote(fake)} {{url}} {{out}}"

    def args(out, routes, *extra):
        return ["shoot", "--base", base, "--routes", routes, "--out", out, *stub_args(c, port, wrap=True, MODE="pages"), "--with", template, *extra]

    out = c.path("wt-out")
    rc, so, se = c.run(*args(out, "/,/about.html,/missing.html"))
    t.ok(rc == 1, f"a failed route exits 1, got {rc}: {se[:160]}")
    t.ok(last_line(so) == "SMOKE: shot(2) failed(/missing.html)", f"verdict line {last_line(so)!r}")
    t.ok(len(so.splitlines()) <= 40, "the output runs past 40 lines")
    for name in ("root.png", "about-html.png"):
        p = os.path.join(out, name)
        t.ok(os.path.exists(p) and open(p, "rb").read(8) == SIG, f"{name} must be a PNG")
    t.ok(not os.path.exists(os.path.join(out, "missing-html.png")), "a failed route leaves no file")
    t.ok(not os.path.exists(os.path.join(out, ".serve.pid")), "the pidfile must be removed on the failure path")
    t.ok(not port_open(port), "the whole server group, a background child included, must die on the failure path")
    man = json.load(open(os.path.join(out, "manifest.json"), encoding="utf-8"))
    t.ok(list(man) == ["tool", "playwright", "channel", "viewport", "full", "base", "routes", "git"], f"manifest keys {list(man)}")
    t.ok(man["tool"] == "deps-smoke/with" and man["playwright"] is None and man["channel"] is None and man["base"] == base, f"manifest {man}")
    t.ok(man["git"] is None or set(man["git"]) == {"head", "branch"}, f"manifest git {man['git']}")
    t.ok([r["ok"] for r in man["routes"]] == [True, True, False], f"manifest routes {man['routes']}")
    t.ok(man["routes"][0] == {"route": "/", "file": "root.png", "ok": True, "error": None}, f"manifest route {man['routes'][0]}")
    t.ok(man["routes"][2]["file"] is None and str(man["routes"][2]["error"]).startswith("exit 1"), f"manifest route {man['routes'][2]}")
    t.ok(not re.search(r"time|date|stamp|\d{4}-\d{2}-\d{2}", json.dumps(man), re.I), "the manifest must not carry timestamps")

    good = "/,/about.html,/about.html?x=1&y=2"
    rc, so, se = c.run(*args(out, good))
    t.ok(rc == 0 and last_line(so) == "SMOKE: shot(3)", f"exit {rc}, verdict line {last_line(so)!r}: {se[:160]}")
    t.ok("server ready (HTTP 200)" in so, f"output {so[:200]!r}")
    t.ok(os.path.exists(os.path.join(out, "about-html-x-1-y-2.png")), "a URL with ? and & must reach the template quoted")
    t.ok(not port_open(port), "the server group must die on the success path")
    rc, so, se = c.run(*args(c.path("wt-json"), good, "--json"))
    doc = json.loads(so.strip())
    t.ok(len(so.strip().splitlines()) == 1 and doc["verdict"] == "SMOKE: shot(3)" and doc["exit"] == 0 and len(doc["routes"]) == 3, f"--json output {so[:200]!r}")
    rc, so, se = c.run("diff", out, c.path("wt-json"))
    t.ok(rc == 0 and last_line(so) == "SMOKE: same(3)", f"two shoots of the same pages are the same, exit {rc}: {so[-160:]!r}")


def browser_shoot(c, t, label, port, routes, out, *extra, **env):
    rc, so, se = c.run("shoot", "--base", f"http://127.0.0.1:{port}", "--routes", routes, "--out", out, *stub_args(c, port, **env), *extra, timeout=180)
    t.ok(rc == 0, f"{label}: exit {rc}: {(se or so)[:200]}")
    return rc


def case_builtin_shoot_mask(c, t):
    c.need_browser()
    port = free_port()
    shots = {}

    def shoot(name, *extra):
        shots[name] = c.path(name)
        browser_shoot(c, t, name, port, "/", shots[name], *extra, MODE="rand")

    shoot("m1", "--mask", "/=#rand")
    shoot("m2", "--mask", "/=#rand")
    rc, data, by = c.diff_json(shots["m1"], shots["m2"])
    t.ok(rc == 0 and by["/"]["verdict"] == "same", f"masked shots of a randomised block must match: {by}")
    shot = os.path.join(shots["m1"], "root.png")
    t.ok(near(pixel(shot, 500, 200), (255, 0, 255), 3), f"the masked box is painted #ff00ff, got {pixel(shot, 500, 200)}")
    w, h, color, _ = read_png(shot, 1)
    t.ok((w, h) == (1440, 900) and color in (2, 6), f"default shot {w}x{h}, colour type {color}")
    man = json.load(open(os.path.join(shots["m1"], "manifest.json"), encoding="utf-8"))
    t.ok(man["tool"] == "deps-smoke/builtin" and man["channel"] == "chrome" and man["full"] is False, f"manifest {man}")
    t.ok(man["viewport"] == {"width": 1440, "height": 900} and isinstance(man["playwright"], str), f"manifest {man}")
    shoot("u1")
    verdict = None
    for attempt in range(3):
        shoot(f"u2-{attempt}")
        rc, data, by = c.diff_json(shots["u1"], shots[f"u2-{attempt}"])
        verdict = by["/"]["verdict"]
        if verdict == "changed":
            break
    t.ok(verdict == "changed", "premise: without a mask the random block differs from shot to shot")
    shoot("tall", "--width", "800", "--height", "600", "--full")
    w, h, _, _ = read_png(os.path.join(shots["tall"], "root.png"), 1)
    t.ok(w == 800 and h >= 2400, f"--width 800 --full gave {w}x{h}")


def case_cap_40_lines(c, t):
    routes = [f"/r{i}" for i in range(60)]
    b = mkset(c, "cap-before", {r: png_of(solid(6, 6, (10, 10, 10))) for r in routes})
    a = mkset(c, "cap-after", {r: png_of(solid(6, 6, (200, 10, 10))) for r in routes})
    rc, so, se = c.run("diff", b, a)
    t.ok(rc == 1, f"exit {rc}, expected 1")
    t.ok(len(so.splitlines()) <= 40, f"diff printed {len(so.splitlines())} lines")
    t.ok(last_line(so).startswith("SMOKE: changed(") and "+" in last_line(so), f"verdict line {last_line(so)!r}")
    rc, so, se = c.run("diff", b, a, "--json")
    t.ok(len(so.strip().splitlines()) == 1 and len(json.loads(so)["routes"]) == 60, "--json keeps every route on one line")
    rc, so, se = c.run("shoot", "--base", "http://127.0.0.1:9", "--routes", ",".join(routes), "--out", c.path("cap-out"), "--with", "false {url} {out}")
    t.ok(rc == 1, f"exit {rc}, expected 1")
    t.ok(len(so.splitlines()) <= 40, f"shoot printed {len(so.splitlines())} lines")
    t.ok(last_line(so).startswith("SMOKE: shot(0) failed(/r0, /r1"), f"verdict line {last_line(so)!r}")


def case_ready_semantics(c, t):
    fixture = c.fixture_png()

    def attempt(label, status, extra, want_rc, mode="fixed", needle=None):
        port = free_port()
        out = c.path(f"rd-{label}")
        base = f"http://127.0.0.1:{port}"
        rc, so, se = c.run("shoot", "--base", base, "--routes", "/", "--out", out, *stub_args(c, port, STATUS=status, MODE=mode),
                           "--ready-timeout", "2", *extra, "--with", cp_template(fixture))
        t.ok(rc == want_rc, f"{label}: exit {rc}, expected {want_rc}: {se.strip()[:200]}")
        if needle:
            t.ok(needle in se, f"{label}: stderr lacks {needle!r}: {se.strip()[:200]!r}")
        t.ok(not os.path.exists(os.path.join(out, ".serve.pid")), f"{label}: the pidfile was left behind")
        t.ok(not port_open(port), f"{label}: the server is still alive after the run")

    attempt("200-default", 200, [], 0)
    attempt("404-default", 404, [], 0)
    attempt("200-2xx", 200, ["--ready-status", "2xx"], 0)
    attempt("404-2xx", 404, ["--ready-status", "2xx"], 2, needle="not ready")
    attempt("503-default", 503, [], 2, needle="HTTP 503")
    attempt("503-any", 503, ["--ready-status", "any"], 0)
    attempt("tcp-only", 200, [], 2, mode="silent", needle="no HTTP answer")
    port = free_port()
    rc, so, se = c.run("shoot", "--base", f"http://127.0.0.1:{port}", "--routes", "/", "--out", c.path("rd-exit"), "--serve", "echo boom >&2; exit 3",
                       "--ready", f"http://127.0.0.1:{port}/", "--ready-timeout", "30", "--with", cp_template(fixture))
    t.ok(rc == 2 and "exited" in se and "code 3" in se, f"a server that dies before it is ready exits 2: {rc} {se.strip()[:200]!r}")
    t.ok("boom" in se, "the tail of the server log must be shown")
    t.ok(last_line(so).startswith("SMOKE: env("), f"verdict line {last_line(so)!r}")


def case_serve_pidfile_reaped(c, t):
    fixture = c.fixture_png()
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    out = c.path("pf-out")
    pidfile = os.path.join(out, ".serve.pid")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    with_pid = c.path("with.pid")
    hang = f"echo $$ > {shlex.quote(with_pid)}; sleep 8 # {{url}} {{out}}"
    first = subprocess.Popen([BIN, "shoot", "--base", base, "--routes", "/", "--out", out, *stub_args(c, port), "--with", hang],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, cwd=c.root)
    old = None

    def shoot_again():
        return c.run("shoot", "--base", base, "--routes", "/", "--out", out, *stub_args(c, port), "--with", cp_template(fixture))

    try:
        if not t.ok(wait_until(lambda: os.path.exists(pidfile) and port_open(port), 30), "the server did not come up"):
            return
        old = int(open(pidfile, encoding="utf-8").read().split()[0])
        time.sleep(0.3)
        first.kill()
        first.wait()
        t.ok(port_open(port) and pid_alive(old), "premise: a killed deps-smoke leaves its server running")
        t.ok(os.path.exists(pidfile), "premise: the pidfile survives the kill")
        rc, so, se = shoot_again()
        t.ok(rc == 0, f"the next shoot must reap the old server before it probes the port, exit {rc}: {se.strip()[:200]!r}")
        t.ok(any(l.startswith("WARN reaped") for l in so.splitlines()), f"the reap is reported: {so[:200]!r}")
        t.ok(wait_until(lambda: not pid_alive(old), 5), "the old server group is still alive")
        t.ok(not port_open(port) and not os.path.exists(pidfile), "the new run must leave neither a server nor a pidfile")
        decoy = subprocess.Popen(["sleep", "30"], start_new_session=True)
        try:
            with open(pidfile, "w", encoding="utf-8") as f:
                f.write(f"{decoy.pid}\nMon Jan  1 00:00:00 1990\n")
            rc, so, se = shoot_again()
            t.ok(rc == 0 and decoy.poll() is None, "a pidfile whose start time does not match must not kill the live process it names")
            t.ok(not os.path.exists(pidfile), "a stale pidfile is removed")
        finally:
            decoy.kill()
            decoy.wait()
        leader = subprocess.Popen(["sleep", "30"], start_new_session=True)
        threading.Thread(target=leader.wait, daemon=True).start()
        try:
            with open(pidfile, "w", encoding="utf-8") as f:
                f.write(f"{leader.pid}\n")
            rc, so, se = shoot_again()
            t.ok(rc == 0 and wait_until(lambda: leader.poll() is not None, 5), "a bare pidfile that names a group leader is reaped")
        finally:
            if leader.poll() is None:
                leader.kill()
    finally:
        if first.poll() is None:
            first.kill()
            first.wait()
        pids = [old] if old is not None else []
        if os.path.exists(with_pid):
            pids.append(int(open(with_pid, encoding="utf-8").read().strip() or 0))
        for pid in pids:
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                pass


def case_serve_killed_on_signal(c, t):
    for name, sig, code in (("sigterm", signal.SIGTERM, 143), ("sigint", signal.SIGINT, 130)):
        port = free_port()
        out = c.path(f"sg-{name}")
        pidfile = os.path.join(out, ".serve.pid")
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        proc = subprocess.Popen([BIN, "shoot", "--base", f"http://127.0.0.1:{port}", "--routes", "/", "--out", out, *stub_args(c, port, wrap=True),
                                 "--with", "sleep 20 # {url} {out}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, cwd=c.root)
        try:
            if not t.ok(wait_until(lambda: os.path.exists(pidfile) and port_open(port), 30), f"{name}: the server did not come up"):
                continue
            time.sleep(0.3)
            proc.send_signal(sig)
            try:
                rc = proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                rc = None
            t.ok(rc == code, f"{name}: exit {rc}, expected {code}")
            t.ok(wait_until(lambda: not port_open(port), 5), f"{name}: the server group must die with deps-smoke")
            t.ok(not os.path.exists(pidfile), f"{name}: the pidfile must be removed")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def case_shoot_cookie(c, t):
    c.need_browser()
    port = free_port()
    for label, extra, want in (("with", ["--cookie", "session=abc", "--cookie", "theme=dark"], (0, 255, 0)), ("without", [], (255, 0, 0))):
        out = c.path(f"ck-{label}")
        browser_shoot(c, t, label, port, "/", out, *extra, MODE="cookie")
        got = pixel(os.path.join(out, "root.png"), 10, 10)
        t.ok(near(got, want), f"{label} the cookie: pixel {got}, expected {want}")


def case_node_pin_path(c, t):
    root, names = nvm_nodes()
    if not names:
        raise Skip("no nvm Node versions installed")
    fixture = c.fixture_png()

    def which(pin, label):
        port = free_port()
        report = c.path(f"pin-{label}.txt")
        rc, so, se = c.run("shoot", "--base", f"http://127.0.0.1:{port}", "--routes", "/", "--out", c.path(f"pin-{label}"), *stub_args(c, port, REPORT=report),
                           "--node-pin", pin, "--with", cp_template(fixture))
        return rc, se, (open(report, encoding="utf-8").read().strip() if os.path.exists(report) else None)

    exact = names[0]
    rc, se, got = which(exact[1:], "exact")
    t.ok(rc == 0 and got == os.path.join(root, exact, "bin", "node"), f"--node-pin {exact[1:]}: exit {rc}, the server saw node at {got}")
    major = exact[1:].split(".")[0]
    newest = [n for n in names if n.startswith(f"v{major}.")][-1]
    rc, se, got = which(major, "major")
    t.ok(rc == 0 and got == os.path.join(root, newest, "bin", "node"), f"--node-pin {major}: exit {rc}, the server saw node at {got}, expected {newest}")
    rc, se, got = which("999", "absent")
    t.ok(rc == 2 and "not installed" in se, f"a version that is not installed exits 2: {rc} {se.strip()[:160]!r}")


def nvm_nodes():
    root = os.path.join(os.environ.get("NVM_DIR") or os.path.expanduser("~/.nvm"), "versions", "node")
    names = [n for n in (os.listdir(root) if os.path.isdir(root) else []) if re.fullmatch(r"v\d+\.\d+\.\d+", n) and os.path.exists(os.path.join(root, n, "bin", "node"))]
    return root, sorted(names, key=lambda n: tuple(int(p) for p in n[1:].split(".")))


def case_doctor_shape(c, t):
    rc, so, se = c.run("doctor")
    lines = so.strip().splitlines()
    t.ok(bool(lines) and lines[-1] in ("DOCTOR: ready", "DOCTOR: not ready"), f"last line {lines[-1:]}")
    t.ok(rc == (0 if lines[-1:] == ["DOCTOR: ready"] else 2), f"exit {rc} for {lines[-1:]}")
    t.ok(all(re.match(r"(ok|missing|info) ", l) for l in lines[:-1]), f"doctor lines {lines}")
    t.ok(len(lines) <= 40, f"doctor printed {len(lines)} lines")
    root, names = nvm_nodes()
    old = [n for n in names if 16 <= int(n[1:].split(".")[0]) < 20]
    if not old:
        return
    node, script = os.path.join(root, old[-1], "bin", "node"), os.path.join(HERE, "deps_smoke.mjs")
    p = subprocess.run([node, script, "doctor"], capture_output=True, text=True, cwd=c.root)
    t.ok(p.returncode == 2 and last_line(p.stdout) == "DOCTOR: not ready" and "missing node>=20" in p.stdout, f"{old[-1]}: doctor exit {p.returncode}: {p.stdout[-160:]!r}")
    p = subprocess.run([node, script, "shoot", "--base", "http://127.0.0.1:9", "--routes", "/", "--out", c.path("old-out"), "--with", cp_template(c.fixture_png())],
                       capture_output=True, text=True, cwd=c.root)
    t.ok(p.returncode == 2 and "Node 20+ required" in p.stderr and last_line(p.stdout).startswith("SMOKE: env("), f"{old[-1]}: shoot exit {p.returncode}: {p.stderr[:120]!r}")


def case_git_manifest(c, t):
    if not shutil.which("git"):
        raise Skip("git is not installed")
    repo = c.mkdir("gm-repo")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")

    def git(*args):
        return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True, env=env).stdout.strip()

    git("init", "-q", "-b", "main")
    git("-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-q", "--allow-empty", "-m", "init")
    out = c.path("gm-out")
    rc, so, se = c.run("shoot", "--base", "http://127.0.0.1:9", "--routes", "/", "--out", out, "--cwd", repo, "--with", cp_template(c.fixture_png()), env=env)
    t.ok(rc == 0, f"exit {rc}: {se[:160]}")
    man = json.load(open(os.path.join(out, "manifest.json"), encoding="utf-8"))
    t.ok(man["git"] == {"head": git("rev-parse", "HEAD"), "branch": "main"}, f"manifest git {man['git']}")


CASES = [
    ("usage_64", case_usage_64),
    ("doctor_shape", case_doctor_shape),
    ("decode_types_0_2_3_4_6", case_decode_types_0_2_3_4_6),
    ("filters_0_to_4", case_filters_0_to_4),
    ("identical_same", case_identical_same),
    ("region_changed_ratio_bbox", case_region_changed_ratio_bbox),
    ("resized", case_resized),
    ("missing", case_missing),
    ("noise_unstable", case_noise_unstable),
    ("unsupported_16bit_and_interlaced", case_unsupported_16bit_and_interlaced),
    ("out_writes_decodable_png", case_out_writes_decodable_png),
    ("no_out_no_writes", case_no_out_no_writes),
    ("manifest_mismatch_warning", case_manifest_mismatch_warning),
    ("serve_port_busy", case_serve_port_busy),
    ("shoot_with_template", case_shoot_with_template),
    ("builtin_shoot_mask", case_builtin_shoot_mask),
    ("cap_40_lines", case_cap_40_lines),
    ("ready_semantics", case_ready_semantics),
    ("serve_pidfile_reaped", case_serve_pidfile_reaped),
    ("serve_killed_on_signal", case_serve_killed_on_signal),
    ("shoot_cookie", case_shoot_cookie),
    ("node_pin_path", case_node_pin_path),
    ("git_manifest", case_git_manifest),
]


def run_case(fn, keep):
    root = os.path.realpath(tempfile.mkdtemp(prefix="deps-smoke-selftest-"))
    t = Check()
    try:
        fn(Ctx(root), t)
        verdict, why = ("FAIL", "; ".join(p[:230] for p in t.problems[:8])) if t.problems else ("PASS", "")
    except Skip as s:
        verdict, why = "SKIP", str(s)
    except Exception as exc:  # a broken harness is a failure, not a crash
        verdict, why = "FAIL", f"harness error: {exc!r}"
    finally:
        if keep:
            print(f"  kept {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)
    return verdict, why


def main():
    ap = argparse.ArgumentParser(description="Behavioural tests for deps_smoke.mjs and scripts/launchers/deps-smoke")
    ap.add_argument("--only", help="run a single case by name")
    ap.add_argument("--keep", action="store_true", help="leave the temp trees on disk")
    args = ap.parse_args()
    if not (os.path.isfile(BIN) and os.path.isfile(os.path.join(HERE, "deps_smoke.mjs"))):
        print(f"scripts/launchers/deps-smoke or deps_smoke.mjs not found under {PLUGIN}")
        return 2
    cases = [case for case in CASES if not args.only or case[0] == args.only]
    if not cases:
        print(f"unknown case {args.only!r}; known: {', '.join(n for n, _ in CASES)}")
        return 2
    tally = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    for name, fn in cases:
        verdict, why = run_case(fn, args.keep)
        tally[verdict] += 1
        print(f"{verdict} {name}" + (f" - {why}" if why else ""), flush=True)
    print(f"{tally['PASS']} PASS · {tally['FAIL']} FAIL · {tally['SKIP']} SKIP (of {len(cases)})")
    return 1 if tally["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
