#!/usr/bin/env python3
"""notify-stop-selftest - behavioural tests for notify-stop.py (stdlib only).

Usage:
  python3 notify-stop-selftest.py [--only SUBSTRING]

Per case: a throwaway JSONL transcript with timestamps relative to now, the hook run as a subprocess with the
Stop JSON on stdin and a clean env. Prints `PASS <case>` or `FAIL <case>: <why>`; exit 1 when any case fails.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "notify-stop.py")
PLUGIN = os.path.dirname(HERE)
CWD = "/srv/work/proj"
LINKS = "Done.\n\n- [Plans](https://example.test/artifact/1)\n- [Prompts](https://example.test/artifact/2)"


def iso(epoch):
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def human(ago, now, **extra):
    return {"type": "user", "timestamp": iso(now - ago), "message": {"role": "user", "content": "do the thing"}, **extra}


def meta(ago, now):
    return {"type": "user", "isMeta": True, "timestamp": iso(now - ago), "message": {"role": "user", "content": "ctx"}}


def task_note(ago, now):
    return {"type": "user", "origin": {"kind": "task-notification"}, "timestamp": iso(now - ago),
            "message": {"role": "user", "content": "<task-notification>done</task-notification>"}}


def tool_result(ago, now):
    return {"type": "user", "timestamp": iso(now - ago),
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}}


def assistant(ago, now, text="ok", tool=None):
    block = {"type": "tool_use", "id": "t1", "name": tool, "input": {}} if tool else {"type": "text", "text": text}
    return {"type": "assistant", "timestamp": iso(now - ago), "message": {"role": "assistant", "content": [block]}}


def run(entries, now, stdin=None, env=None, last="All done.", payload=None, transcript=True):
    tmp = tempfile.mkdtemp(prefix="notify-selftest-")
    try:
        path = os.path.join(tmp, "t.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(json.dumps(e) for e in entries) + "\n")
        data = {"session_id": "s1", "transcript_path": path if transcript else os.path.join(tmp, "missing.jsonl"),
                "cwd": CWD, "stop_hook_active": False, "last_assistant_message": last, "background_tasks": []}
        data.update(payload or {})
        e = {"PATH": os.environ.get("PATH", ""), "HOME": tmp}
        e.update(env or {})
        p = subprocess.run([sys.executable, HOOK], input=json.dumps(data) if stdin is None else stdin,
                           capture_output=True, text=True, env=e, timeout=30)
        return p.returncode, p.stdout.strip()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def silent(rc, out):
    return f"exit {rc}, expected 0" if rc else (f"expected no output, got {out[:120]}" if out else None)


def ctx_of(out):
    try:
        return json.loads(out)["hookSpecificOutput"]["additionalContext"]
    except Exception:
        return None


def fires(rc, out, *needles):
    if rc:
        return f"exit {rc}, expected 0"
    c = ctx_of(out)
    if c is None:
        return f"expected additionalContext, got {out[:120] or '(no output)'}"
    miss = [n for n in needles if n not in c]
    return f"context lacks {miss}: {c[:160]}" if miss else None


def turn(secs, now, *more):
    return [human(secs, now), assistant(secs - 1, now), *more]


def cases(now):
    cc = "CLAUDE_CODE_USE_" + "BEDROCK"
    ppl = lambda ago: assistant(ago, now, tool="PushNotification")
    out = []

    def add(name, fn):
        out.append((name, fn))

    add("short_turn_silent", lambda: silent(*run(turn(120, now), now)))
    add("long_turn_fires", lambda: fires(*run(turn(400, now), now), "Claude finished in proj", "ran 7 min",
                                         'status "proactive"', "select:PushNotification"))
    add("question_needs_you", lambda: fires(*run(turn(400, now), now, last="Which one do you want?"), "Claude needs you in proj"))
    add("push_this_turn_silent", lambda: silent(*run(turn(400, now, ppl(100)), now)))
    add("push_before_last_prompt_fires", lambda: fires(
        *run([human(900, now), ppl(800), human(400, now), assistant(399, now)], now), "Claude finished"))
    add("stop_hook_active_silent", lambda: silent(*run(turn(400, now), now, payload={"stop_hook_active": True})))
    add("background_running_silent", lambda: silent(*run(
        turn(400, now), now, payload={"background_tasks": [{"type": "shell", "status": "running"}]})))
    add("background_pending_silent", lambda: silent(*run(
        turn(400, now), now, payload={"background_tasks": [{"type": "shell", "status": "pending"}]})))
    add("session_cron_silent", lambda: silent(*run(
        turn(400, now), now, payload={"session_crons": [{"id": "c1"}]})))
    add("headless_entrypoint_silent", lambda: silent(*run(
        turn(400, now), now, env={"CLAUDE_CODE_ENTRYPOINT": "sdk-cli"})))
    add("background_done_fires", lambda: fires(*run(
        turn(400, now), now, payload={"background_tasks": [{"type": "shell", "status": "completed"}]})))
    add("notify_off_silent", lambda: silent(*run(turn(400, now), now, env={"ADCM_NOTIFY": "OFF"})))
    add("min_seconds_override_fires", lambda: fires(*run(turn(120, now), now, env={"ADCM_NOTIFY_MIN_SECONDS": "60"})))
    add("min_seconds_bad_value_300", lambda: silent(*run(turn(120, now), now, env={"ADCM_NOTIFY_MIN_SECONDS": "abc"})))
    add("ismeta_keeps_clock", lambda: fires(*run([human(400, now), assistant(399, now), meta(10, now)], now)))
    add("task_notification_keeps_clock", lambda: fires(*run([human(400, now), assistant(399, now), task_note(10, now)], now)))
    add("tool_result_keeps_clock", lambda: fires(*run([human(400, now), assistant(399, now), tool_result(10, now)], now)))
    add("real_prompt_resets_clock", lambda: silent(*run([human(400, now), assistant(399, now), human(30, now)], now)))
    add("no_human_prompt_silent", lambda: silent(*run([assistant(400, now)], now)))

    def links():
        rc, o = run(turn(400, now), now, last=LINKS)
        if rc:
            return f"exit {rc}"
        try:
            d = json.loads(o)
        except Exception:
            return f"not JSON: {o[:100]}"
        if "hookSpecificOutput" in d:
            return "links tail must not ask for a PushNotification"
        return None if d.get("terminalSequence") == "\u001b]9;Claude finished in proj\u0007" else f"bad sequence: {d}"
    add("links_tail_terminal_sequence", links)
    add("garbage_stdin_silent", lambda: silent(*run([], now, stdin="not json {")))
    add("missing_transcript_silent", lambda: silent(*run(turn(400, now), now, transcript=False)))
    add(f"cloud_env_silent", lambda: silent(*run(turn(400, now), now, env={cc: "1"})))

    def one_line():
        rc, o = run(turn(400, now), now, payload={"cwd": "/srv/work/pro\x07j\nx"})
        c = ctx_of(o)
        if c is None:
            return f"no context: {o[:100]}"
        m = c.split('message "', 1)[1].split('"', 1)[0]
        return None if "\n" not in m and "\x07" not in m and len(m) <= 200 else f"bad text: {m!r}"
    add("text_one_line_short", one_line)
    add("project_dir_beats_cwd", lambda: fires(*run(turn(400, now), now, env={"CLAUDE_PROJECT_DIR": "/srv/other/alpha"}),
                                                "Claude finished in alpha"))

    def long_folder():
        rc, o = run(turn(400, now), now, env={"CLAUDE_PROJECT_DIR": "/srv/" + "x" * 90})
        c = ctx_of(o)
        return f"no context: {o[:100]}" if c is None else (None if f'in {"x" * 60}"' in c else f"folder not cut to 60: {c[:140]}")
    add("long_folder_cut_60", long_folder)

    def hooks_json():
        try:
            h = json.load(open(os.path.join(PLUGIN, "hooks", "hooks.json"), encoding="utf-8"))["hooks"]
            cmds = [x["command"] for ev in ("SessionStart", "Stop") for g in h[ev] for x in g["hooks"]]
        except Exception as exc:
            return f"hooks.json unreadable: {exc!r}"
        bad = [c for c in cmds if '"${CLAUDE_PLUGIN_ROOT}' not in c]
        return f"unquoted ${{CLAUDE_PLUGIN_ROOT}}: {bad}" if bad or len(cmds) != 2 else None
    add("hooks_json_quoted", hooks_json)
    return out


def main():
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    now = time.time()
    failed = total = 0
    for name, fn in cases(now):
        if only and only not in name:
            continue
        total += 1
        try:
            problem = fn()
        except Exception as exc:
            problem = f"harness error: {exc!r}"
        if problem:
            failed += 1
            print(f"FAIL {name}: {problem}")
        else:
            print(f"PASS {name}")
    print(f"{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
