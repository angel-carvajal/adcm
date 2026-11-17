#!/usr/bin/env python3
"""guard-fuzz-selftest - deterministic in-process fuzz of main-thread-guard.py (stdlib only).

Usage:
  python3 guard-fuzz-selftest.py [--only SUBSTRING] [--guard PATH] [--seed N] [--count N] [--mutation]

Builds structured hook inputs for every event and tool from an alphabet of NUL, lone surrogates, quotes, `$(`,
backticks, braces, globs, redirections and long runs, feeds them to the guard's handlers in-process with a fixed seed,
and asserts: no exception escapes, no errors.log line is written, and every output is empty or valid (a deny for
PreToolUse, an injection for the other events). Prints `PASS <case>` / `FAIL <case>: why`, then `N/N passed`.
--mutation neutralises the `safe_probe` key and requires the fuzz to fail (the fallback key is killed by the budget suite).
"""
import importlib.util
import json
import os
import random
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = os.path.join(HERE, "main-thread-guard.py")
ATOMS = ["\x00", "\ud800", "\udfff", "'", '"', "$(", ")", "`", "{", "}", ",", "*", "?", "[", "]", ">", ">>", "<", "<<",
         "2>&1", "|", "&&", ";", "\n", "~", "$HOME", "$PWD", "${CLAUDE_PLUGIN_ROOT}", "..", "/", "-", "--", "=", "\\",
         " ", "a", "Z", "9", "é", "modo directo", "sin tanto lío", "modo orquestador", "status", "<agent-message>",
         "<pasted_content>", "```", "«", "»", "handoff", "MEMORY.md", "task.md", ".png", ".jsonl", "x" * 300,
         "\n", "#", " # it's", "pushd ", "popd", "..", ".." + "/", ".." + "/scripts", ".." + "/..", "scripts", "hooks", "<<'X'",
         "\\\n", "builtin cd ", "cd - ", "chdir ", "orch*", "s?ate", "\"oops",
         "{a," + "b" * 5000 + "}", "~/pd\"at\"a", "pd\\ata", "'sc'ripts", "{scripts,hooks}"]
VERBS = ["cat", "rm -rf", "mv", "cp", "ls", "grep", "git status", "git -C", "find", "sed -i", "python3 -c", "bash -c",
         "eval", "env A=1", "B=2", "export C=3;", "xargs rm", "cd", "tee", "dd of=", "chmod -R", "rsync --delete", "head", "pushd", "cat <<'X'"]
TOOLS = ["Bash", "Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "Grep", "Glob", "LS", "Artifact", "ToolSearch",
         "PushNotification", "ScheduleWakeup", "SendMessage", "mcp__claude-in-chrome__navigate", "Agent", "Skill"]
EVENTS = ["PreToolUse"] * 6 + ["UserPromptSubmit"] * 2 + ["PostToolUse", "PreCompact", "SessionStart"]


def load(path, name="guard_under_fuzz"):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def word(rng, tmp, state):
    n = rng.choice([1, 2, 3, 5, 8, 20, 60])
    w = "".join(rng.choice(ATOMS) for _ in range(n))
    if rng.random() < 0.25:
        w = rng.choice([tmp, state, os.path.join(tmp, "work"), os.path.join(state, "s.json")]) + "/" + w
    return w


def command(rng, tmp, state):
    parts = []
    for _ in range(rng.choice([1, 2, 3, 6])):
        parts.append(rng.choice(VERBS) + " " + " ".join(word(rng, tmp, state) for _ in range(rng.choice([0, 1, 2, 4]))))
        parts.append(rng.choice([" ; ", " && ", " | ", "\n", " || "]))
    return "".join(parts)


def tool_input(rng, tool, tmp, state):
    w = lambda: word(rng, tmp, state)
    if tool == "Bash":
        return {"command": command(rng, tmp, state)}
    if tool in ("Read", "Write", "Edit", "NotebookEdit", "MultiEdit"):
        d = {"file_path": rng.choice([w(), os.path.join(tmp, "work", w()), os.path.join(tmp, "brain", "handoffs", w() + ".md")])}
        d.update(content=w() * rng.choice([1, 30]), old_string=w(), new_string=w() * rng.choice([1, 25]),
                 limit=rng.choice([None, 0, 5, "x", True, -1]), offset=rng.choice([None, 3, "y"]), new_source=w(),
                 edits=[{"old_string": w(), "new_string": w(), "replace_all": rng.random() < 0.5}], replace_all=rng.random() < 0.3)
        return d
    if tool in ("Grep", "Glob", "LS"):
        return {"pattern": w(), "path": w()}
    if tool == "Artifact":
        return {"action": rng.choice([None, "open", "publish", w()]), "file_path": w()}
    if tool == "ToolSearch":
        return {"query": rng.choice(["select:PushNotification", w()])}
    return {"prompt": w(), "message": w(), "x": [w(), {"y": w()}]}


def event(rng, tmp, state, transcript):
    name = rng.choice(EVENTS)
    d = {"session_id": rng.choice(["s1a2b3c4-f", "s2b3c4d5-f", "s3c4d5e6-f"]), "transcript_path": transcript,
         "cwd": rng.choice([os.path.join(tmp, "work"), tmp, state, word(rng, tmp, state)]), "hook_event_name": name}
    if rng.random() < 0.3:
        d["agent_id"] = "a2f848b9121c8af1d"
    if name in ("PreToolUse", "PostToolUse"):
        d["tool_name"] = rng.choice(TOOLS)
        d["tool_input"] = tool_input(rng, d["tool_name"], tmp, state)
        if rng.random() < 0.05:
            d["tool_input"] = json.dumps(d["tool_input"])
    elif name == "UserPromptSubmit":
        d["prompt"] = rng.choice(["", "status", "¿en qué nos quedamos?"]) + " ".join(word(rng, tmp, state) for _ in range(rng.choice([1, 3, 30])))
    elif name == "PreCompact":
        d["trigger"] = rng.choice(["auto", "manual", word(rng, tmp, state)])
    else:
        d["source"] = rng.choice(["startup", "resume", "compact", "clear", word(rng, tmp, state)])
    return d


def valid(name, out):
    if out is None:
        return True
    if name == "PreCompact":
        return isinstance(out, str)
    if not isinstance(out, dict):
        return False
    spec = out.get("hookSpecificOutput") or {}
    if spec.get("hookEventName") != name:
        return False
    if name == "PreToolUse":
        return spec.get("permissionDecision") == "deny" and str(spec.get("permissionDecisionReason", "")).startswith(
            "⛔ main-thread-guard [")
    return isinstance(spec.get("additionalContext"), str)


def fuzz(guard_path, seed, count, env_extra):
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="mtg-fuzz-"))
    state = os.path.join(tmp, "st")
    saved = dict(os.environ)
    try:
        os.environ.update({"HOME": tmp, "ADCM_GUARD_STATE_DIR": state, "CLAUDE_CONFIG_DIR": os.path.join(tmp, "cfg")})
        os.environ.update(env_extra)
        os.environ.pop("ADCM_GUARD_TEST_FAULT", None)
        os.makedirs(os.path.join(tmp, "work"))
        os.makedirs(os.path.join(tmp, "brain", "handoffs"))
        transcript = os.path.join(tmp, "cfg", "projects", "-w", "t.jsonl")
        os.makedirs(os.path.dirname(transcript))
        open(transcript, "w").close()
        g = load(guard_path, f"guard_fuzz_{seed}_{len(env_extra)}")
        rng = random.Random(seed)
        stats = {"inputs": 0, "denies": 0, "injections": 0}
        for i in range(count):
            d = event(rng, tmp, state, transcript)
            stats["inputs"] += 1
            try:
                out = g.HANDLERS[d["hook_event_name"]](d)
            except BaseException as exc:
                return f"input {i} ({d['hook_event_name']}/{d.get('tool_name')}) raised {type(exc).__name__}: {exc}", stats
            if not valid(d["hook_event_name"], out):
                return f"input {i} invalid output {str(out)[:120]!r}", stats
            stats["denies" if d["hook_event_name"] == "PreToolUse" and out else "injections"] += 1 if out else 0
            log = os.path.join(state, "errors.log")
            if os.path.exists(log):
                return f"input {i} wrote errors.log: {open(log, encoding='utf-8').read()[:200]!r}", stats
            try:
                json.dumps(out, ensure_ascii=False).encode("utf-8", "replace")
            except Exception as exc:
                return f"input {i} output not encodable: {exc}", stats
        return None, stats
    finally:
        os.environ.clear()
        os.environ.update(saved)
        shutil.rmtree(tmp, ignore_errors=True)


def cases(guard, seed, count):
    out = []
    for label, env in (("attended", {"ADCM_GUARD_FORCE": "1"}),
                       ("unattended", {"ADCM_GUARD_FORCE": "", "CLAUDE_CODE_SESSION_ATTENDED": "0"}),
                       ("low_caps", {"ADCM_GUARD_FORCE": "1", "ADCM_GUARD_BASH_CAP": "2", "ADCM_GUARD_READ_CAP": "1"})):
        n = count if label == "attended" else max(count // 3, 1)
        out.append((f"fuzz_{label}_{n}", lambda env=env, n=n, s=seed + len(out): fuzz(guard, s, n, env)))
    return out


def main():
    argv = sys.argv[1:]
    try:
        only = argv[argv.index("--only") + 1] if "--only" in argv else None
        guard = os.path.abspath(argv[argv.index("--guard") + 1]) if "--guard" in argv else GUARD
        seed = int(argv[argv.index("--seed") + 1]) if "--seed" in argv else 20261116
        count = int(argv[argv.index("--count") + 1]) if "--count" in argv else 3000
    except (IndexError, ValueError):
        print("usage: [--only SUBSTRING] [--guard PATH] [--seed N] [--count N] [--mutation]")
        return 64
    if "--mutation" in argv:
        spec = importlib.util.spec_from_file_location("mtg_harness", os.path.join(HERE, "compaction-breaker-selftest.py"))
        harness = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(harness)
        source = open(guard, encoding="utf-8").read()
        survivors, tmp = 0, tempfile.mkdtemp(prefix="mtg-fuzz-mutant-")
        try:
            for key in ("safe_probe",):
                path = os.path.join(tmp, "plugin", "scripts", "main-thread-guard.py")
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(harness.mutate(source, key))
                killed = any(fn()[0] for _, fn in cases(path, seed, count))
                print(f"KILLED {key}" if killed else f"SURVIVED {key}")
                survivors += 0 if killed else 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        print(f"{1 - survivors}/1 mutants killed")
        return 1 if survivors else 0
    failed = total = 0
    for name, fn in cases(guard, seed, count):
        if only and only not in name:
            continue
        total += 1
        problem, stats = fn()
        if problem:
            failed += 1
            print(f"FAIL {name}: {problem}")
        else:
            print(f"PASS {name}: {stats['inputs']} inputs, {stats['denies']} denies, {stats['injections']} injections")
    print(f"{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
