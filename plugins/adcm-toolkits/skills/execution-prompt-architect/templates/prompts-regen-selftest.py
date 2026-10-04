#!/usr/bin/env python3
"""prompts-regen-selftest - behavioural tests for prompts-regen.py (stdlib only).

Usage:
  python3 prompts-regen-selftest.py [--script PATH] [--only NAME] [--keep]

Builds one throwaway `tempfile` tree per case (a brain dir holding execute.md with a §7 and,
where needed, a hand-made prompts.html), runs prompts-regen.py as a subprocess
(`WAVE_IDS OUT --brain <dir> [flags]`, PYTHONDONTWRITEBYTECODE=1) and prints
`PASS|FAIL|SKIP <case> [- why]`. Exit code 1 when any case FAILs.

What is asserted (on the generated nav + cards, never pixel output):
  - ids with a lowercase suffix (W2a, W2b) are distinct from W2: nav entry, card id and pre id;
  - several deliveries under one wave (`## Entrega N` / `## Delivery N` + a fence each) become one
    <pre> + copy button + <h3> each, a following `## Notas` / appendix fence is not absorbed, and a
    wave with ONE headingless fence renders byte-identical to the pre-change single-prompt card;
  - a `**bold**` status renders one <strong>, never an escaped one;
  - a non-prompt fence (```bash) before the ```text prompt is skipped, and a `## ` line inside a fence
    (that one or the prompt's own) never ends the wave; a prompt-less wave whose §7 header has no
    status takes its glyph (badge + nav mark) from the task.md wave map;
  - `--closed summary` (default) drops <pre> and the copy button of closed waves (keeps nav entry,
    badge and a localized "closed wave" text) and keeps them for pending ones; `--closed full` is
    the pre-change render; with no closed wave summary and full are byte-identical;
  - --init with the template missing exits 2 with a message; --init --check never creates the file;
    --check is 0 after a build and a rebuild is byte-identical.

Header convention used by the fixtures: `### Wave <ID> — <title> — <glyph> <status text>` (the
glyph only counts as a status after a " — " separator, see prompts-regen.py). Fixtures are
generic (project "Acme"). The script under test defaults to the prompts-regen.py next to this
file (its prompts-html.tmpl must sit beside it); pass --script to test another copy. --keep leaves
the temp trees on disk.
"""
import argparse
import hashlib
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
STATUS = {"✅": "✅ DONE", "☐": "☐ pending", "🔄": "🔄 IN PROGRESS", "⛔": "⛔ BLOCKED"}
CLS = {"✅": "ok", "☐": "pending", "🔄": "blocked", "⛔": "blocked"}
MARK = {"✅": " ✅", "☐": "", "🔄": " ★", "⛔": " ⛔"}
COPY = {"es": "Copiar prompt", "en": "Copy prompt"}
BIG = "lorem ipsum dolor sit amet consectetur\n" * 700  # ~27 KB prompt body


class Skip(Exception):
    pass


# ------------------------------------------------------------------ harness
class R:
    """One prompts-regen run."""

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

    def write(self, rel, content):
        p = self.path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(content)
        return p

    def read(self, rel):
        p = self.path(rel)
        if not os.path.isfile(p):
            return ""
        with open(p, encoding="utf-8") as fh:
            return fh.read()

    def sha(self, rel):
        with open(self.path(rel), "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()

    def brain(self, name, execute_md, task_md=None):
        os.makedirs(self.path(name), exist_ok=True)
        self.write(f"{name}/execute.md", execute_md)
        if task_md is not None:
            self.write(f"{name}/task.md", task_md)
        return self.path(name)

    def run(self, ids, out, brain, *flags, script=None):
        cmd = [sys.executable, script or self.script, ids, self.path(out), "--brain", brain] + list(flags)
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
def fence(body):
    return "```text\n" + body + "\n```"


def wave(wid, title, glyph, *parts, word="Wave", status=None):
    """One §7 block. A part is a body string (headingless fence) or (heading, body)."""
    out = [f"### {word} {wid} — {title} — {status or STATUS[glyph]}"]
    for part in parts:
        if isinstance(part, tuple):
            out.append(part[0])
            out.append(fence(part[1]))
        else:
            out.append(fence(part))
    return "\n\n".join(out)


def execute_md(*blocks):
    return ("# Acme — Execution protocol\n\n## 1. Intro\n\nProtocol text.\n\n"
            "## 7. Wave prompts (instantiated, copy-paste)\n\n" + "\n\n".join(blocks) + "\n")


def legacy_card(wid, title, glyph, body, lang="es"):
    """The pre-change single-prompt card, literally (header, badge, h2, one button, one pre)."""
    low = wid.lower()
    return (f'<section class="card" id="{low}">\n'
            f'<header class="card-h"><div><span class="tid">{wid}</span> '
            f'<span class="badge {CLS[glyph]}">{html.escape(STATUS[glyph], quote=False)}</span>\n'
            f'<h2>{html.escape(title, quote=False)}</h2></div>\n'
            f'<button class="copy" data-target="pre-{low}">{COPY[lang]}</button></header>\n'
            f'<pre id="pre-{low}"><code>{html.escape(body, quote=False)}</code></pre>\n'
            f'</section>')


# ------------------------------------------------------------------ output helpers
def card(out, low):
    m = re.search(rf'<section class="card" id="{re.escape(low)}">.*?</section>', out, re.S)
    return m.group(0) if m else ""


def card_ids(out):
    return re.findall(r'<section class="card" id="([^"]+)"', out)


def nav(out):
    return re.findall(r'<a class="nav-a" href="#([^"]+)">(.*?)</a>', out)


def pres(card_html):
    """[(id, body)] of the <pre> blocks of one card."""
    return re.findall(r'<pre[^>]*\bid="([^"]+)"[^>]*>\s*<code>(.*?)</code>\s*</pre>', card_html, re.S)


def copy_targets(card_html):
    tags = re.findall(r"<button\b[^>]*>", card_html)
    return [re.search(r'data-target="([^"]+)"', b).group(1) for b in tags
            if "copy" in b and re.search(r'data-target="([^"]+)"', b)]


def badge(card_html):
    m = re.search(r'<span class="badge [^"]*">(.*?)</span>', card_html, re.S)
    return m.group(1) if m else None


def build(ctx, ids, md, name="brain", out="prompts.html", *flags):
    r = ctx.run(ids, out, ctx.brain(name, md), "--init", *flags)
    return r, ctx.read(out)


# ------------------------------------------------------------------ cases
def case_ids_lowercase_suffix(ctx, t):
    md = execute_md(wave("W2a", "A", "✅", "BODY-A <1> & x"),
                    wave("W2b", "B", "☐", "BODY-B"),
                    wave("W2", "C", "🔄", "BODY-C"))
    r, out = build(ctx, "W2a,W2b,W2", md)
    t.eq(r.rc, 0, "exit code (default --closed)")
    t.eq(nav(out), [("w2a", "W2a ✅"), ("w2b", "W2b"), ("w2", "W2 ★")], "nav entries: three distinct ids, in list order")
    t.eq(card_ids(out), ["w2a", "w2b", "w2"], "card ids")
    t.has(badge(card(out, "w2a")), "DONE", "W2a badge carries its own status")
    t.has(card(out, "w2a"), "<h2>A</h2>", "W2a title")
    t.eq([(i, b) for i, b in pres(card(out, "w2b"))], [("pre-w2b", "BODY-B")], "W2b prompt (pending: kept)")
    t.eq([(i, b) for i, b in pres(card(out, "w2"))], [("pre-w2", "BODY-C")], "W2 prompt (in progress: kept)")
    # full render: every id keeps its own pre, none borrows the neighbour's body
    r, full = build(ctx, "W2a,W2b,W2", md, "brain-full", "full.html", "--closed", "full")
    t.eq(r.rc, 0, "exit code (--closed full)")
    t.eq([i for i, _ in pres(full)], ["pre-w2a", "pre-w2b", "pre-w2"], "pre ids (--closed full)")
    t.eq(pres(card(full, "w2a")), [("pre-w2a", "BODY-A &lt;1&gt; &amp; x")], "W2a own prompt, escaped")
    t.eq(copy_targets(card(full, "w2a")), ["pre-w2a"], "W2a copy button")
    t.lacks(card(full, "w2"), "BODY-A", "W2 does not absorb W2a's prompt")
    t.lacks(card(full, "w2"), "BODY-B", "W2 does not absorb W2b's prompt")


def case_multi_delivery(ctx, t):
    w3, w5 = "BODY-W3 <x> & y", "BODY-W5"
    md = execute_md(
        wave("W3", "Gamma", "☐", w3),
        wave("W4", "Delta", "☐", ("## Entrega 1 — backend", "BODY-W4-A"), ("## Entrega 2 — frontend", "BODY-W4-B")),
        "## Notas\n\nNotes about W4.\n\n" + fence("NOTES-FENCE-MARKER"),
        wave("W5", "Omega", "☐", w5),
        "## 8. Apéndice\n\n" + fence("APPENDIX-FENCE-MARKER"))
    r, out = build(ctx, "W3,W4,W5", md)
    t.eq(r.rc, 0, "exit code")
    c4 = card(out, "w4")
    p4 = pres(c4)
    t.eq([b for _, b in p4], ["BODY-W4-A", "BODY-W4-B"], "W4: two <pre>, one per delivery, in order")
    ids = [i for i, _ in p4]
    t.ok(len(set(ids)) == len(ids) == 2, f"W4: pre ids are distinct, got {ids}")
    targets = copy_targets(c4)
    t.ok(all(targets.count(i) == 1 for i in ids), f"W4: each <pre> has exactly one copy button targeting it, got {targets}")
    t.ok(all(x in ids for x in targets), f"W4: every copy button targets a <pre> of the card, got {targets}")
    heads = [re.sub(r"<[^>]+>", "", h) for h in re.findall(r"<h3[^>]*>(.*?)</h3>", c4, re.S)]
    t.ok(any("Entrega 1" in h for h in heads) and any("Entrega 2" in h for h in heads),
         f"W4: an <h3> per delivery heading, got {heads}")
    if "Entrega 1" in c4 and "Entrega 2" in c4 and "BODY-W4-A" in c4 and "BODY-W4-B" in c4:
        t.ok(c4.index("Entrega 1") < c4.index("BODY-W4-A") < c4.index("Entrega 2") < c4.index("BODY-W4-B"),
             "W4: heading, prompt, heading, prompt order")
    t.has(c4, "<h2>Delta</h2>", "W4 keeps its title in the <h2>")
    t.lacks(out, "NOTES-FENCE-MARKER", "a following `## Notas` fence is not absorbed")
    t.lacks(out, "APPENDIX-FENCE-MARKER", "a following `## 8.` fence is not absorbed")
    # single headingless fence: byte-identical to the pre-change card
    t.eq(card(out, "w3"), legacy_card("W3", "Gamma", "☐", w3), "W3 (one headingless fence) == pre-change card")
    t.eq(card(out, "w5"), legacy_card("W5", "Omega", "☐", w5), "W5 (one fence, followed by an appendix) == pre-change card")


def case_bold_status_badge(ctx, t):
    md = execute_md(wave("W3", "F", "🔄", "BODY-F", status="🔄 **IN PROGRESS** (phase 2)"))
    r, out = build(ctx, "W3", md)
    t.eq(r.rc, 0, "exit code")
    b = badge(card(out, "w3")) or ""
    t.eq(b.count("<strong>IN PROGRESS</strong>"), 1, "badge holds the <strong> exactly once")
    t.lacks(b, "&lt;", "badge has no escaped markup")
    t.lacks(b, "**", "badge has no raw ** markers")
    t.lacks(out, "&lt;strong&gt;", "page has no escaped <strong> anywhere")


def case_leading_nontext_fence(ctx, t):
    body1 = "BODY-W1 prompt\n## SCOPE inside the prompt\nitem"
    md = execute_md(
        "### Wave W1 — Alpha — ☐ pending\n\nSetup first:\n\n```bash\n## not a heading, inside a fence\necho hi\n```\n\n" + fence(body1),
        wave("W2", "Beta", "☐", "BODY-W2"))
    r, out = build(ctx, "W1,W2", md)
    t.eq(r.rc, 0, "exit code")
    c1 = card(out, "w1")
    t.eq(pres(c1), [("pre-w1", body1)], "W1: the card body is the ```text prompt, whole (its own '## ' line included)")
    t.lacks(c1, "```", "W1: no fence marker leaks into the card")
    t.lacks(c1, "echo hi", "W1: the ```bash block is not the prompt")
    t.eq(card(out, "w2"), legacy_card("W2", "Beta", "☐", "BODY-W2"), "W2 is not affected by W1's fences")


def case_summary_badge_promptless(ctx, t):
    task = ("# Acme — Task tracker\n\n## Wave map\n\n"
            "| Status | Wave | Tasks | Gate | Skills | Base branch | Depends on |\n|---|---|---|---|---|---|---|\n"
            "| ✅ | **W1** | T-W1-1 | — | acme-ctx | main | — |\n| ☐ | **W2** | T-W2-1 | — | acme-ctx | main | W1 |\n")
    md = execute_md("### Wave W1 — Alpha\n\nExecuted under a previous flow.", wave("W2", "Beta", "☐", "BODY-W2"))
    brain = ctx.brain("b", md, task)
    r = ctx.run("W1,W2", "prompts.html", brain, "--init")
    t.eq(r.rc, 0, "exit code (default --closed summary)")
    out = ctx.read("prompts.html")
    t.eq(nav(out), [("w1", "W1 ✅"), ("w2", "W2")], "nav: W1 carries the ✅ mark from the wave map")
    c1 = card(out, "w1")
    t.has(c1, '<span class="badge ok">', "W1 badge class is ok")
    t.has(badge(c1), "✅", "W1 badge shows ✅")
    t.lacks(badge(c1) or "", "☐", "W1 badge no longer shows the default ☐")
    t.lacks(c1, "<pre", "W1 (closed, prompt-less): no <pre>")
    t.eq(pres(card(out, "w2")), [("pre-w2", "BODY-W2")], "W2 (pending) keeps its prompt")


def case_closed_summary(ctx, t):
    md = execute_md(
        wave("W1", "Alpha", "✅", "BODY-W1-MARKER\n" + BIG),
        wave("W2", "Beta", "✅", ("## Entrega 1 — a", "BODY-W2-A"), ("## Entrega 2 — b", "BODY-W2-B")),
        wave("W3", "Gamma", "☐", "BODY-W3"),
        wave("W4", "Delta", "🔄", "BODY-W4"),
        wave("W5", "Omega", "⛔", "BODY-W5"))
    ids = "W1,W2,W3,W4,W5"
    r, summ = build(ctx, ids, md, "b-summary", "summary.html")
    t.eq(r.rc, 0, "exit code (default)")
    t.eq(nav(summ), [("w1", "W1 ✅"), ("w2", "W2 ✅"), ("w3", "W3"), ("w4", "W4 ★"), ("w5", "W5 ⛔")],
         "nav keeps every wave, closed ones included")
    for low in ("w1", "w2"):
        c = card(summ, low)
        t.ok(bool(c), f"{low}: card present")
        t.lacks(c, "<pre", f"{low} (closed): no <pre>")
        t.lacks(c, 'class="copy"', f"{low} (closed): no copy button")
        t.has(badge(c), "DONE", f"{low} (closed): badge kept")
        t.has(c.lower(), "ola cerrada", f"{low} (closed): ES closed-wave text")
    t.lacks(summ, "BODY-W1-MARKER", "closed W1 prompt is not inlined")
    t.lacks(summ, "BODY-W2-A", "closed W2 deliveries are not inlined")
    for low, body in (("w3", "BODY-W3"), ("w4", "BODY-W4"), ("w5", "BODY-W5")):
        c = card(summ, low)
        t.eq(pres(c), [(f"pre-{low}", body)], f"{low} (pending): full <pre>")
        t.eq(copy_targets(c), [f"pre-{low}"], f"{low} (pending): copy button")
        t.lacks(c.lower(), "ola cerrada", f"{low} (pending): no closed-wave text")
    r, explicit = build(ctx, ids, md, "b-explicit", "explicit.html", "--closed", "summary")
    t.eq(r.rc, 0, "exit code (--closed summary)")
    t.ok(explicit == summ, "--closed summary is the default (byte-identical)")
    r, en = build(ctx, ids, md, "b-en", "en.html", "--lang", "en")
    t.has(card(en, "w1").lower(), "closed wave", "EN closed-wave text")
    t.lacks(card(en, "w1").lower(), "ola cerrada", "EN page has no ES closed-wave text")
    r, full = build(ctx, ids, md, "b-full", "full.html", "--closed", "full")
    t.eq(r.rc, 0, "exit code (--closed full)")
    t.eq(nav(full), nav(summ), "nav is the same in full and summary")
    t.eq(card(full, "w1"), legacy_card("W1", "Alpha", "✅", "BODY-W1-MARKER\n" + BIG), "full: closed W1 == pre-change card")
    t.eq(card(full, "w3"), legacy_card("W3", "Gamma", "☐", "BODY-W3"), "full: W3 == pre-change card")
    t.eq(card(full, "w4"), legacy_card("W4", "Delta", "🔄", "BODY-W4"), "full: W4 == pre-change card")
    t.eq(card(full, "w5"), legacy_card("W5", "Omega", "⛔", "BODY-W5"), "full: W5 == pre-change card")
    t.eq([b for _, b in pres(card(full, "w2"))], ["BODY-W2-A", "BODY-W2-B"], "full: closed W2 keeps its two deliveries")
    t.ok(len(summ) + 20000 < len(full), f"summary page is much smaller than full ({len(summ)} vs {len(full)} bytes)")
    # nothing closed: summary == full
    open_md = execute_md(wave("W1", "Alpha", "☐", "BODY-A"), wave("W2", "Beta", "🔄", "BODY-B"), wave("W3", "Gamma", "⛔", "BODY-C"))
    r1, s_out = build(ctx, "W1,W2,W3", open_md, "b-open-s", "open-s.html", "--closed", "summary")
    r2, f_out = build(ctx, "W1,W2,W3", open_md, "b-open-f", "open-f.html", "--closed", "full")
    t.ok(r1.rc == 0 and r2.rc == 0, f"exit codes with no closed wave: {r1.rc}/{r2.rc}")
    t.ok(bool(s_out) and s_out == f_out, "with no closed wave, --closed summary == --closed full byte-for-byte")


def case_init_template_missing(ctx, t):
    bare = ctx.path("bare")
    os.makedirs(bare)
    script = os.path.join(bare, "prompts-regen.py")
    shutil.copyfile(ctx.script, script)  # a copy: the template next to the original must not be found
    brain = ctx.brain("b", execute_md(wave("W1", "Alpha", "☐", "BODY")))
    r = ctx.run("W1", "prompts.html", brain, "--init", script=script)
    t.eq(r.rc, 2, "exit code when prompts-html.tmpl is missing")
    t.lacks(r.text, "Traceback", "no traceback")
    t.has(r.text, "prompts-html.tmpl", "the message names the missing template")
    t.ok(not os.path.exists(ctx.path("prompts.html")), "no output file is created")


def case_init_check_no_write(ctx, t):
    brain = ctx.brain("b", execute_md(wave("W1", "Alpha", "☐", "BODY")))
    r = ctx.run("W1", "prompts.html", brain, "--init", "--check")
    t.ok(r.rc != 0, f"--init --check on a missing output is not 'up to date', exit {r.rc}")
    t.ok(not os.path.exists(ctx.path("prompts.html")), "--check never creates the output (even with --init)")
    t.lacks(r.text, "Traceback", "no traceback")


def case_check_idempotent(ctx, t):
    md = execute_md(
        wave("W2a", "A", "✅", "BODY-A"),
        wave("W2b", "B", "☐", "BODY-B"),
        wave("W2", "C", "🔄", "BODY-C"),
        wave("W4", "D", "☐", ("## Entrega 1 — x", "BODY-D1"), ("## Entrega 2 — y", "BODY-D2")))
    ids = "W2a,W2b,W2,W4"
    brain = ctx.brain("b", md)
    r = ctx.run(ids, "prompts.html", brain, "--init")
    t.eq(r.rc, 0, "first build exit code")
    first = ctx.read("prompts.html")
    t.eq(card_ids(first), ["w2a", "w2b", "w2", "w4"], "first build: four distinct cards")
    r = ctx.run(ids, "prompts.html", brain, "--check")
    t.eq(r.rc, 0, "--check right after a build")
    r = ctx.run(ids, "prompts.html", brain)
    t.eq(r.rc, 0, "rebuild exit code")
    t.ok(ctx.read("prompts.html") == first, "rebuild is byte-identical")
    r = ctx.run(ids, "prompts.html", brain, "--check")
    t.eq(r.rc, 0, "--check after the rebuild")
    with open(os.path.join(brain, "execute.md"), "a", encoding="utf-8") as fh:
        fh.write("\n### Wave W6 — E — ☐ pending\n\n" + fence("BODY-E") + "\n")
    r = ctx.run(ids + ",W6", "prompts.html", brain, "--check")
    t.eq(r.rc, 1, "--check is stale (1) once a wave is added to §7")


def case_title_fallback_lowercase_suffix(ctx, t):
    tmpl_path = os.path.join(os.path.dirname(ctx.script), "prompts-html.tmpl")
    if not os.path.isfile(tmpl_path):
        raise Skip("prompts-html.tmpl not found next to the script")
    with open(tmpl_path, encoding="utf-8") as fh:
        shell = fh.read().replace("{{PROJECT_NAME}}", "Acme")
    c0 = shell.find('<section class="card"')
    c1 = shell.rfind("</section>", 0, shell.find("</main>")) + len("</section>")
    hand = ('<section class="card" id="w2a">\n<header class="card-h"><div><span class="tid">W2a</span> '
            '<span class="badge pending">☐</span>\n<h2>Hand Title A</h2></div></header>\n</section>')
    ctx.write("prompts.html", shell[:c0] + hand + shell[c1:])
    md = execute_md("### Wave W2a — 🔄 IN PROGRESS (phase 1)\n\n" + fence("BODY-A"))
    r = ctx.run("W2a", "prompts.html", ctx.brain("b", md))
    t.eq(r.rc, 0, "exit code")
    t.has(card(ctx.read("prompts.html"), "w2a"), "<h2>Hand Title A</h2>",
          "a header with no title falls back to the card's existing <h2> (id match is case-insensitive)")


CASES = [
    ("ids_lowercase_suffix", case_ids_lowercase_suffix),
    ("multi_delivery", case_multi_delivery),
    ("bold_status_badge", case_bold_status_badge),
    ("leading_nontext_fence", case_leading_nontext_fence),
    ("summary_badge_promptless", case_summary_badge_promptless),
    ("closed_summary", case_closed_summary),
    ("init_template_missing", case_init_template_missing),
    ("init_check_no_write", case_init_check_no_write),
    ("check_idempotent", case_check_idempotent),
    ("title_fallback_lowercase_suffix", case_title_fallback_lowercase_suffix),
]


def run_case(fn, script, keep):
    root = os.path.realpath(tempfile.mkdtemp(prefix="prompts-regen-selftest-"))
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
    ap = argparse.ArgumentParser(description="Behavioural tests for prompts-regen.py")
    ap.add_argument("--script", default=os.path.join(HERE, "prompts-regen.py"))
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
