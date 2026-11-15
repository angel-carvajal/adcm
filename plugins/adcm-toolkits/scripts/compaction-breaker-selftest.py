#!/usr/bin/env python3
"""compaction-breaker-selftest - compaction counting, handoff gate (R1b), lock (R1) and handoff stamp of main-thread-guard.py.

Usage:
  python3 compaction-breaker-selftest.py [--only SUBSTRING] [--guard PATH] [--mutation]

Each case gets a fresh temp dir (state dir, transcript, cwd) and runs the guard as a subprocess with the hook JSON on stdin
and a clean env. Prints `PASS <case>` / `FAIL <case>: <why>`, then `N/N passed`; exit 1 on any failure.
--mutation copies the guard, neutralises one `# MUTATION-KEY: <name>` line per mutant, re-runs the suite and requires it
to fail: prints `KILLED <name>` (or `SURVIVED <name>`); exit 1 when a mutant survives.
The two sibling suites (main-thread-budget, heavy-read-guard) import this harness.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = os.path.join(HERE, "main-thread-guard.py")
SID = "s1a2b3c4-0000-4000-8000-000000000001"
MARK = "# MUTATION-KEY:"


class Ctx:
    """One throwaway world: tmp root, state dir, cwd, main transcript, env."""

    def __init__(self, guard):
        self.guard = guard
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="mtg-selftest-"))
        self.state = os.path.join(self.tmp, "state")
        self.cwd = os.path.join(self.tmp, "work")
        self.cfg = os.path.join(self.tmp, "cfg")
        self.proj = os.path.join(self.cfg, "projects", "-work")
        os.makedirs(self.cwd)
        os.makedirs(self.proj)
        self.transcript = os.path.join(self.proj, SID + ".jsonl")
        open(self.transcript, "w").close()
        self.expect_errors = False
        self.env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": self.tmp, "PYTHONDONTWRITEBYTECODE": "1",
                    "ADCM_GUARD_STATE_DIR": self.state, "ADCM_GUARD_FORCE": "1", "CLAUDE_CONFIG_DIR": self.cfg}

    def path(self, *parts):
        return os.path.join(self.tmp, *parts)

    def write(self, rel, text="", size=None):
        p = rel if os.path.isabs(rel) else self.path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
            if size is not None:
                fh.truncate(size)
        return p

    def event(self, name, sid=SID, **kw):
        d = {"session_id": sid, "transcript_path": self.transcript, "cwd": self.cwd, "hook_event_name": name}
        d.update(kw)
        return d

    def run(self, data, env=None, stdin=None, drop=()):
        e = dict(self.env)
        e.update(env or {})
        for k in drop:
            e.pop(k, None)
        p = subprocess.run([sys.executable, "-B", self.guard], input=json.dumps(data) if stdin is None else stdin,
                           capture_output=True, text=True, env=e, timeout=30)
        return Out(p.returncode, p.stdout.strip())

    def tool(self, name, inp, env=None, sub=False, sid=SID):
        kw = {"tool_name": name, "tool_input": inp}
        if sub:
            kw.update(agent_id="a2f848b9121c8af1d", agent_type="general-purpose")
        return self.run(self.event("PreToolUse", sid=sid, **kw), env=env)

    def bash(self, cmd, **kw):
        return self.tool("Bash", {"command": cmd}, **kw)

    def prompt(self, text, env=None, sid=SID):
        return self.run(self.event("UserPromptSubmit", sid=sid, prompt=text), env=env)

    def precompact(self, n=1, env=None, sub=False):
        out = None
        for _ in range(n):
            kw = {"trigger": "auto"}
            if sub:
                kw.update(agent_id="a35ecaee1c64a8228", agent_type="")
            out = self.run(self.event("PreCompact", **kw), env=env)
        return out

    def start(self, source, env=None, sid=SID):
        return self.run(self.event("SessionStart", sid=sid, source=source), env=env)

    def post(self, name, inp, env=None, sub=False, sid=SID):
        kw = {"tool_name": name, "tool_input": inp, "tool_response": {}}
        if sub:
            kw.update(agent_id="a2f848b9121c8af1d", agent_type="general-purpose")
        return self.run(self.event("PostToolUse", sid=sid, **kw), env=env)

    def state_of(self, sid=SID):
        for f in os.listdir(self.state) if os.path.isdir(self.state) else []:
            if f.endswith(".json") and f.startswith(sid[:8]):
                with open(os.path.join(self.state, f), encoding="utf-8") as fh:
                    return json.load(fh)
        return {}

    def close(self):
        problem = None
        log = os.path.join(self.state, "errors.log")
        if not self.expect_errors and os.path.exists(log):
            problem = "errors.log written: " + open(log, encoding="utf-8").read()[:200]
        shutil.rmtree(self.tmp, ignore_errors=True)
        return problem


class Out:
    def __init__(self, rc, text):
        self.rc, self.text = rc, text
        try:
            self.json = json.loads(text) if text.startswith("{") else None
        except ValueError:
            self.json = None

    @property
    def spec(self):
        return (self.json or {}).get("hookSpecificOutput") or {}

    @property
    def denied(self):
        return self.spec.get("permissionDecision") == "deny"

    @property
    def reason(self):
        return self.spec.get("permissionDecisionReason", "")

    @property
    def context(self):
        return self.spec.get("additionalContext", "")

    @property
    def system(self):
        return (self.json or {}).get("systemMessage", "")


def allowed(o):
    if o.rc:
        return f"exit {o.rc}"
    return f"expected allow, got deny: {o.reason[:160]}" if o.denied else None


def denied(o, rule, *needles):
    if o.rc:
        return f"exit {o.rc}"
    if not o.denied:
        return f"expected deny [{rule}], got {o.text[:160] or '(no output)'}"
    head = f"⛔ main-thread-guard [{rule}]:"
    if not o.reason.startswith(head):
        return f"reason does not start with {head!r}: {o.reason[:160]}"
    miss = [n for n in needles if n not in o.reason]
    return f"reason lacks {miss}: {o.reason[:200]}" if miss else None


def has(text, *needles):
    miss = [n for n in needles if n not in text]
    return f"lacks {miss}: {text[:200]!r}" if miss else None


def first(*problems):
    return next((p for p in problems if p), None)


def boundary_record():
    return json.dumps({"type": "system", "subtype": "compact_boundary", "content": "Conversation compacted"},
                      separators=(",", ":"))


def mutate(source, key):
    lines = source.split("\n")
    hits = [i for i, l in enumerate(lines) if l.rstrip().endswith(f"{MARK} {key}")]
    if len(hits) != 1:
        raise ValueError(f"marker {key!r} found {len(hits)} times")
    i = hits[0]
    code, comment = lines[i][:lines[i].index(MARK)].rstrip(), "  " + MARK + f" {key}"
    for pat, rep in ((r"^(\s*)(if|elif)\s+.*?:(.*)$", r"\1\2 False:\3"), (r"^(\s*)return\s+.+$", r"\1return False"),
                     (r"^(\s*)([A-Za-z_][\w\[\]\"']*)\s*=\s*.+$", r"\1\2 = False")):
        if re.match(pat, code):
            lines[i] = re.sub(pat, rep, code) + comment
            return "\n".join(lines)
    raise ValueError(f"marker {key!r} is on a line the mutator cannot neutralise: {code.strip()}")


def run_cases(cases, guard, only=None, quiet=False):
    failed = total = 0
    for name, fn in cases:
        if only and only not in name:
            continue
        total += 1
        ctx = Ctx(guard)
        try:
            problem = fn(ctx)
        except Exception as exc:
            problem = f"harness error: {exc!r}"
        problem = problem or ctx.close()
        shutil.rmtree(ctx.tmp, ignore_errors=True)
        if problem:
            failed += 1
        if not quiet:
            print(f"FAIL {name}: {problem}" if problem else f"PASS {name}")
        if problem and quiet:
            break
    return failed, total


def suite_main(cases, mutants, argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        only = argv[argv.index("--only") + 1] if "--only" in argv else None
        guard = os.path.abspath(argv[argv.index("--guard") + 1]) if "--guard" in argv else GUARD
    except IndexError:
        print("usage: [--only SUBSTRING] [--guard PATH] [--mutation]")
        return 64
    if "--mutation" in argv:
        source = open(guard, encoding="utf-8").read()
        tmp = tempfile.mkdtemp(prefix="mtg-mutant-")
        survivors = 0
        try:
            for key in mutants:
                os.makedirs(os.path.join(tmp, "plugin", "scripts"), exist_ok=True)
                path = os.path.join(tmp, "plugin", "scripts", "main-thread-guard.py")
                try:
                    text = mutate(source, key)
                except ValueError as exc:
                    print(f"SURVIVED {key}: {exc}")
                    survivors += 1
                    continue
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
                failed, _ = run_cases(cases, path, only, quiet=True)
                print(f"KILLED {key}" if failed else f"SURVIVED {key}")
                survivors += 0 if failed else 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        print(f"{len(mutants) - survivors}/{len(mutants)} mutants killed")
        return 1 if survivors else 0
    failed, total = run_cases(cases, guard, only)
    print(f"{total - failed}/{total} passed")
    return 1 if failed else 0


# ---------------------------------------------------------------- cases

HEADER = ("# Handoff W3-01-a\n\n- **Wave:** W3\n- **Phase closed:** a\n- **Result:** done\n- **Next phase:** b\n\n## Notes\nbody\n"
          + "Estado, pendientes, agentes vivos, siguiente paso y prompt de reanudación de la fase.\n" * 3)
LONG = "Estado: fase a cerrada. Pendientes: dos tests. Agentes vivos: ninguno. Siguiente paso: gate. Prompt de reanudación.\n" * 3


def handoff_file(c, text=HEADER):
    return c.write(os.path.join("brain", "handoffs", "W3-01-a.md"), text)


def cases():
    out = []

    def add(name):
        def deco(fn):
            out.append((name, fn))
            return fn
        return deco

    @add("precompact_counts")
    def _(c):
        c.precompact(3)
        s = c.state_of()
        return None if s.get("compactions") == 3 and len(s.get("compact_log", [])) == 3 else f"state {s}"

    @add("precompact_records_trigger")
    def _(c):
        c.precompact(1)
        log = c.state_of().get("compact_log") or [{}]
        return None if log[0].get("trigger") == "auto" and log[0].get("time") else f"log {log}"

    @add("precompact_subagent_ignored")
    def _(c):
        c.precompact(2, sub=True)
        return None if not c.state_of().get("compactions") else f"sub PreCompact counted: {c.state_of()}"

    @add("precompact_second_steers_summary")
    def _(c):
        o1 = c.precompact(1)
        o2 = c.precompact(1)
        return first(None if not o1.text else f"1st must be silent: {o1.text[:100]}", has(o2.text, "handoff", "agentes"))

    @add("notice_1_of_3")
    def _(c):
        c.precompact(1)
        o = c.start("compact")
        return has(o.context, "compactación 1/3")

    @add("notice_2_of_3_fallback_path")
    def _(c):
        c.precompact(2)
        o = c.start("compact")
        want = os.path.join(c.proj, "handoffs", f"handoff-{time.strftime('%Y%m%d')}-{SID[:8]}.md")
        return has(o.context, "COMPACTACIÓN 2/3", "escribe el handoff YA en", want)

    @add("notice_2_of_3_brain_handoffs_dir")
    def _(c):
        h = handoff_file(c)
        c.post("Write", {"file_path": h, "content": HEADER})
        c.precompact(2)
        o = c.start("compact")
        return has(o.context, "COMPACTACIÓN 2/3", os.path.dirname(h) + os.sep)

    @add("notice_3_lock")
    def _(c):
        c.precompact(3)
        o = c.start("compact")
        return has(o.context, "3.ª compactación", "/clear")

    @add("max_with_transcript")
    def _(c):
        with open(c.transcript, "w") as fh:
            fh.write("\n".join([json.dumps({"type": "user"}), boundary_record(), json.dumps({"type": "assistant"}),
                                boundary_record()]) + "\n")
        o = c.start("resume")
        return first(None if c.state_of().get("compactions") == 2 else f"state {c.state_of()}",
                     has(o.context, "COMPACTACIÓN 2/3"))

    @add("max_keeps_state_when_transcript_lower")
    def _(c):
        c.precompact(3)
        with open(c.transcript, "w") as fh:
            fh.write(boundary_record() + "\n")
        c.start("compact")
        return None if c.state_of().get("compactions") == 3 else f"state {c.state_of()}"

    @add("boundary_across_chunk_edge")
    def _(c):
        rec = boundary_record()
        pad = (1 << 20) - 10
        with open(c.transcript, "w") as fh:
            fh.write("x" * pad + rec + "\n" + rec + "\n" + rec + "\n")
        c.start("resume")
        return None if c.state_of().get("compactions") == 3 else f"state {c.state_of()}"

    @add("gate_denies_after_2nd")
    def _(c):
        c.precompact(2)
        return denied(c.bash("echo hi"), "R1b", "2.ª compactación", "escribe el handoff YA en")

    @add("gate_allows_handoff_and_memory")
    def _(c):
        c.precompact(2)
        mem = c.write(os.path.join("cfg", "projects", "-work", "memory", "notes.md"), "x\n")
        h = os.path.join(c.tmp, "brain", "handoffs", "W3-01-a.md")
        return first(allowed(c.tool("Write", {"file_path": h, "content": "x"})),
                     allowed(c.tool("Read", {"file_path": mem})),
                     allowed(c.tool("Edit", {"file_path": mem, "old_string": "x", "new_string": "y"})),
                     allowed(c.tool("PushNotification", {"message": "m"})),
                     allowed(c.tool("ToolSearch", {"query": "select:PushNotification", "max_results": 1})),
                     denied(c.tool("ToolSearch", {"query": "push notification"}), "R1b"),
                     denied(c.tool("Read", {"file_path": c.write("work/a.py", "x")}), "R1b"))

    @add("gate_opens_once_handoff_written")
    def _(c):
        c.precompact(2)
        h = handoff_file(c)
        c.post("Write", {"file_path": h, "content": HEADER})
        return allowed(c.bash("echo hi"))

    @add("gate_opens_for_subagent_handoff")
    def _(c):
        c.precompact(2)
        h = c.write("brain/handoff-w3.md", HEADER)
        c.post("Write", {"file_path": h, "content": HEADER}, sub=True)
        return allowed(c.bash("echo hi"))

    @add("lock_after_3rd")
    def _(c):
        c.precompact(3)
        return denied(c.bash("echo hi"), "R1", "3.ª compactación", "/clear")

    @add("lock_stays_after_handoff")
    def _(c):
        c.precompact(3)
        h = handoff_file(c)
        c.post("Write", {"file_path": h, "content": HEADER})
        return denied(c.bash("echo hi"), "R1")

    @add("lock_allow_list")
    def _(c):
        c.precompact(3)
        mem = c.write(os.path.join("cfg", "projects", "-work", "memory", "MEMORY.md"), "- a\n")
        other = c.write("work/x.md", "x\n")
        return first(allowed(c.tool("Write", {"file_path": c.path("brain", "handoffs", "W3-02-b.md"), "content": "x"})),
                     allowed(c.tool("Read", {"file_path": mem})),
                     allowed(c.tool("Edit", {"file_path": mem, "old_string": "- a", "new_string": "- b"})),
                     allowed(c.tool("PushNotification", {"message": "m"})),
                     denied(c.tool("Edit", {"file_path": other, "old_string": "x", "new_string": "y"}), "R1"),
                     denied(c.tool("Read", {"file_path": other}), "R1"),
                     denied(c.tool("Agent", {"prompt": "p"}), "R1"),
                     denied(c.tool("ToolSearch", {"query": "q"}), "R1"),
                     allowed(c.tool("ToolSearch", {"query": "select:PushNotification"})),
                     denied(c.tool("ToolSearch", {"query": "select:PushNotification,Bash"}), "R1"))

    @add("lock_ignores_direct_mode")
    def _(c):
        c.precompact(3)
        c.prompt("modo directo")
        return denied(c.bash("echo hi"), "R1")

    @add("lock_subagent_free")
    def _(c):
        c.precompact(3)
        return allowed(c.bash("echo hi", sub=True))

    @add("unattended_never_locks")
    def _(c):
        env = {"ADCM_GUARD_FORCE": "", "CLAUDE_CODE_SESSION_ATTENDED": "0"}
        c.precompact(3, env=env)
        o = c.start("compact", env=env)
        return first(allowed(c.bash("echo hi", env=env)), has(o.context, "3.ª compactación"),
                     None if c.state_of().get("compactions") == 3 else "unattended compactions not counted")

    @add("resume_keeps_count")
    def _(c):
        c.precompact(3)
        c.start("resume")
        return denied(c.bash("echo hi"), "R1")

    @add("clear_is_fresh")
    def _(c):
        c.precompact(3)
        new = "99999999-0000-4000-8000-000000000002"
        c.start("clear", sid=new)
        return allowed(c.bash("echo hi", sid=new))

    @add("clear_injects_pending_handoff")
    def _(c):
        h = handoff_file(c)
        c.post("Write", {"file_path": h, "content": HEADER})
        o = c.start("clear", sid="99999999-0000-4000-8000-000000000002")
        return has(o.context, "HANDOFF pendiente: " + h)

    @add("startup_old_handoff_silent")
    def _(c):
        h = handoff_file(c)
        c.post("Write", {"file_path": h, "content": HEADER})
        idx = os.path.join(c.state, "projects")
        for f in os.listdir(idx):
            p = os.path.join(idx, f)
            d = json.load(open(p))
            d["time"] = time.time() - 73 * 3600
            json.dump(d, open(p, "w"))
        o = c.start("startup", sid="99999999-0000-4000-8000-000000000002")
        return None if "HANDOFF pendiente" not in o.text else f"stale handoff injected: {o.text[:160]}"

    @add("startup_runs_memory_check")
    def _(c):
        tmpg = os.path.join(c.tmp, "g")
        os.makedirs(tmpg)
        shutil.copy(c.guard, os.path.join(tmpg, "main-thread-guard.py"))
        with open(os.path.join(tmpg, "check-memory-index.py"), "w") as fh:
            fh.write("import sys\nprint('MEMORIA: indice largo ' + ' '.join(sys.argv[1:]))\n")
        c.write(os.path.join("cfg", "projects", "-work", "memory", "MEMORY.md"), "- a\n")
        c.guard = os.path.join(tmpg, "main-thread-guard.py")
        o = c.start("startup")
        return has(o.context, "MEMORIA: indice largo", "--brief", "--file", os.path.join(c.proj, "memory", "MEMORY.md"))

    @add("startup_memory_check_missing_silent")
    def _(c):
        tmpg = os.path.join(c.tmp, "g")
        os.makedirs(tmpg)
        shutil.copy(c.guard, os.path.join(tmpg, "main-thread-guard.py"))
        c.write(os.path.join("cfg", "projects", "-work", "memory", "MEMORY.md"), "- a\n")
        c.guard = os.path.join(tmpg, "main-thread-guard.py")
        o = c.start("startup")
        return None if o.rc == 0 and not o.text else f"expected silence: {o.rc} {o.text[:120]}"

    @add("prune_old_state")
    def _(c):
        os.makedirs(c.state)
        old = os.path.join(c.state, "deadbeef-old.json")
        json.dump({"compactions": 3}, open(old, "w"))
        t = time.time() - 15 * 86400
        os.utime(old, (t, t))
        c.start("startup")
        return None if not os.path.exists(old) else "15-day-old state not pruned"

    @add("stamp_after_header_bullets")
    def _(c):
        c.bash("echo 1")
        c.bash("echo 2")
        c.tool("Read", {"file_path": c.write("work/a.txt", "a")})
        c.precompact(1)
        h = handoff_file(c)
        c.post("Write", {"file_path": h, "content": HEADER})
        lines = open(h).read().split("\n")
        want = f"- **Main thread:** 2 Bash · 1 Read · 1 compactions (session {SID[:8]})"
        return None if lines[6] == want and lines[5].startswith("- **Next phase:**") else f"lines {lines[4:8]}"

    @add("stamp_replaced_once")
    def _(c):
        h = handoff_file(c)
        c.post("Write", {"file_path": h, "content": HEADER})
        c.bash("echo 1")
        c.post("Edit", {"file_path": h, "old_string": "body", "new_string": "body2"})
        text = open(h).read()
        n = text.count("- **Main thread:**")
        return None if n == 1 and "1 Bash · 0 Read" in text else f"{n} stamp lines: {text[:300]!r}"

    @add("stamp_fills_template_slot")
    def _(c):
        tpl = "# H\n\n- **Wave:** W1\n- **Result:** done\n- **Main thread:**\n- **Next prompt:** Start a clean session\n\nbody\n"
        h = c.write("brain/handoffs/W1-01-a.md", tpl)
        c.post("Write", {"file_path": h, "content": tpl})
        lines = open(h).read().split("\n")
        return None if lines[4].startswith("- **Main thread:** 0 Bash") and lines[5].startswith("- **Next prompt:**") \
            else f"lines {lines[2:7]}"

    @add("stamp_appended_without_bullets")
    def _(c):
        h = c.write(os.path.join(c.proj, "handoffs", "handoff-20261114-s1a2b3c4.md"), "just text")
        c.post("Write", {"file_path": h, "content": "just text"})
        text = open(h).read()
        return None if text.startswith("just text\n- **Main thread:** 0 Bash") else f"text {text!r}"

    @add("stamp_duplicate_lines_collapsed")
    def _(c):
        text = HEADER.replace("- **Next phase:** b\n", "- **Next phase:** b\n- **Main thread:** old\n- **Main thread:** older\n")
        h = handoff_file(c, text)
        c.post("Write", {"file_path": h, "content": text})
        out = open(h).read()
        return None if out.count("- **Main thread:**") == 1 and "old" not in out else f"text {out!r}"

    @add("f2_repo_handoff_md_untouched")
    def _(c):
        text = "# Handoff notes\n\n- **Owner:** team\n"
        p = c.write("repo/HANDOFF.md", text)
        c.precompact(2)
        c.post("Write", {"file_path": p, "content": text})
        o = c.start("clear", sid="99999999-0000-4000-8000-000000000002")
        return first(None if open(p).read() == text else "repo HANDOFF.md was stamped", denied(c.bash("echo hi"), "R1b"),
                     None if "HANDOFF pendiente" not in o.text else "repo HANDOFF.md entered the index")

    @add("f2_handoffs_readme_untouched")
    def _(c):
        text = "# Handoffs\n\n- **Index:** below\n"
        p = c.write("docs/handoffs/README.md", text)
        c.post("Edit", {"file_path": p, "old_string": "a", "new_string": "b"})
        return None if open(p).read() == text else "docs/handoffs/README.md was stamped"

    @add("gate_opens_any_handoff_300_chars")
    def _(c):
        c.precompact(2)
        short = c.write("brain/handoffs/W1-01-a.md", "x" * 299)
        c.post("Write", {"file_path": short, "content": "x"})
        still = denied(c.bash("echo hi"), "R1b", "300 caracteres", "estado, pendientes, agentes vivos")
        h = c.write("brain/handoffs/W1-02-a.md", LONG)
        c.post("Write", {"file_path": h, "content": LONG})
        o = c.start("clear", sid="99999999-0000-4000-8000-000000000002")
        return first(still, allowed(c.bash("echo hi")),
                     None if open(h).read() == LONG else "unlabeled handoff was stamped",
                     None if "HANDOFF pendiente" not in o.text else "unlabeled handoff entered the index")

    @add("gate_boundary_300_and_labels")
    def _(c):
        c.precompact(2)
        lab = "# H\n\n- **Wave:** W1\n- **Phase closed:** a\n- **Result:** done\n"
        short = c.write("brain/handoffs/W1-01-a.md", lab)
        c.post("Write", {"file_path": short, "content": lab})
        shut = first(None if "- **Main thread:**" in open(short).read() else "short labeled handoff not stamped",
                     denied(c.bash("echo hi"), "R1b"))
        exact = c.write("brain/handoffs/W1-02-a.md", "y" * 300)
        c.post("Write", {"file_path": exact, "content": "y"})
        return first(shut, allowed(c.bash("echo hi")))

    @add("fallback_dir_handoff_stamped")
    def _(c):
        h = c.write(os.path.join(c.proj, "handoffs", "handoff-x.md"), "free text\n")
        c.post("Write", {"file_path": h, "content": "free text\n"})
        return None if "- **Main thread:**" in open(h).read() else "fallback-dir handoff not stamped"

    @add("notice_2_names_contents")
    def _(c):
        c.precompact(2)
        return has(c.start("compact").context, "300 caracteres", "pendientes", "prompt de reanudación")

    @add("post_missing_file_ignored")
    def _(c):
        c.precompact(2)
        c.post("Write", {"file_path": c.path("brain", "handoffs", "W9-01-a.md"), "content": HEADER})
        c.post("Write", {"file_path": os.path.join(c.proj, "handoffs", "handoff-gone.md"), "content": "x"})
        return first(None if not c.state_of().get("handoff_written") else "missing file released the gate",
                     denied(c.bash("echo hi"), "R1b"))

    @add("direct_mode_keeps_R1b")
    def _(c):
        c.precompact(2)
        c.prompt("modo directo")
        return denied(c.bash("echo hi"), "R1b")

    @add("lock_multiedit_handoff_allowed")
    def _(c):
        c.precompact(3)
        h = handoff_file(c)
        return allowed(c.tool("MultiEdit", {"file_path": h, "edits": [{"old_string": "body", "new_string": "b2"}]}))

    @add("post_non_handoff_ignored")
    def _(c):
        p = c.write("work/notes.md", HEADER)
        c.post("Write", {"file_path": p, "content": HEADER})
        return None if open(p).read() == HEADER else "non-handoff file was stamped"

    return out


MUTANTS = ["lock", "gate", "transcript", "discriminator", "handoff", "real_handoff", "handoff_size"]

if __name__ == "__main__":
    sys.exit(suite_main(cases(), MUTANTS))
