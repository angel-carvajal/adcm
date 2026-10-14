#!/usr/bin/env python3
"""design-board-selftest - behavioural tests for design-board.py and the capture launcher (stdlib only).

Usage:
  python3 design-board-selftest.py [--script PATH] [--only NAME] [--keep]

Every case works on a throwaway `tempfile` copy of fixtures/demo (Acme, Provider, Invoice, example.com) or on
images written here with zlib + struct, runs design-board.py as a subprocess (PYTHONDONTWRITEBYTECODE=1) and
prints `PASS|FAIL|SKIP <case> [- why]`, then the tally. Exit code 1 when any case FAILs.

The capture cases (doctor-shape, capture-smoke, variants-shots) go through bin/design-board; they SKIP when the
launcher or capture.mjs is absent, and the two that open a browser SKIP unless `design-board doctor` says ready.
thumbs-tool SKIPs without sips or magick. --keep leaves the temp trees on disk.
"""
import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
PLUGIN = os.path.dirname(os.path.dirname(SKILL))
DEMO = os.path.join(SKILL, "fixtures", "demo")
BIN = os.path.join(PLUGIN, "bin", "design-board")
CAPTURE = os.path.join(HERE, "capture.mjs")
BUILD_OUTPUTS = {"board.html", "shots", "tokens.css", "tokens.json", "artifacts.json", "decisions.md", "references.md"}
TABS = ("options", "refs", "market", "method", "tokens")
CONTRACT = ["--font-display", "--font-body", "--font-mono"] + [f"--step-{n}" for n in range(6)] + [
    "--step--1", "--leading-tight", "--leading-body", "--tracking-display"] + [
    f"--color-{r}" for r in ("ground", "surface", "ink", "ink-muted", "primary", "accent", "accent-ink", "border")] + [
    f"--space-{n}" for n in range(1, 7)] + ["--radius", "--dur", "--ease"]
USERS = re.compile("/Us" + "ers/")


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


def validate_regexes():
    """PRIV and BAD_PATH from the dev clone's _build/validate.py (absent in an installed plugin)."""
    d = HERE
    while True:
        cand = os.path.join(d, "_build", "validate.py")
        if os.path.isfile(cand):
            break
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent
    found = {}
    for node in ast.walk(ast.parse(open(cand, encoding="utf-8").read())):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and node.value.args and \
                any(isinstance(t, ast.Name) and t.id in ("PRIV", "BAD_PATH") for t in node.targets):
            flags = re.I if any(isinstance(x, ast.Attribute) and x.attr in ("I", "IGNORECASE")
                                for x in node.value.args[1:]) else 0
            found[node.targets[0].id] = re.compile(ast.literal_eval(node.value.args[0]), flags)
    return found if len(found) == 2 else None


class Skip(Exception):
    pass


class Check:
    def __init__(self):
        self.problems = []

    def ok(self, cond, msg):
        if not cond:
            self.problems.append(msg)
        return cond


class Ctx:
    def __init__(self, root, script):
        self.root = root
        self.script = script

    def run(self, *args, env=None, cmd=None, timeout=120):
        e = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        if env:
            e.update(env)
        argv = cmd or [sys.executable, self.script]
        p = subprocess.run(argv + [str(a) for a in args], capture_output=True, text=True, env=e, timeout=timeout)
        return p.returncode, p.stdout, p.stderr

    def demo(self, name="d"):
        dst = os.path.join(self.root, name)
        shutil.copytree(DEMO, dst, ignore=lambda d, names: [n for n in names if d == DEMO and n in BUILD_OUTPUTS])
        return dst

    @staticmethod
    def load(d, rel="board.json"):
        with open(os.path.join(d, rel), encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def save(d, data, rel="board.json"):
        with open(os.path.join(d, rel), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


def png(path, w, h, rgb=(200, 120, 60)):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
                chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def jpeg_width(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i < len(data) - 9:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01, 0xFF) or 0xD0 <= marker <= 0xD7:
            i += 2 if marker != 0xFF else 1
            continue
        size = struct.unpack(">H", data[i + 2:i + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            return struct.unpack(">H", data[i + 7:i + 9])[0]
        i += 2 + size
    return None


def board_data(d):
    with open(os.path.join(d, "board.html"), encoding="utf-8") as f:
        page = f.read()
    m = re.search(r'<script type="application/json" id="board-data">(.*?)</script>', page, re.S)
    return page, json.loads(m.group(1)) if m else None


def fails_of(out):
    return [l for l in out.splitlines() if l.startswith("FAIL ")]


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


_doctor = {}


def doctor(c):
    if not (os.path.isfile(BIN) and os.path.isfile(CAPTURE)):
        raise Skip("bin/design-board or capture.mjs not present")
    if "res" not in _doctor:
        _doctor["res"] = c.run("doctor", "--out", c.root, cmd=[BIN], timeout=120)
    return _doctor["res"]


def need_ready(c):
    code, out, _ = doctor(c)
    if "DOCTOR: ready" not in out:
        missing = "; ".join(l for l in out.splitlines() if l.startswith("missing"))
        raise Skip(f"doctor not ready ({missing or 'no doctor output'})")


# ------------------------------------------------------------------ cases
def case_check_valid(c, t):
    d = c.demo()
    code, out, err = c.run("check", d)
    t.ok(code == 0, f"exit {code}: {out}{err}")
    t.ok("OK check: 3 options" in out, f"no OK line: {out}")
    t.ok(not fails_of(out), f"unexpected FAIL lines: {fails_of(out)}")


def drop_option(d, ident, rename=None):
    b = Ctx.load(d)
    o = Ctx.load(d, "board.d/options.json")
    for doc in (b, o):
        if rename:
            for opt in doc["options"]:
                if opt["id"] == ident:
                    opt["id"] = rename
        else:
            doc["options"] = [x for x in doc["options"] if x["id"] != ident]
    Ctx.save(d, b)
    Ctx.save(d, o, "board.d/options.json")


def case_check_two_options(c, t):
    d = c.demo()
    drop_option(d, "c")
    code, out, _ = c.run("check", d)
    t.ok(code == 1, f"exit {code}")
    t.ok(any("exactly 3 options" in l for l in fails_of(out)), f"no options FAIL: {out}")


def case_check_bad_id_set(c, t):
    d = c.demo()
    drop_option(d, "c", rename="d")
    code, out, _ = c.run("check", d)
    t.ok(code == 1, f"exit {code}")
    t.ok(any("exactly 3 options" in l and "d" in l for l in fails_of(out)), f"no id-set FAIL: {out}")


def case_check_url_scheme(c, t):
    d = c.demo()
    b = Ctx.load(d)
    b["references"][0]["url"] = "ftp://atlas.example.com/"
    b["references"][1]["via"] = "javascript:alert(1)"
    b["market"][0]["url"] = "providerbooks.example.com"
    Ctx.save(d, b)
    code, out, _ = c.run("check", d)
    f = fails_of(out)
    t.ok(code == 1, f"exit {code}")
    for path in ("references.atlas-studio.url", "references.paper-mill.via", "market.provider-books.url"):
        t.ok(any(l.startswith(f"FAIL {path}:") for l in f), f"no FAIL for {path}: {f}")


def case_check_missing_file(c, t):
    d = c.demo()
    b = Ctx.load(d)
    b["references"][2]["files"] = ["captures/nope-d.jpg"]
    b["market"][1]["files"] = ["captures/absent.jpg"]
    Ctx.save(d, b)
    os.remove(os.path.join(d, "variants", "c.html"))
    code, out, _ = c.run("check", d)
    f = fails_of(out)
    t.ok(code == 1, f"exit {code}")
    for want in ("FAIL captures/nope-d.jpg: missing", "FAIL captures/absent.jpg: missing", "FAIL variants/c.html: missing"):
        t.ok(any(l.startswith(want) for l in f), f"missing {want!r}: {f}")
    b["step"] = "references"
    Ctx.save(d, b)
    code, out, _ = c.run("check", d)
    t.ok("WARN variants/c.html: missing" in out and not any("variants/c.html" in l for l in fails_of(out)),
         f"step references should only WARN a missing variant: {out}")


def case_check_limits(c, t):
    d = c.demo()
    b = Ctx.load(d)
    r = b["references"]
    r[0]["title"] = "x" * 81
    r[1]["tags"] = list("abcdefg")
    r[2]["dropped"] = {"is": True}
    r[2]["surprise"] = 1
    for i in range(10):
        r.append({"id": f"extra-{i}", "title": f"Extra {i}", "url": f"https://extra{i}.example.com/", "kind": "live",
                  "finalist": True, "files": ["captures/atlas-studio-d.jpg"]})
    b["options"][0]["tokens"]["display"] = "ghost-font"
    b["tokens"]["scalePresets"][0]["ratio"] = 2.5
    b["tokens"]["fontShortlist"][1]["stack"] = "Georgia; } body { color: red"
    outside = os.path.join(c.root, "outside.jpg")
    shutil.copy(os.path.join(d, "captures", "grain-co-d.jpg"), outside)
    os.symlink(outside, os.path.join(d, "captures", "linked.jpg"))
    r[4]["files"] = ["captures/linked.jpg"]
    r[3]["commerce"] = "Checkout in two steps"
    Ctx.save(d, b)
    o = Ctx.load(d, "board.d/options.json")
    o["options"][0]["palettes"][0]["colors"]["ink"] = "#FFF"
    Ctx.save(d, o, "board.d/options.json")
    vb = os.path.join(d, "variants", "b.html")
    with open(vb, encoding="utf-8") as f:
        text = f.read()
    text = text.replace("data-board-bridge", "data-x").replace("</style>", ".z{color:#ff0000;font-size:14px}</style>")
    with open(vb, "w", encoding="utf-8") as f:
        f.write(text)
    code, out, _ = c.run("check", d)
    f = fails_of(out)
    t.ok(code == 1, f"exit {code}")
    wants = ("references.atlas-studio.title: 81 chars > 80", "references.paper-mill.tags", "references.quiet-books.dropped.why",
             "finalists > 12", "options.a.tokens.display", "tokens.scalePresets[0].ratio", "palettes[0].ink",
             "variants/b.html: missing the data-board-bridge", "variants/b.html: color literal",
             "variants/b.html: font-size literal", "tokens.fontShortlist[1].stack: only letters",
             "FAIL captures/linked.jpg: outside .design")
    for w in wants:
        t.ok(any(w in l for l in f), f"no FAIL with {w!r}")
    t.ok("WARN board.json.references[2]: unknown key surprise" in out, "unknown key is not a WARN")
    t.ok("unknown key commerce" not in out, "commerce is reported as unknown")


def case_check_dangling_usedref(c, t):
    d = c.demo()
    b = Ctx.load(d)
    b["options"][1]["usedRefs"] = ["ghost-ref"]
    b["options"][2]["usedRefs"] = ["northwind-pay"]
    b["options"][0]["usedMarket"] = ["nobody"]
    Ctx.save(d, b)
    code, out, _ = c.run("check", d)
    f = fails_of(out)
    t.ok(code == 1, f"exit {code}")
    t.ok(any("options.b.usedRefs" in l and "ghost-ref" in l for l in f), f"dangling ref not reported: {f}")
    t.ok(any("options.c.usedRefs" in l and "is dropped" in l for l in f), f"dropped ref not reported: {f}")
    t.ok(any("options.a.usedMarket" in l for l in f), f"dangling market not reported: {f}")


def case_build_deterministic(c, t):
    d1, d2 = c.demo("one"), c.demo("two")
    code, out, err = c.run("build", d1)
    t.ok(code == 0, f"first build exit {code}: {out}{err}")
    page = os.path.join(d1, "board.html")
    first = open(page, "rb").read()
    m1 = os.stat(page).st_mtime_ns
    time.sleep(0.05)
    code, out, _ = c.run("build", d1)
    t.ok(code == 0 and "board.html: unchanged" in out, f"second build: {out}")
    t.ok(open(page, "rb").read() == first, "bytes changed on the second build")
    t.ok(os.stat(page).st_mtime_ns == m1, "mtime changed on the second build")
    c.run("build", d1, "--no-thumbs")
    c.run("build", d2, "--no-thumbs")
    t.ok(open(page, "rb").read() == open(os.path.join(d2, "board.html"), "rb").read(),
         "two copies render different bytes (a path or clock leaked)")
    t.ok(not re.search(r"20\d\d-\d\d-\d\dT\d\d:", first.decode()), "a timestamp is in board.html")


def case_build_asset_hash(c, t):
    d = c.demo()
    c.run("build", d)
    page, _ = board_data(d)
    urls = set(re.findall(r'"((?:shots|variants|captures|inspiration)/[^"?]+)\?v=([0-9a-f]+)"', page))
    t.ok(len(urls) >= 10, f"only {len(urls)} hashed asset URLs")
    for rel, v in urls:
        real = hashlib.sha256(open(os.path.join(d, rel), "rb").read()).hexdigest()[:8]
        t.ok(len(v) == 8 and v == real, f"{rel}: ?v={v} but sha256[:8]={real}")
    t.ok(not re.search(r'"(?:shots|variants)/[^"?]+"', page), "an asset URL without ?v=")
    with open(os.path.join(d, "variants", "a.html"), "a", encoding="utf-8") as f:
        f.write("<!-- edited -->\n")
    code, out, _ = c.run("build", d)
    page2, _ = board_data(d)
    t.ok("board.html: written" in out and page2 != page, "editing a variant did not change board.html")


def case_markup_tabs(c, t):
    d = c.demo()
    c.run("build", d, "--no-thumbs")
    page, data = board_data(d)
    tabs = re.findall(r'data-tab="([a-z]+)" aria-controls="tab-([a-z]+)"', page)
    t.ok([a for a, _ in tabs] == list(TABS), f"tabs {tabs}")
    t.ok(all(a == b for a, b in tabs), "data-tab and aria-controls disagree")
    for tab in TABS:
        t.ok(f'id="tab-{tab}"' in page, f"no panel tab-{tab}")
    t.ok(">Opciones<" in page and ">Referencias<" in page and ">Método<" in page, "Spanish labels missing")
    t.ok("p.id!=='tab-'+t" in page.replace(" ", "") and "$('#tab-'+b.dataset.tab)" in page.replace(" ", ""),
         "panels are not joined as 'tab-'+data-tab")
    t.ok("prefers-color-scheme" in page and "dataset.theme" in page, "theme wiring missing")
    b = Ctx.load(d)
    b["project"]["lang"] = "en"
    Ctx.save(d, b)
    c.run("build", d, "--no-thumbs")
    page, data = board_data(d)
    t.ok(">Options<" in page and ">References<" in page and '<html lang="en">' in page, "English labels missing")


def case_markup_lightbox(c, t):
    d = c.demo()
    c.run("build", d, "--no-thumbs")
    page, data = board_data(d)
    for needle in ('<dialog class="dlg" id="lb"', '<dialog class="dlg" id="viewer"', "showModal()", "'ArrowLeft'",
                   "'ArrowRight'", "opener.focus()", "data-flt", "'finalists'", "'dropped'", "'kind:'", 'data-w="390"',
                   'data-w="1440"', 'loading="lazy"', "T.liveFail"):
        t.ok(needle in page, f"missing {needle!r}")
    kinds = {r.get("kind") for r in data["refs"]}
    t.ok({"awwwards", "framer", "21st", "live", "manual"} <= kinds, f"kinds {kinds}")
    t.ok(any(r.get("dropped") and r.get("why") for r in data["refs"]), "no dropped reference with its reason")


def case_markup_urls(c, t):
    d = c.demo()
    b = Ctx.load(d)
    b["references"][0]["url"] = "https://atlas.example.com/a?x=1&y=2"
    b["references"][0]["notes"] = "</script><script>alert(1)</script> & <b>"
    b["market"][0]["works"] = "<!-- x --> </script> still data"
    Ctx.save(d, b)
    code, out, _ = c.run("build", d, "--no-thumbs")
    t.ok(code == 0, out)
    page, data = board_data(d)
    t.ok(data is not None, "board-data does not parse (</ not escaped?)")
    if data:
        ref = data["refs"][0]
        t.ok(ref["url"] == "https://atlas.example.com/a?x=1&y=2", f"url changed: {ref['url']}")
        t.ok(ref["notes"].startswith("</script>"), "notes did not round-trip")
        t.ok(data["market"][0]["works"] == "<!-- x --> </script> still data", "a <!-- note did not round-trip")
        block = re.search(r'id="board-data">(.*?)</script>', page, re.S).group(1)
        t.ok(not re.search(r"[<>&]", block), "raw < > or & inside the data block")
        t.ok(all(r.get("url") for r in data["refs"]), "a reference lost its url")
        t.ok(all(r.get("via") for r in data["refs"] if r["id"] in ("atlas-studio", "paper-mill")), "via lost")
    t.ok(page.count("</script>") == 3, "a raw </script> leaked out of the data block")
    t.ok('href="${esc(u)}" target="_blank" rel="noopener"' in page, "link builder lacks escaped href + rel=noopener")
    t.ok("/^https?:\\/\\//i.test(u" in page, "link builder does not refuse non-http URLs")


def case_markup_export(c, t):
    d = c.demo()
    c.run("build", d, "--no-thumbs")
    page, data = board_data(d)
    for needle in ("new Blob(", "`tokens-${S.o}.css`", "`tokens-${S.o}.json`", "navigator.clipboard", '<pre id="tk-css">',
                   "id=\"tk-combo\"", "setProperty(k,v)", "postMessage({type: 'board-tokens'", "location.hash",
                   "history.replaceState"):
        t.ok(needle in page, f"missing {needle!r}")
    t.ok("localStorage" not in page and "sessionStorage" not in page, "browser storage in board.html")
    code, out, _ = c.run("adopt", "--dry", "a/f1/r1.2/p1", d)
    t.ok(code == 0, f"adopt --dry exit {code}")
    for var in CONTRACT:
        t.ok(re.search(rf"^\s*{re.escape(var)}: .+;$", out, re.M), f"adopt --dry lacks {var}")
    t.ok(not os.path.exists(os.path.join(d, "tokens.css")), "--dry wrote tokens.css")
    code, out, _ = c.run("adopt", "b/f2/compact/p2", d)
    t.ok(code == 0 and Ctx.load(d)["decisions"]["chosen"] == "b", f"adopt did not set decisions.chosen: {out}")
    tj = Ctx.load(d, "tokens.json")
    t.ok(tj.get("combo") == "b/f2/r1.2/p2" and tj["scale"]["base"] == 15, f"tokens.json {tj.get('combo')}")
    code, out, _ = c.run("adopt", "--dry", "b/f2/r1.25b18/p1", d)
    t.ok(code == 0 and "--step-0: 1.125rem;" in out and "b/f2/r1.25b18/p1" in out, "combo with b<base> not honoured")
    t.ok(c.run("adopt", "--dry", "b/f2/r1.25b30/p1", d)[0] == 1, "base out of range is not exit 1")
    t.ok("b'+fmt(S.b)" in page, "the board does not emit b<base> in the combo")
    css1 = open(os.path.join(d, "tokens.css"), encoding="utf-8").read()
    shutil.copy(os.path.join(d, "tokens.json"), os.path.join(c.root, "exported.json"))
    code, out, _ = c.run("adopt", "--file", os.path.join(c.root, "exported.json"), d)
    t.ok(code == 0, f"adopt --file exit {code}: {out}")
    t.ok(open(os.path.join(d, "tokens.css"), encoding="utf-8").read() == css1, "adopt --file round-trip differs")


def case_markup_no_base64(c, t):
    d = c.demo()
    c.run("build", d)
    page, _ = board_data(d)
    t.ok("data:image" not in page and ";base64," not in page, "inline base64 in board.html")
    size = len(page.encode())
    t.ok(size <= 400 * 1024, f"board.html is {size} bytes")
    ext = re.findall(r'(?:src|href)="(https?://[^"]+)"', page)
    t.ok(all(u.startswith(("https://fonts.googleapis.com", "https://fonts.gstatic.com")) for u in ext),
         f"external resources other than Google Fonts: {ext}")
    t.ok(not re.search(r"<script[^>]+src=", page), "a script src in board.html")
    tmpl = os.path.join(SKILL, "templates", "board.html.tmpl")
    t.ok(os.path.getsize(tmpl) <= 45 * 1024, f"template is {os.path.getsize(tmpl)} bytes")


def case_index_sidecar(c, t):
    d = c.demo()
    insp = os.path.join(d, "inspiration")
    for n in os.listdir(insp):
        os.remove(os.path.join(insp, n))
    png(os.path.join(insp, "Mood One.png"), 8, 6)
    png(os.path.join(insp, "mood_two.png"), 8, 6, (20, 40, 200))
    with open(os.path.join(insp, "Mood One.png.url"), "w") as f:
        f.write("https://www.pinterest.com/pin/1/\n")
    with open(os.path.join(insp, "sources.txt"), "w") as f:
        f.write("Mood One.png\thttps://loser.example.com/\tIgnored\nmood_two.png\thttps://moods.example.com/2\tSecond mood\n")
    b = Ctx.load(d)
    b["references"].append({"id": "insp-mood-two", "dropped": {"is": True, "why": "Too loud"}, "title": "Not used"})
    Ctx.save(d, b)
    code, out, _ = c.run("build", d, "--no-thumbs")
    t.ok(code == 0, out)
    _, data = board_data(d)
    by = {r["id"]: r for r in data["refs"]} if data else {}
    one, two = by.get("insp-mood-one"), by.get("insp-mood-two")
    t.ok(one and one.get("url") == "https://www.pinterest.com/pin/1/" and one.get("kind") == "pinterest",
         f"sidecar did not win or kind is wrong: {one}")
    t.ok(two and two.get("url") == "https://moods.example.com/2" and two.get("kind") == "manual" and
         two.get("title") == "Second mood", f"sources.txt line not applied: {two}")
    t.ok(two and two.get("dropped") and two.get("why") == "Too loud", "board.json override of dropped not applied")
    t.ok(one and one["media"][0]["t"].startswith("inspiration/Mood%20One.png?v="), "inspiration asset URL not quoted")


def case_thumbs_fallback(c, t):
    d = c.demo()
    empty = os.path.join(c.root, "empty-bin")
    os.makedirs(empty)
    code, out, err = c.run("build", d, env={"PATH": empty})
    t.ok(code == 0, f"exit {code}: {out}{err}")
    t.ok("WARN thumbs: no sips/magick" in out, f"no fallback WARN: {out}")
    src = open(os.path.join(d, "captures", "atlas-studio-d.jpg"), "rb").read()
    t.ok(open(os.path.join(d, "shots", "atlas-studio-d-480.jpg"), "rb").read() == src, "fallback is not a plain copy")


def case_thumbs_tool(c, t):
    if not (shutil.which("sips") or shutil.which("magick")):
        raise Skip("no sips or magick on PATH")
    d = c.demo()
    png(os.path.join(d, "inspiration", "wide.png"), 1000, 40)
    code, out, _ = c.run("build", d)
    t.ok(code == 0, out)
    small = os.path.join(d, "shots", "insp-wide-src-480.jpg")
    large = os.path.join(d, "shots", "insp-wide-src-1440.jpg")
    w1 = jpeg_width(small) if os.path.isfile(small) else None
    w2 = jpeg_width(large) if os.path.isfile(large) else None
    t.ok(w1 is not None and w1 <= 480, f"480 thumb width {w1}")
    t.ok(w2 is not None and w2 <= 1000, f"1440 thumb upscaled or missing: {w2}")
    code, out, _ = c.run("build", d)
    t.ok("thumbs: 0 made" in out, f"second build remade thumbs: {out}")


def case_registry_files_patch(c, t):
    d = c.demo()
    reg = {"docs_dir": ".", "artifacts": [
        {"file": "other.html", "title": "Other", "files": {"x.png": "x.png"}},
        {"file": "board.html", "title": "Acme · Design board", "in_close_block": False, "regen": "design-board build .",
         "files": {}, "sources": ["board.json"]}]}
    with open(os.path.join(d, "artifacts.json"), "w") as f:
        json.dump(reg, f, indent=2)
    code, out, _ = c.run("build", d)
    t.ok(code == 0 and "registry: files patched" in out, f"{out}")
    new = Ctx.load(d, "artifacts.json")
    row = new["artifacts"][1]
    t.ok(list(row) == ["file", "title", "in_close_block", "regen", "files", "sources"], f"key order {list(row)}")
    t.ok(new["artifacts"][0] == reg["artifacts"][0], "another row was touched")
    page, _ = board_data(d)
    used = set(re.findall(r'"((?:shots|variants)/[^"?]+)\?v=', page))
    t.ok(used and set(row["files"]) == used, f"files keys differ from the assets board.html uses")
    t.ok(all(k == v for k, v in row["files"].items()), "files values are not relative to the registry folder")
    raw = open(os.path.join(d, "artifacts.json"), encoding="utf-8").read()
    t.ok(raw.endswith("}\n") and '\n  "artifacts": [' in raw, "registry not written with indent=2")
    m = os.stat(os.path.join(d, "artifacts.json")).st_mtime_ns
    code, out, _ = c.run("build", d)
    t.ok("registry: files unchanged" in out and os.stat(os.path.join(d, "artifacts.json")).st_mtime_ns == m,
         "registry rewritten without changes")
    outer = os.path.join(c.root, "artifacts.json")
    with open(outer, "w") as f:
        json.dump({"artifacts": [{"file": "d/board.html", "title": "B"}]}, f)
    code, out, _ = c.run("build", d, "--registry", outer)
    row = Ctx.load(c.root, "artifacts.json")["artifacts"][0]
    t.ok(row.get("files") and all(v == "d/" + k for k, v in row["files"].items()), f"outer registry paths: {row}")
    with open(outer, "w") as f:
        json.dump({"artifacts": [{"file": "nothing.html"}]}, f)
    code, out, _ = c.run("build", d, "--registry", outer)
    t.ok(code == 0 and "WARN registry: no row" in out, f"no-row case: {out}")


def case_exit_codes(c, t):
    d = c.demo()
    t.ok(c.run("check", os.path.join(c.root, "nowhere"))[0] == 2, "missing folder is not exit 2")
    empty = os.path.join(c.root, "empty")
    os.makedirs(empty)
    t.ok(c.run("check", empty)[0] == 2, "missing board.json is not exit 2")
    bad = c.demo("bad")
    with open(os.path.join(bad, "board.json"), "w") as f:
        f.write("{ nope")
    t.ok(c.run("check", bad)[0] == 2, "unparseable board.json is not exit 2")
    frag = c.demo("frag")
    with open(os.path.join(frag, "board.d", "broken.json"), "w") as f:
        f.write("[1,")
    t.ok(c.run("build", frag)[0] == 2, "unparseable fragment is not exit 2")
    for argv in (["bogus"], [], ["check", d, "--nope"], ["check", d, "extra"], ["log", d, "--step", "2", "--decided", "x"],
                 ["log", d, "--step", "2", "--decided", "x", "--date", "14/10/2026"], ["adopt", "a/f1", d],
                 ["mark", d, "--drop", "R01"], ["build", d, "--dry"]):
        t.ok(c.run(*argv)[0] == 64, f"{argv} is not exit 64")
    t.ok(c.run("log", d, "--step", "5b", "--decided", "x", "--date", "2026-10-14", "--dry")[0] == 0, "--step 5b refused")
    t.ok(c.run("log", d, "--step", "five", "--decided", "x", "--date", "2026-10-14")[0] == 64, "--step five accepted")
    code, out, _ = c.run("--help")
    t.ok(code == 0 and out.startswith("usage: design-board.py <init|check|build|mark|adopt|log|pack>"), "--help")
    t.ok(c.run("adopt", d, "--dry", "b/f2/r1.25/p1")[0] == 0, "adopt <dir> <combo> order refused")
    t.ok(c.run("adopt", "--dry", "b/f2/r1.25/p1", d)[0] == 0, "adopt <combo> <dir> order refused")
    t.ok(c.run("adopt", "a/f1/r1.2/p9", d)[0] == 1, "unknown palette is not exit 1")
    t.ok(c.run("adopt", "a/f1/r3/p1", d)[0] == 1, "ratio out of range is not exit 1")
    t.ok(c.run("mark", d, "--drop", "ghost", "--why", "x")[0] == 1, "unknown id is not exit 1")
    code, out, _ = c.run("mark", d, "--drop", "R03", "--why", "Too quiet")
    ref = next(r for r in Ctx.load(d)["references"] if r["id"] == "quiet-books")
    t.ok(code == 0 and ref["dropped"] == {"is": True, "why": "Too quiet"}, f"R03 drop: {out}")
    t.ok(c.run("mark", d, "--finalist", "quiet-books")[0] == 1, "finalist on a dropped ref is not exit 1")
    code, _, _ = c.run("mark", d, "--undrop", "quiet-books")
    code2, _, _ = c.run("mark", d, "--finalist", "insp-invoice-grid")
    refs = {r["id"]: r for r in Ctx.load(d)["references"]}
    t.ok(code == 0 and code2 == 0 and refs["insp-invoice-grid"] == {"id": "insp-invoice-grid", "finalist": True},
         "mark on an inspiration item did not add a stub override")
    t.ok(c.run("check", d)[0] == 0, "board no longer checks after mark")
    code, _, _ = c.run("log", d, "--step", "3", "--decided", "Option A", "--date", "2026-10-14")
    code2, _, _ = c.run("log", d, "--step", "4", "--decided", "Lock", "--date", "2026-10-15", "--debt", "Dark mode later")
    log = open(os.path.join(d, "decisions.md"), encoding="utf-8").read()
    t.ok(code == code2 == 0 and log.index("2026-10-14") < log.index("2026-10-15") and "Dark mode later" in log
         and "| R01 | atlas-studio |" in log, "log entries not appended in order with tables")
    code, _, _ = c.run("pack", d)
    pack = open(os.path.join(d, "references.md"), encoding="utf-8").read()
    t.ok(code == 0 and "https://atlas.example.com/" in pack and "Too quiet" not in pack and "## Mercado" in pack,
         "pack output")
    t.ok(c.run("init", d)[0] == 1, "init over an existing board is not exit 1")
    fresh = os.path.join(c.root, "fresh")
    t.ok(c.run("init", fresh)[0] == 0 and c.run("check", fresh)[0] == 0, "init + check on a fresh folder")
    failing = c.demo("failing")
    drop_option(failing, "a")
    code, out, _ = c.run("build", failing)
    t.ok(code == 1 and not os.path.exists(os.path.join(failing, "board.html")), "build rendered despite a FAIL")


def case_scores_finalist(c, t):
    d = c.demo()
    b = Ctx.load(d)
    for r in b["references"]:
        r.pop("finalist", None)
    b.pop("scores", None)
    Ctx.save(d, b)
    five = ["atlas-studio", "paper-mill", "quiet-books", "grain-co", "tally-house"]
    with open(os.path.join(d, "board.d", "scores.json"), "w") as f:
        json.dump({k: {"fit": 4, "finalist": True} for k in five}, f)
    code, out, _ = c.run("check", d)
    t.ok(code == 0, f"check exit {code}: {out}")
    c.run("build", d, "--no-thumbs")
    _, data = board_data(d)
    got = sorted(r["id"] for r in data["refs"] if r.get("finalist"))
    t.ok(got == sorted(five), f"finalists from scores.json: {got}")
    b = Ctx.load(d)
    next(r for r in b["references"] if r["id"] == "paper-mill")["finalist"] = False
    Ctx.save(d, b)
    with open(os.path.join(d, "board.d", "scores.json"), "w") as f:
        json.dump([dict(id=k, finalist=True) for k in five] + [{"id": "northwind-pay", "dropped": True}], f)
    c.run("build", d, "--no-thumbs")
    _, data = board_data(d)
    got = sorted(r["id"] for r in data["refs"] if r.get("finalist"))
    t.ok(got == sorted(set(five) - {"paper-mill"}), f"board.json finalist:false did not win: {got}")


def case_doctor_shape(c, t):
    code, out, err = doctor(c)
    lines = out.strip().splitlines()
    t.ok(lines and re.match(r"^DOCTOR: (ready|not ready)$", lines[-1]), f"last line {lines[-1:]}")
    t.ok(all(re.match(r"^(ok|missing|info) \S", l) for l in lines[:-1]), f"bad lines: {lines[:-1]}")
    ready = lines and lines[-1] == "DOCTOR: ready"
    t.ok(code == (0 if ready else 2), f"exit {code} with {lines[-1:]}")
    for item in ("node>=20", "playwright-core", "chrome", "image tool", "python3"):
        t.ok(any(item in l for l in lines), f"doctor does not report {item}")


def case_capture_smoke(c, t):
    need_ready(c)
    site = os.path.join(c.root, "site")
    os.makedirs(site)
    with open(os.path.join(site, "index.html"), "w") as f:
        f.write("<!doctype html><title>Acme</title><body style='background:#f4efe6;color:#211c17'>"
                "<h1 style='font:700 48px Georgia'>Acme Invoice</h1><p>Provider demo page.</p></body>")
    port, dead = free_port(), free_port()
    srv = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", site],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), 0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        out_dir = os.path.join(c.root, "cap")
        os.makedirs(out_dir)
        Ctx.save(out_dir, {"schema": 1, "references": [
            {"id": "good", "title": "Good", "url": f"http://127.0.0.1:{port}/", "kind": "live"},
            {"id": "dead", "title": "Dead", "url": f"http://127.0.0.1:{dead}/", "kind": "live"}]})
        code, out, err = c.run("capture", "--board", os.path.join(out_dir, "board.json"), "--quick", "--timeout", "15",
                               cmd=[BIN], timeout=300)
        t.ok(code == 1, f"exit {code} (one dead URL must make it 1): {out[-300:]}{err[-300:]}")
        t.ok(os.path.isfile(os.path.join(out_dir, "captures", "good-d.jpg")), "no captures/good-d.jpg")
        meta = os.path.join(out_dir, "captures", "dead.json")
        t.ok(os.path.isfile(meta) and json.load(open(meta)).get("captureError"), "dead URL has no captureError")
    finally:
        srv.terminate()
        srv.wait()


def case_variants_shots(c, t):
    need_ready(c)
    d = c.demo()
    code, out, err = c.run("capture", "--variants", "--out", d, cmd=[BIN], timeout=300)
    t.ok(code == 0, f"exit {code}: {out[-300:]}{err[-300:]}")
    for o in "abc":
        for k in "dm":
            t.ok(os.path.isfile(os.path.join(d, "shots", f"opt-{o}-{k}.jpg")), f"no shots/opt-{o}-{k}.jpg")


def case_privacy(c, t):
    rx = validate_regexes() or {}
    hook = hook_regexes()
    if not rx and not hook:
        raise Skip("neither validate.py nor the pre-push hook found")
    d = c.demo()
    c.run("build", d)
    files = [os.path.join(d, "board.html")]
    for sub in ("scripts", "templates", "fixtures"):
        for root, _, names in os.walk(os.path.join(SKILL, sub)):
            files += [os.path.join(root, n) for n in names
                      if n.endswith((".md", ".js", ".mjs", ".py", ".json", ".html", ".tmpl", ".txt", ".sh", ".url"))]
    for root, _, names in os.walk(os.path.join(SKILL, "fixtures")):
        for nm in names:
            if any(h.search(nm) for h in hook):
                t.ok(False, f"pre-push pattern in file name {nm}")
    for path in files:
        text = open(path, encoding="utf-8", errors="ignore").read()
        rel = os.path.relpath(path, c.root if path.startswith(c.root) else SKILL)
        for n, line in enumerate(text.splitlines(), 1):
            if rx and rx["PRIV"].search(line):
                t.ok(False, f"PRIV word in {rel}:{n}")
            hit = next((h.pattern for h in hook if h.search(line)), None)
            if hit:
                t.ok(False, f"pre-push pattern {hit} in {rel}:{n}")
            if (rx and rx["BAD_PATH"].search(line)) or USERS.search(line):
                t.ok(False, f"BAD_PATH in {rel}:{n}")


CASES = [(n, f) for n, f in (
    ("check-valid", case_check_valid), ("check-two-options", case_check_two_options),
    ("check-bad-id-set", case_check_bad_id_set), ("check-url-scheme", case_check_url_scheme),
    ("check-missing-file", case_check_missing_file), ("check-limits", case_check_limits),
    ("check-dangling-usedRef", case_check_dangling_usedref), ("build-deterministic", case_build_deterministic),
    ("build-asset-hash", case_build_asset_hash), ("markup-tabs", case_markup_tabs),
    ("markup-lightbox", case_markup_lightbox), ("markup-urls", case_markup_urls),
    ("markup-export", case_markup_export), ("markup-no-base64", case_markup_no_base64),
    ("index-sidecar", case_index_sidecar), ("thumbs-fallback", case_thumbs_fallback),
    ("thumbs-tool", case_thumbs_tool), ("registry-files-patch", case_registry_files_patch),
    ("exit-codes", case_exit_codes), ("scores-finalist", case_scores_finalist), ("doctor-shape", case_doctor_shape), ("capture-smoke", case_capture_smoke),
    ("variants-shots", case_variants_shots), ("privacy", case_privacy))]


def run_case(fn, script, keep):
    root = os.path.realpath(tempfile.mkdtemp(prefix="design-board-selftest-"))
    t = Check()
    try:
        fn(Ctx(root, script), t)
        verdict, why = ("FAIL", "; ".join(p[:230] for p in t.problems[:8])) if t.problems else ("PASS", "")
    except Skip as s:
        verdict, why = "SKIP", str(s)
    except Exception as exc:  # a crashing builder or harness is a failure, not a crash
        verdict, why = "FAIL", f"harness error: {exc!r}"
    finally:
        if keep:
            print(f"  kept {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)
    return verdict, why


def main():
    ap = argparse.ArgumentParser(description="Behavioural tests for design-board.py and bin/design-board")
    ap.add_argument("--script", default=os.path.join(HERE, "design-board.py"), help="the design-board.py to test")
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
    tally = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    for name, fn in cases:
        verdict, why = run_case(fn, script, args.keep)
        tally[verdict] += 1
        print(f"{verdict} {name}" + (f" - {why}" if why else ""), flush=True)
    print(f"{tally['PASS']} PASS · {tally['FAIL']} FAIL · {tally['SKIP']} SKIP (of {len(cases)})")
    return 1 if tally["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
