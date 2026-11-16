#!/usr/bin/env python3
"""Run every *-selftest.py of the plugin and print one result line per suite plus a total.

  python3 selftest-all.py [--only SUBSTR] [--list] [--mutation] [--timeout SECONDS]

--only SUBSTR   run just the suites whose path contains SUBSTR
--list          print the discovered suites and exit
--mutation      run `--mutation` on the suites that support it (a mutant that survives fails the suite)
Exit 0 when every suite passes, 1 when any fails, 64 on bad usage. The three main-thread guard suites run last.
"""
import os
import re
import subprocess
import sys
import time

sys.stdout.reconfigure(line_buffering=True)

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAST = ("guard-fuzz", "compaction-breaker", "main-thread-budget", "heavy-read-guard")


def discover():
    found = []
    for root, dirs, files in os.walk(PLUGIN):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "node_modules")]
        found += [os.path.join(root, f) for f in files if f.endswith("-selftest.py")]
    key = lambda p: (any(n in os.path.basename(p) for n in LAST), os.path.relpath(p, PLUGIN))
    return sorted(found, key=key)


def supports_mutation(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return "--mutation" in fh.read()
    except OSError:
        return False


def counts(out):
    m = re.findall(r"(\d+)\s*/\s*(\d+)\s+(?:checks?\s+)?(?:passed|ok)", out, re.I)
    if m:
        return int(m[-1][0]), int(m[-1][1])
    m = re.findall(r"(\d+) PASS . (\d+) FAIL . (\d+) SKIP \(of (\d+)\)", out)
    if m:
        return int(m[-1][0]), int(m[-1][3])
    m = re.findall(r"(\d+)/(\d+)\s*$", out, re.M)
    if m:
        return int(m[-1][0]), int(m[-1][1])
    k = re.findall(r"KILLED", out)
    return (len(k), len(k)) if k else (0, 0)


def main(argv):
    only, listing, mutation, timeout = None, False, False, 900
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--list":
            listing = True
        elif a == "--mutation":
            mutation = True
        elif a in ("--only", "--timeout") and i + 1 < len(argv):
            i += 1
            if a == "--only":
                only = argv[i]
            else:
                try:
                    timeout = int(argv[i])
                except ValueError:
                    print("usage: --timeout takes whole seconds", file=sys.stderr)
                    return 64
        else:
            print(__doc__, file=sys.stderr)
            return 64
        i += 1
    suites = [s for s in discover() if only is None or only in os.path.relpath(s, PLUGIN)]
    if mutation:
        suites = [s for s in suites if supports_mutation(s)]
    if listing:
        for s in suites:
            print(os.path.relpath(s, PLUGIN) + ("  [mutation]" if supports_mutation(s) else ""))
        return 0
    if not suites:
        print("no suites matched", file=sys.stderr)
        return 64
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    failed, ok_n, all_n = [], 0, 0
    for s in suites:
        rel = os.path.relpath(s, PLUGIN)
        cmd = [sys.executable, "-B", s] + (["--mutation"] if mutation else [])
        t0 = time.time()
        try:
            p = subprocess.run(cmd, cwd=os.path.dirname(s), env=env, capture_output=True, text=True, timeout=timeout)
            out, rc = (p.stdout or "") + (p.stderr or ""), p.returncode
        except subprocess.TimeoutExpired:
            out, rc = "timeout", 1
        a, b = counts(out)
        ok_n, all_n = ok_n + a, all_n + b
        if rc != 0:
            failed.append(rel)
        print("%-4s %-82s %4d/%-4d %5.1fs" % ("OK" if rc == 0 else "FAIL", rel, a, b, time.time() - t0))
        if rc != 0:
            for line in out.strip().splitlines()[-8:]:
                print("     " + line[:200])
    print("TOTAL%s: %d suites · %d failed · %d/%d checks" % (" (mutation)" if mutation else "", len(suites), len(failed), ok_n, all_n))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
