#!/usr/bin/env python3
"""Selftest for check-memory-index.py. Usage: [--only SUBSTR] [--script PATH] [--mutation]"""
import json, os, subprocess, sys, tempfile, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "check-memory-index.py")
RESULTS = []


def run(script, args, env_extra=None):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONDONTWRITEBYTECODE": "1"}
    env.update(env_extra or {})
    p = subprocess.run([sys.executable, "-B", script] + args, capture_output=True, text=True, env=env, timeout=30)
    return p.returncode, p.stdout, p.stderr


def mk(tmp, text, name="MEMORY.md"):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def good_index(n=5):
    return "# Memory index\n\n" + "".join("- [Note %d](note%d.md) - short hook %d\n" % (i, i, i) for i in range(n))


def cases(script):
    out = []

    def case(name, fn):
        out.append((name, fn))

    def ok_small(tmp):
        rc, o, e = run(script, ["--file", mk(tmp, good_index())])
        return (rc == 0, "rc=%d" % rc)

    def long_line(tmp):
        txt = good_index() + "- [Big](big.md) - " + "x" * 200 + "\n"
        rc, o, e = run(script, ["--file", mk(tmp, txt)])
        return (rc == 1 and "line" in (o + e).lower(), "rc=%d" % rc)

    def line_boundary(tmp):
        line = "- [A](a.md) - " + "y" * (150 - len("- [A](a.md) - "))
        assert len(line) == 150
        rc, o, e = run(script, ["--file", mk(tmp, line + "\n")])
        rc2, _, _ = run(script, ["--file", mk(tmp, line + "z\n", "M2.md")])
        return (rc == 0 and rc2 == 1, "rc=%d/%d" % (rc, rc2))

    def too_many_tokens(tmp):
        txt = "".join("- [N%d](n%d.md) - %s\n" % (i, i, "w" * 100) for i in range(150))
        rc, o, e = run(script, ["--file", mk(tmp, txt)])
        return (rc == 1 and "token" in (o + e).lower(), "rc=%d" % rc)

    def token_flag(tmp):
        txt = "x" * 90 + "\n"
        rc, _, _ = run(script, ["--file", mk(tmp, txt), "--max-tokens", "20", "--max-line", "200"])
        rc2, _, _ = run(script, ["--file", mk(tmp, txt, "M2.md"), "--max-tokens", "40", "--max-line", "200"])
        return (rc == 1 and rc2 == 0, "rc=%d/%d" % (rc, rc2))

    def json_out(tmp):
        rc, o, e = run(script, ["--file", mk(tmp, good_index()), "--json"])
        try:
            d = json.loads(o)
        except Exception as ex:
            return (False, "bad json %s" % ex)
        f = d["files"][0] if isinstance(d, dict) else d[0]
        return (rc == 0 and f["ok"] is True and f["lines"] > 0 and f["est_tokens"] > 0, str(f))

    def brief_ok_silent(tmp):
        rc, o, e = run(script, ["--file", mk(tmp, good_index()), "--brief"])
        return (rc == 0 and o.strip() == "", repr(o))

    def brief_fail_spanish(tmp):
        rc, o, e = run(script, ["--file", mk(tmp, good_index() + "z" * 400 + "\n"), "--brief"])
        lines = [l for l in o.splitlines() if l.strip()]
        return (rc == 1 and len(lines) == 1 and "MEMORY" in lines[0] and "línea" in lines[0] and "al cerrar la fase" in lines[0], repr(o))

    def usage(tmp):
        rc, _, _ = run(script, ["--bogus"])
        rc2, _, _ = run(script, ["--file", os.path.join(tmp, "nope.md")])
        return (rc == 64 and rc2 == 64, "rc=%d/%d" % (rc, rc2))

    def all_mode(tmp):
        for proj, txt in (("p1", good_index()), ("p2", good_index() + "q" * 300 + "\n")):
            d = os.path.join(tmp, "projects", proj, "memory")
            os.makedirs(d)
            mk(d, txt)
        rc, o, e = run(script, ["--all", "--config-dir", tmp, "--brief"])
        lines = [l for l in o.splitlines() if l.strip()]
        rc_ok, _, _ = run(script, ["--all", "--config-dir", tmp, "--max-line", "400", "--max-tokens", "9000"])
        return (rc == 1 and len(lines) == 1 and rc_ok == 0, "rc=%d lines=%d rc_ok=%d" % (rc, len(lines), rc_ok))

    def all_env(tmp):
        d = os.path.join(tmp, "projects", "p1", "memory")
        os.makedirs(d)
        mk(d, good_index())
        rc, _, _ = run(script, ["--all"], {"CLAUDE_CONFIG_DIR": tmp})
        return (rc == 0, "rc=%d" % rc)

    for n, f in [("small-index-passes", ok_small), ("long-line-fails", long_line),
                 ("line-limit-boundary", line_boundary), ("token-limit-fails", too_many_tokens),
                 ("token-flag-boundary", token_flag), ("json-shape", json_out),
                 ("brief-silent-when-ok", brief_ok_silent), ("brief-spanish-when-fail", brief_fail_spanish),
                 ("usage-errors-64", usage), ("all-mode-config-dir", all_mode), ("all-mode-env", all_env)]:
        case(n, f)
    return out


def suite(script, only=None):
    passed = total = 0
    for name, fn in cases(script):
        if only and only not in name:
            continue
        total += 1
        tmp = tempfile.mkdtemp(prefix="mic-")
        try:
            good, why = fn(tmp)
        except Exception as ex:
            good, why = False, "exception %r" % ex
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        print(("PASS %s" % name) if good else ("FAIL %s: %s" % (name, why)))
        passed += good
    print("%d/%d passed" % (passed, total))
    return passed == total


def mutation():
    src = open(SCRIPT, encoding="utf-8").read().splitlines(True)
    keys = [(i, l.split("MUTATION-KEY:")[1].strip()) for i, l in enumerate(src) if "MUTATION-KEY:" in l]
    if not keys:
        print("FAIL no MUTATION-KEY markers")
        return False
    survived = False
    for i, key in keys:
        mut = list(src)
        indent = mut[i][: len(mut[i]) - len(mut[i].lstrip())]
        head = mut[i].lstrip().split(None, 1)[0]  # if / elif
        mut[i] = "%s%s False:  # mutated\n" % (indent, head)
        tmp = tempfile.mkdtemp(prefix="mic-mut-")
        try:
            path = os.path.join(tmp, "mutant.py")
            open(path, "w", encoding="utf-8").write("".join(mut))
            import io, contextlib
            with contextlib.redirect_stdout(io.StringIO()):
                ok = suite(path)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if ok:
            print("SURVIVED %s" % key)
            survived = True
        else:
            print("KILLED %s" % key)
    return not survived


def main():
    a = sys.argv[1:]
    only = script = None
    mut = False
    while a:
        x = a.pop(0)
        if x == "--only" and a:
            only = a.pop(0)
        elif x == "--script" and a:
            script = a.pop(0)
        elif x == "--mutation":
            mut = True
        else:
            print("usage: memory-index-check-selftest.py [--only S] [--script P] [--mutation]")
            return 64
    if mut:
        return 0 if mutation() else 1
    return 0 if suite(script or SCRIPT, only) else 1


if __name__ == "__main__":
    sys.exit(main())
