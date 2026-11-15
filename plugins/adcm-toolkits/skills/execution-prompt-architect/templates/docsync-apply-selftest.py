#!/usr/bin/env python3
"""docsync-apply-selftest - behavioural tests for docsync_apply.py (stdlib only).

Usage: python3 docsync-apply-selftest.py [--tool PATH] [--only SUBSTR] [--mutation]

Every case builds a throwaway temp tree, runs the tool as a subprocess with a clean env and
prints PASS|FAIL <case>. Last line `N/N passed`; exit 1 on any failure.
--mutation copies the tool, neutralises ONE line marked `# MUTATION-KEY: <name>` per mutant,
re-runs the suite against the mutant and requires it to FAIL (`KILLED <name>`).
Fixtures are generic (project "Acme").
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LONG = "x" * 301
DOC = ("# Plan\n\n## Tasks\n- [ ] T-1 build\n- [ ] T-2 ship\n\n## Notes\nalpha beta\nalpha beta\n\n"
       "## Table\n| id | name |\n|----|------|\n| 1 | one |\n\n## Other\n| id | name |\n|--|--|\n| 9 | nine |\n")
LOG_NEW = "## Logbook\nAppend one entry per wave.\n### 2026-01-02 — W2\n- a\n\n### 2026-01-01 — W1\n- b\n\n## Footer\nend\n"
LOG_OLD = "## Logbook\nAppend one entry per wave.\n### 2026-01-01 — W1\n- b\n\n### 2026-01-02 — W2\n- a\n\n## Footer\nend\n"
ENTRY = "### 2026-01-03 — W3\n- c"
CASES = []


def case(fn):
    CASES.append(fn)
    return fn


class Run:
    def __init__(self, tool, files, sheet, markers=None, args=("--check",), raw_files=None, root=True):
        self.dir = tempfile.mkdtemp(prefix="dsa-")
        self.tool = tool
        for name, text in (files or {}).items():
            with open(os.path.join(self.dir, name), "w", encoding="utf-8", newline="") as f:
                f.write(text)
        for name, data in (raw_files or {}).items():
            with open(os.path.join(self.dir, name), "wb") as f:
                f.write(data)
        sp = os.path.join(self.dir, "_sheet.json")
        with open(sp, "w") as f:
            f.write(sheet if isinstance(sheet, str) else json.dumps({"edits": sheet}))
        cmd = [sys.executable, "-B", tool, "--sheet", sp]
        if markers is not None:
            mp = os.path.join(self.dir, "_markers.json")
            with open(mp, "w") as f:
                json.dump(markers, f)
            cmd += ["--markers", mp]
        if root:
            cmd += ["--root", self.dir]
        cmd += list(args)
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1", "LC_ALL": "C.UTF-8"}
        p = subprocess.run(cmd, capture_output=True, env=env, timeout=60)
        self.rc = p.returncode
        self.out = p.stdout.decode("utf-8", "replace")
        self.err = p.stderr.decode("utf-8", "replace")
        self.last = self.out.strip().splitlines()[-1] if self.out.strip() else ""

    def read(self, name):
        with open(os.path.join(self.dir, name), "rb") as f:
            return f.read().decode("utf-8")

    def done(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def expect(cond, why):
    if not cond:
        raise AssertionError(why)


def e(op, **kw):
    d = {"file": "d.md", "op": op, "why": "t"}
    d.update(kw)
    return d


def summary(r, ok, failed, opn):
    want = "DOCSYNC: %d ok · %d failed · %d open placeholders" % (ok, failed, opn)
    expect(r.last == want, "last line %r != %r" % (r.last, want))


def one(tool, files, edits, args=("--check",), markers=None, **kw):
    return Run(tool, files, edits, markers=markers, args=args, **kw)


# ---- sub
@case
def sub_match(tool):
    r = one(tool, {"d.md": DOC}, [e("sub", old="build", new="built")], ("--write",))
    expect(r.rc == 0, r.out)
    expect("T-1 built" in r.read("d.md"), "not replaced")
    summary(r, 1, 0, 0)
    r.done()


@case
def sub_no_match(tool):
    r = one(tool, {"d.md": DOC}, [e("sub", old="zzz", new="y")])
    expect(r.rc == 1, "rc %s" % r.rc)
    expect("d.md" in r.out and "#0" in r.out and "t" in r.out and "0 match" in r.out, r.out)
    summary(r, 0, 1, 0)
    r.done()


@case
def sub_too_many(tool):
    r = one(tool, {"d.md": DOC}, [e("sub", old="alpha", new="gamma")], ("--write",))
    expect(r.rc == 1, "rc")
    expect("alpha" in r.read("d.md") and "gamma" not in r.read("d.md"), "file touched")
    expect("2 match" in r.out, r.out)
    r.done()


@case
def sub_count_two(tool):
    r = one(tool, {"d.md": DOC}, [e("sub", old="alpha", new="gamma", count=2)], ("--write",))
    expect(r.rc == 0 and r.read("d.md").count("gamma") == 2, r.out)
    r.done()


@case
def sub_already_applied(tool):
    r = one(tool, {"d.md": DOC.replace("build", "built")}, [e("sub", old="build", new="built")])
    expect(r.rc == 0 and "already applied" in r.out, r.out)
    summary(r, 1, 0, 0)
    r.done()


@case
def sub_scope(tool):
    ed = [e("sub", old="| 1 | one |", new="| 1 | uno |", scope="Table")]
    r = one(tool, {"d.md": DOC}, ed, ("--write",))
    expect(r.rc == 0 and "| 1 | uno |" in r.read("d.md"), r.out)
    r.done()
    # scope limits the search: 'nine' lives under Other
    r = one(tool, {"d.md": DOC}, [e("sub", old="nine", new="NINE", scope="Table")])
    expect(r.rc == 1, "scope leaked")
    r.done()
    r = one(tool, {"d.md": DOC}, [e("sub", old="alpha", new="g", scope="Missing heading")])
    expect(r.rc == 1 and "heading" in r.out, r.out)
    r.done()


# ---- tick
@case
def tick_ops(tool):
    r = one(tool, {"d.md": DOC}, [e("tick", match="T-1", suffix=" (done)")], ("--write",))
    expect(r.rc == 0 and "- [x] T-1 build (done)" in r.read("d.md"), r.out)
    r.done()
    r = one(tool, {"d.md": "- [x] T-1 build\n"}, [e("tick", match="T-1")])
    expect(r.rc == 0 and "already applied" in r.out, r.out)
    r.done()
    r = one(tool, {"d.md": DOC}, [e("tick", match="T-9")])
    expect(r.rc == 1, "no match must fail")
    r.done()
    r = one(tool, {"d.md": DOC}, [e("tick", match="T-")])
    expect(r.rc == 1 and "2 match" in r.out, r.out)
    r.done()


# ---- insert
@case
def insert_ops(tool):
    r = one(tool, {"d.md": DOC}, [e("insert_after", anchor="## Tasks", text="intro"),
                                   e("insert_before", anchor="## Notes", text="a\nb")], ("--write",))
    expect(r.rc == 0, r.out)
    t = r.read("d.md")
    expect("## Tasks\nintro\n- [ ] T-1" in t and "a\nb\n## Notes" in t, t)
    r.done()
    r = one(tool, {"d.md": DOC.replace("## Tasks\n", "## Tasks\nintro\n")}, [e("insert_after", anchor="## Tasks", text="intro")])
    expect(r.rc == 0 and "already applied" in r.out, r.out)
    r.done()
    r = one(tool, {"d.md": DOC}, [e("insert_after", anchor="nope", text="x")])
    expect(r.rc == 1, "no anchor")
    r.done()
    r = one(tool, {"d.md": DOC}, [e("insert_before", anchor="alpha", text="x")])
    expect(r.rc == 1 and "2 match" in r.out, r.out)
    r.done()
    r = one(tool, {"d.md": DOC}, [e("insert_after", anchor="| id | name |", text="x")])
    expect(r.rc == 1, "ambiguous anchor must fail")
    r.done()


# ---- append_rows
@case
def append_rows_ops(tool):
    ed = [e("append_rows", anchor="## Table", text="| 2 | two |\n| 3 | three |")]
    r = one(tool, {"d.md": DOC}, ed, ("--write",))
    expect(r.rc == 0 and "| 1 | one |\n| 2 | two |\n| 3 | three |\n\n## Other" in r.read("d.md"), r.read("d.md"))
    r.done()
    r = one(tool, {"d.md": DOC}, [e("append_rows", anchor="| id | name |", text="| 2 | two |", scope="Other")], ("--write",))
    expect(r.rc == 0 and "| 9 | nine |\n| 2 | two |" in r.read("d.md"), r.out)
    r.done()
    r = one(tool, {"d.md": DOC.replace("| 1 | one |", "| 1 | one |\n| 2 | two |")}, [e("append_rows", anchor="## Table", text="| 2 | two |")])
    expect(r.rc == 0 and "already applied" in r.out, r.out)
    r.done()
    r = one(tool, {"d.md": DOC}, [e("append_rows", anchor="## Tasks", text="| 2 | two |")])
    expect(r.rc == 1 and "table" in r.out, r.out)
    r.done()
    r = one(tool, {"d.md": DOC}, [e("append_rows", anchor="## Nowhere", text="| 2 |")])
    expect(r.rc == 1, "no anchor")
    r.done()


# ---- logbook
@case
def logbook_ops(tool):
    r = one(tool, {"d.md": LOG_NEW}, [e("logbook", heading="Logbook", text=ENTRY)], ("--write",))
    t = r.read("d.md")
    expect(r.rc == 0 and t.index("W3") < t.index("W2") and "## Logbook\nAppend one entry per wave.\n### 2026-01-03" in t, t)
    r.done()
    r = one(tool, {"d.md": LOG_OLD}, [e("logbook", heading="## Logbook", text=ENTRY)], ("--write",))
    t = r.read("d.md")
    expect(r.rc == 0 and t.index("W2") < t.index("W3") < t.index("## Footer") and "- c\n\n## Footer" in t, t)
    r.done()
    r = one(tool, {"d.md": LOG_NEW.replace("## Footer", ENTRY + "\n\n## Footer")}, [e("logbook", heading="Logbook", text=ENTRY)])
    expect(r.rc == 0 and "already applied" in r.out, r.out)
    r.done()
    r = one(tool, {"d.md": LOG_NEW}, [e("logbook", heading="Journal", text=ENTRY)])
    expect(r.rc == 1, "no heading")
    r.done()
    r = one(tool, {"d.md": "## Logbook\n"}, [e("logbook", heading="Logbook", text=ENTRY)], ("--write",))
    expect(r.rc == 0 and r.read("d.md") == "## Logbook\n\n" + ENTRY + "\n", repr(r.read("d.md")))
    r.done()


# ---- placeholders
@case
def placeholders(tool):
    ed = [e("sub", old="build", new="built {{SMOKE}} and {{X}}")]
    r = one(tool, {"d.md": DOC}, ed, ("--check",), markers={"SMOKE": "ok"})
    expect(r.rc == 0, "check tolerates open: %s" % r.out)
    summary(r, 1, 0, 1)
    r.done()
    r = one(tool, {"d.md": DOC}, ed, ("--write",), markers={"SMOKE": "ok"})
    expect(r.rc == 1 and r.read("d.md") == DOC, "write must refuse and not touch")
    summary(r, 1, 0, 1)
    r.done()
    r = one(tool, {"d.md": DOC}, ed, ("--write",), markers={"SMOKE": "ok", "X": "why"})
    expect(r.rc == 0 and "built ok and why" in r.read("d.md"), r.out)
    summary(r, 1, 0, 0)
    r.done()
    r = one(tool, {"d.md": DOC}, [e("sub", old="{{GONE}}", new="y")])
    expect(r.rc == 0, "open search field tolerated in check")
    summary(r, 0, 0, 1)
    r.done()


# ---- lint
@case
def lint_300(tool):
    r = one(tool, {"d.md": DOC}, [e("sub", old="build", new=LONG)])
    expect(r.rc == 1 and "300" in r.out and "#0" in r.out, r.out)
    r.done()
    r = one(tool, {"d.md": DOC}, [e("sub", old="build", new="y" * 285)])
    expect(r.rc == 0, "exactly 300 chars is allowed")
    r.done()
    long_line = "- [ ] T-1 " + LONG + "\n"
    r = one(tool, {"d.md": long_line}, [e("tick", match="T-1")])
    expect(r.rc == 1, "a tick that grows no new line over 300 still rewrites a >300 line")
    r.done()


# ---- atomicity / files
@case
def atomic_all_or_nothing(tool):
    a, b = "alpha\n", "beta\n"
    ed = [e("sub", file="a.md", old="alpha", new="A"), e("sub", file="b.md", old="nothere", new="B")]
    r = one(tool, {"a.md": a, "b.md": b}, ed, ("--write",))
    expect(r.rc == 1 and r.read("a.md") == a and r.read("b.md") == b, "a failing op must leave every file untouched")
    r.done()
    ed[1]["old"] = "beta"
    r = one(tool, {"a.md": a, "b.md": b}, ed, ("--write",))
    expect(r.rc == 0 and r.read("a.md") == "A\n" and r.read("b.md") == "B\n", r.out)
    expect("a.md" in r.out and "b.md" in r.out and "+0" in r.out, "line deltas: %s" % r.out)
    expect(not [n for n in os.listdir(r.dir) if n.startswith(".")], "temp files left")
    r.done()


@case
def check_never_writes(tool):
    r = one(tool, {"d.md": DOC}, [e("sub", old="build", new="built")])
    expect(r.rc == 0 and r.read("d.md") == DOC, "check wrote")
    r.done()


@case
def sequential_ops(tool):
    ed = [e("sub", old="build", new="built"), e("sub", old="built", new="finished")]
    r = one(tool, {"d.md": DOC}, ed, ("--write",))
    expect(r.rc == 0 and "T-1 finished" in r.read("d.md"), r.out)
    r.done()


@case
def rerun_is_clean(tool):
    ed = [e("sub", old="build", new="built"), e("tick", match="T-2", suffix=" ok"),
          e("append_rows", anchor="## Table", text="| 2 | two |"), e("logbook", heading="Logbook", text=ENTRY)]
    files = {"d.md": DOC + "\n" + LOG_NEW}
    r = one(tool, files, ed, ("--write",))
    expect(r.rc == 0, r.out)
    second = r.read("d.md")
    with open(os.path.join(r.dir, "d.md"), "w", newline="") as f:
        f.write(second)
    sp = os.path.join(r.dir, "_sheet.json")
    p = subprocess.run([sys.executable, "-B", tool, "--sheet", sp, "--root", r.dir, "--write"], capture_output=True)
    out = p.stdout.decode()
    expect(p.returncode == 0 and out.count("already applied") == 4 and r.read("d.md") == second, out)
    r.done()


@case
def crlf_and_no_final_newline(tool):
    crlf = DOC.replace("\n", "\r\n")
    r = one(tool, {"d.md": crlf}, [e("sub", old="build", new="built"), e("tick", match="T-2"),
                                   e("append_rows", anchor="## Table", text="| 2 | two |")], ("--write",))
    t = r.read("d.md")
    expect(r.rc == 0 and t.count("\r\n") == t.count("\n") and "- [x] T-2 ship\r\n" in t and "| 2 | two |\r\n" in t, repr(t[:120]))
    r.done()
    nofinal = "- [ ] T-1 a\n- [ ] T-2 b"
    r = one(tool, {"d.md": nofinal}, [e("tick", match="T-2"), e("insert_after", anchor="T-2", text="tail")], ("--write",))
    expect(r.rc == 0 and r.read("d.md") == "- [ ] T-1 a\n- [x] T-2 b\ntail", repr(r.read("d.md")))
    r.done()


@case
def non_utf8_clean_failure(tool):
    r = one(tool, {}, [e("sub", old="a", new="b")], ("--write",), raw_files={"d.md": b"caf\xe9 a\n"})
    expect(r.rc == 1 and "utf-8" in r.out.lower() and "Traceback" not in r.err, r.out + r.err)
    r.done()


@case
def missing_file_fails(tool):
    r = one(tool, {"d.md": DOC}, [e("sub", file="nope.md", old="a", new="b")])
    expect(r.rc == 1 and "nope.md" in r.out, r.out)
    r.done()


@case
def bad_op_and_fields(tool):
    r = one(tool, {"d.md": DOC}, [e("explode"), {"file": "d.md", "op": "sub", "why": "t", "old": "a"}])
    expect(r.rc == 1 and r.out.count("FAIL") == 2, r.out)
    summary(r, 0, 2, 0)
    r.done()


# ---- usage / json
@case
def usage_64(tool):
    env = {"PATH": os.environ.get("PATH", "")}
    base = [sys.executable, "-B", tool]
    for args in ([], ["--sheet", "/nonexistent.json", "--check", "--root", "/tmp"], ["--bogus"]):
        p = subprocess.run(base + args, capture_output=True, env=env)
        expect(p.returncode == 64 and b"Traceback" not in p.stderr, "%s -> %s" % (args, p.returncode))
    r = one(tool, {"d.md": DOC}, [e("sub", old="a", new="b")], args=("--check", "--write"))
    expect(r.rc == 64, "check+write")
    r.done()
    r = one(tool, {"d.md": DOC}, [e("sub", old="a", new="b")], args=(), )
    expect(r.rc == 64, "neither mode")
    r.done()
    r = one(tool, {"d.md": DOC}, "{not json", args=("--check",))
    expect(r.rc == 64, "bad json")
    r.done()
    r = one(tool, {"d.md": DOC}, [e("sub", old="a", new="b")], root=False)
    expect(r.rc == 64, "relative path without --root")
    r.done()
    ap = os.path.join(tempfile.gettempdir(), "dsa-abs-%d.md" % os.getpid())
    with open(ap, "w") as f:
        f.write("one\n")
    try:
        r = one(tool, {}, [e("sub", file=ap, old="one", new="two")], root=False, args=("--write",))
        expect(r.rc == 0 and open(ap).read() == "two\n", "absolute path without root: %s" % r.out)
        r.done()
    finally:
        os.remove(ap)


@case
def json_mirrors(tool):
    r = one(tool, {"d.md": DOC}, [e("sub", old="build", new="b"), e("sub", old="zzz", new="y")], ("--check", "--json"))
    data = json.loads(r.out.strip().splitlines()[0])
    expect(data["ok"] == 1 and data["failed"] == 1 and data["open"] == 0 and len(data["results"]) == 2, data)
    expect(data["results"][1]["status"] == "failed" and data["results"][1]["index"] == 1, data)
    summary(r, 1, 1, 0)
    r.done()


# ---- harness
def run_suite(tool, only):
    env_fail = 0
    n = 0
    for fn in CASES:
        if only and only not in fn.__name__:
            continue
        n += 1
        try:
            fn(tool)
            print("PASS %s" % fn.__name__)
        except AssertionError as ex:
            env_fail += 1
            print("FAIL %s: %s" % (fn.__name__, str(ex)[:200].replace("\n", " | ")))
        except Exception as ex:  # a crash is a failure, never a pass
            env_fail += 1
            print("FAIL %s: %s %s" % (fn.__name__, type(ex).__name__, str(ex)[:150]))
    print("%d/%d passed" % (n - env_fail, n))
    return env_fail


MUTANTS = {
    "match-count": ("n != expected", "False"),
    "lint-threshold": ("> LINT_MAX", "> 10 ** 9"),
    "write-gate": ("if failed or (write and openn):", "if False:"),
}


def mutation(tool, only):
    bad = 0
    src = open(tool, encoding="utf-8").read().split("\n")
    for name, (old, new) in MUTANTS.items():
        key = "# MUTATION-KEY: " + name
        idx = [i for i, l in enumerate(src) if key in l]
        if len(idx) != 1 or old not in src[idx[0]]:
            print("FAIL mutant %s: marker/snippet not found exactly once" % name)
            bad += 1
            continue
        lines = list(src)
        lines[idx[0]] = lines[idx[0]].replace(old, new)
        d = tempfile.mkdtemp(prefix="dsa-mut-")
        mp = os.path.join(d, "docsync_apply.py")
        with open(mp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fails = run_suite(mp, only)
        shutil.rmtree(d, ignore_errors=True)
        if fails:
            print("KILLED %s (%d case(s) failed)" % (name, fails))
        else:
            print("SURVIVED %s" % name)
            bad += 1
    print("%d/%d mutants killed" % (len(MUTANTS) - bad, len(MUTANTS)))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tool", default=os.path.join(HERE, "docsync_apply.py"))
    ap.add_argument("--only", default="")
    ap.add_argument("--mutation", action="store_true")
    a = ap.parse_args()
    if a.mutation:
        sys.exit(1 if mutation(a.tool, a.only) else 0)
    sys.exit(1 if run_suite(a.tool, a.only) else 0)


if __name__ == "__main__":
    main()
