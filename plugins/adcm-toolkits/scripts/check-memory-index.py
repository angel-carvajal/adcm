#!/usr/bin/env python3
"""Check that MEMORY.md indexes stay small enough to load whole.

Usage: check-memory-index.py [--file PATH]... | --all [--config-dir DIR]
       [--max-line 150] [--max-tokens 4000] [--json] [--brief]
Estimate of tokens = ceil(chars / 3.0). Exit 0 ok, 1 over a limit, 64 usage.
"""
import glob
import json
import math
import os
import sys

USAGE = __doc__


def check(path, max_line, max_tokens):
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    lines = text.splitlines()
    longest = max((len(l) for l in lines), default=0)
    est = int(math.ceil(len(text) / 3.0))
    over = [i + 1 for i, l in enumerate(lines) if len(l) > max_line]
    problems = []
    if len(over) > 0 and longest > max_line:  # MUTATION-KEY: line-limit
        problems.append("line: %d line(s) over %d chars (first: %d)" % (len(over), max_line, over[0]))
    if est > max_tokens:  # MUTATION-KEY: token-limit
        problems.append("tokens: estimate %d over %d" % (est, max_tokens))
    return {"file": path, "ok": not problems, "lines": len(lines), "bytes": len(text.encode("utf-8")),
            "chars": len(text), "est_tokens": est, "longest_line": longest, "lines_over": over,
            "problems": problems}


def main(argv):
    files, use_all, cfg, js, brief = [], False, None, False, False
    max_line, max_tokens = 150, 4000
    a = list(argv)
    try:
        while a:
            x = a.pop(0)
            if x == "--file":
                files.append(a.pop(0))
            elif x == "--all":
                use_all = True
            elif x == "--config-dir":
                cfg = a.pop(0)
            elif x == "--max-line":
                max_line = int(a.pop(0))
            elif x == "--max-tokens":
                max_tokens = int(a.pop(0))
            elif x == "--json":
                js = True
            elif x == "--brief":
                brief = True
            else:
                raise ValueError(x)
    except (IndexError, ValueError):
        sys.stderr.write(USAGE)
        return 64
    if use_all or not files:
        base = cfg or os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
        files += sorted(glob.glob(os.path.join(base, "projects", "*", "memory", "MEMORY.md")))
    for f in files:
        if not os.path.isfile(f):
            sys.stderr.write("no existe: %s\n" % f)
            return 64
    res = [check(f, max_line, max_tokens) for f in files]
    bad = [r for r in res if not r["ok"]]
    if js:
        print(json.dumps({"files": res, "ok": not bad}, indent=1))
    elif brief:
        for r in bad:
            print("MEMORY.md demasiado grande (%s): %d líneas, %d tokens est., línea más larga %d; resume cada línea del índice y mueve el detalle a su archivo."
                  % (r["file"], r["lines"], r["est_tokens"], r["longest_line"]))
    else:
        for r in res:
            print("%s %s: %d lines, %d bytes, ~%d tokens, longest %d%s" % (
                "OK  " if r["ok"] else "FAIL", r["file"], r["lines"], r["bytes"], r["est_tokens"],
                r["longest_line"], "".join("; " + p for p in r["problems"])))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
