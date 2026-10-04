#!/usr/bin/env python3
"""renovate-selftest - behavioural tests for renovate_check.py (stdlib only).

Usage:
  python3 renovate-selftest.py [--checker PATH] [--only NAME] [--keep]

Builds one throwaway `tempfile` tree per case (brains holding execute.md, task.md,
artifacts.json, scripts/ and a fake skill dir `skilltpl/templates/` whose six template files
have known content), runs the checker as a subprocess (`--brain <dir> --skill-dir <tmp>/skilltpl
[flags]`, PYTHONDONTWRITEBYTECODE=1, HOME=<tmp>) and prints `PASS|FAIL|SKIP <case> [- why]`.
Exit code 1 when any case FAILs.

Every run is asserted twice (plain + --json with the same flags): exit code, <= 40 plain lines,
last line `RENOVATE: up-to-date | needed(a,b) | unparsed (...)` consistent with the exit code
and with json.needed, json.text == plain stdout lines, and the brain tree untouched unless the
case passes --copy-scripts. Fixtures are generic (Acme, modules/billing, example.com).
The checker under test defaults to the renovate_check.py next to this file.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
RELEASE = "0.14.2"  # what plugin.json, the template Protocol line and __version__ must all say
VERSION = RELEASE  # the checker's own __version__ (read in main) drives the fixtures
FILES = ("status_digest.py", "status-brief.md", "plans-regen.py", "plans-html.tmpl",
         "prompts-regen.py", "prompts-html.tmpl")
TYPES = ("executor", "auditor", "researcher", "courier", "digester")
BLOCKS = ("scripts", "artifacts", "execute", "task", "rules", "context", "modules")
KEYS = ("version", "target", "brain", "module", "protocol", "blocks", "needed", "invariants", "text")
DONE = "✅🔀"
DOCS = {"en": ("master-plan.md", "detailed-plan.md"),
        "es": ("propuesta-ejecutiva.md", "plan-maestro.md", "plan-detallado.md")}
HDR = {"✅": "✅ DONE (2026-01-05)", "☐": "☐", "🔄": "🔄 IN PROGRESS", "⛔": "⛔ BLOCKED",
       "⏸": "⏸ PAUSED", "🔀": "🔀 MERGED"}
W3 = [("W1", "✅"), ("W2", "☐"), ("W3", "🔄")]
RULE_EN = ("   One counter per session, `model` explicit on every call or an `adcm-toolkits:*` type "
           "(a per-call `model` overrides the type's default: `researcher` + `model: opus` for Opus "
           "investigations; types fix the TOOL SET).")
RULE_ES = ("   Los tipos `adcm-toolkits:*` fijan el conjunto de herramientas; el `model` explícito por llamada "
           "manda sobre el del tipo.")
RULE_BAD_ES = "   Los tipos `adcm-toolkits:*` fijan las herramientas; el `model` se elige en la sesión."
RULE_BAD_EN = "   One counter per session, `model` explicit on every call or an `adcm-toolkits:*` type."
ES_EX = {"es": True, "nxt": "Siguiente", "blk": "bloqueadas"}
ES_TK = {"es": True, "nxt": "Siguiente"}


class Skip(Exception):
    pass


# ------------------------------------------------------------------ harness
class R:
    def __init__(self, p):
        self.rc, self.out, self.err = p.returncode, p.stdout, p.stderr
        self.lines = p.stdout.splitlines()
        try:
            data = json.loads(p.stdout)
        except ValueError:
            data = None
        self.data = data if isinstance(data, dict) else None


def tpl(name):
    return f"# fake template {name} (selftest v1)\n"


def custom(name):
    return f"# customised {name} (project copy)\n"


def snap(root):
    out = {}
    for dp, dn, fn in os.walk(root):
        for d in dn:
            out[os.path.relpath(os.path.join(dp, d), root) + "/"] = "dir"
        for f in fn:
            p = os.path.join(dp, f)
            try:
                with open(p, "rb") as fh:
                    out[os.path.relpath(p, root)] = hashlib.sha256(fh.read()).hexdigest()
            except OSError:
                out[os.path.relpath(p, root)] = "?"
    return out


def read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


class Ctx:
    def __init__(self, checker, root):
        self.checker, self.root = checker, root
        self.skill = os.path.join(root, "skilltpl")
        for n in FILES:
            self.write("skilltpl/templates/" + n, tpl(n))
        self.env = dict(os.environ)
        self.env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
                         "PYTHONUTF8": "1", "HOME": root,
                         "CLAUDE_CONFIG_DIR": os.path.join(root, "cfg")})

    def path(self, rel):
        return os.path.join(self.root, *rel.split("/"))

    def write(self, rel, content):
        p = self.path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(content)
        return p

    def brain(self, name, execute=None, task=None, art=None, scripts="all", docs="en", extra=None, under=""):
        """Create <root>[/under]/<name>/. scripts: 'all' | 'none' | {file: content}; docs: 'en'|'es'|None."""
        rel = (under + "/" if under else "") + name
        os.makedirs(self.path(rel), exist_ok=True)
        if execute is not None:
            self.write(rel + "/execute.md", execute)
        if task is not None:
            self.write(rel + "/task.md", task)
        if art is not None:
            self.write(rel + "/artifacts.json", art_json(art))
        if scripts == "all":
            for n in FILES:
                self.write(rel + "/scripts/" + n, tpl(n))
        elif isinstance(scripts, dict):
            for n, body in scripts.items():
                self.write(rel + "/scripts/" + n, body)
        for n in DOCS.get(docs, ()):
            self.write(rel + "/" + n, f"# {n}\n")
        for r, body in (extra or {}).items():
            self.write(rel + "/" + r, body)
        return self.path(rel)

    def run(self, brain, *flags, skill=True, checker=None):
        cmd = ([sys.executable, checker or self.checker] + (["--brain", brain] if brain else [])
               + (["--skill-dir", self.skill] if skill else []) + list(flags))
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=self.env, cwd=self.root, timeout=60)
        return R(p)


class Check:
    def __init__(self):
        self.problems = []
        self.tag = ""

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
        else:
            return None
    return d


def blk(d, name, *rest):
    return dig(d, "blocks", name, *rest)


def anyline(lines, needle):
    return any(needle in x for x in (lines or []))


def both(ctx, t, brain, *flags, rc=0, twin=None, ro=True):
    """Plain + --json with the same flags (the --json run goes on `twin` when given: same fixture,
    separate tree, for flows that write). Checks the shared contract; returns the JSON dict."""
    jb = twin or brain
    before = snap(brain) if ro and not twin else None
    plain = ctx.run(brain, *flags)
    js = ctx.run(jb, "--json", *flags)
    t.eq(plain.rc, rc, "plain exit code")
    t.eq(js.rc, rc, "--json exit code")
    t.ok(len(plain.lines) <= 40, f"plain run prints {len(plain.lines)} lines, cap 40")
    last = plain.lines[-1] if plain.lines else "(empty)"
    if rc == 0:
        t.eq(last, "RENOVATE: up-to-date", "last plain line")
    elif rc == 1:
        t.ok(re.fullmatch(r"RENOVATE: needed\([a-z,]+\)", last) is not None,
             f"last plain line must be 'RENOVATE: needed(a,b)', got {last[:60]!r}")
    else:
        t.ok(last.startswith("RENOVATE: unparsed"), f"last plain line must start 'RENOVATE: unparsed', got {last[:60]!r}")
    d = js.data
    if d is None:
        t.ok(False, f"--json stdout is not a JSON object: {js.out[:50]!r}")
        return None
    t.eq(d.get("text"), [x.replace(brain, jb) for x in plain.lines], "json text == plain stdout lines")
    t.eq(d.get("version"), VERSION, "json version")
    if rc in (0, 1):
        gone = [k for k in KEYS if k not in d]
        t.ok(not gone, f"json lacks keys {gone}")
        t.eq(d.get("target"), VERSION, "json target")
        got = set((d.get("blocks") or {}).keys())
        t.ok(set(BLOCKS) - {"rules"} <= got <= set(BLOCKS), f"json blocks keys, got {sorted(got)}")
        m = re.fullmatch(r"RENOVATE: needed\((.*)\)", last)
        t.eq(d.get("needed"), m.group(1).split(",") if m else [], "json needed == last plain line")
        need = d.get("needed") or []
        t.ok("context" not in need and need == sorted(need, key=lambda n: BLOCKS.index(n) if n in BLOCKS else 99),
             f"needed never holds context and follows the block order, got {need}")
        if "--module" not in flags:
            t.eq(os.path.realpath(d.get("brain") or ""), os.path.realpath(jb), "json brain")
    if before is not None:
        t.eq(snap(brain), before, "brain tree untouched by a read-only run")
    return d


# ------------------------------------------------------------------ fixtures
def art(file_, regen=None):
    r = {"file": file_, "title": file_}
    if regen is not None:
        r["regen"] = regen
    return r


def art_json(rows):
    return json.dumps({"close_markers": ["task.md", "execute.md"], "artifacts": rows}, indent=1) + "\n"


def plans_cmd(lang):
    return f"python3 scripts/plans-regen.py --brain . --lang {lang} plans.html"


def prompts_cmd(lang, ids):
    return f"python3 scripts/prompts-regen.py --brain . --lang {lang} --init {','.join(ids)} prompts.html"


def ok_rows(lang="en", ids=("W1", "W2", "W3")):
    return [art("plans.html", plans_cmd(lang)), art("prompts.html", prompts_cmd(lang, ids))]


def opening(p, where="s2"):
    es = p["es"]
    verb, rd = ('Carga el skill', 'lee') if es else ('Load the skill', 'read')
    out = ([verb, f"`{p['ctx']}`, {rd}"] if p["wrap"] else [f"{verb} `{p['ctx']}`, {rd}"])
    out.append("`docs/execute.md` (this protocol).")
    if p["digest"] is True or (p["digest"] == "s7" and where == "s7"):
        s = ("Then run `python3 docs/scripts/status_digest.py --brain docs`: this wave's deps ✅, "
             "no foreign `[PARTIAL]` open; never read task.md whole.")
        if "digester" in p["types"]:
            s += " Exit 2 → one `adcm-toolkits:digester` with `docs/scripts/status-brief.md`."
        out.append(s)
    else:
        out.append("Then read `docs/task.md`: this wave's deps ✅, no foreign `[PARTIAL]` open.")
    if p["last_log"] == "s2":
        out.append("The digest's LAST LOG line names the open `[PARTIAL]` entry.")
    return out


EXEC_DEFAULTS = dict(protocol=VERSION, types=TYPES, digest=True, last_log="s4", nxt="Next", blk="blocked",
                     rule=True, skills=(), ctx="business-init-acme", prose=(), es=False, trap=False, sim=False,
                     wrap=False, hdrs={}, outside=(), appendix=())


def exec_doc(waves, **o):
    """execute.md carrying the REAL marker lines of the 0.14.1 template, each one switchable."""
    p = {**EXEC_DEFAULTS, **o}
    ty, es = set(p["types"]), p["es"]
    L = []
    if p["trap"]:
        L += ["<!--", "Draft notes, not part of the protocol.", "## Ghost section", "### Wave W0 ghost", "-->"]
    L += ["# Acme — Execution protocol (Billing revamp)", ""]
    if p["protocol"]:
        L += [f"> **Protocol:** adcm-toolkits {p['protocol']}", ""]
    L += ["> **What this is.** The operating manual of the build. It defines HOW the catalog in",
          "> `detailed-plan.md` gets executed: wave sessions, self-verified loops with the DoD-auto",
          "> as the exit criterion. The copy-paste prompts per wave are at the end (§7).", ""]
    if p["prose"]:
        L += [*p["prose"], ""]
    L += ["## 1. Principles", "",
          "1. **Session = one wave: 1–4 coupled tasks, one branch/MR per wave.**",
          "2. **The loop ends by DoD, not by fatigue.** Max 5 rounds; the same failure 3 times → stop.",
          "7. **Agent budget 20 with fixed roles.** The main session ORCHESTRATES and integrates."]
    if "researcher" in ty:
        L.append("   `opus` agents investigate (`adcm-toolkits:researcher`, called with `model: opus`),")
    if "auditor" in ty:
        L.append("   review regression and verify (`adcm-toolkits:auditor`) (quota 10 per session);")
    if "executor" in ty:
        L.append("   `sonnet` agents (`adcm-toolkits:executor`) implement NO-gate tasks from briefs.")
    if "courier" in ty:
        L.append("   One delivery `adcm-toolkits:courier` per batch, `sonnet` always.")
    if p["rule"] is True:
        L.append(RULE_ES if es else RULE_EN)
    elif p["rule"]:
        L.append(p["rule"])
    if p["sim"]:
        L += ["11. **SIMPLIFY — one pass per wave** with the packaged `code-simplifier:code-simplifier`."]
    L += ["", "## 2. Canonical wave-prompt template", "", "```text", *opening(p), "",
          "# GOAL — Wave <Wx>: <titles>", "- [ ] <command> → <expected result>", "",
          "# WORKFLOW (fan-out)", "## Executor brief — <ID>", "<TASK · FILES · SKILLS · DELIVERABLE>",
          "## Simplifier brief", "<one per wave, ≤20 lines>", "```", ""]
    nxt = f"**{p['nxt']}:**" if p["nxt"] else "next command"
    blk_ = f"**{p['blk']}**" if p["blk"] else "blocked"
    L += ["## 2b. Doc-sync at close (mandatory)", "", "Closing a wave updates ALL plan docs in ONE pass:", "",
          f"1. **`task.md`** — logbook entry (date of execution · branch/MR · tasks closed · {blk_} ·",
          f"   files touched · notes · wall clock · agents used n/20 · escalations · {nxt} exact next",
          "   command/prompt, or \"wave closed\") AND the wave-map status flip.",
          "2. **`execute.md` §7** — this wave's prompt header flip.", "",
          "## 3. Delivery / merge policy", "", "| Wave type | Delivery |", "|---|---|",
          "| NO-gate | commit without push for review |", ""]
    s4 = "The resuming session runs `python3 docs/scripts/status_digest.py --brain docs`" if p["digest"] is True \
        else "The resuming session reads the logbook"
    if p["last_log"] == "s4":
        s4 += " (LAST LOG gives the `[PARTIAL]` entry's next/blocked/agents)"
    L += ["## 4. Checkpoint / resume", "",
          "If a session dies mid-wave: partial state lives in the wave branch and a `[PARTIAL]` entry.",
          s4 + ".", "",
          "## 5. Wave map (identity; fine ORDER is set by task.md)", "",
          "| Wave | Tasks | Gate | Skills to load | Base branch | Depends on |", "|---|---|---|---|---|---|"]
    for i, (w, _) in enumerate(waves):
        L.append(f"| **{w}** | T-{w}-1 | — | business-init-acme | main | {waves[i - 1][0] if i else '—'} |")
    L += ["", "## 6. Attack checklists (adversarial verification per gate)", "",
          "- **W1**: tenant escapes, rounding drift.", *p["outside"], "",
          "## 7. Wave prompts (instantiated, copy-paste)", "",
          "> Each wave header carries a status marker; the canonical status is the task.md wave map.", ""]
    for i, (w, g) in enumerate(waves):
        L += [p["hdrs"].get(w) or f"### {'Ola' if es else 'Wave'} {w} — {HDR[g]}", "", "```text", *opening(p, "s7"), "",
              f"# GOAL — Wave {w}: Invoices", "- [ ] pytest -q → exit 0", "",
              "# WORKFLOW (fan-out)", f"## Executor brief — T-{w}-1", f"- TASK: T-{w}-1 — Round invoices",
              "- FILES: src/invoice.py — rounding"]
        if w in p["skills"]:
            L.append(f"- SKILLS: {p['ctx']}")
        L += ["- DOD-SLICE: pytest -q → exit 0", "", "## Simplifier brief", "- FILES: src/invoice.py"]
        if p["trap"] and i == 1:
            L.append("### Wave W9 (quoted inside a fence)")
        L += ["```", ""]
    if p["appendix"]:
        L += list(p["appendix"])
    return "\n".join(L)


def task_doc(waves, pending="canonical", nxt="Next", n_log=2, es=False):
    L = ["# Acme — Task tracker: Billing revamp", "", "> Execution state of the billing revamp.", "",
         "## Mapa de olas" if es else "## Wave map", "",
         "| Estado | Ola | Tareas | Gate | Skills | Rama | Depende de |" if es else
         "| Status | Wave | Tasks | Gate | Skills to load | Base branch | Depends on |",
         "|---|---|---|---|---|---|---|"]
    for i, (w, g) in enumerate(waves):
        L.append(f"| {g} | **{w}** | T-{w}-1 | — | business-init-acme | main | {waves[i - 1][0] if i else '—'} |")
    L += ["", "Status legend: ☐ pending · 🔄 in progress · ⛔ blocked (DoD-human pending) · ✅ done.", ""]
    if pending == "canonical":
        L += ["## DoD-human pending", "", "| # | Item | Owner | Blocks | Due |", "|---|---|---|---|---|",
              "| 1 | Approve the invoice template | A | W2 | — |", ""]
    elif pending:
        L += [f"## {pending}", "", "| # | Qué | Bloquea | Límite |", "|---|---|---|---|",
              "| 1 | Aprobar la plantilla de factura | W2 | — |", ""]
    L += ["## Weekly burn", "", "| Week | Planned | Closed | Burn | Action |", "|---|---|---|---|---|", "",
          "## Bitácora" if es else "## Logbook", "", "Append one entry per wave session.", ""]
    for i in range(1, n_log + 1):
        L += [f"### 2026-01-0{i} — {'Ola' if es else 'Wave'} W{i}", "",
              f"- **Branch/MR:** feat/acme-w{i} (https://example.com/acme/mr/{i})",
              f"- **Tasks closed:** T-W{i}-1 · **Blocked:** none",
              f"- **{nxt}:** run the next prompt" if nxt else "- **Notes/decisions:** none", ""]
    return "\n".join(L)


def fresh(ctx, name, waves=W3, ex=None, tk=None, rows=None, under="", **kw):
    """A fully up-to-date 0.14.1 brain: SKILLS on every pending wave unless `skills` says otherwise."""
    ex = dict(ex or {})
    ex.setdefault("skills", {w for w, g in waves if g not in DONE})
    return ctx.brain(name, execute=exec_doc(waves, **ex), task=task_doc(waves, **(tk or {})),
                     art=ok_rows(ids=[w for w, _ in waves]) if rows is None else rows, under=under, **kw)


LEGACY_FLAGS = dict(protocol=None, types=(), digest=False, last_log=None, nxt=None, blk=None, rule=False)


def legacy_08(ctx, name, under="", scripts="none"):
    waves = [("W1", "☐"), ("W2", "☐")]
    ex = exec_doc(waves, prose=["Built with adcm-toolkits 0.8.0 (see the plugin changelog)."], **LEGACY_FLAGS)
    return ctx.brain(name, execute=ex, task=task_doc(waves, pending=None, nxt=None, n_log=1),
                     art=[art("plans.html"), art("prompts.html", "")], scripts=scripts, docs="en", under=under)


def module_files(prefix):
    waves = [("W1", "☐")]
    return {prefix + "/execute.md": exec_doc(waves, **LEGACY_FLAGS),
            prefix + "/task.md": task_doc(waves, pending=None, nxt=None, n_log=1),
            prefix + "/artifacts.json": art_json([art("plans.html")])}


def count_h2(text):
    """`## ` headings outside fences and HTML comments, plus the naive count for comparison."""
    real = naive = 0
    fence = comment = False
    for ln in text.split("\n"):
        s = ln.strip()
        if ln.startswith("## "):
            naive += 1
            real += not (fence or comment)
        if s.startswith("```"):
            fence = not fence
        if not fence:
            if s.startswith("<!--") and "-->" not in s:
                comment = True
            elif "-->" in s:
                comment = False
    return real, naive


MARKERS_ON = {"digest_line": True, "last_log_s4": True, "next_label": True, "blocked_label": True,
              "model_rule": True, "protocol_line": True}


def markers_check(t, d, **want):
    m = blk(d, "execute", "markers") or {}
    types = m.get("types") or {}
    t.eq({k: bool(types.get(k)) for k in TYPES}, {k: want.get("types", {}).get(k, True) for k in TYPES}, "markers.types")
    for k, v in MARKERS_ON.items():
        t.eq(m.get(k), want.get(k, v), f"markers.{k}")


# ------------------------------------------------------------------ cases
def case_fresh_0141_up_to_date(ctx, t):
    b = fresh(ctx, "brain")
    d = both(ctx, t, b, "--invariants")
    if d:
        t.eq(d.get("needed"), [], "needed")
        t.eq(d.get("module"), None, "module")
        t.eq(dig(d, "protocol", "found"), VERSION, "protocol.found")
        t.eq(dig(d, "protocol", "inferred"), "0.14", "protocol.inferred")
        t.eq([blk(d, "scripts", k) for k in ("state", "missing", "outdated", "copied")], ["ok", [], [], []], "scripts block")
        t.eq([blk(d, "artifacts", k) for k in ("state", "total", "rows_without_regen")], ["ok", 2, []], "artifacts block")
        t.eq(blk(d, "execute", "state"), "ok", "execute.state")
        markers_check(t, d)
        t.eq(blk(d, "execute", "markers", "skills_lines"), {"have": 2, "pending_waves": 2}, "skills_lines (the done wave needs none)")
        t.eq([blk(d, "task", k) for k in ("state", "shape", "last_entry_has_next")], ["ok", "canonical", True], "task block")
        t.has(blk(d, "task", "heading") or "", "DoD-human pending", "task.heading")
        t.eq(blk(d, "modules"), [], "modules")
        inv = d.get("invariants")
        four = ("s7_wave_headers", "h2_sections", "logbook_entries", "wave_rows")
        t.ok(isinstance(inv, dict) and sorted(inv) == sorted(four) and all(isinstance(v, int) for v in inv.values()),
             f"--invariants fills exactly the four identity counters, got {inv!r}")
        t.ok(isinstance(dig(d, "stats", "execute_lines"), int), f"stats.execute_lines is an int, got {d.get('stats')!r}")
    d = ctx.run(b, "--json").data
    t.eq((d or {}).get("invariants", "absent"), None, "invariants is null without --invariants")
    flat = os.path.join(ctx.root, "flat")
    os.makedirs(flat)
    shutil.copy(ctx.checker, os.path.join(flat, "renovate_check.py"))
    for n in FILES:
        ctx.write("flat/" + n, tpl(n))
    r = ctx.run(b, skill=False, checker=os.path.join(flat, "renovate_check.py"))
    t.eq(r.rc, 0, "without --skill-dir the templates are the checker's own directory (flat layout)")


def case_legacy_08(ctx, t):
    b = legacy_08(ctx, "legacy")
    d = both(ctx, t, b, rc=1)
    if not d:
        return
    t.eq(d.get("needed"), ["scripts", "artifacts", "execute", "task"], "needed")
    t.eq(dig(d, "protocol", "found"), None, "protocol.found (prose 'adcm-toolkits 0.8.0' is not a Protocol line)")
    t.eq(dig(d, "protocol", "inferred"), "0.8", "protocol.inferred")
    t.eq(blk(d, "scripts", "state"), "missing", "scripts.state")
    t.eq(sorted(blk(d, "scripts", "missing") or []), sorted(FILES), "scripts.missing lists the six files")
    t.eq([blk(d, "scripts", "outdated"), blk(d, "scripts", "copied")], [[], []], "scripts outdated/copied")
    t.eq([blk(d, "artifacts", "state"), blk(d, "artifacts", "total")], ["missing", 2], "artifacts state/total")
    rows = [{"file": "plans.html", "suggest": plans_cmd("en")},
            {"file": "prompts.html", "suggest": prompts_cmd("en", ("W1", "W2"))}]
    t.eq(blk(d, "artifacts", "rows_without_regen"), rows, "rows_without_regen (absent and empty regen; --init in wave-map order)")
    for r in rows:
        t.ok(anyline(d.get("text"), r["suggest"]), f"plain output prints the suggestion for {r['file']}")
    t.eq(blk(d, "execute", "state"), "missing", "execute.state")
    markers_check(t, d, types={k: False for k in TYPES}, **{k: False for k in MARKERS_ON})
    t.eq(blk(d, "execute", "markers", "skills_lines"), {"have": 0, "pending_waves": 2}, "skills_lines")
    t.eq([blk(d, "task", k) for k in ("state", "shape", "heading", "last_entry_has_next")],
         ["missing", "missing", None, False], "task block")


def case_legacy_011(ctx, t):
    waves = [("W1", "✅"), ("W2", "☐"), ("W3", "☐")]
    ex = exec_doc(waves, sim=True, prose=["Prompts page: `python3 docs/scripts/prompts-regen.py --init W1,W2,W3 prompts.html`."],
                  **LEGACY_FLAGS)
    rows = [art("plans.html"), art("prompts.html", "python3 .build/render-prompts.py --titles prompts-titles.json --out prompts.html")]
    scripts = {"prompts-regen.py": custom("prompts-regen.py"), "prompts-html.tmpl": tpl("prompts-html.tmpl")}
    b = ctx.brain("legacy", execute=ex, task=task_doc(waves, pending="Pendientes humanos (DoD-human)", nxt=None, n_log=1),
                  art=rows, scripts=scripts, docs="es")
    d = both(ctx, t, b, rc=1)
    if d:
        t.eq(d.get("needed"), ["scripts", "artifacts", "execute"], "needed (task is ok in its legacy shape)")
        t.eq(dig(d, "protocol", "found"), None, "protocol.found")
        t.eq(dig(d, "protocol", "inferred"), "0.11", "protocol.inferred (code-simplifier / prompts-regen mentioned)")
        t.eq(blk(d, "scripts", "outdated"), ["prompts-regen.py"], "scripts.outdated (same file name, different sha256)")
        t.eq(sorted(blk(d, "scripts", "missing") or []),
             sorted(["status_digest.py", "status-brief.md", "plans-regen.py", "plans-html.tmpl"]), "scripts.missing")
        t.eq(blk(d, "scripts", "state"), "missing", "scripts.state (missing wins; outdated is informational)")
        t.eq([blk(d, "artifacts", "state"), blk(d, "artifacts", "total")], ["missing", 2], "artifacts state/total")
        t.eq(blk(d, "artifacts", "rows_without_regen"), [{"file": "plans.html", "suggest": plans_cmd("es")}],
             "rows_without_regen (a regen of another shape counts ok; Spanish docs set -> --lang es)")
        t.eq(blk(d, "execute", "state"), "missing", "execute.state")
        t.eq([blk(d, "task", "state"), blk(d, "task", "shape")], ["ok", "legacy"], "task state/shape")
        t.has(blk(d, "task", "heading") or "", "Pendientes humanos", "task.heading")
    # Only a differing copy: informational, never needed; --force-outdated still overwrites it.
    t.tag = "(only outdated) "
    only = {n: tpl(n) for n in FILES}
    only["prompts-regen.py"] = custom("prompts-regen.py")
    a = fresh(ctx, "only-outdated", under="a", scripts=only)
    b = fresh(ctx, "only-outdated", under="b", scripts=only)
    d = both(ctx, t, a)
    if d:
        t.eq(d.get("needed"), [], "needed (a customised copy never puts scripts in needed)")
        t.eq([blk(d, "scripts", k) for k in ("state", "missing", "outdated")], ["ok", [], ["prompts-regen.py"]], "scripts block")
        t.ok("SCRIPTS ok · custom: prompts-regen.py" in (d.get("text") or []), "plain line 'SCRIPTS ok · custom: prompts-regen.py'")
    d = both(ctx, t, a, "--copy-scripts", "--force-outdated", twin=b, ro=False)
    if d:
        t.eq(blk(d, "scripts", "copied"), ["prompts-regen.py"], "scripts.copied (--force-outdated still overwrites)")
        t.eq(read(os.path.join(b, "scripts", "prompts-regen.py")), tpl("prompts-regen.py"), "the copy now equals the template")
        t.eq([blk(d, "scripts", "state"), blk(d, "scripts", "outdated")], ["ok", []], "scripts block after the force")
    # 0.13 shape: digest line + LAST LOG, no role types, no Protocol line.
    t.tag = "(0.13) "
    ex = exec_doc(waves, sim=True, **{**LEGACY_FLAGS, "digest": True, "last_log": "s4"})
    b = ctx.brain("legacy-013", execute=ex, task=task_doc(waves), art=ok_rows(ids=["W1", "W2", "W3"]))
    d = both(ctx, t, b, rc=1)
    if d:
        t.eq(dig(d, "protocol", "inferred"), "0.13", "protocol.inferred")
        t.eq(blk(d, "execute", "state"), "partial", "execute.state")
        markers_check(t, d, types={k: False for k in TYPES}, next_label=False, blocked_label=False,
                      model_rule=False, protocol_line=False)
        t.eq(d.get("needed"), ["execute"], "needed")


def case_skills_partial(ctx, t):
    def go(tag, waves, ex):
        """One 0.14.1 brain with exactly one thing wrong in execute.md: needed == [execute], partial."""
        t.tag = f"({tag}) "
        d = both(ctx, t, fresh(ctx, "b-" + re.sub(r"\W+", "-", tag), waves, ex=ex), rc=1)
        if d:
            t.eq(d.get("needed"), ["execute"], "needed")
            t.eq(blk(d, "execute", "state"), "partial", "execute.state")
        return d

    d = go("1 of 2 pending", W3, {"skills": {"W2"}})
    if d:
        t.eq(blk(d, "execute", "markers", "skills_lines"), {"have": 1, "pending_waves": 2}, "skills_lines")
        markers_check(t, d)
    d = go("done wave only", W3, {"skills": {"W1"}})
    if d:
        t.eq(blk(d, "execute", "markers", "skills_lines"), {"have": 0, "pending_waves": 2},
             "skills_lines (a SKILLS line on a done wave does not count)")
    five = [("W1", "✅"), ("W2", "🔀"), ("W3", "⛔"), ("W4", "⏸"), ("W5", "🔄")]
    d = go("glyphs", five, {"skills": {"W3", "W4"}})
    if d:
        t.eq(blk(d, "execute", "markers", "skills_lines"), {"have": 2, "pending_waves": 3},
             "skills_lines (⛔ ⏸ 🔄 are pending; ✅ 🔀 are not)")
    d = go("no protocol line", W3, {"protocol": None})
    if d:
        t.eq(dig(d, "protocol", "found"), None, "protocol.found")
        t.eq(dig(d, "protocol", "inferred"), "0.14", "protocol.inferred (role types present)")
        markers_check(t, d, protocol_line=False)
    d = go("types missing", W3, {"types": ("executor", "auditor", "researcher")})
    if d:
        markers_check(t, d, types={"courier": False, "digester": False})
    d = go("LAST LOG outside s4", W3, {"last_log": "s2"})
    if d:
        markers_check(t, d, last_log_s4=False)


def case_modules(ctx, t):
    b = fresh(ctx, "mods", extra=module_files("modules/billing"))
    d = both(ctx, t, b)
    if d:
        t.eq([d.get("needed"), blk(d, "modules")], [[], []], "root only without --all-modules (needed, modules)")
    d = both(ctx, t, b, "--all-modules", rc=1)
    if d:
        t.eq(d.get("needed"), ["modules"], "needed (root is up to date)")
        t.eq(blk(d, "modules"), [{"module": "modules/billing", "needed": ["artifacts", "execute", "task"]}], "modules")
        t.eq(blk(d, "execute", "state"), "ok", "root execute.state")
        t.ok(anyline((d.get("text") or [])[:-1], "billing"), "plain output names the module")
    d = both(ctx, t, b, "--module", "modules/billing", rc=1)
    if d:
        t.eq(d.get("module"), "modules/billing", "module")
        t.eq(d.get("needed"), ["artifacts", "execute", "task"], "needed (module run)")
        t.eq(blk(d, "scripts", "state"), "n/a", "scripts.state (scripts live in the root only)")


def case_regen_none_ok(ctx, t):
    b = fresh(ctx, "none-ok", rows=[art("plans.html", "none"), art("prompts.html", "python3 .build/x.py")])
    d = both(ctx, t, b)
    if d:
        t.eq([blk(d, "artifacts", k) for k in ("state", "total", "rows_without_regen")], ["ok", 2, []], "artifacts block")
        t.eq(d.get("needed"), [], "needed")
    b = fresh(ctx, "other-html", rows=[art("plans.html", plans_cmd("en")), art("ui-mockup.html")])
    d = both(ctx, t, b, rc=1)
    if d:
        t.eq(blk(d, "artifacts", "rows_without_regen"), [{"file": "ui-mockup.html", "suggest": "none"}],
             "an html without a known source suggests 'none'")
        t.eq(d.get("needed"), ["artifacts"], "needed")


def case_copy_scripts(ctx, t):
    def files_ok(root, names=FILES):
        return all(read(os.path.join(root, "scripts", n)) == tpl(n) for n in names)

    a, b = legacy_08(ctx, "brain", under="a"), legacy_08(ctx, "brain", under="b")
    d = both(ctx, t, a, "--copy-scripts", rc=1, twin=b, ro=False)
    if d:
        t.eq(sorted(blk(d, "scripts", "copied") or []), sorted(FILES), "scripts.copied lists the six files")
        t.ok(files_ok(b) and files_ok(a), "the six files appear with the template content")
        t.eq(d.get("needed"), ["artifacts", "execute", "task"], "needed after the copy")
    d = both(ctx, t, b, rc=1)
    if d:
        t.eq([blk(d, "scripts", "state"), blk(d, "scripts", "copied")], ["ok", []], "second run: scripts ok, nothing copied")
        t.ok("scripts" not in (d.get("needed") or []), "second run: scripts not needed")
    mine = custom("prompts-regen.py")
    keep = {"prompts-regen.py": mine, "custom-builder.py": "print('mine')\n"}
    c1 = legacy_08(ctx, "brain", under="c1", scripts=keep)
    c2 = legacy_08(ctx, "brain", under="c2", scripts=keep)
    t.tag = "(outdated) "
    d = both(ctx, t, c1, "--copy-scripts", rc=1, twin=c2, ro=False)
    if d:
        rest = [n for n in FILES if n != "prompts-regen.py"]
        t.eq(sorted(blk(d, "scripts", "copied") or []), sorted(rest), "scripts.copied (the five missing ones only)")
        t.eq(blk(d, "scripts", "outdated"), ["prompts-regen.py"], "scripts.outdated")
        t.eq(blk(d, "scripts", "state"), "ok", "scripts.state (nothing missing; the differing copy is informational)")
        t.eq(d.get("needed"), ["artifacts", "execute", "task"], "needed (a differing copy never puts scripts in needed)")
        t.eq(read(os.path.join(c2, "scripts", "prompts-regen.py")), mine, "the differing copy is NOT overwritten")
        t.eq(read(os.path.join(c2, "scripts", "custom-builder.py")), keep["custom-builder.py"], "other scripts/ files untouched")
        t.ok(files_ok(c2, rest), "the five missing files carry the template content")
    t.tag = "(force) "
    d = both(ctx, t, c1, "--copy-scripts", "--force-outdated", rc=1, twin=c2, ro=False)
    if d:
        t.eq(blk(d, "scripts", "copied"), ["prompts-regen.py"], "scripts.copied (the overwritten one)")
        t.eq(read(os.path.join(c2, "scripts", "prompts-regen.py")), tpl("prompts-regen.py"), "--force-outdated overwrites")
        t.eq(read(os.path.join(c2, "scripts", "custom-builder.py")), keep["custom-builder.py"], "other scripts/ files untouched")
        t.eq([blk(d, "scripts", "state"), blk(d, "scripts", "outdated")], ["ok", []], "scripts ok after the force")


def case_context_names(ctx, t):
    cases = [("plugin-prefixed", "acme-plataforma:code-project-context-acme-web", {}, {}, "acme-plataforma"),
             ("bare", "code-project-context-acme-web", {}, {}, None),
             ("spanish line", "acme-plataforma:code-project-context-acme-web", ES_EX, ES_TK, "acme-plataforma")]
    for tag, name, ex, tk, plugin in cases:
        t.tag = f"({tag}) "
        d = both(ctx, t, fresh(ctx, "c-" + tag.replace(" ", "-"), ex=dict(ex, ctx=name), tk=tk))
        if d:
            t.eq([blk(d, "context", "state"), blk(d, "context", "skill"), blk(d, "context", "plugin")],
                 ["ok", "code-project-context-acme-web", plugin], "context state/skill/plugin")
            t.eq(blk(d, "context", "last_scanned"), None, "context.last_scanned (no plugin cache in the temp HOME)")
            t.ok(anyline(d.get("text"), "ok (code-project-context-acme-web)"), "plain context line 'ok (<skill>)'")
            t.eq(d.get("needed"), [], "context never enters needed")
    t.tag = "(business only) "
    d = both(ctx, t, fresh(ctx, "c-business", ex={"ctx": "business-init-acme"}))
    if d:
        t.eq([blk(d, "context", k) for k in ("state", "skill", "plugin", "last_scanned")], ["n/a", None, None, None],
             "context block")
        t.ok(anyline(d.get("text"), "n/a (business-context only)"), "plain context line 'n/a (business-context only)'")


def case_invariants_stable(ctx, t):
    ex = exec_doc(W3, skills={"W2", "W3"}, trap=True)
    b = ctx.brain("inv", execute=ex, task=task_doc(W3), art=ok_rows())
    real, naive = count_h2(ex)
    t.ok(naive > real, "the fixture exercises the fence/comment traps")
    d = both(ctx, t, b, "--invariants")
    runs = [ctx.run(b, "--json", "--invariants") for _ in range(2)] + [ctx.run(b, "--invariants") for _ in range(2)]
    t.eq(runs[0].out, runs[1].out, "two --json runs are byte-identical")
    t.eq(runs[2].out, runs[3].out, "two plain runs are byte-identical")
    want = {"s7_wave_headers": 3, "h2_sections": real, "logbook_entries": 2, "wave_rows": 3}
    lines = len(ex.splitlines())
    t.eq((d or {}).get("invariants"), want, "invariants (fenced '###'/'##' lines and HTML comments are not counted)")
    t.eq(runs[0].data and runs[0].data.get("invariants"), want, "invariants (second --json run)")
    t.eq(dig(runs[0].data, "stats"), {"execute_lines": lines}, "stats (the line count is informational, not an identity counter)")
    line = f"INVARIANTS s7_wave_headers=3 h2_sections={real} logbook_entries=2 wave_rows=3 · lines={lines}"
    t.ok(line in runs[2].lines, f"plain line {line!r}")


def case_version_consistency(ctx, t):
    plugin, d = None, HERE
    for _ in range(6):
        cand = os.path.join(d, ".claude-plugin", "plugin.json")
        if os.path.isfile(cand):
            plugin = cand
            break
        d = os.path.dirname(d)
    if not plugin:
        raise Skip("no .claude-plugin/plugin.json above the selftest")
    try:
        v_plugin = json.loads(read(plugin) or "{}").get("version")
    except ValueError:
        v_plugin = None
    m = re.search(r"^>\s*\*\*Protocol:\*\*\s*adcm-toolkits\s+(\S+)\s*$", read(os.path.join(HERE, "execute.md.tmpl")) or "", re.M)
    v_tmpl = m.group(1) if m else None
    m = re.search(r"""^__version__\s*=\s*["']([^"']+)["']""", read(ctx.checker) or "", re.M)
    v_check = m.group(1) if m else None
    t.ok(v_tmpl is not None, "execute.md.tmpl has no '> **Protocol:** adcm-toolkits X.Y.Z' line")
    t.ok(v_check is not None, "renovate_check.py has no __version__")
    t.eq([v_plugin, v_tmpl, v_check], [RELEASE] * 3, f"plugin.json == execute.md.tmpl Protocol line == __version__ == {RELEASE}")


def case_usage_error(ctx, t):
    b = fresh(ctx, "ok")
    for flags, what in ((["--bogus"], "unknown flag"),
                        (["--module", "modules/billing", "--all-modules"], "--module with --all-modules"),
                        (["--module"], "--module without a value")):
        t.eq(ctx.run(b, *flags).rc, 64, f"{what} -> exit 64")
    t.eq(ctx.run(None).rc, 64, "no --brain -> exit 64")


def case_no_execute(ctx, t):
    both(ctx, t, ctx.brain("no-exec", task=task_doc(W3), scripts="none"), rc=2)
    t.tag = "(brain dir missing) "
    both(ctx, t, os.path.join(ctx.root, "nowhere"), rc=2)
    t.tag = "(execute.md unreadable) "
    both(ctx, t, ctx.brain("exec-dir", task=task_doc(W3), scripts="none", extra={"execute.md/readme.txt": "x\n"}), rc=2)


def case_spanish_markers(ctx, t):
    heading = "⛔ Bloqueantes abiertos — DoD-human de A"
    d = both(ctx, t, fresh(ctx, "es", ex=ES_EX, tk=dict(ES_TK, pending=heading), docs="es", rows=ok_rows("es")))
    if d:
        markers_check(t, d)
        t.eq(blk(d, "execute", "markers", "skills_lines"), {"have": 2, "pending_waves": 2}, "skills_lines ('### Ola' headers)")
        t.eq([blk(d, "task", k) for k in ("state", "shape", "last_entry_has_next")], ["ok", "legacy", True], "task block")
        t.has(blk(d, "task", "heading") or "", "Bloqueantes abiertos", "task.heading")
        t.eq(d.get("needed"), [], "needed (legacy pending section is not migrated)")
    for tag, pend, state, shape in (("open questions", "Open questions", "ok", "legacy"),
                                    ("pendientes", "Pendientes humanos", "ok", "legacy"),
                                    ("blockers", "Blockers", "ok", "legacy"),
                                    ("preguntas", "Preguntas abiertas", "ok", "legacy"),
                                    ("not an alias", "Notes", "missing", "missing")):
        t.tag = f"({tag}) "
        r = ctx.run(fresh(ctx, "al-" + tag.replace(" ", "-"), tk={"pending": pend}), "--json")
        t.eq([blk(r.data, "task", "state"), blk(r.data, "task", "shape")], [state, shape], "task state/shape")


def case_s7_header_prefixes(ctx, t):
    waves = [("W8", "✅"), ("W13", "⛔"), ("W18", "☐"), ("W2", "🔄")]
    hdrs = {"W8": "### ✅ DONE (28 ago) Ola W8 — Cimientos", "W13": "### ⛔ Ola W13 — x",
            "W18": "### ☐ Wave W18 — title", "W2": "### 🔄 Wave W2 (parcial)"}
    ex = {"hdrs": hdrs, "skills": {"W13", "W2"}, "outside": ["", "### Notes about the Wave W1 metrics"]}
    d = both(ctx, t, fresh(ctx, "prefixes", waves, ex=ex), "--invariants", rc=1)
    if d:
        t.eq(dig(d, "invariants", "s7_wave_headers"), 4,
             "s7_wave_headers (glyph/DONE prefixes count; '### Notes about the Wave W1 metrics' outside §7 does not)")
        t.eq(blk(d, "execute", "markers", "skills_lines"), {"have": 2, "pending_waves": 3}, "skills_lines (W8 is done)")
        t.eq(blk(d, "execute", "state"), "partial", "execute.state")
        t.eq(d.get("needed"), ["execute"], "needed")
        t.ok(anyline(d.get("text"), "skills 2/3"), "plain output shows 'skills 2/3'")
    t.tag = "(wrapped load line) "
    name = "acme-plataforma:code-project-context-acme-web"
    d = both(ctx, t, fresh(ctx, "wrapped", ex=dict(ES_EX, ctx=name, wrap=True), tk=ES_TK))
    if d:
        t.eq([blk(d, "context", "state"), blk(d, "context", "skill"), blk(d, "context", "plugin")],
             ["ok", "code-project-context-acme-web", "acme-plataforma"],
             "context across a line break after 'Carga el skill'")


def case_audit_round2(ctx, t):
    def one(tag, name, ex=None, flags=(), rc=1, waves=W3, **kw):
        t.tag = f"({tag}) "
        return both(ctx, t, fresh(ctx, name, waves, ex=ex, **kw), *flags, rc=rc)

    # (a) a Protocol line of another version is not the current one
    d = one("a protocol 0.13.0", "a", {"protocol": "0.13.0"})
    if d:
        t.eq(dig(d, "protocol", "found"), "0.13.0", "protocol.found")
        markers_check(t, d, protocol_line=False)
        t.eq([blk(d, "execute", "state"), d.get("needed")], ["partial", ["execute"]], "execute.state / needed")
        line = next((x for x in d.get("text") or [] if x.startswith("EXECUTE")), "")
        t.ok("protocol-line" in line and "0.13.0" in line, f"EXECUTE line names protocol-line and the found version, got {line!r}")
    # (b) the colon may sit inside the bold
    for i, label in enumerate(("Blocked:", "bloqueado:")):
        d = one(f"b {label}", f"b{i}", {"blk": label}, rc=0)
        if d:
            markers_check(t, d)
            t.eq(d.get("needed"), [], "needed")
    # (c) the digest call counts in section 2 only, not in a wave prompt
    d = one("c digest only in s7", "c", {"digest": "s7"})
    if d:
        markers_check(t, d, digest_line=False)
        t.eq(d.get("needed"), ["execute"], "needed")
    # (d) a heading after section 7 closes it
    ex = exec_doc(W3, skills={"W2", "W3"}, appendix=["## Appendix", "", "### Wave W9 — ☐", "", "Spare notes.", ""])
    t.tag = "(d appendix) "
    d = both(ctx, t, ctx.brain("d", execute=ex, task=task_doc(W3), art=ok_rows()), "--invariants")
    if d:
        t.eq(dig(d, "invariants", "s7_wave_headers"), 3, "s7_wave_headers (the Appendix '### Wave W9' is outside section 7)")
        t.eq(dig(d, "invariants", "h2_sections"), count_h2(ex)[0], "h2_sections (the Appendix is a section)")
        t.eq(blk(d, "execute", "markers", "skills_lines"), {"have": 2, "pending_waves": 2}, "skills_lines")
    # (e) a bold header; the wave-map glyph (pending) wins over the header's own marker
    d = one("e bold header", "e", {"hdrs": {"W2": "### **Wave W2** — ✅ DONE (2026-01-05)"}}, ("--invariants",), rc=0)
    if d:
        t.eq(dig(d, "invariants", "s7_wave_headers"), 3, "s7_wave_headers")
        t.eq(blk(d, "execute", "markers", "skills_lines"), {"have": 2, "pending_waves": 2}, "skills_lines (id W2, not 'W2**')")
    # (f) the model rule fallback needs the per-call wording
    for k, (tag, ex, want) in enumerate((("f es without por llamada", dict(ES_EX, rule=RULE_BAD_ES), False),
                                         ("f en without per-call", {"rule": RULE_BAD_EN}, False),
                                         ("f es with por llamada", dict(ES_EX), True))):
        d = one(tag, f"f{k}", ex, rc=0 if want else 1, tk=ES_TK if ex.get("es") else None)
        if d:
            markers_check(t, d, model_rule=want)
            t.eq(d.get("needed"), [] if want else ["execute"], "needed")
    # (g) no task.md: no wave ids, so no prompts-regen command
    t.tag = "(g no task.md) "
    b = ctx.brain("g", execute=exec_doc(W3, skills={"W2", "W3"}),
                  art=[art("plans.html", plans_cmd("en")), art("prompts.html")])
    d = both(ctx, t, b, rc=1)
    if d:
        t.eq(blk(d, "artifacts", "rows_without_regen"), [{"file": "prompts.html", "suggest": "blocked: needs wave ids"}],
             "suggest (never a command without ids)")
        t.ok("artifacts" in (d.get("needed") or []), "artifacts needed")
    # (h) a registry that is not a list of rows is a problem, not 'n/a'
    for k, (tag, raw) in enumerate((("h malformed", "{not json"),
                                    ("h object without rows", json.dumps({"plans.html": {"regen": "none"}})))):
        d = one(tag, f"h{k}", rc=1, extra={"artifacts.json": raw})
        if d:
            t.eq(blk(d, "artifacts", "state"), "unparsed", "artifacts.state")
            t.ok("artifacts" in (d.get("needed") or []), "artifacts needed")
    # (i) --copy-scripts never writes through a symlink
    t.tag = "(i symlink) "
    if hasattr(os, "symlink") and os.name != "nt":
        made = []
        for sub in ("s1", "s2"):
            b = legacy_08(ctx, "brain", under=sub, scripts="none")
            target = os.path.join(ctx.root, sub + "-outside", "target.txt")
            os.makedirs(os.path.join(b, "scripts"), exist_ok=True)
            os.makedirs(os.path.dirname(target), exist_ok=True)  # a write through the link would succeed
            try:
                os.symlink(target, os.path.join(b, "scripts", "prompts-regen.py"))
            except (OSError, NotImplementedError):
                break
            made.append((b, target))
        if len(made) == 2:
            d = both(ctx, t, made[0][0], "--copy-scripts", rc=1, twin=made[1][0], ro=False)
            b, target = made[1]
            link = os.path.join(b, "scripts", "prompts-regen.py")
            t.ok(os.path.islink(link) and not os.path.lexists(target), "the target behind the symlink was not written")
            if d:
                t.ok("prompts-regen.py" not in (blk(d, "scripts", "copied") or []), "scripts.copied does not list the symlink")
                t.ok(any("prompts-regen.py" in str(x) for x in blk(d, "scripts", "failed") or [])
                     or anyline(d.get("text"), "symlink"), "the symlink is reported (scripts.failed or a 'symlink' mention)")
                t.eq(sorted(blk(d, "scripts", "copied") or []), sorted(n for n in FILES if n != "prompts-regen.py"),
                     "the five regular missing files are still copied")
    # (j) the 40-line cap trims artifact rows and module lines before the INVARIANTS lines
    t.tag = "(j 12 modules) "
    mods = {}
    for i in range(1, 13):
        mods.update(module_files(f"modules/m{i:02d}"))
    d = both(ctx, t, fresh(ctx, "many", rows=[art(f"page{i}.html") for i in range(1, 11)], extra=mods),
             "--all-modules", "--invariants", rc=1)
    if d:
        txt = d.get("text") or []
        for i in range(1, 13):
            t.ok(any(x.startswith(f"INVARIANTS modules/m{i:02d}") for x in txt), f"INVARIANTS line of modules/m{i:02d} kept")
        t.ok(any(x.startswith("INVARIANTS s7_wave_headers=") for x in txt), "root INVARIANTS line kept")
        t.ok(any(x.startswith("ARTIFACTS") for x in txt) and any(x.startswith("MODULES") for x in txt),
             "ARTIFACTS and MODULES summaries kept")
        t.eq(len(blk(d, "modules") or []), 12, "json modules")
        t.ok(all(isinstance((m or {}).get("invariants"), dict) for m in blk(d, "modules") or []), "json modules[].invariants")
    # (k) a huge execute.md is refused with a reason
    t.tag = "(k 21 MB) "
    b = ctx.brain("k", task=task_doc(W3), scripts="none")
    with open(os.path.join(b, "execute.md"), "wb") as fh:
        fh.truncate(21 * 1024 * 1024)
    d = both(ctx, t, b, rc=2)
    if d:
        last = (d.get("text") or [""])[-1]
        t.ok("too large" in last, f"last line says 'too large', got {last[:80]!r}")


def sanitize(path):
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def note(line):
    """A memory file whose only interesting line is line 3."""
    return f"# Note\n\n{line}\n"


def memdir(ctx, container):
    return os.path.join(ctx.root, "cfg", "projects", sanitize(container), "memory")


def put_mem(ctx, container, files):
    d = memdir(ctx, container)
    for n, body in files.items():
        put(os.path.join(d, n), body)
    return d


def container_brain(ctx, name, layout="ai/ai-brain", **kw):
    """An up-to-date brain at <root>/<name>/<layout>; returns (brain, container)."""
    under, leaf = os.path.split(layout)
    return fresh(ctx, leaf, under=(name + "/" + under).rstrip("/"), **kw), os.path.join(ctx.root, name)


def rules_of(d):
    return blk(d, "rules") or {}


def found(d):
    return sorted((f.get("file"), f.get("id"), f.get("severity")) for f in rules_of(d).get("findings") or [])


def rules_lines(d):
    """(the RULES summary line, the indented finding lines right after it, the '… +k more' line or None)."""
    txt = d.get("text") or []
    i = next((k for k, x in enumerate(txt) if x.startswith("RULES ")), None)
    if i is None:
        return None, [], None
    det = []
    for x in txt[i + 1:]:
        if re.match(r"  \S+:\d+ [a-z][a-z-]+ — ", x):
            det.append(x)
        else:
            break
    more = txt[i + 1 + len(det)] if i + 1 + len(det) < len(txt) and txt[i + 1 + len(det)].startswith("  … +") else None
    return txt[i], det, more


STALE16 = {  # file -> (stale line, id, severity); every stale line sits on line 3 of its file
    "version-plain.md": ("The brain follows adcm-toolkits 0.8.0 for every execution.", "old-version", "fix"),
    "version-bold.md": ("Skill execution-prompt-architect **0.8.0** is the standard here.", "old-version", "fix"),
    "version-protocolo.md": ("Seguimos el protocolo 0.11.0 para las olas.", "old-version", "fix"),
    "roles-old.md": ("`opus` ejecuta ⚠gates · `sonnet` implementa", "roles-old", "fix"),
    "prompts-only.md": ("Regenerate the prompts page with prompts-regen.py after each wave.", "prompts-only-regen", "review"),
    "plans-by-hand.md": ("plans.html se actualiza a mano cada cierre.", "plans-by-hand", "review"),
    "guard-main.md": ("El guard solo cuenta el texto principal del mensaje final.", "guard-main-only", "review"),
    "courier-gp.md": ("Launch general-purpose for the courier close of every wave.", "courier-general-purpose", "fix"),
    "reads-task.md": ("Al arrancar la sesión, lee task.md completo para retomar el trabajo.", "reads-task-md", "fix"),
    "courier-missing.md": ("El subagente `artifact-courier` no existe en este proyecto.", "courier-missing", "fix"),
    "media.md": ("El courier envía las capturas con SendUserFile al terminar.", "subagent-sends-media", "fix"),
}


def case_rules_memory(ctx, t):
    b, c = container_brain(ctx, "mem")
    files = {n: note(v[0]) for n, v in STALE16.items()}
    files["no-existe-bare.md"] = note("El archivo de configuración no existe todavía; hay que crearlo.")
    files["MEMORY.md"] = ("# Memory index\n\n"
                          "- [Plain notes](version-plain.md) — follows adcm-toolkits 0.11.0 for every brain\n"
                          "- [adcm-toolkits 0.8.0 notes](roles-old.md) — neutral hook text\n")
    md = put_mem(ctx, c, files)
    before = snap(os.path.join(ctx.root, "cfg"))
    d = both(ctx, t, b, rc=1)
    if d:
        want = sorted([(n, v[1], v[2]) for n, v in STALE16.items()] + [("MEMORY.md", "old-version", "fix")])
        t.eq(found(d), want, "findings (file, id, severity): 9 fix + 3 review; 'no existe' alone and the MEMORY.md title are not findings")
        t.eq(d.get("needed"), ["rules"], "needed")
        r = rules_of(d)
        t.eq(r.get("state"), "needed", "rules.state")
        t.eq(os.path.realpath(r.get("memory_dir") or ""), os.path.realpath(md), "rules.memory_dir")
        t.eq(r.get("files_scanned"), len(files), "rules.files_scanned (every .md of the memory dir, MEMORY.md included)")
        for f in r.get("findings") or []:
            want_line = 3 if f.get("file") != "prompts-only.md" else f.get("line")
            t.ok(f.get("line") == want_line and isinstance(f.get("line"), int) and f["line"] >= 1,
                 f"{f.get('file')}: line {f.get('line')!r}, want {want_line}")
            t.ok(isinstance(f.get("snippet"), str) and f["snippet"] and isinstance(f.get("correction"), str) and f["correction"],
                 f"{f.get('file')}: snippet and correction are non-empty strings")
        head, det, more = rules_lines(d)
        t.ok(head is not None and head.startswith("RULES needed · memory ") and sanitize(c) in head
             and head.endswith(" · claude.md 0 · findings 12 (fix 9 · review 3)"), f"RULES line, got {head!r}")
        t.eq(len(det), 6, "six detail lines '  <file>:<line> <id> — <snippet>'")
        t.eq(more, "  … +6 more (use --json)", "overflow line")
        t.ok(all(len(x.split(" — ", 1)[1]) <= 60 for x in det), "detail snippets are at most 60 characters")
    t.eq(snap(os.path.join(ctx.root, "cfg")), before, "the memory dir is never written")
    # only `review` findings: listed, but rules stays out of needed and the exit is 0
    t.tag = "(review only) "
    b2, c2 = container_brain(ctx, "mem-review")
    put_mem(ctx, c2, {n: note(v[0]) for n, v in STALE16.items() if v[2] == "review"})
    d = both(ctx, t, b2)
    if d:
        t.eq([rules_of(d).get("state"), d.get("needed")], ["ok", []], "rules.state ok and needed empty with review findings only")
        t.eq(sorted(s for _, _, s in found(d)), ["review"] * 3, "three review findings")
        head, _, _ = rules_lines(d)
        t.ok((head or "").startswith("RULES ok · memory ") and (head or "").endswith("findings 3 (fix 0 · review 3)"),
             f"RULES line, got {head!r}")


def case_rules_whitelist_idempotent(ctx, t):
    b, c = container_brain(ctx, "white")
    superseded = ("# Old note\n\nFollow adcm-toolkits 0.8.0 for planning sessions.\n\n"
                  "**Superseded (protocol 0.14.2, 2026-10-03):** the current protocol applies "
                  "(line 3: \"Follow adcm-toolkits 0.8.0 for planning sessions.\")\n")
    files = {
        "current.md": note("Migrated the brain a 0.8.0 → 0.14.1 last week; protocolo 0.11.0 ya no es el vigente."),
        "regen-none.md": note("plans.html se mantiene a mano; `regen: none` por un bug del generador."),
        "renovate-notes.md": "# Renovate\n\nadcm-toolkits 0.8.0 stays in this log.\n\n`opus` ejecuta ⚠gates · `sonnet` implementa\n",
        "superseded.md": superseded,
        "html-note.md": note("<!-- renovate: adcm-toolkits 0.8.0 kept for history -->"),
        "MEMORY.md": ("# Memory index\n\n- [Old](superseded.md) — adcm-toolkits 0.8.0 rules · ⚠ superseded (protocol 0.14.2)\n"
                      "- [Current](current.md) — follows adcm-toolkits 0.14.1\n"),
    }
    put_mem(ctx, c, files)
    d = both(ctx, t, b)
    if d:
        t.eq(found(d), [], "no findings: 0.14.x / vigente lines, regen: none, renovate-*.md, quoted Superseded notes are ignored")
        t.eq([rules_of(d).get("state"), d.get("needed")], ["ok", []], "rules.state / needed")
        head, det, more = rules_lines(d)
        t.ok((head or "").startswith("RULES ok · memory ") and (head or "").endswith("findings 0 (fix 0 · review 0)")
             and not det and more is None, f"RULES line without detail lines, got {head!r}")
    runs = [ctx.run(b, "--json") for _ in range(2)] + [ctx.run(b) for _ in range(2)]
    t.eq(runs[0].out, runs[1].out, "two --json runs are byte-identical")
    t.eq(runs[2].out, runs[3].out, "two plain runs are byte-identical")


def case_rules_targets(ctx, t):
    stale = note("Plan every brain with adcm-toolkits 0.8.0 from now on.")
    cfg = os.path.join(ctx.root, "cfg")
    # (a) nothing to read: n/a; the config dir's own CLAUDE.md / ORCHESTRATOR.md are never targets
    t.tag = "(a nothing) "
    b, c = container_brain(ctx, "none")
    for p in (os.path.join(cfg, "CLAUDE.md"), os.path.join(cfg, "ORCHESTRATOR.md"), os.path.join(ctx.root, ".claude", "CLAUDE.md")):
        put(p, stale)
    d = both(ctx, t, b)
    if d:
        r = rules_of(d)
        t.eq([r.get("state"), r.get("memory_dir"), r.get("files_scanned"), r.get("findings")], ["n/a", None, 0, []], "rules block")
        head, _, _ = rules_lines(d)
        t.ok((head or "").startswith("RULES n/a"), f"RULES line starts 'RULES n/a', got {head!r}")
        t.eq(d.get("needed"), [], "needed")
    # (b) --memory-dir overrides the derived location
    t.tag = "(b --memory-dir) "
    b, c = container_brain(ctx, "over")
    custom_dir = os.path.join(ctx.root, "custom-mem")
    put(os.path.join(custom_dir, "stale.md"), stale)
    d = both(ctx, t, b, "--memory-dir", custom_dir, rc=1)
    if d:
        t.eq(os.path.realpath(rules_of(d).get("memory_dir") or ""), os.path.realpath(custom_dir), "rules.memory_dir")
        t.eq(found(d), [("stale.md", "old-version", "fix")], "findings")
        t.eq(d.get("needed"), ["rules"], "needed")
    # (c) --no-rules skips the block even with stale memory
    t.tag = "(c --no-rules) "
    b, c = container_brain(ctx, "skip")
    put_mem(ctx, c, {"stale.md": stale})
    d = both(ctx, t, b, rc=1)
    if d:
        t.eq(d.get("needed"), ["rules"], "sanity: the same brain needs rules without the flag")
    d = both(ctx, t, b, "--no-rules")
    if d:
        t.eq([rules_of(d).get("state"), rules_of(d).get("findings"), d.get("needed")], ["n/a", [], []], "rules block / needed")
        head, _, _ = rules_lines(d)
        t.ok((head or "").startswith("RULES n/a") and "skipped" in (head or ""), f"RULES line says skipped, got {head!r}")
    # (d) instruction files of the container: absolute paths, no memory dir needed
    t.tag = "(d claude.md) "
    b, c = container_brain(ctx, "instr")
    cm = put(os.path.join(c, "CLAUDE.md"), note("Use protocolo execution-prompt-architect **0.8.0** for planning."))
    ag = put(os.path.join(c, "ai", "AGENTS.md"), note("Always use adcm-toolkits 0.11.0 for plans."))
    d = both(ctx, t, b, rc=1)
    if d:
        fs = rules_of(d).get("findings") or []
        t.eq(sorted(os.path.realpath(f.get("file") or "") for f in fs), sorted([os.path.realpath(cm), os.path.realpath(ag)]),
             "findings point at the CLAUDE.md and the AGENTS.md")
        t.ok(all(os.path.isabs(f.get("file") or "") for f in fs), "files are absolute paths for instruction files")
        t.eq(sorted((f.get("id"), f.get("severity"), f.get("line")) for f in fs), [("old-version", "fix", 3)] * 2, "ids / severities / lines")
        head, _, _ = rules_lines(d)
        t.eq(head, "RULES needed · memory none · claude.md 2 · findings 2 (fix 2 · review 0)", "RULES line")
        t.eq(d.get("needed"), ["rules"], "needed")
    # (e) sanitisation turns '_' and '.' into '-'
    t.tag = "(e sanitisation) "
    b, c = container_brain(ctx, "client_projects/acme.web")
    md = put_mem(ctx, c, {"stale.md": stale})
    d = both(ctx, t, b, rc=1)
    if d:
        t.eq(os.path.realpath(rules_of(d).get("memory_dir") or ""), os.path.realpath(md), "rules.memory_dir")
        t.eq(found(d), [("stale.md", "old-version", "fix")], "findings")
    # (f) the three brain layouts resolve to the same container
    for k, layout in enumerate(("ai/ai-brain", "ai-brain", "docs/ai-brain")):
        t.tag = f"(f layout {layout}) "
        b, c = container_brain(ctx, f"lay{k}", layout)
        md = put_mem(ctx, c, {"stale.md": stale})
        d = both(ctx, t, b, rc=1)
        if d:
            t.eq(os.path.realpath(rules_of(d).get("memory_dir") or ""), os.path.realpath(md), "rules.memory_dir")
            t.eq(found(d), [("stale.md", "old-version", "fix")], "findings")
    # (g) a memory dir named after the brain's own cwd is read too
    t.tag = "(g brain-cwd memory) "
    b, c = container_brain(ctx, "cwd")
    put_mem(ctx, c, {"clean.md": note("Nothing stale in here.")})
    put_mem(ctx, b, {"brain-only.md": stale})
    d = both(ctx, t, b, rc=1)
    if d:
        t.eq(sorted(os.path.basename(f.get("file") or "") for f in rules_of(d).get("findings") or []), ["brain-only.md"], "findings")


def case_rules_cap(ctx, t):
    mods = {}
    for i in range(1, 6):
        mods.update(module_files(f"modules/m{i:02d}"))
    b, c = container_brain(ctx, "cap", extra=mods)
    put_mem(ctx, c, {f"n{i:02d}.md": note(f"Follow adcm-toolkits 0.8.0 rule {i}.") for i in range(30)})
    d = both(ctx, t, b, "--all-modules", "--invariants", rc=1)
    if d:
        t.eq(d.get("needed"), ["rules", "modules"], "needed")
        t.eq(len(rules_of(d).get("findings") or []), 30, "json carries all 30 findings")
        head, det, more = rules_lines(d)
        t.ok((head or "").startswith("RULES needed · memory ") and (head or "").endswith("findings 30 (fix 30 · review 0)"),
             f"RULES line, got {head!r}")
        t.eq(len(det), 6, "exactly six detail lines")
        t.eq(more, "  … +24 more (use --json)", "overflow line")
        txt = d.get("text") or []
        t.ok(any(x.startswith("INVARIANTS s7_wave_headers=") for x in txt), "root INVARIANTS line kept")
        for i in range(1, 6):
            t.ok(any(x.startswith(f"INVARIANTS modules/m{i:02d}") for x in txt), f"INVARIANTS line of modules/m{i:02d} kept")
        t.ok(txt and txt[-1].startswith("RENOVATE: needed("), "last line intact")
    # pressure: 14 registry rows push the output past 40 lines; INVARIANTS and the RULES summary survive
    t.tag = "(pressure) "
    b, c = container_brain(ctx, "cap2", extra=mods, rows=[art(f"page{i}.html") for i in range(14)])
    put_mem(ctx, c, {f"n{i:02d}.md": note(f"Follow adcm-toolkits 0.8.0 rule {i}.") for i in range(30)})
    d = both(ctx, t, b, "--all-modules", "--invariants", rc=1)
    if d:
        txt = d.get("text") or []
        t.ok(len(txt) <= 40, f"{len(txt)} lines")
        t.ok(any(x.startswith("RULES needed") for x in txt), "RULES summary kept")
        t.ok(any(x.startswith("INVARIANTS s7_wave_headers=") for x in txt), "root INVARIANTS line kept")
        for i in range(1, 6):
            t.ok(any(x.startswith(f"INVARIANTS modules/m{i:02d}") for x in txt), f"INVARIANTS line of modules/m{i:02d} kept")


def case_rules_round2(ctx, t):
    cfg = os.path.join(ctx.root, "cfg")
    stale = note("Plan every brain with adcm-toolkits 0.8.0 from now on.")

    def lines_of(d, wild=()):
        return sorted((f.get("file"), f.get("line"), f.get("id"), "*" if (f.get("file"), f.get("line")) in wild else f.get("severity"))
                      for f in rules_of(d).get("findings") or [])

    def mem_run(tag, name, files, expect, wild=()):
        """One container with `files` in its memory dir: findings must be exactly `expect` (file, line, id, severity)."""
        t.tag = f"({tag}) "
        b, c = container_brain(ctx, name)
        put_mem(ctx, c, files)
        fix = any(s == "fix" for *_, s in expect)
        rc = 1 if fix else ctx.run(b, "--json").rc if wild else 0
        d = both(ctx, t, b, rc=rc)
        if d:
            t.eq(lines_of(d, wild), sorted(expect), "findings (file, line, id, severity)")
            t.eq(d.get("needed"), ["rules"] if rc == 1 else [], "needed")
        return d

    # (a) negated and current wordings are not stale; (b) the stale wordings still are
    mem_run("a negated", "r2a", {"a.md": "# Note\n\n" + "\n".join([
        "nunca lee task.md al arrancar",
        "status_digest.py reads task.md at session start",
        "the courier reads task.md wave map to restart pages",
        "sub-agents have no SendUserFile",
        "courier cannot call SendUserFile; the main session sends",
        "general-purpose fallback when the agent types are not loaded",
        "Opus executes only ⚠gate waves"]) + "\n"}, [])
    mem_run("b still stale", "r2b", {"b.md": "# Note\n\nlee task.md al arrancar para saber el estado\n"
                                    "the courier sends the screenshots with SendUserFile\n"},
            [("b.md", 3, "reads-task-md", "fix"), ("b.md", 4, "subagent-sends-media", "fix")])
    # (c) old-version: a 'current' word only excuses the line when it comes AFTER the version
    mem_run("c positional skip", "r2c", {"c.md": "# Note\n\n" + "\n".join([
        "Protocolo VIGENTE (adcm-toolkits 0.8.0)",
        "adcm-toolkits 0.8.0 ya no es el vigente",
        "currently uses adcm-toolkits 0.8.0",
        "concurrent sessions on adcm-toolkits 0.8.0"]) + "\n"},
            [("c.md", 3, "old-version", "fix"), ("c.md", 5, "old-version", "fix"), ("c.md", 6, "old-version", "fix")])
    # (d) keywords: another plugin or MCP is not ours; 'toolkit' / 'actualizado a' are; a bare 'protocolo' is only `review`
    mem_run("d keywords", "r2d", {"d.md": "# Note\n\n" + "\n".join([
        "acme-admin plugin 0.7.1",
        "MCP protocol 0.8",
        "el toolkit en 0.11.0",
        "adcm-toolkits actualizado a 0.11.0",
        "ola ejecutada con protocolo 0.8.0"]) + "\n"},
            [("d.md", 5, "old-version", "*"), ("d.md", 6, "old-version", "*"), ("d.md", 7, "old-version", "review")],
            wild={("d.md", 5), ("d.md", 6)})
    # (e) two memory dirs (container + brain cwd) with the same file name: `file` is relative to <config>/projects/
    t.tag = "(e two memory dirs) "
    b, c = container_brain(ctx, "r2e")
    dirs = [put_mem(ctx, c, {"stale.md": stale}), put_mem(ctx, b, {"stale.md": stale})]
    d = both(ctx, t, b, rc=1)
    if d:
        fs = rules_of(d).get("findings") or []
        t.eq(len(fs), 2, "one finding per memory dir")
        t.eq(len({f.get("file") for f in fs}), 2, "the two `file` values differ")
        t.ok(all(not os.path.isabs(f.get("file") or "/") and os.path.isfile(os.path.join(cfg, "projects", f.get("file") or ""))
                 for f in fs),
             f"`file` is relative to <config>/projects/, got {[f.get('file') for f in fs]}")
        t.eq(sorted(os.path.realpath(x) for x in rules_of(d).get("memory_dirs") or []), sorted(os.path.realpath(x) for x in dirs),
             "rules.memory_dirs lists both directories")
    # (f) a stale line right under a Superseded note (no blank line) is still a finding; only the note line and its
    #     indented / '(line' continuation lines are skipped
    mem_run("f line under a note", "r2f", {"f.md": "# Note\n\n"
            "**Superseded (protocol 0.14.2, 2026-10-03):** the roles changed\n"
            "  (line 9: \"Follow adcm-toolkits 0.6.6 for old things\")\n"
            "(line 11: \"Use adcm-toolkits 0.7.0 for older things\")\n"
            "Follow adcm-toolkits 0.8.0 for planning sessions.\n"}, [("f.md", 6, "old-version", "fix")])
    # (g) MEMORY.md hooks separated by ' - ' or ': ' are scanned; a version in the link title is not
    mem_run("g hook separators", "r2g", {"MEMORY.md": "# Memory index\n\n"
            "- [Plain](a.md) - follows adcm-toolkits 0.11.0 for every brain\n"
            "- [Other](b.md): follows adcm-toolkits 0.8.0 for planning\n"
            "- [adcm-toolkits 0.6.6 notes](c.md) - neutral hook text\n"},
            [("MEMORY.md", 3, "old-version", "fix"), ("MEMORY.md", 4, "old-version", "fix")])
    # (h) a brain reached through a symlink with another name still resolves its container
    t.tag = "(h symlinked brain) "
    if hasattr(os, "symlink") and os.name != "nt":
        b, c = container_brain(ctx, "r2h")
        put_mem(ctx, c, {"stale.md": stale})
        link = os.path.join(ctx.root, "links", "shortcut")
        os.makedirs(os.path.dirname(link))
        try:
            os.symlink(b, link)
        except (OSError, NotImplementedError):
            link = None
        if link:
            d = both(ctx, t, link, rc=1)
            if d:
                t.eq(lines_of(d), [("stale.md", 3, "old-version", "fix")], "findings (container resolved through the symlink)")
    # (j) `plans.html = none (a mano)` is a hand-kept page by design; a file that cites 0.14.0 is current
    mem_run("j hand-kept page / 0.14.0", "r2j", {
        "j1.md": note("plans.html = `none` (a mano)"),
        "j2.md": "# Note\n\nplans.html se actualiza a mano cada cierre.\nPrompts page via prompts-regen.py.\n"
                 "Brain migrated under protocol 0.14.0 last month.\n"}, [])
    # (i) the config dir's own CLAUDE.md / ORCHESTRATOR.md are never scanned, even when the brain lives inside it
    #     or --memory-dir points at it
    t.tag = "(i config dir) "
    home_cfg = os.path.join(ctx.root, ".claude")
    old_env = ctx.env
    ctx.env = dict(old_env, CLAUDE_CONFIG_DIR=home_cfg)
    try:
        for n in ("CLAUDE.md", "ORCHESTRATOR.md"):
            put(os.path.join(home_cfg, n), note("Plan every brain with adcm-toolkits 0.8.0 and `opus` ejecuta ⚠gates."))
        b = fresh(ctx, "ai-brain", under=".claude")
        d = both(ctx, t, b)
        if d:
            t.eq([lines_of(d), rules_of(d).get("claude_files")], [[], 0], "findings / claude_files with the brain inside ~/.claude")
        put(os.path.join(home_cfg, "stale.md"), stale)
        rc = ctx.run(b, "--json", "--memory-dir", home_cfg).rc  # whether the other files of that dir are scanned is open
        d = both(ctx, t, b, "--memory-dir", home_cfg, rc=rc)
        if d:
            t.ok(rc in (0, 1) and {f[0] for f in lines_of(d)} <= {"stale.md"} and rules_of(d).get("claude_files") == 0,
                 f"with --memory-dir ~/.claude neither CLAUDE.md nor ORCHESTRATOR.md is scanned, got {lines_of(d)} claude_files={rules_of(d).get('claude_files')}")
    finally:
        ctx.env = old_env


CASES = [
    ("fresh_0141_up_to_date", case_fresh_0141_up_to_date),
    ("legacy_08", case_legacy_08),
    ("legacy_011", case_legacy_011),
    ("skills_partial", case_skills_partial),
    ("modules", case_modules),
    ("regen_none_ok", case_regen_none_ok),
    ("copy_scripts", case_copy_scripts),
    ("context_names", case_context_names),
    ("invariants_stable", case_invariants_stable),
    ("version_consistency", case_version_consistency),
    ("usage_error", case_usage_error),
    ("no_execute", case_no_execute),
    ("spanish_markers", case_spanish_markers),
    ("s7_header_prefixes", case_s7_header_prefixes),
    ("audit_round2", case_audit_round2),
    ("rules_memory", case_rules_memory),
    ("rules_whitelist_idempotent", case_rules_whitelist_idempotent),
    ("rules_targets", case_rules_targets),
    ("rules_cap", case_rules_cap),
    ("rules_round2", case_rules_round2),
]


def run_case(fn, checker, keep):
    root = os.path.realpath(tempfile.mkdtemp(prefix="renovate-selftest-"))
    t = Check()
    try:
        fn(Ctx(checker, root), t)
        verdict, why = ("FAIL", "; ".join(p[:140] for p in t.problems[:8])) if t.problems else ("PASS", "")
    except Skip as s:
        verdict, why = "SKIP", str(s)
    except Exception as exc:  # a broken harness or a crashing checker is a failure, not a crash
        verdict, why = "FAIL", f"harness error: {exc!r}"
    finally:
        if keep:
            print(f"  kept {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)
    return verdict, why


def main():
    ap = argparse.ArgumentParser(description="Behavioural tests for renovate_check.py")
    ap.add_argument("--checker", default=os.path.join(HERE, "renovate_check.py"))
    ap.add_argument("--only", help="run a single case by name")
    ap.add_argument("--keep", action="store_true", help="leave the temp trees on disk")
    args = ap.parse_args()
    checker = os.path.abspath(os.path.expanduser(args.checker))
    if not os.path.isfile(checker):
        print(f"checker not found: {checker}")
        return 2
    global VERSION
    m = re.search(r"""^__version__\s*=\s*["']([^"']+)["']""", read(checker) or "", re.M)
    if m:
        VERSION = m.group(1)
        EXEC_DEFAULTS["protocol"] = VERSION
    cases = [c for c in CASES if not args.only or c[0] == args.only]
    if not cases:
        print(f"unknown case {args.only!r}; known: {', '.join(n for n, _ in CASES)}")
        return 2
    tally = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    for name, fn in cases:
        verdict, why = run_case(fn, checker, args.keep)
        tally[verdict] += 1
        print(f"{verdict} {name}" + (f" — {why}" if why else ""))
    print(f"{tally['PASS']} PASS · {tally['FAIL']} FAIL · {tally['SKIP']} SKIP (of {len(cases)})")
    return 1 if tally["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
