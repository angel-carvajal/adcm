#!/usr/bin/env python3
"""artifact-guard-selftest — behavioural tests for artifact-guard.py (stdlib only).

Usage:
  python3 artifact-guard-selftest.py [--guard PATH]

Builds a throwaway tree per case:
  T/proj/ai/ai-brain/{artifacts.json, task.md, plans.html, modules/m/{task.md, plans.html}}
sets mtimes with os.utime, writes a JSONL transcript (a human prompt at now-600, another
at now-300, then assistant text / tool_use entries), runs the guard as a subprocess with
HOME=T and stdin {cwd, transcript_path, stop_hook_active:false}, and prints
`PASS <case>` or `FAIL <case>: <why>`. Exit code 1 when any case fails.

The guard under test defaults to the artifact-guard.py that sits next to this file; pass
--guard to test an installed copy.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
URL_ROOT = "https://claude.ai/code/artifact/00000000-root"
URL_MOD = "https://claude.ai/code/artifact/00000000-module"
ART_ROOT = {"file": "plans.html", "url": URL_ROOT, "title": "Brain Plans", "favicon": "📒"}
ART_MOD = {"file": "modules/m/plans.html", "url": URL_MOD, "title": "Module Plans", "favicon": "🧩"}
# A row that also lives on another claude.ai account: `url` is the canonical link, `url_alt` the other account's.
URL_ALT = "https://claude.ai/code/artifact/00000000-other-account"
ART_ALT = dict(ART_ROOT, url_alt=URL_ALT)


def iso(epoch):
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def link(a):
    return f"- [{a['favicon']} {a['title']}]({a['url']})"


def block(*arts):
    return "\n".join(link(a) for a in arts)


def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def build(now, case):
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="guard-selftest-"))
    proj = os.path.join(tmp, "proj")
    brain = os.path.join(proj, "ai", "ai-brain")
    files = {
        "task.md": "# task\n",
        "plans.html": ROOT_HTML,
        "modules/m/task.md": "# module task\n",
        "modules/m/plans.html": "<html>module</html>\n",
    }
    for rel, body in files.items():
        write(os.path.join(brain, rel), body)
    mtimes = {"task.md": now - 1000, "plans.html": now - 1000,
              "modules/m/task.md": now - 1000, "modules/m/plans.html": now - 1000}
    mtimes.update(case.get("mtimes", {}))
    for rel, mt in mtimes.items():
        os.utime(os.path.join(brain, rel), (mt, mt))

    arts = []
    for base in case.get("arts", [ART_ROOT]):
        row = dict(base)
        row.update(case.get("stamp", {}).get(base["file"], {}))
        arts.append(row)
    registry = os.path.join(brain, "artifacts.json")
    if case.get("bad_registry"):
        write(registry, "{ this is not json")
    else:
        write(registry, json.dumps({"close_markers": ["task.md"], "artifacts": arts}, indent=2))

    transcript = os.path.join(tmp, "transcript.jsonl")
    if case.get("bad_transcript"):
        write(transcript, "garbage\n{not json\n[1,2,3]\n\x00\x01\n")
    else:
        entries = [
            {"type": "user", "timestamp": iso(now - 600), "message": {"role": "user", "content": "first request"}},
            {"type": "assistant", "timestamp": iso(now - 550),
             "message": {"content": [{"type": "text", "text": "working on it"}]}},
            {"type": "user", "timestamp": iso(now - 300), "message": {"role": "user", "content": "now close the wave"}},
            {"type": "assistant", "timestamp": iso(now - 250),
             "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "true"}}]}},
            {"type": "assistant", "timestamp": iso(now - 20),
             "message": {"content": [{"type": "text", "text": case.get("text", "done")}]}},
        ]
        for rel, ts in case.get("publishes", []):
            # Main-transcript Artifact publish of a registered file (absolute path, as the tool sees it).
            entries.insert(4, {"type": "assistant", "timestamp": iso(ts), "message": {"content": [
                {"type": "tool_use", "name": "Artifact",
                 "input": {"action": "publish", "file_path": os.path.join(brain, rel)}}]}})
        write(transcript, "\n".join(json.dumps(e) for e in entries) + "\n")
    return tmp, proj, transcript, brain


def run_guard(guard, tmp, proj, transcript):
    payload = json.dumps({"cwd": proj, "transcript_path": transcript, "stop_hook_active": False})
    env = dict(os.environ)
    env["HOME"] = tmp
    p = subprocess.run([sys.executable, guard], input=payload, capture_output=True, text=True, env=env, timeout=60)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def decision(out):
    try:
        data = json.loads(out)
    except Exception:
        return None, ""
    return data.get("decision"), data.get("reason") or data.get("systemMessage") or ""


def expect_block(rc, out, *needles):
    if rc != 0:
        return f"exit {rc}, expected 0"
    dec, reason = decision(out)
    if dec != "block":
        return f"expected a block decision, got: {out[:120] or '(no output)'}"
    for n in needles:
        if n not in reason:
            return f"reason lacks {n!r}"
    return None


def expect_silent(rc, out, *_):
    if rc != 0:
        return f"exit {rc}, expected 0"
    if out:
        return f"expected no output, got: {out[:160]}"
    return None


ROOT_HTML = "<html>root</html>\n"
ROOT_SHA = hashlib.sha256(ROOT_HTML.encode("utf-8")).hexdigest()


def make_cases(now):
    closing_text = "Wave closed.\n\n" + block(ART_ROOT)
    both_text = "Wave closed.\n\n" + block(ART_ROOT, ART_MOD)
    fresh_file = {"plans.html": now - 100}
    return [
        # (name, case spec, checker, extra args for the checker)
        ("stale_no_evidence",
         dict(mtimes=fresh_file, text=closing_text),
         lambda rc, out: expect_block(rc, out, "DESACTUALIZADOS", "plans.html"), None),
        ("registry_trust",
         dict(mtimes=fresh_file, text=closing_text,
              stamp={"plans.html": {"published_at": iso(now - 50), "version": "v2"}}),
         expect_silent, None),
        ("stamp_older",
         dict(mtimes=fresh_file, text=closing_text,
              stamp={"plans.html": {"published_at": iso(now - 200), "version": "v1"}}),
         lambda rc, out: expect_block(rc, out, "DESACTUALIZADOS", "plans.html"), None),
        ("sha_identical",
         dict(mtimes=fresh_file, text=closing_text,
              stamp={"plans.html": {"published_at": iso(now - 200), "version": "v1",
                                    "sha256": ROOT_SHA}}),
         expect_silent, None),
        ("multi_module",
         dict(arts=[ART_ROOT, ART_MOD], text=both_text,
              mtimes={"task.md": now - 100, "modules/m/task.md": now - 100}),
         expect_silent, None),
        ("multi_missing",
         dict(arts=[ART_ROOT, ART_MOD], text=closing_text,
              mtimes={"task.md": now - 100, "modules/m/task.md": now - 100}),
         lambda rc, out: expect_block(rc, out, "Module Plans"), None),
        ("courier_hint",
         dict(mtimes=fresh_file, text=closing_text),
         lambda rc, out: expect_block(rc, out, "artifact-courier", "sonnet"), None),
        ("text_after_links",
         dict(mtimes={"task.md": now - 100}, text=closing_text + "\n\nAll set, nothing else."),
         lambda rc, out: expect_block(rc, out, "DESPUÉS"), None),
        ("lan_without_localhost",
         dict(mtimes={"task.md": now - 100},
              text="Wave closed.\n\n- [📱 Preview · LAN](http://192.168.1.20:3000/)\n" + block(ART_ROOT)),
         lambda rc, out: expect_block(rc, out, "3000", "localhost"), None),
        # A stamp beyond the skew window (hand-edited / clock-skewed) must never disable the check.
        ("stamp_future",
         dict(mtimes=fresh_file, text=closing_text,
              stamp={"plans.html": {"published_at": "2099-01-01T00:00:00.000Z", "version": "v9"}}),
         lambda rc, out: expect_block(rc, out, "DESACTUALIZADOS", "plans.html"), None),
        # No stamp: a publish in the main transcript after the file's mtime is enough evidence.
        ("transcript_publish",
         dict(mtimes=fresh_file, text=closing_text, publishes=[("plans.html", now - 50)]),
         expect_silent, None),
        # Future mtime (beyond skew) with a courier stamp from this session counts as fresh.
        ("future_mtime_with_stamp",
         dict(mtimes={"plans.html": now + 600}, text=closing_text,
              stamp={"plans.html": {"published_at": iso(now - 50), "version": "v2"}}),
         expect_silent, None),
        # Session on the other account: the closing message lists the row's `url_alt` link, not `url`:
        # the guard accepts it (fail-open stays; it never blocks over a link it cannot tell apart).
        ("url_alt_account",
         dict(arts=[ART_ALT], mtimes=fresh_file, text="Wave closed.\n\n" + block(dict(ART_ALT, url=URL_ALT)),
              stamp={"plans.html": {"published_at": iso(now - 50), "version": "v2"}}),
         expect_silent, None),
        # ...but a link that is neither of the row's URLs is still a missing link.
        ("url_alt_account_unrelated_link_blocks",
         dict(arts=[ART_ALT], mtimes=fresh_file,
              text="Wave closed.\n\n" + block(dict(ART_ROOT, url="https://claude.ai/code/artifact/00000000-unrelated")),
              stamp={"plans.html": {"published_at": iso(now - 50), "version": "v2"}}),
         lambda rc, out: expect_block(rc, out, "Brain Plans"), None),
        ("fail_open",
         dict(bad_registry=True, bad_transcript=True),
         expect_silent, None),
    ]


def main():
    guard = os.path.join(HERE, "artifact-guard.py")
    argv = sys.argv[1:]
    if "--guard" in argv:
        i = argv.index("--guard")
        guard = os.path.abspath(os.path.expanduser(argv[i + 1]))
    if not os.path.isfile(guard):
        print(f"guard not found: {guard}")
        return 2

    now = time.time()
    failed = 0
    for name, spec, check, _ in make_cases(now):
        tmp = None
        try:
            tmp, proj, transcript, brain = build(now, spec)
            rc, out, _err = run_guard(guard, tmp, proj, transcript)
            problem = check(rc, out)
        except Exception as exc:  # a broken harness is a failure, not a crash
            problem = f"harness error: {exc!r}"
        finally:
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)
        if problem:
            failed += 1
            print(f"FAIL {name}: {problem}")
        else:
            print(f"PASS {name}")
    total = len(make_cases(now))
    print(f"{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
