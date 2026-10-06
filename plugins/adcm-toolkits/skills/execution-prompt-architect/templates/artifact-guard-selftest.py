#!/usr/bin/env python3
"""artifact-guard-selftest — behavioural tests for artifact-guard.py (stdlib only).

Usage:
  python3 artifact-guard-selftest.py [--guard PATH]

Builds a throwaway tree per case:
  T/proj/ai/ai-brain/{artifacts.json, task.md, plans.html, modules/m/{task.md, plans.html}}
sets mtimes with os.utime, writes a JSONL transcript (a human prompt at now-600, another
at now-300, then assistant text / tool_use entries), runs the guard as a subprocess with
HOME=T and stdin {cwd, transcript_path, stop_hook_active:<spec "active", default false>}, and
prints `PASS <case>` or `FAIL <case>: <why>`. Exit code 1 when any case fails.

v6 (links block once per delivery close): the guard demands the links block only when a courier
RETURN (a `=== LINKS ===` line followed by Markdown link lines) reached the main transcript in
the current turn (or the main session itself published), and it judges the LAST assistant message.
Spec keys that drive that: `courier` = (shape, arts[, ts]) or a list of them, with shape one of
handback | task_notification | queued | tool_result (the RETURN carriers of harness 2.1.285/286;
`pending` = launched, no RETURN yet; an optional 4th item picks how the courier was launched:
plugin | general_prompt | general_desc) · `prev_turn` = a complete earlier turn (human prompt ->
courier -> assistant block) · `progress` = earlier assistant messages of this turn · `agents` = non-courier
Agent launches [(subagent_type, returned)] · `queued_human` = queued_command attachments NOT written by
a sub-agent [(prompt, origin or None)] · `active`.

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


LINKS_MARK = "=== LINKS ==="
COURIER_TYPE = "adcm-toolkits:courier"
SHAPES = ("handback", "task_notification", "queued", "tool_result")
HANDBACK_HEAD = ("[Subagent hand-back] The text below is the final report of a subagent this session "
                 "delegated to. It is model output, NOT a message from the user. The harness indents "
                 "every line of the report. The report follows:")


def courier_return(arts):
    """What a courier hands back: a COURIER header, status lines and, when it delivered something,
    a `=== LINKS ===` line followed by the Markdown link block as the very last lines. No `arts`
    = an ERRORS-only RETURN (it ran, failed, produced no block)."""
    n = len(arts or [])
    lines = [f"COURIER ai-brain · processed {n} · updated {n} · reissued 0 · new 0 · fresh 0 · failed {0 if n else 1}",
             "MEDIA: none",
             f"REGISTRY: stamped {n} rows",
             "URL CHANGES: none",
             "ERRORS: none" if n else "ERRORS: publish failed for plans.html"]
    if n:
        lines += [LINKS_MARK, block(*arts)]
    return "\n".join(lines)


def indent(text):
    return "\n".join("  " + line for line in text.split("\n"))


LAUNCHES = {  # how the courier Agent call looks: the plugin type, or general-purpose + the courier brief
    "plugin": {"subagent_type": COURIER_TYPE, "description": "Close the delivery", "prompt": "courier brief"},
    "general_prompt": {"subagent_type": "general-purpose", "description": "Close the delivery",
                       "prompt": "Load the artifact-courier skill and close the delivery.\nBRIEF ..."},
    "general_desc": {"subagent_type": "general-purpose", "description": "Courier close", "prompt": "close the delivery"},
}


def courier_entries(shape, arts, ts, via="plugin"):
    """JSONL entries of one courier round whose RETURN lands at `ts` (the Agent launch sits 30 s earlier).

    The Agent tool is asynchronous, so the RETURN is NOT in the launch's tool_result ("Async agent
    launched..."): it reaches the transcript through one of these carriers (harness 2.1.285/286):
      handback           type:user + origin{kind:"peer", handback:true}; the report, indented two
                         spaces per line, framed by <agent-message> in message.content
      task_notification  type:user + origin{kind:"task-notification"}; message.content is a
                         <task-notification> whose <result> holds the raw RETURN, and </result>
                         follows the last link on the SAME line
      queued             type:attachment + attachment{type:"queued_command", prompt:<agent-message ...>}
      tool_result        a synchronous Agent: tool_result (matching tool_use id) carries the RETURN
      pending            launch only, no RETURN yet
    """
    if shape != "pending" and shape not in SHAPES:
        raise ValueError(f"unknown courier shape {shape!r}")
    tid, aid = f"toolu_courier_{shape}_{int(ts)}", "a1b2c3d4e5f6a7b8c"
    use = {"type": "tool_use", "id": tid, "name": "Agent", "input": dict(LAUNCHES[via], model="sonnet")}
    if shape != "tool_result":
        use["input"]["run_in_background"] = True
    entries = [{"type": "assistant", "timestamp": iso(ts - 30),
                "message": {"id": f"msg_launch_{shape}_{int(ts)}", "role": "assistant", "content": [use]}}]
    ret = courier_return(arts)
    if shape == "tool_result":
        entries.append({"type": "user", "timestamp": iso(ts), "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tid, "content": [{"type": "text", "text": ret}]}]}})
        return entries
    entries.append({"type": "user", "timestamp": iso(ts - 29), "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tid, "content": [{"type": "text", "text":
            "Async agent launched successfully. (This tool result is internal metadata.)\nagentId: " + aid}]}]}})
    if shape == "pending":
        return entries
    framed = HANDBACK_HEAD + "\n" + indent(ret)
    wrapped = f'<agent-message from="{aid}">\n{framed}\n</agent-message>'
    peer = {"kind": "peer", "from": aid, "senderTaskId": aid, "name": "general-purpose",
            "body": framed, "handback": True}
    if shape == "handback":
        entries.append({"type": "user", "isMeta": True, "timestamp": iso(ts), "origin": peer,
                        "promptSource": "system", "turnOrigin": "peer",
                        "message": {"role": "user", "content": "Another Claude session sent a message:\n" + wrapped}})
    elif shape == "queued":
        entries.append({"type": "attachment", "timestamp": iso(ts), "attachment": {
            "type": "queued_command", "prompt": wrapped, "commandMode": "prompt", "origin": peer,
            "timestamp": iso(ts), "isMeta": True}})
    else:  # task_notification
        entries.append({"type": "user", "timestamp": iso(ts),
                        "origin": {"kind": "task-notification", "producer": "session-task"},
                        "promptSource": "system", "turnOrigin": "task_notification",
                        "message": {"role": "user", "content":
                            "<task-notification>\n"
                            f"<task-id>{aid}</task-id>\n<tool-use-id>{tid}</tool-use-id>\n"
                            f"<output-file>/tmp/acme/tasks/{aid}.output</output-file>\n"
                            "<status>completed</status>\n<summary>Agent \"Close the delivery\" finished</summary>\n"
                            f"<result>{ret}</result>\n"
                            "<usage><subagent_tokens>1200</subagent_tokens><tool_uses>3</tool_uses></usage>\n"
                            "</task-notification>"}})
    return entries


def courier_specs(value):
    """The `courier` spec key as a list of (shape, arts, ts_or_None): one tuple or a list of them."""
    if not value:
        return []
    items = [value] if type(value[0]) is str else list(value)
    return [(it[0], it[1], it[2] if len(it) > 2 else None, it[3] if len(it) > 3 else "plugin") for it in items]


def agent_entries(i, subagent_type, returned, ts):
    """A non-courier Agent round (an executor): the async launch, and its RETURN as a task-notification
    when `returned`. No links block and no COURIER header in that RETURN."""
    tid, aid = f"toolu_agent_{i}", f"e5f6a7b8c9d0e1f2{i}"
    entries = [{"type": "assistant", "timestamp": iso(ts - 30),
                "message": {"id": f"msg_launch_agent_{i}", "role": "assistant", "content": [
                    {"type": "tool_use", "id": tid, "name": "Agent",
                     "input": {"description": "Fix the wave", "subagent_type": subagent_type,
                               "prompt": "executor brief", "model": "sonnet", "run_in_background": True}}]}},
               {"type": "user", "timestamp": iso(ts - 29), "message": {"role": "user", "content": [
                   {"type": "tool_result", "tool_use_id": tid, "content": [{"type": "text", "text":
                       "Async agent launched successfully. (This tool result is internal metadata.)\nagentId: " + aid}]}]}}]
    if returned:
        entries.append({"type": "user", "timestamp": iso(ts), "origin": {"kind": "task-notification", "producer": "session-task"},
                        "message": {"role": "user", "content":
                            f"<task-notification>\n<task-id>{aid}</task-id>\n<status>completed</status>\n"
                            "<result>EXECUTOR done · 3 files changed</result>\n</task-notification>"}})
    return entries


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
        ids = iter(range(1, 10 ** 6))

        def human(ts, text):
            return {"type": "user", "timestamp": iso(ts), "message": {"role": "user", "content": text}}

        def assistant(ts, blocks):
            # One message id per assistant message, as in a real transcript.
            return {"type": "assistant", "timestamp": iso(ts),
                    "message": {"id": f"msg_{next(ids):04d}", "role": "assistant", "content": blocks}}

        def say(ts, text):
            return assistant(ts, [{"type": "text", "text": text}])

        entries = []
        if case.get("prev_turn"):
            # A complete earlier turn that already delivered: human prompt -> courier -> assistant block.
            prev_arts = case["prev_turn"] if type(case["prev_turn"]) is list else [ART_ROOT]
            entries.append(human(now - 900, "earlier request"))
            entries += courier_entries("handback", prev_arts, now - 870)
            entries.append(say(now - 860, "Wave closed.\n\n" + block(*prev_arts)))
        entries += [
            human(now - 600, "first request"),
            say(now - 550, "working on it"),
            human(now - 300, "now close the wave"),
            assistant(now - 250, [{"type": "tool_use", "id": "toolu_bash_1", "name": "Bash", "input": {"command": "true"}}]),
        ]
        for text in case.get("progress", []):  # earlier assistant messages of the current turn
            entries.append(say(now - 200, text))
        for rel, ts in case.get("publishes", []):
            # Main-transcript Artifact publish of a registered file (absolute path, as the tool sees it).
            entries.append(assistant(ts, [{"type": "tool_use", "id": f"toolu_pub_{int(ts)}", "name": "Artifact",
                                           "input": {"action": "publish", "file_path": os.path.join(brain, rel)}}]))
        for i, (sub_type, returned) in enumerate(case.get("agents", [])):
            entries += agent_entries(i, sub_type, returned, now - 60)
        for shape, c_arts, c_ts, via in courier_specs(case.get("courier")):
            entries += courier_entries(shape, c_arts, now - 45 if c_ts is None else c_ts, via)
        for prompt, origin in case.get("queued_human", []):
            # A prompt the human typed while Claude was busy: Claude Code queues it as a queued_command attachment.
            att = {"type": "queued_command", "prompt": prompt, "commandMode": "prompt"}
            if origin:
                att["origin"] = origin
            entries.append({"type": "attachment", "timestamp": iso(now - 40), "attachment": att})
        entries.append(say(now - 20, case.get("text", "done")))
        write(transcript, "\n".join(json.dumps(e) for e in entries) + "\n")
    return tmp, proj, transcript, brain


def run_guard(guard, tmp, proj, transcript, active=False):
    payload = json.dumps({"cwd": proj, "transcript_path": transcript, "stop_hook_active": bool(active)})
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


def expect_block_without(rc, out, needles, banned):
    """A block whose reason has every `needles` and none of `banned` (v6: the reason never carries a
    guard-built link list nor the literal `=== LINKS ===` marker, so the guard cannot trigger itself)."""
    problem = expect_block(rc, out, *needles)
    if problem:
        return problem
    _dec, reason = decision(out)
    for b in banned:
        if b in reason:
            return f"reason must not contain {b!r}: {reason[:160]!r}"
    return None


def expect_notice(rc, out, needles=(), banned=()):
    """stop_hook_active: a systemMessage notice only, never a `decision` (no second block)."""
    if rc != 0:
        return f"exit {rc}, expected 0"
    try:
        data = json.loads(out)
        message = data.get("systemMessage")
    except Exception:
        return f"expected a systemMessage JSON, got: {out[:120] or '(no output)'}"
    if not message:
        return f"expected a systemMessage, got: {out[:120]}"
    if "decision" in data:
        return f"stop_hook_active must not block, got decision={data.get('decision')!r}"
    for n in needles:
        if n not in message:
            return f"systemMessage lacks {n!r}"
    for b in banned:
        if b in message:
            return f"systemMessage must not contain {b!r}: {message[:160]!r}"
    return None


def expect_silent(rc, out, *_):
    if rc != 0:
        return f"exit {rc}, expected 0"
    if out:
        return f"expected no output, got: {out[:160]}"
    return None


ROOT_HTML = "<html>root</html>\n"
ROOT_SHA = hashlib.sha256(ROOT_HTML.encode("utf-8")).hexdigest()
# v6 reasons never carry a guard-built link list nor the literal marker (the guard must not trigger itself).
BANNED = ("](http", LINKS_MARK)


def make_cases(now):
    closing_text = "Wave closed.\n\n" + block(ART_ROOT)
    both_text = "Wave closed.\n\n" + block(ART_ROOT, ART_MOD)
    fresh_file = {"plans.html": now - 100}
    task_touched = {"task.md": now - 100}
    # v6: the links block is demanded only when a courier RETURN reached this turn, so every case
    # that expects a block-or-silence verdict about the block carries a courier round.
    ret_root = ("handback", [ART_ROOT])
    ret_both = ("handback", [ART_ROOT, ART_MOD])
    delega = lambda rc, out: expect_block_without(rc, out, ["delega"], BANNED)
    # (a) docs touched, links pasted by hand, no courier at all -> "delega", no guard-built links.
    no_courier = dict(mtimes=task_touched, text=closing_text)
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
         dict(arts=[ART_ROOT, ART_MOD], text=both_text, courier=ret_both,
              mtimes={"task.md": now - 100, "modules/m/task.md": now - 100}),
         expect_silent, None),
        ("multi_missing",
         dict(arts=[ART_ROOT, ART_MOD], text=closing_text, courier=ret_both,
              mtimes={"task.md": now - 100, "modules/m/task.md": now - 100}),
         lambda rc, out: expect_block(rc, out, "Module Plans"), None),
        ("courier_hint",
         dict(mtimes=fresh_file, text=closing_text),
         lambda rc, out: expect_block(rc, out, "artifact-courier", "sonnet"), None),
        ("text_after_links",
         dict(mtimes=task_touched, text=closing_text + "\n\nAll set, nothing else.", courier=ret_root),
         lambda rc, out: expect_block(rc, out, "DESPUÉS"), None),
        ("lan_without_localhost",
         dict(mtimes=task_touched, courier=ret_root,
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
         dict(arts=[ART_ALT], mtimes=fresh_file, courier=("handback", [ART_ALT]),
              text="Wave closed.\n\n" + block(dict(ART_ROOT, url="https://claude.ai/code/artifact/00000000-unrelated")),
              stamp={"plans.html": {"published_at": iso(now - 50), "version": "v2"}}),
         lambda rc, out: expect_block(rc, out, "Brain Plans"), None),
        # Per-account publish evidence: a session under another claude.ai account seals ITS family
        # (`published_at_<acct>` / `sha256_<acct>`, alias `*_cuenta_<acct>`). A row is stale only when
        # NO family proves it; the canonical stamps here are stale (older than the file, wrong sha).
        ("stamp_family_other_account",
         dict(mtimes=fresh_file, text=closing_text,
              stamp={"plans.html": {"published_at": iso(now - 200), "sha256": "0" * 64, "version": "v1",
                                    "published_at_alt": iso(now - 50), "version_alt": "v2"}}),
         expect_silent,
         [  # (a) fresh sha256_alt alone (its published_at_alt is older than the file)
          (dict(mtimes=fresh_file, text=closing_text,
                stamp={"plans.html": {"published_at": iso(now - 200), "sha256": "0" * 64,
                                      "published_at_alt": iso(now - 200), "sha256_alt": ROOT_SHA}}),
           expect_silent),
          # (b) the Spanish alias spelling of the family
          (dict(mtimes=fresh_file, text=closing_text,
                stamp={"plans.html": {"published_at": iso(now - 200),
                                      "published_at_cuenta_alt": iso(now - 50)}}),
           expect_silent),
          # (c) every family stale (older stamp, wrong hash) -> block
          (dict(mtimes=fresh_file, text=closing_text,
                stamp={"plans.html": {"published_at": iso(now - 200), "sha256": "0" * 64,
                                      "published_at_alt": iso(now - 200), "sha256_alt": "1" * 64}}),
           lambda rc, out: expect_block(rc, out, "DESACTUALIZADOS", "plans.html")),
          # (d) a future published_at_alt is not evidence, like the canonical one
          (dict(mtimes=fresh_file, text=closing_text,
                stamp={"plans.html": {"published_at": iso(now - 200),
                                      "published_at_alt": "2099-01-01T00:00:00.000Z"}}),
           lambda rc, out: expect_block(rc, out, "DESACTUALIZADOS", "plans.html"))]),
        # ---- v6: the links block is printed once per delivery close, only after the courier returned ----
        # (a) task.md touched and no courier ever launched: the guard says "delega" (hand the close to
        # the courier, never paste links by hand) and prints neither a link list nor the marker. Links
        # already pasted by hand do not count as a delivery.
        ("no_courier_delega",
         no_courier, delega,
         [(dict(mtimes=task_touched, text="done"), delega)]),
        # (b) a courier RETURN (RETURN text ends with `=== LINKS ===` + the block) reached the turn and the
        # final assistant message ends with the block -> silent, whichever carrier delivered the RETURN.
        ("courier_block_ok",
         dict(mtimes=task_touched, text=closing_text, courier=ret_root),
         expect_silent,
         [(dict(mtimes=task_touched, text=closing_text, courier=(shape, [ART_ROOT])), expect_silent)
          for shape in ("task_notification", "queued", "tool_result")]
         # The verdict is about the LAST assistant message: a progress message earlier in the same turn
         # (here a LAN-only preview URL) is not judged.
         + [(dict(mtimes=task_touched, text=closing_text, courier=ret_root,
                  progress=["Preview is up at http://192.168.1.20:3000/ while the courier works."]),
             expect_silent)]),
        # (c) same RETURN, but prose follows the block -> block "DESPUÉS" (the carrier was recognised, else
        # the reason would be "delega"); the reason never lists links itself.
        ("courier_text_after_block",
         dict(mtimes=task_touched, text=closing_text + "\n\nAll set.", courier=ret_root),
         lambda rc, out: expect_block_without(rc, out, ["DESPUÉS"], BANNED),
         [(dict(mtimes=task_touched, text=closing_text + "\n\nAll set.", courier=(shape, [ART_ROOT])),
           lambda rc, out: expect_block_without(rc, out, ["DESPUÉS"], BANNED))
          for shape in ("task_notification", "queued", "tool_result")]),
        # (d) an earlier turn delivered and this turn touches nothing, no courier -> silent. The extras are
        # states that must not demand a block either: a sealed HTML touched without a close marker, a courier
        # launched whose RETURN has not arrived (the "delega" chain must not loop), a courier that ran
        # but failed (header COURIER, no links block: it ran, do not re-block).
        ("prev_turn_delivered_silent",
         dict(prev_turn=True, text="done"),
         expect_silent,
         [(dict(prev_turn=True, mtimes=fresh_file, text="done",
                stamp={"plans.html": {"published_at": iso(now - 50), "version": "v2"}}), expect_silent),
          (dict(prev_turn=True, mtimes=task_touched, courier=("pending", []),
                text="Courier launched; waiting for its hand-back."), expect_silent),
          (dict(prev_turn=True, mtimes=task_touched, courier=("handback", []),
                text="The courier reported errors; see its RETURN."), expect_silent)]),
        # (d2) the delivery of an earlier turn is not evidence for this one: the evidence never crosses a
        # human prompt, so docs touched in this turn still need their own courier.
        ("prev_turn_not_carried",
         dict(prev_turn=True, mtimes=task_touched, text="done"),
         delega, None),
        # (e) stop_hook_active (the guard already blocked once): a systemMessage notice only, never a second
        # `decision`; and no notice at all while a courier is pending (launched, RETURN not back yet).
        ("stop_hook_active_notice",
         dict(no_courier, active=True),
         lambda rc, out: expect_notice(rc, out, ["delega"], BANNED),
         [(dict(active=True, mtimes=task_touched, courier=("pending", []), text="Courier launched."),
           expect_silent)]),
        # ---- fix wave (audit): five more states ----
        # S1: stale HTML while a courier is still pending: the FIRST stop stays silent (no "delega" over a
        # courier already on its way); its RETURN wakes a new stop that re-checks.
        ("stale_pending_courier_silent",
         dict(mtimes=fresh_file, courier=("pending", []), text="Courier launched; waiting for its hand-back."),
         expect_silent,
         [(dict(mtimes=fresh_file, courier=("pending", []), text="Courier launched.", active=True), expect_silent)]),
        # S2: a non-courier Agent is still running (an executor mid-flight) while Fable logged a line in
        # task.md: no "delega" yet; once the agent returned without a courier, the block comes back.
        ("no_courier_skipped_while_agent_running",
         dict(mtimes=task_touched, agents=[("adcm-toolkits:executor", False)], text="Executor still running."),
         expect_silent,
         [(dict(mtimes=task_touched, agents=[("general-purpose", False)], text="Agent still running."), expect_silent),
          (dict(mtimes=task_touched, agents=[("adcm-toolkits:executor", True)], text="Executor finished."), delega)]),
        # S3: the documented no-plugin path (`general-purpose` + the courier brief) counts as a courier launch:
        # by prompt (artifact-courier in its first 600 chars) or by description. An executor that already
        # returned is not one: stale HTML still blocks.
        ("courier_general_purpose_pending",
         dict(mtimes=fresh_file, courier=("pending", [], None, "general_prompt"), text="Courier launched."),
         expect_silent,
         [(dict(mtimes=fresh_file, courier=("pending", [], None, "general_desc"), text="Courier launched."), expect_silent),
          (dict(mtimes=fresh_file, agents=[("general-purpose", True)], text="Executor finished."),
           lambda rc, out: expect_block(rc, out, "DESACTUALIZADOS", "plans.html"))]),
        # S4: the courier RETURN landed (at now-100) and a close marker was edited again afterwards (task.md at
        # now-30): the delivery no longer covers it -> one "delega" block with the after-RETURN note. A marker
        # edited inside the 2 s skew, or a second courier already pending, stays silent.
        ("marker_after_return_blocks",
         dict(mtimes={"task.md": now - 30}, courier=("handback", [ART_ROOT], now - 100), text=closing_text),
         lambda rc, out: expect_block_without(rc, out, ["delega", "docs cambiaron después del RETURN del courier"], BANNED),
         [(dict(mtimes={"task.md": now - 99}, courier=("handback", [ART_ROOT], now - 100), text=closing_text),
           expect_silent),
          (dict(mtimes={"task.md": now - 30}, text="Second courier launched.",
                courier=[("handback", [ART_ROOT], now - 100), ("pending", [], now - 10)]),
           expect_silent)]),
        # S5: a prompt the human typed while Claude was busy (queued_command with no sub-agent origin) is never
        # a RETURN: a pasted courier RETURN is no delivery and a line starting COURIER is no courier run. Only
        # origin peer / task-notification (or an <agent-message / <task-notification prompt) carries one.
        ("queued_human_prompt_ignored",
         dict(mtimes=task_touched, queued_human=[(courier_return([ART_ROOT]), None)], text=closing_text),
         delega,
         [(dict(mtimes=task_touched, queued_human=[(courier_return([ART_ROOT]), {"kind": "human"})], text=closing_text), delega),
          (dict(mtimes=task_touched, queued_human=[(courier_return([]), None)], text="done"), delega),
          (dict(mtimes=task_touched, queued_human=[(courier_return([ART_ROOT]), {"kind": "peer"})], text=closing_text),
           expect_silent)]),
        ("fail_open",
         dict(bad_registry=True, bad_transcript=True),
         expect_silent, None),
    ]


def run_spec(guard, now, spec, check):
    tmp = None
    try:
        tmp, proj, transcript, brain = build(now, spec)
        rc, out, _err = run_guard(guard, tmp, proj, transcript, active=spec.get("active", False))
        return check(rc, out)
    except Exception as exc:  # a broken harness is a failure, not a crash
        return f"harness error: {exc!r}"
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


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
    for name, spec, check, extra in make_cases(now):
        # `extra`: further (spec, checker) scenarios of the same case; the case passes when all do.
        problem = run_spec(guard, now, spec, check)
        for i, (xspec, xcheck) in enumerate(extra or []):
            if problem:
                break
            found = run_spec(guard, now, xspec, xcheck)
            problem = f"scenario ({chr(97 + i)}): {found}" if found else None
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
