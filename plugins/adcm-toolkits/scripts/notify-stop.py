#!/usr/bin/env python3
# Stop hook: after a long turn, asks the main session to send one phone notification (PushNotification).
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

LINK_LINE = re.compile(r"^\s*(?:[-*•]\s*)?\[[^\]]+\]\(\S+\)\s*$")
CTRL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
CLOUD = ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")
DONE = {"completed", "done", "failed", "killed", "stopped", "cancelled", "canceled"}


def is_human_prompt(entry):
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isCompactSummary"):
        return False
    origin = entry.get("origin") or {}
    if isinstance(origin, dict) and origin.get("kind") and origin.get("kind") != "human":
        return False
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return not content.lstrip().startswith("<task-notification>")
    if isinstance(content, list):
        kinds = {b.get("type") for b in content if isinstance(b, dict)}
        if "text" not in kinds or "tool_result" in kinds:
            return False
        first = next((b.get("text") for b in content if isinstance(b, dict) and b.get("type") == "text"), "")
        return not str(first).lstrip().startswith("<task-notification>")
    return False


def is_push_call(entry):
    if entry.get("type") != "assistant":
        return False
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "PushNotification" for b in content)


def epoch(entry):
    return datetime.fromisoformat(str(entry["timestamp"]).replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()


def clock_start(path):
    human = push = None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                entry = json.loads(line)
                if is_human_prompt(entry):
                    human, push = epoch(entry), None
                elif human is not None and is_push_call(entry):
                    push = epoch(entry)
            except Exception:
                continue
    return None if human is None or push is not None else human


def main():
    data = json.load(sys.stdin)
    if str(os.environ.get("ADCM_NOTIFY", "")).strip().lower() == "off" or data.get("stop_hook_active"):
        return
    if any(os.environ.get(k) for k in CLOUD):
        return
    # Headless runs nudge a text-less turn into writing again, which would replace the real final message.
    if os.environ.get("CLAUDE_CODE_ENTRYPOINT", "").startswith("sdk"):
        return
    if any(not isinstance(t, dict) or t.get("status") not in DONE for t in data.get("background_tasks") or []):
        return
    if data.get("session_crons"):
        return
    start = clock_start(data["transcript_path"])
    if start is None:
        return
    try:
        minimum = int(os.environ.get("ADCM_NOTIFY_MIN_SECONDS", "300"))
    except ValueError:
        minimum = 300
    elapsed = time.time() - start
    if elapsed < minimum:
        return
    base = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or ""
    folder = CTRL.sub("", os.path.basename(base.rstrip("/\\")))[:60]
    final = str(data.get("last_assistant_message") or "").strip()
    text = f"Claude needs you in {folder}" if final.endswith("?") else f"Claude finished in {folder}"
    lines = [l for l in final.split("\n") if l.strip()]
    if lines and LINK_LINE.match(lines[-1]):
        out = {"terminalSequence": f"\u001b]9;{text}\u0007"}
    else:
        minutes = max(1, round(elapsed / 60))
        out = {"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": (
            f'adcm-toolkits notify: this turn ran {minutes} min. Call PushNotification once with message "{text}" '
            'and status "proactive" (deferred: ToolSearch query "select:PushNotification"; no such tool → skip). '
            '"not sent" is fine; never retry. Then end the turn WITHOUT writing any text — your previous message '
            'stays the final one — unless another hook asked you for something; do that after this call.')}}
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        pass
    sys.exit(0)
