#!/usr/bin/env python3
"""plans-regen-selftest - behavioural tests for plans-regen.py (stdlib only).

Usage:
  python3 plans-regen-selftest.py [--script PATH] [--only NAME] [--keep]

Builds one throwaway `tempfile` tree per case (a brain dir holding the four plan docs +
task.md, in the ES or EN file-name set), runs plans-regen.py as a subprocess
(`<out.html> --brain <dir> [flags]`, PYTHONDONTWRITEBYTECODE=1) and prints
`PASS|FAIL|SKIP <case> [- why]`. Exit code 1 when any case FAILs.

What is asserted (structure of the generated articles, never pixel output):
  - an inline-code `<!--` does not open a comment (every `##` section renders, the span is kept
    as escaped literal text), a `<!--` inside a fenced block is kept, a real comment (also one in
    task.md) is stripped;
  - wave ids WX, WI, WSKILL-ARCH, W2a, W3, WC-V2, WO-1, W18 get a status badge in the master and
    detailed headings, a .task card inside their section, and a Gantt row + bar; a wave-map row
    `**W2a** ... depends W3` resolves to W2a, not to W3;
  - the wave id is read from the header's Wave column: a bold word in the Tasks column (`**Pagos**`,
    `**T-W7-01**`) is never an id, an un-bolded `W6` is;
  - a link whose URL is a code span (or javascript:) never becomes an <a> / event handler;
  - --check: fresh 0, stale 1, hand-maintained layout 3; --init needs --force over an existing
    file; a second run is byte-identical; the EN file-name set works.

Fixtures are generic (project "Acme", example.com, owner-less). The script under test defaults
to the plans-regen.py next to this file (its plans-html.tmpl must sit beside it); pass --script
to test another copy. --keep leaves the temp trees on disk.
"""
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
KEYS = ("proposal", "master", "detailed", "timeframe")
PREFIX = {"master": "m", "detailed": "d", "timeframe": "t", "proposal": "p"}
NAMES = {
    "es": {"proposal": "propuesta-ejecutiva.md", "master": "plan-maestro.md",
           "detailed": "plan-detallado.md", "timeframe": "plan-timeframe.md"},
    "en": {"proposal": "executive-proposal.md", "master": "master-plan.md",
           "detailed": "detailed-plan.md", "timeframe": "timeframe-plan.md"},
}
WORD = {"es": "Ola", "en": "Wave"}
LABEL = {"es": {"✅": "hecha", "⛔": "bloqueada", "⏸": "en pausa", "🔄": "en curso", "☐": "pendiente"},
         "en": {"✅": "done", "⛔": "blocked", "⏸": "paused", "🔄": "in progress", "☐": "pending"}}
CLS = {"✅": "ok", "⛔": "blocked", "⏸": "blocked", "🔄": "pending", "☐": "pending"}
NAV = {"es": "Propuesta ejecutiva", "en": "Executive proposal"}

# id, glyph, title, sessions, weeks, stream, depends-on
WAVES = [
    ("WX", "✅", "Setup", "1", "1", "Core", "—"),
    ("WI", "🔄", "Infra", "2", "1-2", "Core", "WX"),
    ("WSKILL-ARCH", "☐", "Skill architecture", "2", "2-3", "Skills", "WI"),
    ("W2a", "☐", "Foundations", "1", "3", "Core", "W3"),
    ("W3", "✅", "Core", "1", "2", "Core", "WX"),
    ("WC-V2", "⛔", "Checkout v2", "2", "3-4", "Skills", "WSKILL-ARCH"),
    ("WO-1", "⏸", "Ops", "1", "4", "Ops", "WC-V2"),
    ("W18", "☐", "Close", "1", "5", "Ops", "WO-1"),
]
SMALL = [  # plain digit ids only: used where the wave ids are not what is under test
    ("W1", "✅", "Alpha", "1", "1", "Core", "—"),
    ("W2", "☐", "Beta", "1", "2", "Core", "W1"),
    ("W3", "☐", "Gamma", "1", "3", "Core", "W2"),
]
TXT = {
    "es": {"h1": "Propuesta ejecutiva", "m1": "Plan maestro", "d1": "Plan detallado", "t1": "Plan timeframe",
           "want": "Qué se busca", "ask": "Qué se pide aprobar", "dec": "Decisión", "close": "Cierre",
           "desc": "Descripción de {}.", "task": "Implementar", "sum": "Resumen",
           "hdr": "| Ola | Sesiones | Semana | Flujo | Depende de |",
           "t0": "Resumen", "t1h": "Tabla de olas", "t2": "Ruta crítica",
           "task_hdr": "| Estado | Ola | Tareas | Gate | Skills | Rama | Depende de |"},
    "en": {"h1": "Executive proposal", "m1": "Master plan", "d1": "Detailed plan", "t1": "Timeframe plan",
           "want": "What is sought", "ask": "What to approve", "dec": "Decision", "close": "Close",
           "desc": "Description of {}.", "task": "Implement", "sum": "Summary",
           "hdr": "| Wave | Sessions | Week | Stream | Depends on |",
           "t0": "Summary", "t1h": "Wave table", "t2": "Critical path",
           "task_hdr": "| Status | Wave | Tasks | Gate | Skills | Base branch | Depends on |"},
}


class Skip(Exception):
    pass


# ------------------------------------------------------------------ harness
class R:
    """One plans-regen run."""

    def __init__(self, p):
        self.rc, self.out, self.err = p.returncode, p.stdout, p.stderr
        self.text = p.stdout + p.stderr


class Ctx:
    def __init__(self, script, root):
        self.script, self.root = script, root
        self.env = dict(os.environ)
        self.env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
                         "HOME": root})

    def path(self, rel):
        return os.path.join(self.root, *rel.split("/"))

    def write(self, rel, content, age=120):
        """Write a file; `age` = seconds into the past for its mtime (None keeps 'now')."""
        p = self.path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(content)
        if age is not None:
            t = time.time() - age
            os.utime(p, (t, t))
        return p

    def read(self, rel):
        with open(self.path(rel), encoding="utf-8") as fh:
            return fh.read()

    def sha(self, rel):
        with open(self.path(rel), "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()

    def brain(self, name, docs, lang="es"):
        """Write the four docs (file names of `lang`) + task.md under <root>/<name>/."""
        for k in KEYS:
            self.write(f"{name}/{NAMES[lang][k]}", docs[k])
        self.write(f"{name}/task.md", docs["task"])
        return self.path(name)

    def run(self, out, brain, *flags, script=None):
        cmd = [sys.executable, script or self.script, self.path(out), "--brain", brain] + list(flags)
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=self.env, cwd=self.root, timeout=60)
        return R(p)


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
            self.problems.append(f"{what}: {needle!r} not in {(hay or '')[:80]!r}")

    def lacks(self, hay, needle, what):
        if needle in (hay or ""):
            self.problems.append(f"{what}: {needle!r} must not be present")


# ------------------------------------------------------------------ fixtures
def task_md(lang, waves, pre=""):
    T = TXT[lang]
    rows = [f"| {g} | **{wid}** — {title} | T-{wid}-1 | — | acme-ctx | main | "
            + ("—" if dep == "—" else f"depends {dep}") + " |" for wid, g, title, _s, _w, _st, dep in waves]
    return (pre + "# Acme — Task tracker: Billing revamp\n\n## " + ("Mapa de olas" if lang == "es" else "Wave map")
            + "\n\n" + T["task_hdr"] + "\n|---|---|---|---|---|---|---|\n" + "\n".join(rows) + "\n")


def wave_sections(lang, waves, tasks):
    T, out = TXT[lang], []
    for wid, _g, title, *_ in waves:
        out.append(f"## {WORD[lang]} {wid} — {title}\n\n{T['desc'].format(wid)}\n")
        if tasks:
            out.append(f"### T-{wid}-1 — {T['task']} {wid}\n\n- DoD: done\n")
    return "\n".join(out)


def timeframe_md(lang, waves):
    T = TXT[lang]
    rows = "\n".join(f"| {wid} — {title} | {ses} | {wk} | {stream} | {dep} |"
                     for wid, _g, title, ses, wk, stream, dep in waves)
    return (f"# Acme — {T['t1']}\n\n## 0. {T['t0']}\n\nStart 2026-01-05, estimated close 2026-03-20.\n\n"
            f"## 1. {T['t1h']}\n\n{T['hdr']}\n|---|---|---|---|---|\n{rows}\n\n## 2. {T['t2']}\n\nPath text.\n")


def build_docs(lang="es", waves=WAVES):
    T = TXT[lang]
    return {
        "proposal": (f"# Acme — {T['h1']}\n\nAcme renews its billing module in several waves.\n\n"
                     f"## {T['want']}\n\nA new billing module.\n\n## {T['ask']}\n\n- Budget\n- Calendar\n"),
        "master": (f"# Acme — {T['m1']}: Billing revamp\n\n## {T['dec']}\n\nWe adopt the wave design.\n\n"
                   + wave_sections(lang, waves, False) + f"\n## {T['close']}\n\nEnd.\n"),
        "detailed": (f"# Acme — {T['d1']}\n\n## {T['sum']}\n\nTask catalog.\n\n"
                     + wave_sections(lang, waves, True) + f"\n## {T['close']}\n\nEnd.\n"),
        "timeframe": timeframe_md(lang, waves),
        "task": task_md(lang, waves),
    }


# ------------------------------------------------------------------ output helpers
def article(out_html, key):
    m = re.search(rf'<article\s+id="doc-{key}"[^>]*>(.*?)</article>', out_html, re.S)
    return m.group(1) if m else ""


def sections(art):
    return re.findall(r'<section class="sec" id="([^"]+)"', art)


def find_section(art, word, wid):
    """(section id, h2 inner HTML, section HTML) of the section whose heading starts '<word> <wid>'."""
    for m in re.finditer(r'<section class="sec" id="([^"]+)">\s*<h2>(.*?)</h2>(.*?)</section>', art, re.S):
        if re.match(rf'{word} {re.escape(wid)}(?![A-Za-z0-9-])', m.group(2)):
            return m.group(1), m.group(2), m.group(3)
    return None


def check_waves(t, out_html, lang, waves):
    """Every wave: badge + id in master/detailed headings, .task card in detailed, Gantt row + bar."""
    word = WORD[lang]
    for key in ("master", "detailed"):
        art = article(out_html, key)
        no_sec, bad_id, no_badge, bad_badge, no_task = [], [], [], [], []
        for wid, g, *_ in waves:
            sec = find_section(art, word, wid)
            if sec is None:
                no_sec.append(wid)
                continue
            sid, h2, body = sec
            if sid != f"{PREFIX[key]}-{wid.lower()}":
                bad_id.append(f"{wid}->{sid}")
            m = re.search(r'<span class="badge (\w+)"[^>]*>(.*?)</span>', h2)
            if not m:
                no_badge.append(wid)
            elif (m.group(1), m.group(2)) != (CLS[g], f"{g} {LABEL[lang][g]}"):
                bad_badge.append(f"{wid}:{m.group(1)}/{m.group(2)}")
            if key == "detailed" and f'<span class="tid">T-{wid}-1</span>' not in body:
                no_task.append(wid)
        t.ok(not no_sec, f"{key}: no section for wave(s) {no_sec}")
        t.ok(not bad_id, f"{key}: section id is not '{PREFIX[key]}-<id lowercase>': {bad_id}")
        t.ok(not no_badge, f"{key}: no status badge in the heading of {no_badge}")
        t.ok(not bad_badge, f"{key}: wrong badge (class/label) {bad_badge}")
        t.ok(not no_task, f"detailed: no .task card inside the section of {no_task}")
    tf = article(out_html, "timeframe")
    labels = re.findall(r'<div class="g-lab"[^>]*>(.*?)</div>', tf)
    tips = re.findall(r'<div class="g-bar s\d"[^>]*title="([^"]*)"', tf)
    no_row = [w[0] for w in waves if not any(x.startswith(f"{w[0]} —") for x in labels)]
    no_bar = [w[0] for w in waves
              if not any(x.startswith(f"{w[0]} · ") and x.endswith(LABEL[lang][w[1]]) for x in tips)]
    t.ok(not no_row, f"Gantt: no row label for {no_row}")
    t.ok(not no_bar, f"Gantt: no bar (tooltip '<id> · ... · <status>') for {no_bar}")
    t.eq(len(tips), len(waves), "Gantt: number of wave bars")


class Tags(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags, self.text = [], []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, attrs))

    def handle_data(self, data):
        self.text.append(data)


# ------------------------------------------------------------------ cases
def case_code_span_comment_opener(ctx, t):
    d = build_docs("es", SMALL)
    d["master"] = (
        "# Acme — Plan maestro: Billing revamp\n\n## Decisión\n\n"
        "Usamos `<!--` solo dentro de código. El tag `<!-- x -->` se muestra literal.\n\n"
        "## Ola W1 — Alpha\n\n| Marca | Significado |\n|---|---|\n| `<!--` | abre un comentario |\n"
        "| `-->` | lo cierra |\n\n"
        "## Ola W2 — Beta\n\n- Usa `<!-- x -->` en una lista.\n- Usa `<!--` para abrir y `-->` para cerrar.\n\n"
        "## Cierre\n\nSENTINEL-MASTER-END\n")
    d["detailed"] = (
        "# Acme — Plan detallado\n\n## Resumen\n\nEl analizador no trata `<!--` como comentario dentro de código.\n\n"
        "## Ola W1 — Alpha\n\n### T-W1-1 — Tarea uno\n\nTexto con `<!-- x -->` literal.\n\n"
        "### T-W1-2 — Tarea dos\n\nOtra línea con `<!--` y luego `-->`.\n\n"
        "## Ola W2 — Beta\n\n### T-W2-1 — Tarea tres\n\nSENTINEL-DETAILED-W2\n\n"
        "## Cierre\n\nSENTINEL-DETAILED-END\n")
    r = ctx.run("plans.html", ctx.brain("c1", d))
    t.eq(r.rc, 0, "exit code")
    out = ctx.read("plans.html") if os.path.isfile(ctx.path("plans.html")) else ""
    m, dt = article(out, "master"), article(out, "detailed")
    t.eq(len(sections(m)), 4, "master: <section> count == number of '##' headings")
    t.eq(len(sections(dt)), 4, "detailed: <section> count == number of '##' headings")
    t.has(m, "SENTINEL-MASTER-END", "master: text after the code-span <!-- renders")
    t.has(dt, "SENTINEL-DETAILED-END", "detailed: text after the code-span <!-- renders")
    t.has(dt, "SENTINEL-DETAILED-W2", "detailed: wave W2 body renders")
    t.eq(dt.count('class="task"'), 3, "detailed: .task cards")
    t.ok(m.count("<code>&lt;!-- x --&gt;</code>") >= 2, "master: `<!-- x -->` kept as escaped literal (>= 2 spans)")
    t.ok(m.count("<code>&lt;!--</code>") >= 3, "master: `<!--` kept as literal (prose, table cell, list item)")
    t.ok(m.count("<code>--&gt;</code>") >= 2, "master: `-->` kept as literal (table cell, list item)")
    t.has(m, "<td><code>&lt;!--</code></td>", "master: table cell holding `<!--`")
    t.ok(dt.count("<code>&lt;!-- x --&gt;</code>") >= 1, "detailed: `<!-- x -->` kept as escaped literal")
    t.ok(dt.count("<code>&lt;!--</code>") >= 2 and dt.count("<code>--&gt;</code>") >= 1,
         "detailed: both spans of the 'abrir ... cerrar' line survive")


def case_fence_and_real_comments(ctx, t):
    d = build_docs("es", [SMALL[0]])
    d["master"] = (
        "# Acme — Plan maestro: Billing revamp\n\n<!-- LINE-START-COMMENT-ONE -->\n\n## Decisión\n\n"
        "Texto antes <!-- INLINE-HIDDEN --> y después.\n\n<!--\nMULTILINE-HIDDEN\n## Sección fantasma\n-->\n\n"
        "## Plantillas\n\n```html\n<!-- FENCED-COMMENT-KEPT -->\n<div>ok</div>\n<!-- opener left open inside the fence\n```\n\n"
        "## Ola W1 — Alpha\n\nReal wave.\n\n## Ola W9 — Fantasma\n\nSolo existe en un comentario de task.md.\n\n"
        "## Cierre\n\nFin SENTINEL-AFTER-FENCE.\n")
    ghost = ("<!--\nNotas de la plantilla. Filas de ejemplo, no son olas reales:\n\n"
             "| Estado | Ola | Tareas | Gate | Skills | Rama | Depende de |\n|---|---|---|---|---|---|---|\n"
             "| ✅ | **W9** — Fantasma | T-W9-1 | — | acme-ctx | main | — |\n-->\n\n")
    d["task"] = task_md("es", [SMALL[0]], pre=ghost)
    r = ctx.run("plans.html", ctx.brain("c2", d))
    t.eq(r.rc, 0, "exit code")
    out = ctx.read("plans.html") if os.path.isfile(ctx.path("plans.html")) else ""
    m = article(out, "master")
    t.eq(len(sections(m)), 5, "master: <section> count (Decisión, Plantillas, Ola W1, Ola W9, Cierre; comments add none)")
    t.has(m, "SENTINEL-AFTER-FENCE", "text after the fence + comments renders")
    t.has(m, "FENCED-COMMENT-KEPT", "`<!--` inside a fenced block is preserved")
    t.has(m, "opener left open inside the fence", "an unterminated `<!--` inside a fence is preserved")
    t.has(m, "&lt;!-- FENCED-COMMENT-KEPT --&gt;", "the fenced comment is shown escaped")
    for ghost_text in ("LINE-START-COMMENT-ONE", "INLINE-HIDDEN", "MULTILINE-HIDDEN", "Sección fantasma"):
        t.lacks(m, ghost_text, "a real comment is stripped")
    sec9, sec1 = find_section(m, "Ola", "W9"), find_section(m, "Ola", "W1")
    t.ok(sec1 is not None and 'class="badge ok"' in sec1[1], "real wave W1 keeps its badge")
    t.ok(sec9 is not None and "badge" not in sec9[1],
         "wave W9 exists only in a commented-out task.md row: no badge (task.md gets the same comment handling)")


def case_wave_ids_es(ctx, t):
    r = ctx.run("plans.html", ctx.brain("c3", build_docs("es", WAVES)))
    t.eq(r.rc, 0, "exit code")
    out = ctx.read("plans.html") if os.path.isfile(ctx.path("plans.html")) else ""
    t.has(out, '<html lang="es"', "lang auto-detected from the ES file names")
    check_waves(t, out, "es", WAVES)


def case_wave_map_row_own_id(ctx, t):
    waves = [WAVES[3], WAVES[4]]  # W2a (☐, "depends W3") listed before W3 (✅)
    d = build_docs("es", waves)
    t.has(d["task"], "| ☐ | **W2a** — Foundations | T-W2a-1 | — | acme-ctx | main | depends W3 |", "fixture row")
    r = ctx.run("plans.html", ctx.brain("c4", d))
    t.eq(r.rc, 0, "exit code")
    out = ctx.read("plans.html") if os.path.isfile(ctx.path("plans.html")) else ""
    for key in ("master", "detailed"):
        s2, s3 = find_section(article(out, key), "Ola", "W2a"), find_section(article(out, key), "Ola", "W3")
        t.ok(s2 is not None and 'class="badge pending"' in s2[1], f"{key}: W2a row resolves to W2a (pending badge)")
        t.ok(s3 is not None and 'class="badge ok"' in s3[1],
             f"{key}: W3 keeps its own done badge (the 'depends W3' text of the W2a row did not steal it)")
    check_waves(t, out, "es", waves)


def case_wave_map_column(ctx, t):
    waves = [("W6", "☐", "Pagos", "1", "1", "Core", "—"), ("W7", "✅", "Cobros", "1", "2", "Core", "W6")]
    d = build_docs("es", waves)
    d["task"] = ("# Acme — Task tracker: Billing revamp\n\n## Mapa de olas\n\n"
                 "| Status | Wave | Tasks | Gate | Skills | Base branch | Depends on |\n|---|---|---|---|---|---|---|\n"
                 "| ☐ | W6 | **Pagos** | — | acme-ctx | main | — |\n"
                 "| ✅ | **W7** | **T-W7-01** — Cobros | — | acme-ctx | main | W6 |\n")
    d["master"] += "\n## Ola Pagos — Extra\n\nTexto.\n\n## Ola T-W7-01 — Tarea\n\nTexto.\n"
    r = ctx.run("plans.html", ctx.brain("c10", d))
    t.eq(r.rc, 0, "exit code")
    out = ctx.read("plans.html") if os.path.isfile(ctx.path("plans.html")) else ""
    check_waves(t, out, "es", waves)  # W6 (un-bolded id) and W7 resolve; sections, tasks, Gantt
    m = article(out, "master")
    for word in ("Pagos", "T-W7-01"):
        sec = find_section(m, "Ola", word)
        t.ok(sec is not None, f"fixture: a section 'Ola {word}' exists")
        t.ok(sec is not None and "badge" not in sec[1],
             f"'{word}' is a bold word of the Tasks column, not a wave id: its heading gets no badge")


def case_xss_links(ctx, t):
    d = build_docs("es", SMALL)
    d["detailed"] = (
        "# Acme — Plan detallado\n\n## Notas\n\nEnlace seguro: [ok](https://example.com/ok).\n\n"
        "Malicioso uno: [x](`\" onmouseover=alert(1) x=\"`)\n\nMalicioso dos: [x](javascript:alert(1))\n\n"
        "## Cierre\n\nFin.\n")
    r = ctx.run("plans.html", ctx.brain("c5", d))
    t.eq(r.rc, 0, "exit code")
    out = ctx.read("plans.html") if os.path.isfile(ctx.path("plans.html")) else ""
    art = article(out, "detailed")
    p = Tags()
    p.feed(art)
    handlers = [(tag, a[0]) for tag, attrs in p.tags for a in attrs if a[0].lower().startswith("on")]
    t.ok(not handlers, f"no event-handler attribute is injected, found {handlers}")
    hrefs = [dict(attrs).get("href") for tag, attrs in p.tags if tag == "a"]
    t.eq(hrefs, ["https://example.com/ok"], "the only <a> is the legitimate https link (no href from a code span or javascript:)")
    text = "".join(p.text)
    t.has(text, "onmouseover=alert(1)", "the code-span URL is shown as plain text, not dropped")
    t.has(text, "[x](", "the link source stays visible as text")
    t.has(art, "[x](javascript:alert(1))", "the javascript: link is plain escaped text")
    t.ok(len(sections(art)) == 2, "both sections render")


def case_check_exit_codes(ctx, t):
    brain = ctx.brain("c6", build_docs("es", WAVES))
    r = ctx.run("plans.html", brain)
    t.eq(r.rc, 0, "initial build exit code")
    r = ctx.run("plans.html", brain, "--check")
    t.eq(r.rc, 0, "--check on a fresh output")
    master = os.path.join(brain, NAMES["es"]["master"])
    with open(master, "a", encoding="utf-8") as fh:
        fh.write("\n## Apéndice\n\nTexto nuevo.\n")
    before = ctx.sha("plans.html")
    r = ctx.run("plans.html", brain, "--check")
    t.eq(r.rc, 1, "--check on a stale output (source changed)")
    t.eq(ctx.sha("plans.html"), before, "--check writes nothing")
    ctx.write("hand.html", '<!doctype html><html lang="es"><body><main><article id="legacy">'
                           "<p>Hand-made layout.</p></article></main></body></html>\n")
    sha = ctx.sha("hand.html")
    r = ctx.run("hand.html", brain, "--check")
    t.eq(r.rc, 3, "--check on an output without doc-* articles")
    t.has(r.text.lower(), "hand-maintained", "message names the hand-maintained layout")
    t.eq(ctx.sha("hand.html"), sha, "--check leaves the hand-maintained file untouched")


def case_init_requires_force(ctx, t):
    brain = ctx.brain("c7", build_docs("es", WAVES))
    legacy = ('<!doctype html><html lang="es"><body><main><article id="legacy">'
              "<p>Hand-made layout.</p></article></main></body></html>\n")
    ctx.write("hand.html", legacy)
    sha = ctx.sha("hand.html")
    r = ctx.run("hand.html", brain, "--init")
    t.ok(r.rc != 0, f"--init over an existing file without --force must fail, exit {r.rc}")
    t.eq(ctx.sha("hand.html"), sha, "file unchanged after the refused --init")
    t.has(r.text, "--force", "the refusal message names --force")
    t.lacks(r.text, "Traceback", "no traceback")
    r = ctx.run("hand.html", brain, "--init", "--force")
    t.eq(r.rc, 0, "--init --force exit code")
    now = ctx.read("hand.html")
    t.ok(ctx.sha("hand.html") != sha, "--init --force rewrites the file")
    t.ok('id="doc-master"' in now and 'id="doc-detailed"' in now, "rewritten file has the doc-* articles")
    t.lacks(now, "Hand-made layout", "old hand-made content is gone after --force")


def case_idempotent_second_run(ctx, t):
    brain = ctx.brain("c8", build_docs("es", WAVES))
    r1 = ctx.run("plans.html", brain)
    t.eq(r1.rc, 0, "first run exit code")
    first = ctx.read("plans.html") if os.path.isfile(ctx.path("plans.html")) else ""
    check_waves(t, first, "es", WAVES)  # the first output must also be the fixed one
    r2 = ctx.run("plans.html", brain)
    t.eq(r2.rc, 0, "second run exit code")
    t.ok(ctx.read("plans.html") == first if os.path.isfile(ctx.path("plans.html")) else False,
         "second run output is byte-identical to the first")
    t.has(r2.out, "unchanged", "second run reports 'unchanged'")
    t.eq(ctx.run("plans.html", brain, "--check").rc, 0, "--check after the runs")


def case_en_docs_set(ctx, t):
    r = ctx.run("plans.html", ctx.brain("c9", build_docs("en", WAVES), lang="en"))
    t.eq(r.rc, 0, "exit code")
    out = ctx.read("plans.html") if os.path.isfile(ctx.path("plans.html")) else ""
    t.has(out, '<html lang="en"', "lang auto-detected from the EN file names")
    t.has(out, f">{NAV['en']}<", "EN nav label")
    t.lacks(out, f">{NAV['es']}<", "no ES nav label")
    check_waves(t, out, "en", WAVES)
    t.eq(len(sections(article(out, "master"))), len(WAVES) + 2, "master: one <section> per '##' heading")


CASES = [
    ("code_span_comment_opener", case_code_span_comment_opener),
    ("fence_and_real_comments", case_fence_and_real_comments),
    ("wave_ids_es", case_wave_ids_es),
    ("wave_map_row_own_id", case_wave_map_row_own_id),
    ("wave_map_column", case_wave_map_column),
    ("xss_links", case_xss_links),
    ("check_exit_codes", case_check_exit_codes),
    ("init_requires_force", case_init_requires_force),
    ("idempotent_second_run", case_idempotent_second_run),
    ("en_docs_set", case_en_docs_set),
]


def run_case(fn, script, keep):
    root = os.path.realpath(tempfile.mkdtemp(prefix="plans-regen-selftest-"))
    t = Check()
    try:
        fn(Ctx(script, root), t)
        verdict, why = ("FAIL", "; ".join(p[:150] for p in t.problems[:8])) if t.problems else ("PASS", "")
    except Skip as s:
        verdict, why = "SKIP", str(s)
    except Exception as exc:  # a broken harness or a crashing script is a failure, not a crash
        verdict, why = "FAIL", f"harness error: {exc!r}"
    finally:
        if keep:
            print(f"  kept {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)
    return verdict, why


def main():
    ap = argparse.ArgumentParser(description="Behavioural tests for plans-regen.py")
    ap.add_argument("--script", default=os.path.join(HERE, "plans-regen.py"))
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
        print(f"{verdict} {name}" + (f" — {why}" if why else ""))
    print(f"{tally['PASS']} PASS · {tally['FAIL']} FAIL · {tally['SKIP']} SKIP (of {len(cases)})")
    return 1 if tally["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
