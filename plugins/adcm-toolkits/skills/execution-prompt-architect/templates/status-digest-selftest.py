#!/usr/bin/env python3
"""status-digest-selftest - behavioural tests for status_digest.py (stdlib only).

Usage:
  python3 status-digest-selftest.py [--digest PATH] [--only NAME] [--keep]

Builds one throwaway `tempfile` tree per case (a brain dir holding task.md, plus git
repos / fake courier scripts where the case needs them), runs the digest as a subprocess
(`--brain <dir> [flags]`, PYTHONDONTWRITEBYTECODE=1) and prints `PASS|FAIL|SKIP <case>
[- why]`. Exit code 1 when any case FAILs.

Structure is asserted on `--json` (exit code, status, glyph counts, ids, last log entry,
order, pending shape/open, ready list, irregular rows, git kind); the plain run is
asserted for the output contract only: line count <= --lines, every line <= --width
chars, last line starts with `DIGEST:`, plus a few labelled lines.

Fixtures are generic (project "Acme", modules/billing, owner "A", example.com).
The digest under test defaults to the status_digest.py next to this file; pass
--digest to test an installed copy. --keep leaves the temp trees on disk.
"""
import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ORDERS = ("newest-first", "oldest-first", "mixed", "ambiguous", "single", "none")
LAST_LINE = {"ok": "DIGEST: ok", "partial": "DIGEST: partial(", "unparsed": "DIGEST: unparsed ("}


class Skip(Exception):
    pass


# ------------------------------------------------------------------ harness
class R:
    """One digest run."""

    def __init__(self, p):
        self.rc, self.out, self.err = p.returncode, p.stdout, p.stderr
        self.lines = p.stdout.splitlines()
        try:
            data = json.loads(p.stdout)
        except ValueError:
            data = None
        self.data = data if isinstance(data, dict) else None


class Ctx:
    def __init__(self, digest, root):
        self.digest, self.root = digest, root
        self.env = dict(os.environ)
        self.env.update({
            "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
            "HOME": root, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CEILING_DIRECTORIES": os.path.dirname(root), "GIT_TERMINAL_PROMPT": "0"})

    def path(self, rel):
        return os.path.join(self.root, *rel.split("/"))

    def write(self, rel, content, mode=None):
        p = self.path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(content)
        if mode:
            os.chmod(p, mode)
        return p

    def brain(self, name, task=None, extra=None):
        """Create <root>/<name>/ with task.md (unless None) and extra {relpath: content}."""
        os.makedirs(self.path(name), exist_ok=True)
        if task is not None:
            self.write(name + "/task.md", task)
        for rel, body in (extra or {}).items():
            self.write(name + "/" + rel, body)
        return self.path(name)

    def run(self, brain, *flags):
        cmd = [sys.executable, self.digest] + (["--brain", brain] if brain else []) + list(flags)
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=self.env, cwd=self.root, timeout=60)
        return R(p)

    @contextlib.contextmanager
    def env_patch(self, **kv):
        """Temporarily change the digest's environment (None removes a variable)."""
        old = self.env
        self.env = dict(old)
        for k, v in kv.items():
            if v is None:
                self.env.pop(k, None)
            else:
                self.env[k] = v
        try:
            yield
        finally:
            self.env = old

    def git(self, cwd, *args):
        cmd = ["git", "-c", "user.name=Acme", "-c", "user.email=dev@example.com",
               "-c", "commit.gpgsign=false"] + list(args)
        return subprocess.run(cmd, cwd=cwd, env=self.env, capture_output=True, text=True,
                              check=True, timeout=60).stdout.strip()


class Check:
    def __init__(self):
        self.problems = []
        self.tag = ""  # sub-run label prefixed to every problem (set by multi-part cases)

    def ok(self, cond, what):
        if not cond:
            self.problems.append(self.tag + what)

    def eq(self, got, want, what):
        if got != want:
            self.problems.append(f"{self.tag}{what}: got {got!r}, want {want!r}")

    def has(self, hay, needle, what):
        if needle not in (hay or ""):
            self.problems.append(f"{self.tag}{what}: {needle!r} not in {(hay or '')[:80]!r}")


def dig(d, *path):
    for k in path:
        if isinstance(d, dict):
            d = d.get(k)
        elif isinstance(d, list) and isinstance(k, int) and -len(d) <= k < len(d):
            d = d[k]
        else:
            return None
    return d


def ids(d):
    return [r.get("id") for r in (dig(d, "waves", "rows") or [])]


def row(d, wid):
    return next((r for r in (dig(d, "waves", "rows") or []) if r.get("id") == wid), None)


def find(lines, prefix):
    return next((x for x in (lines or []) if x.lstrip().startswith(prefix)), None)


def need(t, lines, prefix):
    x = find(lines, prefix)
    t.ok(x is not None, f"no plain line starts with {prefix!r}")
    return x or ""


def line_of(text, prefix):
    for i, x in enumerate(text.split("\n"), 1):
        if x.startswith(prefix):
            return i
    return -1


def both(ctx, t, brain, *flags, rc=0, status="ok", max_lines=40, width=160):
    """Run plain + --json with the same flags; check the shared contract; return the JSON dict."""
    plain = ctx.run(brain, *flags)
    js = ctx.run(brain, "--json", *flags)
    t.eq(plain.rc, rc, "plain exit code")
    t.eq(js.rc, rc, "--json exit code")
    t.ok(len(plain.lines) <= max_lines, f"plain run prints {len(plain.lines)} lines, cap {max_lines}")
    wide = [len(x) for x in plain.lines if len(x) > width]
    t.ok(not wide, f"{len(wide)} plain line(s) wider than {width} (max {max(wide or [0])})")
    t.ok(bool(plain.lines) and plain.lines[-1].startswith(LAST_LINE[status]),
         f"last plain line must start with {LAST_LINE[status]!r}, got {(plain.lines or ['(empty)'])[-1][:60]!r}")
    d = js.data
    if d is None:
        t.ok(False, f"--json stdout is not a JSON object: {js.out[:50]!r}")
        return None
    t.eq(d.get("status"), status, "json status")
    t.ok(isinstance(d.get("version"), str) and bool(d["version"]), "json version is a non-empty string")
    t.eq(d.get("text"), plain.lines, "json text == plain stdout lines")
    if status == "ok":
        t.eq(d.get("missing"), [], "json missing")
        t.eq(d.get("reason"), None, "json reason")
    elif status == "partial":
        t.ok(isinstance(d.get("missing"), list) and bool(d["missing"]), "partial lists what is missing")
    else:
        t.ok(isinstance(d.get("reason"), str) and bool(d["reason"]), "unparsed carries a reason")
    waves = d.get("waves")
    if status != "unparsed" and waves:
        rows = waves.get("rows") or []
        t.eq(waves.get("count"), len(rows), "waves.count == len(rows)")
        t.eq(sum((waves.get("by_glyph") or {}).values()), len(rows), "by_glyph sums to count")
        t.eq([r.get("id") for r in rows if r.get("ready")], d.get("ready"), "ready == rows flagged ready")
        t.ok(dig(d, "logbook", "order") in ORDERS, f"logbook.order is one of {ORDERS}")
    return d


# ------------------------------------------------------------------ fixtures
H1 = "# Acme — Task tracker: Billing revamp"
HDR7 = ("| Status | Wave | Tasks | Gate | Skills to load | Base branch | Depends on |\n"
        "|---|---|---|---|---|---|---|")
BURN = ("## Weekly burn\n\nEvery Monday: waves planned vs closed.\n\n"
        "| Week | Planned | Closed | Burn | Action |\n|---|---|---|---|---|")
LEGEND = "Status legend: ☐ pending · 🔄 in progress · ⛔ blocked (DoD-human pending) · ✅ done."
INTRO = "Append one entry per wave session."


def r7(glyph, wave, tasks="T-1", gate="—", dep="—"):
    return f"| {glyph} | {wave} | {tasks} | {gate} | acme-ctx | main | {dep} |"


def wave_map(*rows, title="## Wave map", hdr=HDR7):
    return "\n".join([title, "", hdr, *rows])


def entry(heading, *bullets):
    return "\n".join([f"### {heading}", "", *bullets])


def logbook(*entries, title="## Logbook", intro=INTRO):
    return "\n\n".join([title, intro, *entries])


def doc(*parts):
    return "\n\n".join(parts) + "\n"


def simple(pending=None, before=False, log=None):
    """Three-wave tracker; `pending` is an extra section placed before or after the logbook."""
    wm = wave_map(r7("✅", "**W1**"), r7("🔄", "**W2**", dep="W1"), r7("☐", "**W3**", dep="W2"))
    lb = logbook(*(log or [entry("2026-01-05 — Wave W2", "- **Next:** continue W2",
                                  "- **Blocked:** W3 awaits A")]))
    parts = [H1, wm, BURN] + ([pending] if pending and before else []) + [lb]
    return doc(*parts + ([pending] if pending and not before else []))


GOOD = doc(H1, wave_map(r7("☐", "**W1**")), BURN,
           logbook(entry("2026-01-05 — Wave W1", "- **Next:** go")))


# ------------------------------------------------------------------ cases
def case_en_template_exact(ctx, t):
    body = doc(
        "<!--\nTemplate: task.md — the STATE: wave map + burn + logbook.\n"
        "This is the only document that mutates during execution.\n-->",
        H1,
        "> Execution state of the billing revamp. Task specs live in `detailed-plan.md`;\n"
        "> the protocol and per-wave prompts in `execute.md`. Mark a wave ✅ only when its\n"
        "> DoD-auto passed AND its DoD-human (if any) was confirmed by A.",
        wave_map(r7("☐", "**W1**", "T-W1-1 + T-W1-2"), r7("☐", "**W2**", "T-W2-1", "⚠", "W1")),
        LEGEND, BURN,
        logbook(entry(
            "2026-01-15 — Wave W1 [PARTIAL]",
            "- **Branch/MR:** feat/acme-w1 (https://example.com/acme/mr/1)",
            "- **Tasks closed:** T-W1-1 · **Blocked:** T-W1-2 + pending DoD-human",
            "- **Files touched:** per manifest",
            "- **Manifest drift:** none",
            "- **Notes/decisions:** invoices are rounded half-up",
            "- **Wall clock:** 2h",
            "- **Reuse:** none",
            "- **Simplifier:** packaged `code-simplifier:code-simplifier` ran over `abc1234..HEAD`",
            "- **Orchestrator fix:** none",
            "- **Agents used:** 7/20 (opus 3 · sonnet 4) — opus: audit x3; sonnet: execute",
            "  and verify x4 (continuation line)",
            "- **Escalations:** none",
            "- **Next:** run the W2 prompt after A approves the invoice template"),
            intro="Append one entry per wave session (including `[PARTIAL]` ones — see `execute.md` §4):"))
    d = both(ctx, t, ctx.brain("template", body))
    if not d:
        return
    txt = d.get("text") or []
    t.eq(dig(d, "project", "title"), "Acme", "project.title")
    t.eq(dig(d, "project", "subtitle"), "Task tracker: Billing revamp", "project.subtitle")
    t.eq(dig(d, "git", "kind"), "none", "git.kind outside any repo")
    t.eq(dig(d, "waves", "count"), 2, "waves.count")
    t.eq(dig(d, "waves", "by_glyph"), {"☐": 2}, "waves.by_glyph")
    t.eq(ids(d), ["W1", "W2"], "wave ids")
    t.eq(dig(row(d, "W2"), "depends"), ["W1"], "W2.depends")
    t.eq(dig(row(d, "W1"), "depends"), [], "W1.depends")
    t.eq(dig(d, "waves", "irregular"), 0, "waves.irregular")
    t.eq(d.get("ready"), ["W1"], "ready")
    t.eq(dig(d, "logbook", "order"), "single", "logbook.order")
    t.eq(dig(d, "logbook", "entries"), 1, "logbook.entries")
    t.eq(dig(d, "logbook", "last", "date"), "2026-01-15", "last.date")
    t.eq(dig(d, "logbook", "last", "suffix"), None, "last.suffix")
    t.eq(dig(d, "logbook", "last", "wave"), "W1", "last.wave")
    t.eq(dig(d, "logbook", "last", "partial"), True, "last.partial")
    t.eq(dig(d, "logbook", "last", "stop"), False, "last.stop")
    t.has(" ".join(dig(d, "logbook", "last", "next") or []), "run the W2 prompt", "last.next")
    t.has(" ".join(dig(d, "logbook", "last", "closed") or []), "T-W1-1", "last.closed")
    t.has(" ".join(dig(d, "logbook", "last", "blocked") or []), "T-W1-2", "last.blocked (inline split)")
    ag = dig(d, "logbook", "last", "agents") or {}
    t.eq([ag.get(k) for k in ("used", "budget", "opus", "sonnet")], [7, 20, 3, 4], "last.agents")
    a, z = dig(d, "logbook", "last", "lines") or [0, 0]
    t.eq(a, line_of(body, "### 2026-01-15"), "last.lines[0] = 1-based heading line")
    t.ok(z >= line_of(body, "- **Next:**"), "last.lines[1] covers the whole entry")
    t.eq(dig(d, "pending", "shape"), "logbook-fallback", "pending.shape")
    t.eq(dig(d, "pending", "open"), 1, "pending.open")
    t.eq(dig(d, "artifacts", "state"), "no-registry", "artifacts.state")
    t.ok(find(txt, "STATUS Acme — Task tracker: Billing revamp") is not None, "STATUS line")
    t.has(need(t, txt, "WAVES 2:"), "☐ 2", "WAVES line")
    t.has(need(t, txt, "NEXT"), "W1", "NEXT line")
    t.has(need(t, txt, f"LAST LOG 2026-01-15"), "PARTIAL", "LAST LOG line")
    t.has(need(t, txt, "LAST LOG"), f"@L{a}-{z}", "LAST LOG line range")
    t.ok("git: none" in txt, "git: none line")
    t.ok("ARTIFACTS no registry" in txt, "ARTIFACTS line")


def case_es_aliases(ctx, t):
    hdr = ("| Ola | Estado | Tareas | Gate | Skills | Rama | Depende de |\n"
           "|---|---|---|---|---|---|---|")
    wm = wave_map(
        "| **W1** | ✅ | T-W1-1 | — | acme-ctx | main | — |",
        "| **W2** | 🔄 | T-W2-1 + T-W2-2 | ⚠ | acme-ctx | main | W1 |",
        "| **W3** | ☐ | T-W3-1 | — | acme-ctx | main | W2 |",
        title="## Mapa de olas", hdr=hdr)
    body = doc(
        "# Acme — Task tracker: Facturación", wm,
        "## Weekly burn\n\n| Week | Planned | Closed | Burn | Action |\n|---|---|---|---|---|",
        "## Dueños y RACI\n\n| Rol | Persona | Nota |\n|---|---|---|\n| Dueño | A | — |",
        logbook(
            entry("2026-02-10 — Ola W2 [PARCIAL]",
                  "- **Siguiente:** correr el prompt W2 de nuevo",
                  "- **Bloqueadas**: T-W2-2 espera la aprobación de A",
                  "- **Tareas cerradas:** T-W2-1",
                  "- **Agentes usados:** 5/20 (opus 1 · sonnet 4)"),
            entry("2026-02-01 — Ola W1",
                  "- **Tareas cerradas:** T-W1-1",
                  "- **Agentes usados**: 3/20 (opus 0 · sonnet 3)"),
            title="## Bitácora"))
    d = both(ctx, t, ctx.brain("es", body))
    if not d:
        return
    txt = d.get("text") or []
    t.eq(dig(d, "project", "subtitle"), "Task tracker: Facturación", "project.subtitle")
    t.eq(ids(d), ["W1", "W2", "W3"], "wave ids (header-indexed columns)")
    t.eq(dig(d, "waves", "by_glyph"), {"✅": 1, "🔄": 1, "☐": 1}, "waves.by_glyph")
    t.eq(dig(row(d, "W3"), "depends"), ["W2"], "W3.depends")
    t.eq(d.get("ready"), [], "ready")
    t.eq(d.get("waiting_on"), ["W2"], "waiting_on")
    t.has(need(t, txt, "NEXT"), "none ready (waiting on W2", "NEXT line")
    t.ok(find(txt, "🔄 W2") is not None, "🔄 W2 line")
    t.eq(dig(d, "logbook", "order"), "newest-first", "logbook.order")
    t.eq(dig(d, "logbook", "entries"), 2, "logbook.entries")
    t.eq(dig(d, "logbook", "last", "date"), "2026-02-10", "last.date")
    t.eq(dig(d, "logbook", "last", "wave"), "W2", "last.wave")
    t.eq(dig(d, "logbook", "last", "partial"), True, "last.partial ([PARCIAL])")
    t.has(" ".join(dig(d, "logbook", "last", "next") or []), "correr el prompt W2", "last.next (Siguiente)")
    t.has(" ".join(dig(d, "logbook", "last", "blocked") or []), "T-W2-2", "last.blocked (colon outside bold)")
    t.has(" ".join(dig(d, "logbook", "last", "closed") or []), "T-W2-1", "last.closed (Tareas cerradas)")
    ag = dig(d, "logbook", "last", "agents") or {}
    t.eq([ag.get(k) for k in ("used", "budget", "opus", "sonnet")], [5, 20, 1, 4], "last.agents")
    t.eq(dig(d, "logbook", "prev", 0, "date"), "2026-02-01", "prev[0].date")
    t.eq(dig(d, "logbook", "prev", 0, "wave"), "W1", "prev[0].wave")
    t.eq(dig(d, "logbook", "prev", 0, "partial"), False, "prev[0].partial")


def case_suffix_mixed_order(ctx, t):
    wm = wave_map(r7("✅", "**W1**"), r7("✅", "**W2**", dep="W1"), r7("🔄", "**W3**", dep="W2"))
    body = doc(H1, wm, BURN, logbook(
        entry("2026-03-02 — Wave W1", "- **Next:** old a"),
        entry("2026-03-05 (b) — Wave W3 [PARTIAL]", "- **Next:** second b"),
        entry("2026-03-05 (3) — Wave W3 [PARTIAL]", "- **Next:** newest three"),
        entry("2026-03-04 — Wave W2", "- **Next:** old c"),
        entry("2026-03-01 — Wave W1", "- **Next:** old d")))
    b = ctx.brain("suffix", body)
    d = both(ctx, t, b)
    if not d:
        return
    txt = d.get("text") or []
    t.eq(dig(d, "logbook", "order"), "mixed", "logbook.order")
    t.eq(dig(d, "logbook", "entries"), 5, "logbook.entries")
    t.eq(dig(d, "logbook", "last", "date"), "2026-03-05", "last.date")
    t.eq(dig(d, "logbook", "last", "suffix"), "3", "last.suffix (digits beat a letter)")
    t.eq(dig(d, "logbook", "last", "wave"), "W3", "last.wave")
    t.eq(dig(d, "logbook", "last", "partial"), True, "last.partial")
    t.eq([dig(d, "logbook", "prev", 0, "date"), dig(d, "logbook", "prev", 0, "suffix")],
         ["2026-03-05", "b"], "prev[0] = (b)")
    t.eq(dig(d, "logbook", "prev", 1, "date"), "2026-03-04", "prev[1].date")
    ll = need(t, txt, "LAST LOG 2026-03-05 (3)")
    t.has(ll, "order mixed", "LAST LOG flags the order")
    r = ctx.run(b, "--entry")
    t.eq(r.rc, 0, "--entry exit code")
    t.ok("2026-03-05 (3)" in r.out and "newest three" in r.out and "second b" not in r.out,
         "--entry prints the newest entry in full")
    t.ok(len(r.lines) <= 40, "--entry prints <= 40 lines")
    r = ctx.run(b, "--entry", "2")
    t.ok("(b)" in r.out and "second b" in r.out and "newest three" not in r.out,
         "--entry 2 prints the second most recent entry")


def case_marker_in_bold_and_backticks(ctx, t):
    wm = wave_map(r7("✅", "**W1**"), r7("✅", "**W2**", dep="W1"), r7("🔄", "**W3**", dep="W2"))
    body = doc(H1, wm, BURN, logbook(
        entry("2026-04-03 — Wave W3 `[PARCIAL]` [STOP]", "- **Next:** resume W3"),
        entry("2026-04-02 — **W2 [PARTIAL] — cierre**", "- **Next:** n/a"),
        entry("2026-04-01 — Wave W1", "- **Next:** n/a")))
    d = both(ctx, t, ctx.brain("markers", body))
    if not d:
        return
    t.eq(dig(d, "logbook", "last", "partial"), True, "last.partial (marker in backticks)")
    t.eq(dig(d, "logbook", "last", "stop"), True, "last.stop")
    t.eq(dig(d, "logbook", "last", "wave"), "W3", "last.wave")
    h = dig(d, "logbook", "last", "heading") or ""
    t.ok(bool(h) and "`" not in h and "**" not in h, f"last.heading is plain text, got {h!r}")
    t.eq(dig(d, "logbook", "prev", 0, "partial"), True, "prev[0].partial (marker in bold)")
    t.eq(dig(d, "logbook", "prev", 0, "wave"), "W2", "prev[0].wave")
    t.eq(dig(d, "logbook", "prev", 1, "partial"), False, "prev[1].partial")
    t.has(need(t, d.get("text"), "LAST LOG"), "STOP", "LAST LOG line carries STOP")


def case_malformed_rows(ctx, t):
    huge = ("billing-reconcile " * 180)[:3000]
    body = doc(H1, wave_map(
        r7("✅", "**W1**"),
        r7("✅", "**W2**", dep="W1"),
        "| ✅ | **W3** — Core | T-W3-1 | — | W2 |",
        "| ☐ | **W4** | T-W4-1 | — | acme-ctx | main | notes | W3 |",
        "| ☐ | **W5** | T-W5-1 | ⚠ | acme-ctx | main | notes | extra | W4 |",
        r7("🔄", "**W6**", "T-W6-1 + " + huge, dep="W3")),
        BURN, logbook(entry("2026-05-01 — Wave W3", "- **Next:** W4")))
    d = both(ctx, t, ctx.brain("malformed", body))
    if not d:
        return
    t.eq(ids(d), ["W1", "W2", "W3", "W4", "W5", "W6"], "wave ids")
    t.eq(dig(d, "waves", "irregular"), 3, "waves.irregular (5-, 8- and 9-cell rows)")
    t.eq(dig(d, "waves", "by_glyph"), {"✅": 3, "☐": 2, "🔄": 1}, "waves.by_glyph")
    t.eq(dig(row(d, "W3"), "glyph"), "✅", "W3.glyph (5 cells)")
    t.eq(dig(row(d, "W3"), "depends"), ["W2"], "W3.depends = last cell (5 cells)")
    t.eq(dig(row(d, "W4"), "depends"), ["W3"], "W4.depends = last cell (8 cells)")
    t.eq(dig(row(d, "W5"), "depends"), ["W4"], "W5.depends = last cell (9 cells)")
    t.eq(d.get("ready"), ["W4"], "ready")
    t.has(need(t, d.get("text"), "WAVES"), "3 irregular", "WAVES line counts irregular rows")


def case_second_table_in_section(ctx, t):
    hdr5 = "| Status | Wave | Tasks | Gate | Depends on |\n|---|---|---|---|---|"
    wm = "\n\n".join([
        wave_map(r7("✅", "**W1**"), r7("🔄", "**W2**", dep="W1")),
        "Gate owners:",
        "| Gate | Owner | Due |\n|---|---|---|\n| G1 | A | 2026-06-01 |\n| ☐ | **W9** | 2026-06-02 |",
        "Second batch:",
        hdr5 + "\n| ☐ | **W3** | T-W3-1 | — | W2 |"])
    body = doc(H1, wm, BURN, logbook(
        entry("2026-06-01 — Wave W1", "- **Next:** W2"),
        entry("2026-06-02 — Wave W2", "- **Next:** W3")))
    d = both(ctx, t, ctx.brain("second-table", body))
    if d:
        t.eq(ids(d), ["W1", "W2", "W3"], "wave ids (3-column table ignored, 2nd wave table read)")
        t.eq(dig(d, "waves", "irregular"), 0, "waves.irregular")
        t.eq(dig(d, "logbook", "order"), "oldest-first", "logbook.order")
        t.eq(dig(d, "logbook", "last", "date"), "2026-06-02", "last.date (oldest-first file)")
        t.has(need(t, d.get("text"), "LAST LOG"), "order oldest-first", "LAST LOG flags the order")
    # No "Wave map"-style section at all: the Wave|Ola header test still finds the table.
    body = doc(H1, wave_map(r7("✅", "**W1**"), r7("☐", "**W2**", dep="W1"), title="## Plan por olas"),
               logbook(entry("2026-06-02 — Wave W1", "- **Next:** W2")))
    d = both(ctx, t, ctx.brain("second-table-b", body))
    if d:
        t.eq(ids(d), ["W1", "W2"], "wave ids found by header test without a Wave-map section")


def case_glyph_tags(ctx, t):
    rows = [
        r7("**✅**", "**W1**", "T-1"),
        r7("⛔\ufe0f superada", "**W2**", "T-2", dep="W1"),
        r7("⛔", "**W3**", "T-3", "⛔ DoD-human pending", "W1"),
        r7("☐\ufe0f deuda", "**W4**", "T-4", dep="W1"),
        r7("⏸ opcional", "**W5**", "T-5"),
        r7("🔀 fusionada", "**W6**", "T-6"),
        r7("🔬", "**W7**", "T-7"),
        r7("🔄", "**W8**", "T-8", dep="W1"),
        r7("❗", "**W9**", "T-9"),
    ]
    body = doc(H1, wave_map(*rows), BURN, logbook(entry("2026-07-01 — Wave W8", "- **Next:** W8")))
    d = both(ctx, t, ctx.brain("glyphs", body))
    if not d:
        return
    txt = d.get("text") or []
    t.eq(dig(d, "waves", "by_glyph"),
         {"✅": 1, "⛔": 2, "☐": 1, "⏸": 1, "🔀": 1, "🔬": 1, "🔄": 1, "other:❗": 1},
         "waves.by_glyph (FE0F and ** stripped, unknown glyph -> other:<ch>)")
    tags = dig(d, "waves", "tags") or {}
    t.eq(tags.get("⛔"), {"superada": 1}, "tags[⛔]")
    t.eq(tags.get("☐"), {"deuda": 1}, "tags[☐]")
    t.eq(tags.get("⏸"), {"opcional": 1}, "tags[⏸]")
    t.eq(tags.get("🔀"), {"fusionada": 1}, "tags[🔀]")
    t.eq(dig(row(d, "W2"), "tag"), "superada", "W2.tag")
    t.eq(dig(row(d, "W3"), "tag"), None, "W3.tag")
    t.ok(str(dig(row(d, "W3"), "gate") or "").startswith("⛔"), "W3.gate keeps the ⛔ cell")
    w = need(t, txt, "WAVES 9:")
    t.ok("(superada 1)" in w and "(deuda 1)" in w, f"WAVES line shows the tags, got {w[:100]!r}")
    t.ok(find(txt, "⛔ W3") is not None, "untagged ⛔ W3 is listed")
    t.ok(find(txt, "⛔ W2") is None, "⛔ superada W2 stays out of the ⛔ list")


def case_non_wid_ids(ctx, t):
    body = doc(H1, wave_map(
        r7("✅", "**Wave W1**"),
        r7("✅", "**W2a**", dep="W1"),
        r7("✅", "**W8 — Cimientos**", "T-8", dep="W2a"),
        r7("🔄", "**OPS/métricas**", "T-G", dep="W8"),
        r7("☐", "**WSKILL-DEMO**", "T-S", dep="W8"),
        r7("☐", "**WO-3 (docs)**", "T-O", dep="WSKILL-DEMO, OPS/métricas"),
        r7("☐", "**W10:** Cierre", "T-10", dep="WO-3")),
        BURN, logbook(
            entry("2026-05-03 — ABC-12 · T-W9-3 · WO-3 (docs)", "- **Next:** x"),
            entry("2026-05-02 — Wave OPS/métricas cierre", "- **Next:** y"),
            entry("2026-05-01 — W8 — Cimientos", "- **Next:** z")))
    d = both(ctx, t, ctx.brain("odd-ids", body))
    if not d:
        return
    t.eq(ids(d), ["W1", "W2a", "W8", "OPS/métricas", "WSKILL-DEMO", "WO-3", "W10"], "wave ids")
    t.eq(dig(row(d, "W8"), "title"), "Cimientos", "W8.title = text after the dash")
    t.eq(dig(row(d, "WO-3"), "depends"), ["WSKILL-DEMO", "OPS/métricas"], "WO-3.depends")
    t.eq(d.get("ready"), ["WSKILL-DEMO"], "ready")
    t.eq(dig(d, "logbook", "last", "wave"), "WO-3", "last.wave skips ABC-12 and T-W9-3")
    t.eq(dig(d, "logbook", "prev", 0, "wave"), "OPS/métricas", "prev[0].wave (Wave <id> fallback)")
    t.eq(dig(d, "logbook", "prev", 1, "wave"), "W8", "prev[1].wave")


def case_placeholder_headings(ctx, t):
    body = doc(H1, wave_map(r7("☐", "**W1**")), BURN, logbook(
        entry("{{fecha}} — Wave {{Wx}}", "- **Branch/MR:** {{branch}}"),
        entry("<fecha> — Wave <Wx> [PARTIAL]", "- **Next:** <next>"),
        entry("{date of execution} — Wave {Wx} {[PARTIAL] if unfinished}", "- **Next:** {next}")))
    d = both(ctx, t, ctx.brain("placeholders", body))
    if not d:
        return
    t.eq(dig(d, "logbook", "entries"), 0, "logbook.entries")
    t.eq(dig(d, "logbook", "last"), None, "logbook.last")
    t.eq(dig(d, "logbook", "order"), "none", "logbook.order")
    t.eq(dig(d, "logbook", "prev"), [], "logbook.prev")
    t.ok(find(d.get("text"), "LAST LOG none yet") is not None, "LAST LOG none yet line")
    t.eq(dig(d, "pending", "open"), 0, "pending.open")


def pending_checks(t, d, shape, open_, total):
    t.eq(dig(d, "pending", "shape"), shape, "pending.shape")
    t.eq(dig(d, "pending", "open"), open_, "pending.open")
    t.eq(dig(d, "pending", "total"), total, "pending.total")
    t.eq(len(dig(d, "pending", "items") or []), total, "len(pending.items)")


def case_pending_table_que_bloquea(ctx, t):
    sec = ("## Pendientes humanos (DoD-human)\n\n| # | Qué | Bloquea | Límite |\n|---|---|---|---|\n"
           "| 1 | Aprobar el contrato con el cliente | W4 | 2026-07-01 |\n"
           "| 2 | ~~Enviar credenciales de pruebas~~ ✅ | W2 | 2026-06-15 |\n"
           "| 3 | Confirmar el dominio https://example.com/billing | W5 | — |\n"
           "| 4 | Pagar la licencia del proveedor | W5 | — |")
    d = both(ctx, t, ctx.brain("pend-a", simple(sec)))
    if d:
        pending_checks(t, d, "table/Qué-Bloquea", 3, 4)
        items = dig(d, "pending", "items") or []
        t.eq([i.get("ref") for i in items], ["1", "2", "3", "4"], "items[].ref")
        t.eq([i.get("resolved") for i in items], [False, True, False, False], "items[].resolved (~~ / ✅)")
        t.eq([i.get("blocks") for i in items], ["W4", "W2", "W5", "W5"], "items[].blocks")
        t.has(str(dig(d, "pending", "section")), "Pendientes humanos", "pending.section")
        t.ok(not any("awaits" in (i.get("text") or "") for i in items), "last-log Blocked bullets are not mixed in")
        txt = d.get("text") or []
        t.ok(need(t, txt, "PENDING-HUMAN 3/4 open").find("table/Qué-Bloquea") > 0, "PENDING-HUMAN line shows the shape")
        t.ok(any("Aprobar el contrato" in x and "→ W4" in x for x in txt), "item line '<item> → <blocks>'")
    sec = ("## Pending human actions\n\n| # | What | Blocks | Due |\n|---|---|---|---|\n"
           "| 1 | Approve the contract | W4 | 2026-07-01 |\n| 2 | ~~Send test credentials~~ | W2 | — |")
    d = both(ctx, t, ctx.brain("pend-a-en", simple(sec)))
    if d:
        pending_checks(t, d, "table/Qué-Bloquea", 1, 2)


def case_pending_table_item_dueno(ctx, t):
    sec = ("## Bloqueantes humanos\n\n| # | Ítem | Dueño | Bloquea |\n|---|---|---|---|\n"
           "| 1 | Revisar el texto legal | A | W3 |\n"
           "| 2 | ✅ Abrir la cuenta de pagos | A | W2 |\n"
           "| 3 | ~~Definir precios~~ | A | W2 |\n"
           "| 4 | ⛔ Firmar el acuerdo de datos | A | W3 |")
    d = both(ctx, t, ctx.brain("pend-b", simple(sec, before=True)))
    if d:
        pending_checks(t, d, "table/Ítem-Dueño", 2, 4)
        items = dig(d, "pending", "items") or []
        hard = [i for i in items if i.get("hard")]
        t.eq(len(hard), 1, "exactly one hard (⛔) item")
        t.has((hard[0].get("text") if hard else ""), "Firmar el acuerdo", "hard item text")
        t.eq(sorted(i.get("ref") for i in items if i.get("resolved")), ["2", "3"], "resolved refs")
        txt = d.get("text") or []
        pos = {k: next((n for n, x in enumerate(txt) if k in x), -1) for k in ("Firmar el acuerdo", "Revisar el texto")}
        t.ok(0 <= pos["Firmar el acuerdo"] < pos["Revisar el texto"], f"⛔ item is listed first, positions {pos}")
    sec = ("## DoD-human pending\n\n| # | Item | Owner | Blocks | Due |\n|---|---|---|---|---|\n"
           "| 1 | Sign the data agreement | A | W3 | 2026-07-01 |\n"
           "| 2 | ~~Rotate the staging key~~ ✅ | A | W2 | — |")
    d = both(ctx, t, ctx.brain("pend-b-en", simple(sec)))
    if d:
        pending_checks(t, d, "table/Ítem-Dueño", 1, 2)


def case_pending_checklist(ctx, t):
    sec = ("## Open questions\n\n"
           "- [ ] Confirm the pricing page copy at https://example.com/pricing\n"
           "- [x] Approve the invoice template\n"
           "- [ ] ⛔ Rotate the staging key\n"
           "- [ ] Book the review call with A")
    d = both(ctx, t, ctx.brain("pend-c", simple(sec)))
    if not d:
        return
    pending_checks(t, d, "checklist", 3, 4)
    items = dig(d, "pending", "items") or []
    t.ok(all(i.get("ref") is None for i in items), "checklist items have ref null")
    t.eq(sorted(i.get("resolved") for i in items), [False, False, False, True], "items[].resolved")
    t.eq([bool(i.get("hard")) for i in items if "Rotate" in (i.get("text") or "")], [True], "⛔ item is hard")
    txt = d.get("text") or []
    pos = {k: next((n for n, x in enumerate(txt) if k in x), -1) for k in ("Rotate the staging", "Confirm the pricing")}
    t.ok(0 <= pos["Rotate the staging"] < pos["Confirm the pricing"], f"⛔ item is listed first, positions {pos}")
    t.ok(any(x.startswith("  •") and "Rotate the staging" in x for x in txt), "checklist line starts with '  •'")
    t.has(str(dig(d, "pending", "section")), "Open questions", "pending.section")


def case_pending_logbook_fallback(ctx, t):
    log = [entry("2026-11-02 — Wave W3",
                 "- **Notes/decisions:** x",
                 "- **Blocked:** W3 needs the approval",
                 "  of the pricing page (continuation)",
                 "- **DoD-human:** confirm https://example.com/staging works",
                 "- **Next:** retry"),
           entry("2026-11-01 — Wave W2", "- **Blocked:** old thing that was resolved")]
    d = both(ctx, t, ctx.brain("pend-d", simple(log=log)))
    if not d:
        return
    pending_checks(t, d, "logbook-fallback", 2, 2)
    items = dig(d, "pending", "items") or []
    t.ok("pricing page" in (items[0].get("text") if items else ""), "first item merges its continuation line")
    t.ok(any("staging" in (i.get("text") or "") for i in items), "DoD-human bullet becomes an item")
    t.ok(not any("old thing" in (i.get("text") or "") for i in items), "only the LAST entry feeds the fallback")
    t.eq(len(dig(d, "logbook", "last", "blocked") or []), 2, "last.blocked has both bullets")
    pl = need(t, d.get("text"), "PENDING-HUMAN")
    t.ok("from last log" in pl or "logbook-fallback" in pl, f"PENDING-HUMAN line names the source, got {pl[:80]!r}")


def case_no_logbook_section(ctx, t):
    wm = wave_map(r7("✅", "**W1**"), r7("☐", "**W2**", dep="W1"))
    log = logbook(entry("2026-01-05 — Wave W1", "- **Next:** W2"))
    d = both(ctx, t, ctx.brain("no-log", doc(H1, wm, BURN)), rc=1, status="partial")
    if d:
        t.eq(d.get("missing"), ["logbook"], "missing")
        t.eq(dig(d, "logbook", "last"), None, "logbook.last")
        t.eq(dig(d, "waves", "count"), 2, "waves still parsed")
        t.ok(dig(d, "pending", "open") == 0 and dig(d, "pending", "shape") in ("none", "logbook-fallback"),
             "no pending without a logbook")
        t.ok((d.get("text") or [""])[-1].startswith("DIGEST: partial(logbook)"), "DIGEST line names logbook")
    d = both(ctx, t, ctx.brain("no-h1-brain", doc(wm, BURN, log)), rc=1, status="partial")
    if d:
        t.eq(d.get("missing"), ["header"], "missing (no H1)")
        t.eq(dig(d, "project", "title"), None, "project.title (no H1)")
        t.ok("no-h1-brain" in ((d.get("text") or [""])[0]), "STATUS line falls back to the dir name")
        t.ok((d.get("text") or [""])[-1].startswith("DIGEST: partial(header)"), "DIGEST line names header")
    d = both(ctx, t, ctx.brain("no-waves", doc(H1, BURN, log)), rc=1, status="partial")
    if d:
        t.eq(d.get("missing"), ["waves"], "missing (no wave map)")
        t.ok(dig(d, "waves", "count") in (0, None), "no waves")
        t.eq(dig(d, "logbook", "last", "date"), "2026-01-05", "logbook still parsed")
    both(ctx, t, ctx.brain("no-sections", doc(H1, "Some prose, no tables and no log.")),
         rc=2, status="unparsed", max_lines=5)


def case_no_task_md(ctx, t):
    d = both(ctx, t, ctx.brain("empty-dir"), rc=2, status="unparsed", max_lines=5)
    if d:
        t.has(d.get("reason"), "task.md", "reason names task.md")
    d = both(ctx, t, ctx.brain("tasks-only", extra={"TASKS.md": "# Acme tasks\n\n- [ ] do the thing\n"}),
             rc=2, status="unparsed", max_lines=5)
    if d:
        t.has(d.get("reason"), "unsupported format", "reason (TASKS.md only)")
        t.has((d.get("text") or [""])[-1], "unsupported format", "DIGEST line (TASKS.md only)")
    both(ctx, t, ctx.brain("blank", "\n\n"), rc=2, status="unparsed", max_lines=5)


def case_html_comment_preamble(ctx, t):
    ghost = ("<!--\nDraft notes (not part of the tracker)\n# Ghost Title — Fake\n## Wave map\n\n"
             + HDR7 + "\n" + r7("✅", "**W99**") + "\n-->")
    body = doc(
        ghost, H1,
        wave_map(r7("✅", "**W1**"), r7("🔄", "**W2**", dep="W1")), BURN,
        logbook("<!-- ### 2026-12-31 — Wave W9 -->",
                entry("2026-08-02 — Wave W2 [PARTIAL]", "- **Next:** run the W2 prompt again"),
                entry("2026-08-01 — Wave W1", "- **Tasks closed:** T-W1-1")),
        "## Punto de retomada\n\n- Run the W2 prompt after A confirms https://example.com/ok.\n"
        "- Second bullet that must not appear.")
    d = both(ctx, t, ctx.brain("comment", body))
    if not d:
        return
    t.eq(dig(d, "project", "title"), "Acme", "project.title (H1 after the comment)")
    t.eq(ids(d), ["W1", "W2"], "wave ids (no W99 from inside the comment)")
    t.eq(dig(d, "logbook", "entries"), 2, "logbook.entries (commented heading ignored)")
    t.eq(dig(d, "logbook", "last", "date"), "2026-08-02", "last.date")
    t.eq(dig(d, "logbook", "last", "lines", 0), line_of(body, "### 2026-08-02"), "last.lines[0] counts comment lines")
    t.has(d.get("resume"), "Run the W2 prompt", "resume")
    t.ok("Second bullet" not in (d.get("resume") or ""), "resume is the first bullet only")
    t.has(need(t, d.get("text"), "RESUME"), "Run the W2 prompt", "RESUME line")


def case_worktree_git_file(ctx, t):
    if not shutil.which("git"):
        raise Skip("git not installed")
    repo = os.path.join(ctx.root, "repo")
    os.makedirs(repo)
    ctx.write("repo/task.md", GOOD)
    ctx.git(repo, "init", "-q")
    ctx.git(repo, "add", "task.md")
    ctx.git(repo, "commit", "-q", "-m", "init Acme tracker")
    full, branch = ctx.git(repo, "rev-parse", "HEAD"), ctx.git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    wt = os.path.join(ctx.root, "wt")
    try:
        ctx.git(repo, "worktree", "add", "-q", "-b", "acme-wt", wt)
    except (subprocess.CalledProcessError, OSError):
        raise Skip("git worktree unavailable")

    def kind_checks(d, kind, br, dirty):
        g = dig(d, "git") or {}
        t.eq(g.get("kind"), kind, f"git.kind ({kind})")
        t.eq(g.get("branch"), br, f"git.branch ({kind})")
        sha = g.get("sha") or ""
        t.ok(len(sha) >= 7 and full.startswith(sha), f"git.sha is a prefix of HEAD ({kind}), got {sha!r}")
        t.ok(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(g.get("date"))) is not None, f"git.date ({kind})")
        t.eq(g.get("subject"), "init Acme tracker", f"git.subject ({kind})")
        t.eq(g.get("dirty"), dirty, f"git.dirty ({kind})")
        t.eq(g.get("unpushed"), None, f"git.unpushed without upstream ({kind})")

    d = both(ctx, t, repo)
    if d:
        kind_checks(d, "repo", branch, 0)
    ctx.write("repo/notes.txt", "scratch\n")
    d = both(ctx, t, repo)
    if d:
        t.eq(dig(d, "git", "dirty"), 1, "git.dirty counts the untracked file")
        t.has(need(t, d.get("text"), "git "), "dirty 1", "git line")
    d = both(ctx, t, wt)
    if d:
        kind_checks(d, "worktree", "acme-wt", 0)
        gl = need(t, d.get("text"), "git ")
        t.ok('"init Acme tracker"' in gl and "worktree" in gl and "unpushed ?" in gl, f"git line, got {gl[:120]!r}")
    ctx.write("repo/docs/brain/task.md", GOOD)
    d = both(ctx, t, os.path.join(repo, "docs", "brain"))
    if d:
        t.eq(dig(d, "git", "kind"), "repo", "git.kind for a brain inside a repo subdir")
    d = both(ctx, t, ctx.brain("norepo", GOOD))
    if d:
        t.eq(dig(d, "git", "kind"), "none", "git.kind outside any repo")
        t.ok("git: none" in (d.get("text") or []), "git: none line")
    d = both(ctx, t, repo, "--no-git")
    if d:
        g = d.get("git")
        t.ok(g is None or g.get("kind") == "off", "--no-git -> git null or kind off")
        t.ok("git: off" in (d.get("text") or []), "git: off line")
    # Submodule: optional extra (skipped silently when this git refuses a local submodule).
    try:
        src, sup = os.path.join(ctx.root, "subsrc"), os.path.join(ctx.root, "super")
        os.makedirs(src)
        os.makedirs(sup)
        ctx.write("subsrc/task.md", GOOD)
        ctx.git(src, "init", "-q")
        ctx.git(src, "add", "task.md")
        ctx.git(src, "commit", "-q", "-m", "init sub")
        ctx.git(sup, "init", "-q")
        ctx.git(sup, "commit", "-q", "--allow-empty", "-m", "init super")
        ctx.git(sup, "-c", "protocol.file.allow=always", "submodule", "add", "-q", src, "vendor/brain")
    except (subprocess.CalledProcessError, OSError):
        return
    d = both(ctx, t, os.path.join(sup, "vendor", "brain"))
    if d:
        t.eq(dig(d, "git", "kind"), "submodule", "git.kind for a submodule")


def cap_doc():
    """30 long 🔄 waves, 20 open checklist items, 4 long entries, a RESUME section."""
    long = "lorem ipsum dolor sit amet " * 10
    waves = [r7("🔄", f"**W{i}** — {long}", f"T-W{i}-1 + {long}", "—", f"W{i - 1}" if i > 1 else "—")
             for i in range(1, 31)]
    pend = "## Open questions\n\n" + "\n".join(f"- [ ] Item {i} {long}" for i in range(1, 21))
    log = [entry(f"2026-10-0{k} — Wave W{k} {long}" + (" [PARTIAL]" if k == 4 else ""),
                 f"- **Next:** {long}", f"- **Blocked:** {long}", "- **Agents used:** 4/20 (opus 1 · sonnet 3)")
           for k in (4, 3, 2, 1)]
    body = doc(H1, wave_map(*waves), BURN, pend, logbook(*log),
               "## Punto de retomada\n\n- " + long + "\n- second")
    return body


def case_line_cap(ctx, t):
    b = ctx.brain("cap", cap_doc())
    d = both(ctx, t, b)
    if d:
        t.eq(dig(d, "waves", "count"), 30, "waves.count")
        t.eq(dig(d, "waves", "by_glyph"), {"🔄": 30}, "waves.by_glyph")
        t.eq([dig(d, "pending", "total"), dig(d, "pending", "open")], [20, 20], "pending total/open")
        txt = d.get("text") or []
        t.ok(any("+27 more" in x for x in txt), "🔄 list ends with '+27 more'")
        t.ok(any("+14 more" in x for x in txt), "pending list ends with '+14 more'")
    d = both(ctx, t, b, "--lines", "20", max_lines=20)
    if d:
        txt = d.get("text") or []
        for pre in ("STATUS", "git", "WAVES", "LAST LOG", "PENDING-HUMAN", "ARTIFACTS"):
            need(t, txt, pre)
        t.eq(dig(d, "waves", "count"), 30, "waves.count (--lines 20)")
    both(ctx, t, b, "--width", "100", width=100)


def case_module(ctx, t):
    def tracker(title, wave, glyph, date, extra=""):
        return doc(title, wave_map(r7(glyph, f"**{wave}**")), BURN,
                   logbook(entry(f"{date} — Wave {wave} [PARTIAL]", "- **Next:** continue" + extra)))
    b = ctx.brain("mods", tracker("# Acme — Task tracker: Platform", "W1", "✅", "2026-09-01"), extra={
        "modules/billing/task.md": tracker("# Acme Billing — Task tracker: Invoicing", "B1", "🔄", "2026-09-15"),
        "modules/payroll/task.md": tracker("# Acme Payroll — Task tracker: Books", "L1", "☐", "2026-09-10"),
        "modules/notes/readme.md": "not a module\n"})
    d = both(ctx, t, b)
    if d:
        t.eq(dig(d, "project", "module"), None, "project.module")
        t.eq(sorted(os.path.basename(x) for x in (dig(d, "project", "modules") or [])), ["billing", "payroll"],
             "project.modules lists modules/*/task.md only")
        t.eq(dig(d, "logbook", "last", "date"), "2026-09-01", "root last.date")
        bl = (d.get("text") or ["", ""])[1]
        t.ok(bl.startswith("brain ") and "billing, payroll" in bl and "--module" in bl, f"brain line lists modules, got {bl[:100]!r}")
    d = both(ctx, t, b, "--module", "modules/billing")
    if d:
        t.eq(dig(d, "project", "module"), "modules/billing", "project.module")
        t.eq(dig(d, "project", "title"), "Acme Billing", "project.title (module tracker)")
        t.eq(ids(d), ["B1"], "wave ids (module tracker)")
        t.eq(dig(d, "logbook", "last", "date"), "2026-09-15", "module last.date")
        t.ok("module modules/billing" in (d.get("text") or ["", ""])[1], "brain line shows the module")
    both(ctx, t, b, "--module", "modules/nope", rc=2, status="unparsed", max_lines=5)


def case_deps(ctx, t):
    body = doc(H1, wave_map(
        r7("✅", "**W1**"), r7("✅", "**W2**", dep="W1"),
        r7("☐", "**W3**", dep="W1"),
        r7("☐", "**W4**", dep="W1–W2"),
        r7("☐", "**W5**", dep="W2..W3"),
        r7("☐", "**W6**", dep="W1, T10"),
        r7("☐", "**W7**", dep="W3 + W4")),
        BURN, logbook(entry("2026-09-01 — Wave W2", "- **Next:** W3")))
    d = both(ctx, t, ctx.brain("deps", body))
    if d:
        t.eq(d.get("ready"), ["W3", "W4", "W6"], "ready")
        t.eq(dig(row(d, "W4"), "depends"), ["W1", "W2"], "W4.depends (en-dash range)")
        t.eq(dig(row(d, "W5"), "depends"), ["W2", "W3"], "W5.depends (.. range)")
        t.eq(dig(row(d, "W6"), "depends"), ["W1"], "W6.depends keeps known ids only")
        t.eq([r.get("id") for r in dig(d, "waves", "rows") if r.get("cond")], ["W6"], "rows flagged cond")
        nl = need(t, d.get("text"), "NEXT")
        t.ok("W3, W4, W6" in nl and "(+cond)" in nl, f"NEXT line, got {nl[:100]!r}")
    body = doc(H1, wave_map(r7("🔄", "**W1**"), r7("☐", "**W2**", dep="W1")), BURN,
               logbook(entry("2026-09-01 — Wave W1", "- **Next:** W2")))
    d = both(ctx, t, ctx.brain("deps-blocked", body))
    if d:
        t.eq(d.get("ready"), [], "ready (nothing ready)")
        t.eq(d.get("waiting_on"), ["W1"], "waiting_on")
        t.has(need(t, d.get("text"), "NEXT"), "none ready (waiting on W1", "NEXT line")


def case_usage_error(ctx, t):
    b = ctx.brain("usage", GOOD)
    r = ctx.run(b, "--bogus")
    t.eq(r.rc, 64, "--bogus exit code")
    t.ok(bool(r.err.strip()), "usage message goes to stderr")
    t.eq(ctx.run(b, "--lines", "many").rc, 64, "--lines many exit code")
    t.eq(ctx.run(None).rc, 64, "missing --brain exit code")
    r = ctx.run(None, "--version")
    t.eq(r.rc, 0, "--version exit code")
    t.ok(bool((r.out + r.err).strip()), "--version prints something")
    d = ctx.run(b, "--json").data or {}
    t.has(r.out + r.err, str(d.get("version") or "?"), "--version matches json version")


def case_artifacts(ctx, t):
    def fake(name, text, code, echo=False):
        src = ("#!/usr/bin/env python3\nimport sys\n" f"out = {text!r}\n"
               + ("out += ' '.join(sys.argv[1:])\n" if echo else "")
               + "sys.stdout.buffer.write((out + '\\n').encode('utf-8'))\n" f"sys.exit({code})\n")
        return ctx.write(name, src, 0o755)

    reg = {"artifacts.json": json.dumps({"close_markers": ["task.md"], "artifacts": []})}
    d = both(ctx, t, ctx.brain("art-none", GOOD))
    if d:
        t.eq([dig(d, "artifacts", k) for k in ("state", "exit", "line")], ["no-registry", None, "no registry"],
             "no registry")
        t.ok("ARTIFACTS no registry" in (d.get("text") or []), "ARTIFACTS no registry line")
    b = ctx.brain("art-ok", GOOD, reg)
    ok = fake("courier-ok.py", "courier-preflight: 2 rows · fresh 2 · nothing to publish", 0)
    d = both(ctx, t, b, "--courier", ok)
    if d:
        t.eq([dig(d, "artifacts", k) for k in ("state", "exit", "line")],
             ["ok", 0, "2 rows · fresh 2 · nothing to publish"], "courier ok (prefix stripped)")
        txt = d.get("text") or []
        t.ok("ARTIFACTS 2 rows · fresh 2 · nothing to publish" in txt, "ARTIFACTS line")
        t.ok(not any("courier-preflight:" in x for x in txt), "no courier-preflight: prefix in the output")
    bad = fake("courier-bad.py", "courier-preflight: boom", 3)
    d = both(ctx, t, b, "--courier", bad)
    if d:
        t.eq([dig(d, "artifacts", k) for k in ("state", "exit", "line")],
             ["error", 3, "preflight error (exit 3)"], "courier exit 3 (digest exit code stays 0)")
        t.ok("ARTIFACTS preflight error (exit 3)" in (d.get("text") or []), "ARTIFACTS error line")
    d = both(ctx, t, b, "--courier", os.path.join(ctx.root, "nowhere", "courier.py"))
    if d:
        t.eq([dig(d, "artifacts", k) for k in ("state", "exit", "line")],
             ["not-found", None, "preflight not found (pass --courier)"], "--courier pointing nowhere")
        t.ok("ARTIFACTS preflight not found (pass --courier)" in (d.get("text") or []), "ARTIFACTS not-found line")
    echo = fake("courier-echo.py", "courier-preflight: args ", 0, echo=True)
    b = ctx.brain("art-mod", GOOD, {"modules/billing/task.md": GOOD, "modules/billing/artifacts.json": reg["artifacts.json"],
                                    **reg})
    d = both(ctx, t, b, "--module", "modules/billing", "--courier", echo)
    if d:
        ln = dig(d, "artifacts", "line") or ""
        t.eq(dig(d, "artifacts", "state"), "ok", "courier ok (module run)")
        t.ok("--module" in ln and "modules/billing" in ln, f"--module REL is passed to the preflight, got {ln!r}")


def case_mixed_glyph_rows(ctx, t):
    body = doc(H1, wave_map(
        r7("✅", "**W1**"),
        r7("", "**W2**", "T-W2-1", dep="W1"),
        r7("Done", "**W3**", "T-W3-1", dep="W1"),
        r7("☐", "**W4**", "T-W4-1", dep="W2")),
        BURN, logbook(entry("2026-01-05 — Wave W1", "- **Next:** W2")))
    d = both(ctx, t, ctx.brain("mixed-glyphs", body), rc=1, status="partial")
    if not d:
        return
    t.ok("waves" in (d.get("missing") or []), f"missing names 'waves', got {d.get('missing')!r}")
    t.eq(dig(d, "waves", "count"), 2, "waves.count (glyph rows only)")
    t.eq(ids(d), ["W1", "W4"], "wave ids (empty and text status cells are not rows)")
    t.has(need(t, d.get("text"), "WAVES"), "2 unparsed rows", "WAVES line counts unparsed rows")
    t.ok("W4" not in (d.get("ready") or []), "W4 is not ready: its dependency W2 has no status")
    t.ok("W2" in (d.get("waiting_on") or []), f"waiting_on names W2, got {d.get('waiting_on')!r}")
    t.has((d.get("text") or [""])[-1], "waves", "DIGEST line names waves")


def case_heading_wave_longest_match(ctx, t):
    wm = wave_map(r7("✅", "**W1**"), r7("✅", "**W2**", dep="W1"), r7("🔄", "**W2a**", dep="W2"))
    body = doc(H1, wm, BURN, logbook(
        entry("2026-03-02 — Wave W2a — closing the slice", "- **Next:** W2a"),
        entry("2026-03-01 — Wave W2 — kickoff", "- **Next:** W2a")))
    d = both(ctx, t, ctx.brain("longest", body))
    if d:
        t.eq(dig(d, "logbook", "last", "wave"), "W2a", "last.wave is the longest known id, not its prefix W2")
        t.eq(dig(d, "logbook", "prev", 0, "wave"), "W2", "prev[0].wave")
    wm = wave_map(r7("✅", "**W1**"), r7("🔄", "**W2**", dep="W1"))
    body = doc(H1, wm, BURN, logbook(entry("2026-03-02 — Ola W2b-fix", "- **Next:** W2")))
    d = both(ctx, t, ctx.brain("longest-b", body))
    if d:
        w = dig(d, "logbook", "last", "wave")
        t.ok(w in (None, "—"), f"last.wave is null/'—' when only a prefix (W2) is known, got {w!r}")


def case_logbook_signals(ctx, t):
    wm = wave_map(r7("✅", "**W1**"), r7("🔄", "**W2**", dep="W1"))
    t.tag = "(a) "
    body = doc(H1, wm, BURN, logbook(entry("2026/01/05 — x", "- **Next:** a"),
                                     entry("Jan 5, 2026 — y", "- **Next:** b")))
    d = both(ctx, t, ctx.brain("signals-a", body), rc=1, status="partial")
    if d:
        t.ok("logbook" in (d.get("missing") or []), f"missing names 'logbook', got {d.get('missing')!r}")
        t.eq(dig(d, "logbook", "last"), None, "logbook.last")
        t.has(need(t, d.get("text"), "LAST LOG"), "2 undated headings", "LAST LOG line")
    t.tag = "(b) "
    body = doc(H1, wm, BURN, logbook(
        entry("2026-04-02 — Wave W2", "- **Next:** wrap the `<!--` handling in the parser",
              "- **Notes/decisions:** the string `<!--` shows up in prose here"),
        entry("2026-04-01 — Wave W1", "- **Next:** W2")),
        "## Punto de retomada\n\n- Resume at the W2 closing pass.")
    d = both(ctx, t, ctx.brain("signals-b", body))
    if d:
        t.eq(dig(d, "logbook", "entries"), 2, "logbook.entries")
        t.eq(dig(d, "logbook", "last", "date"), "2026-04-02", "last.date (an inline `<!--` is not a comment)")
        t.has(d.get("resume"), "Resume at the W2", "resume section after the entry still parsed")
    t.tag = "(c) "
    body = doc(H1, wm, BURN, logbook(
        "   <!-- ### 2026-12-31 — Wave W9 -->",
        "  <!--\n### 2026-12-30 — Wave W9\n-->",
        entry("2026-04-02 — Wave W2", "- **Next:** x"),
        entry("2026-04-01 — Wave W1", "- **Next:** y")))
    d = both(ctx, t, ctx.brain("signals-c", body))
    if d:
        t.eq(dig(d, "logbook", "entries"), 2, "logbook.entries (indented line-start comments stripped)")
        t.eq(dig(d, "logbook", "last", "date"), "2026-04-02", "last.date")


def case_pending_unrecognised(ctx, t):
    sec = ("## Pendientes humanos\n\n- Confirmar el contrato con el cliente\n"
           "- Revisar el dominio https://example.com/billing")
    d = both(ctx, t, ctx.brain("pend-unparsed", simple(sec)))
    if not d:
        return
    t.eq(dig(d, "pending", "shape"), "unparsed", "pending.shape")
    pl = need(t, d.get("text"), "PENDING-HUMAN")
    t.ok(pl.startswith("PENDING-HUMAN ? ·") and "unparsed" in pl, f"PENDING-HUMAN line, got {pl[:80]!r}")


def case_hardening(ctx, t):
    wm = wave_map(r7("✅", "**W1**"), r7("🔄", "**W2**", dep="W1"))

    t.tag = "(a) "
    b = ctx.brain("hard-a", cap_doc())
    d = both(ctx, t, b, "--lines", "8", max_lines=8)
    if d:
        for pre in ("STATUS", "git", "WAVES", "LAST LOG", "PENDING-HUMAN", "ARTIFACTS"):
            need(t, d.get("text"), pre)

    t.tag = "(b) "
    g = ctx.brain("hard-b", GOOD)
    t.eq(ctx.run(g, "--width", "20").rc, 64, "--width 20 exit code")
    t.eq(ctx.run(g, "--width", "59").rc, 64, "--width 59 exit code (minimum is 60)")
    d = both(ctx, t, g, "--width", "60", width=60)
    if d:
        t.eq((d.get("text") or [""])[-1], "DIGEST: ok", "DIGEST line is not clipped at --width 60")
    d = both(ctx, t, ctx.brain("hard-b2", doc(H1, wm, BURN)), "--width", "60", width=60, rc=1, status="partial")
    if d:
        last = (d.get("text") or [""])[-1]
        t.ok(last.endswith(")") and "…" not in last, f"partial(...) is not clipped at --width 60, got {last!r}")

    t.tag = "(c) "
    t.eq(ctx.run(g, "--entry", "99").rc, 64, "--entry 99 exit code (only 1 entry)")

    t.tag = "(d) "
    bullets = [f"- **Notes/decisions:** line {n} " + ("x" * (300 if n % 7 == 0 else 20)) for n in range(1, 61)]
    big = doc(H1, wm, BURN, logbook(entry("2026-05-01 — Wave W2", *bullets), entry("2026-04-01 — Wave W1", "- **Next:** W2")))
    b = ctx.brain("hard-d", big)
    for flags, width in (((), 160), (("--width", "80"), 80)):
        r = ctx.run(b, "--entry", "1", *flags)
        t.eq(r.rc, 0, f"--entry 1 exit code {flags}")
        t.ok(len(r.lines) <= 40, f"--entry 1 prints {len(r.lines)} lines, cap 40 including the footer {flags}")
        t.ok(all(len(x) <= width for x in r.lines), f"--entry 1 lines wider than {width}")
        t.ok(bool(r.lines) and r.lines[-1].startswith("ENTRY 1/"), f"last line starts with 'ENTRY 1/', got {(r.lines or [''])[-1][:40]!r}")

    t.tag = "(e) "
    ctx.brain("outside", GOOD)
    t.eq(ctx.run(ctx.brain("hard-e", GOOD), "--module", "../outside").rc, 64, "--module ../outside exit code")

    t.tag = "(f) "
    if os.name != "nt" and hasattr(os, "geteuid") and os.geteuid() != 0:
        b = ctx.brain("hard-f", GOOD)
        os.chmod(b, 0o311)
        try:
            r = ctx.run(b)
        finally:
            os.chmod(b, 0o755)
        t.eq(r.rc, 2, "unreadable brain dir exit code")
        t.ok(r.out.rstrip().endswith("DIGEST: unparsed (internal error: PermissionError)"),
             f"last line, got {(r.lines or [''])[-1][:80]!r}")

    t.tag = "(g) "
    if shutil.which("git"):
        repo = ctx.brain("hard-g", GOOD)
        ctx.git(repo, "init", "-q")
        ctx.write("fakebin/git", "#!/bin/sh\nexec sleep 8\n", 0o755)
        with ctx.env_patch(PATH=os.path.join(ctx.root, "fakebin") + os.pathsep + ctx.env.get("PATH", "")):
            r = ctx.run(repo)
        t.eq(r.rc, 0, "exit code when git hangs")
        gl = find(r.lines, "git")
        t.ok(gl is not None and (gl == "git ?" or gl.startswith("git ? ")), f"git line is 'git ?', got {gl!r}")

    t.tag = "(h) "
    if shutil.which("git"):
        other = ctx.brain("hard-h-other")
        ctx.git(other, "init", "-q")
        ctx.git(other, "commit", "-q", "--allow-empty", "-m", "elsewhere")
        with ctx.env_patch(GIT_DIR=os.path.join(other, ".git")):
            d = both(ctx, t, ctx.brain("hard-h", GOOD))
        if d:
            t.eq(dig(d, "git", "kind"), "none", "git.kind ignores an exported GIT_DIR")

    t.tag = "(i) "
    log = [entry("2026-01-05 — Wave W2", "- **Next:** continue", "- **Blocked:** none — all clear")]
    d = both(ctx, t, ctx.brain("hard-i", simple(log=log)))
    if d:
        t.eq(dig(d, "pending", "open"), 0, "pending.open ('none — all clear' is not an item)")
        t.ok(not dig(d, "pending", "items"), f"pending.items empty, got {dig(d, 'pending', 'items')!r}")

    t.tag = "(j) "
    for head, want in (("Wave W2 fixed the STOP button", False), ("Wave W2 [STOP]", True)):
        d = both(ctx, t, ctx.brain("hard-j", simple(log=[entry("2026-05-02 — " + head, "- **Next:** x")])))
        if d:
            t.eq(dig(d, "logbook", "last", "stop"), want, f"last.stop for {head!r}")

    t.tag = "(k) "
    body = doc(H1, wm, BURN,
               "## Log de decisiones\n\n" + entry("2026-09-09 — Decision about invoice rounding", "- chose half-up"),
               logbook(entry("2026-05-01 — Wave W2", "- **Next:** W2")))
    d = both(ctx, t, ctx.brain("hard-k", body))
    if d:
        t.eq(dig(d, "logbook", "entries"), 1, "logbook.entries (the decisions log is not the logbook)")
        t.eq(dig(d, "logbook", "last", "date"), "2026-05-01", "last.date")

    t.tag = "(l) "
    body = doc(H1, wave_map(r7("✅", "**W1**"), r7("🔄", "**W2**", "T-W2-*", dep="W1")), BURN,
               logbook(entry("2026-05-01 — Wave W1", "- **Next:** W2")))
    d = both(ctx, t, ctx.brain("hard-l", body))
    if d:
        t.has(need(t, d.get("text"), "🔄 W2"), "T-W2-*", "🔄 line keeps the lone *")
        t.has(str(dig(row(d, "W2"), "tasks")), "T-W2-*", "W2.tasks keeps the lone *")

    t.tag = "(m) "
    log = [entry("2026-05-02 — Wave W1 [PARTIAL]", "- **Next:** first"), entry("2026-05-02 — Wave W2", "- **Next:** second")]
    d = both(ctx, t, ctx.brain("hard-m", simple(log=log)))
    if d:
        t.eq(dig(d, "logbook", "order"), "ambiguous", "logbook.order (same-day entries, no suffix)")
        t.eq(dig(d, "logbook", "last", "wave"), "W2", "last = the later entry in the file")
        t.eq(dig(d, "logbook", "prev", 0, "wave"), "W1", "prev[0] = the earlier entry in the file")


def case_audit_round3(ctx, t):
    wm2 = wave_map(r7("✅", "**W1**"), r7("🔄", "**W2**", dep="W1"))

    t.tag = "(a) "
    body = doc(H1, wm2, BURN, logbook(entry("2026/01/09 — Wave W2", "- **Next:** b"),
                                      entry("2026-01-01 — Wave W1", "- **Next:** a")))
    d = both(ctx, t, ctx.brain("r3-a", body))
    if d:
        t.eq(dig(d, "logbook", "undated"), 1, "logbook.undated")
        t.eq(dig(d, "logbook", "entries"), 1, "logbook.entries (only the ISO-dated one)")
        t.eq(dig(d, "logbook", "last", "date"), "2026-01-01", "last.date")
        t.has(need(t, d.get("text"), "LAST LOG"), "1 undated headings", "LAST LOG line (no silent loss)")

    t.tag = "(b) "
    body = doc(H1, wm2, BURN, logbook("#### 2026-01-05 — Wave W1\n\n- **Next:** a",
                                      " ### 2026-01-05 — Wave W1\n\n- **Next:** b"))
    d = both(ctx, t, ctx.brain("r3-b", body), rc=1, status="partial")
    if d:
        t.ok("logbook" in (d.get("missing") or []), f"missing names 'logbook', got {d.get('missing')!r}")
        t.eq(dig(d, "logbook", "undated"), 2, "logbook.undated (#### and 1-space-indented ### headings)")
        t.has(need(t, d.get("text"), "LAST LOG"), "2 undated headings", "LAST LOG line")
        t.has((d.get("text") or [""])[-1], "partial(logbook)", "DIGEST line")

    t.tag = "(c) "
    body = doc(H1, wave_map(
        r7("✅", "**W1**"),
        "| | **Kickoff** | T-K-1 | — | — | main | — |",
        "| | **Total** | 12 tasks |",
        r7("☐", "**W4**", "T-W4-1", dep="Kickoff")),
        BURN, logbook(entry("2026-01-05 — Wave W1", "- **Next:** W4")))
    d = both(ctx, t, ctx.brain("r3-c", body), rc=1, status="partial")
    if d:
        t.ok("waves" in (d.get("missing") or []), f"missing names 'waves', got {d.get('missing')!r}")
        t.eq(dig(d, "waves", "unparsed"), 1, "waves.unparsed (Kickoff counts, the Total row does not)")
        t.eq(ids(d), ["W1", "W4"], "wave ids")
        t.ok("W4" not in (d.get("ready") or []), "W4 is not ready: Kickoff has no status")
        t.ok("Kickoff" in (d.get("waiting_on") or []), f"waiting_on names Kickoff, got {d.get('waiting_on')!r}")
        t.has(need(t, d.get("text"), "WAVES"), "unparsed", "WAVES line")

    t.tag = "(d) "
    quiet = [entry("2026-01-05 — Wave W2", "- **Next:** continue")]
    sec = "## DoD-human pending\n\n| # | Item | Owner | Blocks | Due |\n|---|---|---|---|---|"
    d = both(ctx, t, ctx.brain("r3-d1", simple(sec, log=quiet)))
    if d:
        pending_checks(t, d, "table/Ítem-Dueño", 0, 0)
        t.ok(need(t, d.get("text"), "PENDING-HUMAN").startswith("PENDING-HUMAN 0/0 open · table/Ítem-Dueño"),
             "PENDING-HUMAN 0/0 line for a header-only table")
    d = both(ctx, t, ctx.brain("r3-d2", simple("## Pendientes humanos\n\nNone right now.", log=quiet)))
    if d:
        pending_checks(t, d, "none", 0, 0)
        t.ok("?" not in need(t, d.get("text"), "PENDING-HUMAN"), "no '?' in the PENDING-HUMAN line")

    t.tag = "(e) "
    d = both(ctx, t, ctx.brain("r3-e1", simple(log=[entry(
        "2026-01-05 — Wave W2", "- **Blocked:** None of the staging keys work for W3")])))
    if d:
        pending_checks(t, d, "logbook-fallback", 1, 1)
        t.ok(bool(dig(d, "logbook", "last", "blocked")), "last.blocked is non-empty")
    for n, text in ((2, "none — all clear"), (3, "None.")):
        d = both(ctx, t, ctx.brain(f"r3-e{n}", simple(log=[entry("2026-01-05 — Wave W2", f"- **Blocked:** {text}")])))
        if d:
            t.eq(dig(d, "pending", "open"), 0, f"pending.open for 'Blocked: {text}'")
            t.ok(not dig(d, "pending", "items"), f"pending.items empty for 'Blocked: {text}'")

    t.tag = "(f) "
    waves = ([r7("✅", "**W1**")] + [r7("🔄", f"**W{i}**", f"T-W{i}-1", dep="W1") for i in range(2, 7)]
             + [r7("☐", "**W7**", "T-W7-1", dep="W1")])
    log = [entry(f"2026-02-0{k} — Wave W{k}", f"- **Next:** go {k}", f"- **Blocked:** thing {k}",
                 "- **Agents used:** 3/20 (opus 1 · sonnet 2)") for k in (3, 2, 1)]
    pend = "## Open questions\n\n" + "\n".join(f"- [ ] Question {i}" for i in range(1, 9))
    body = doc(H1, wave_map(*waves), BURN, pend, logbook(*log), "## Punto de retomada\n\n- Pick up at W7.")
    d = both(ctx, t, ctx.brain("r3-f", body), "--lines", "10", max_lines=10)
    if d:
        t.eq(d.get("ready"), ["W7"], "ready")
        t.has(need(t, d.get("text"), "NEXT"), "W7", "NEXT line is kept at --lines 10")
        for pre in ("STATUS", "git", "WAVES", "LAST LOG", "PENDING-HUMAN", "ARTIFACTS"):
            need(t, d.get("text"), pre)


CASES = [
    ("en_template_exact", case_en_template_exact),
    ("es_aliases", case_es_aliases),
    ("suffix_mixed_order", case_suffix_mixed_order),
    ("marker_in_bold_and_backticks", case_marker_in_bold_and_backticks),
    ("malformed_rows", case_malformed_rows),
    ("second_table_in_section", case_second_table_in_section),
    ("glyph_tags", case_glyph_tags),
    ("non_wid_ids", case_non_wid_ids),
    ("placeholder_headings", case_placeholder_headings),
    ("pending_table_que_bloquea", case_pending_table_que_bloquea),
    ("pending_table_item_dueno", case_pending_table_item_dueno),
    ("pending_checklist", case_pending_checklist),
    ("pending_logbook_fallback", case_pending_logbook_fallback),
    ("no_logbook_section", case_no_logbook_section),
    ("no_task_md", case_no_task_md),
    ("html_comment_preamble", case_html_comment_preamble),
    ("worktree_git_file", case_worktree_git_file),
    ("line_cap", case_line_cap),
    ("module", case_module),
    ("deps", case_deps),
    ("usage_error", case_usage_error),
    ("artifacts", case_artifacts),
    ("mixed_glyph_rows", case_mixed_glyph_rows),
    ("heading_wave_longest_match", case_heading_wave_longest_match),
    ("logbook_signals", case_logbook_signals),
    ("pending_unrecognised", case_pending_unrecognised),
    ("hardening", case_hardening),
    ("audit_round3", case_audit_round3),
]


def run_case(fn, digest, keep):
    root = os.path.realpath(tempfile.mkdtemp(prefix="digest-selftest-"))
    t = Check()
    try:
        fn(Ctx(digest, root), t)
        verdict, why = ("FAIL", "; ".join(p[:140] for p in t.problems[:8])) if t.problems else ("PASS", "")
    except Skip as s:
        verdict, why = "SKIP", str(s)
    except Exception as exc:  # a broken harness or a crashing digest is a failure, not a crash
        verdict, why = "FAIL", f"harness error: {exc!r}"
    finally:
        if keep:
            print(f"  kept {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)
    return verdict, why


def main():
    ap = argparse.ArgumentParser(description="Behavioural tests for status_digest.py")
    ap.add_argument("--digest", default=os.path.join(HERE, "status_digest.py"))
    ap.add_argument("--only", help="run a single case by name")
    ap.add_argument("--keep", action="store_true", help="leave the temp trees on disk")
    args = ap.parse_args()
    digest = os.path.abspath(os.path.expanduser(args.digest))
    if not os.path.isfile(digest):
        print(f"digest not found: {digest}")
        return 2
    cases = [c for c in CASES if not args.only or c[0] == args.only]
    if not cases:
        print(f"unknown case {args.only!r}; known: {', '.join(n for n, _ in CASES)}")
        return 2
    tally = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    for name, fn in cases:
        verdict, why = run_case(fn, digest, args.keep)
        tally[verdict] += 1
        print(f"{verdict} {name}" + (f" — {why}" if why else ""))
    print(f"{tally['PASS']} PASS · {tally['FAIL']} FAIL · {tally['SKIP']} SKIP (of {len(cases)})")
    return 1 if tally["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
