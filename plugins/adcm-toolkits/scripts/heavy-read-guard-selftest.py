#!/usr/bin/env python3
"""heavy-read-guard-selftest - heavy-read rule (R3) of main-thread-guard.py: Read and Bash branches, the peek boundary,
globs, wrapper prefixes, transcripts, missing files and direct mode.

Usage:
  python3 heavy-read-guard-selftest.py [--only SUBSTRING] [--guard PATH] [--mutation]

Harness, output and --mutation as in compaction-breaker-selftest.py (imported from the same folder).
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("mtg_harness", os.path.join(HERE, "compaction-breaker-selftest.py"))
H = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(H)
allowed, denied, first = H.allowed, H.denied, H.first

KB = 1024
LINE = "y" * 127 + "\n"  # 128 bytes per line


def read(c, path, **kw):
    return c.tool("Read", dict({"file_path": path}, **kw))


def cases():
    out = []

    def add(name):
        def deco(fn):
            out.append((name, fn))
            return fn
        return deco

    @add("read_images_and_pdf_denied")
    def _(c):
        return first(*[denied(read(c, c.write(f"work/a.{e}", "x")), "R3", "SendUserFile") for e in (
            "png", "JPG", "jpeg", "gif", "webp", "pdf", "bmp", "tif", "tiff", "heic", "avif")],
            denied(read(c, c.path("work", "missing.png")), "R3"),
            denied(read(c, c.write("work/b.png", "x"), limit=5), "R3"))

    @add("read_size_boundary")
    def _(c):
        return first(allowed(read(c, c.write("work/at.md", size=40 * KB))),
                     denied(read(c, c.write("work/over.md", size=40 * KB + 1)), "R3", "offset", "adcm-toolkits:researcher"))

    @add("read_protected_docs")
    def _(c):
        return first(*[denied(read(c, c.write(f"brain/{n}", "small\n")), "R3") for n in (
            "task.md", "execute.md", "plan-detallado.md", "detailed-plan.md", "plans.html", "prompts.html")],
            allowed(read(c, c.write("brain/tasks.md", "small\n"))))

    @add("read_offset_without_limit_is_whole")
    def _(c):
        return denied(read(c, c.write("brain/task.md", "a\n"), offset=10), "R3")

    @add("peek_boundary")
    def _(c):
        p = c.write("work/big.md", LINE * 1000)
        return first(allowed(read(c, p, limit=64)), denied(read(c, p, limit=65), "R3", "8 KB"),
                     allowed(read(c, p, offset=900, limit=64)), denied(read(c, p, offset=900, limit=65), "R3"),
                     allowed(read(c, p, offset=990, limit=500)))

    @add("peek_one_byte_over")
    def _(c):
        p = c.write("work/edge.md", LINE * 64 + "\n" + LINE * 500)
        return first(allowed(read(c, p, limit=64)), denied(read(c, p, limit=65), "R3"))

    @add("bad_limit_is_whole_read")
    def _(c):
        p = c.write("work/big.md", LINE * 1000)
        return first(*[denied(read(c, p, limit=v), "R3", "offset/limit") for v in (0, -5, "abc", None, True)],
                     allowed(read(c, p, limit="64")))

    @add("names_case_and_realpath")
    def _(c):
        shot = c.write("work/shot.png", "x")
        link = c.path("work", "notes.txt")
        os.symlink(shot, link)
        return first(denied(read(c, c.write("brain/Task.MD", "x\n")), "R3"), denied(read(c, link), "R3", "SendUserFile"),
                     denied(read(c, c.write("work/IMG.HEIC", "x")), "R3"))

    @add("peek_protected_doc")
    def _(c):
        p = c.write("brain/execute.md", LINE * 100)
        return first(allowed(read(c, p, offset=1, limit=40)), denied(read(c, p, limit=100), "R3"))

    @add("read_missing_file_allowed")
    def _(c):
        return allowed(read(c, c.path("work", "nope.md")))

    @add("read_relative_path_uses_cwd")
    def _(c):
        c.write("work/rel.md", size=50 * KB)
        return denied(read(c, "rel.md"), "R3")

    @add("bash_dumpers")
    def _(c):
        big = c.write("work/big.md", size=50 * KB)
        small = c.write("work/small.md", "x\n")
        return first(*[denied(c.bash(f"{p} {big}"), "R3") for p in ("cat", "bat", "less", "more", "nl", "tac", "/bin/cat")],
                     allowed(c.bash(f"cat {small}")), allowed(c.bash(f"head -n 5 {big}")),
                     allowed(c.bash(f"wc -l {big}")), allowed(c.bash(f"echo hi > {big}")))

    @add("bash_prefixes")
    def _(c):
        big = c.write("work/big.md", size=50 * KB)
        return first(*[denied(c.bash(f"{p} cat {big}"), "R3") for p in (
            "rtk", "rtk proxy", "env", "env FOO=1", "sudo", "sudo -u root", "command", "FOO=1")])

    @add("bash_rtk_subcommands")
    def _(c):
        big = c.write("work/big.md", size=50 * KB)
        t = c.write(".claude-x/projects/-p/s.jsonl", size=6 * 1024 * KB)
        return first(denied(c.bash(f"rtk read {big}"), "R3"), denied(c.bash(f"rtk cat {big}"), "R3"),
                     denied(c.bash(f"rtk grep foo {t}"), "R3"), denied(c.bash(f"rtk proxy tail {t}"), "R3"),
                     allowed(c.bash(f"rtk wc {big}")), allowed(c.bash("rtk git status")))

    @add("bash_shell_c_one_level")
    def _(c):
        big = c.write("work/big.md", size=50 * KB)
        return first(*[denied(c.bash(f"{sh} -c 'cat {big}'"), "R3") for sh in ("bash", "sh", "zsh", "/bin/bash")],
                     denied(c.bash(f'echo a && bash -c "echo b; cat {big}"'), "R3"),
                     allowed(c.bash("bash -c 'echo hi'")), allowed(c.bash("bash -c")))

    @add("bash_compound_and_redirect")
    def _(c):
        big = c.write("work/big.md", size=50 * KB)
        return first(denied(c.bash(f"cd /tmp && cat {big} | wc -l"), "R3"), denied(c.bash(f"echo a; cat < {big}"), "R3"),
                     denied(c.bash(f"echo a\ncat {big}"), "R3"), allowed(c.bash(f"cat /dev/null > {big}")))

    @add("bash_protected_and_image")
    def _(c):
        return first(denied(c.bash("cat " + c.write("work/task.md", "x\n")), "R3"),
                     denied(c.bash("cat " + c.write("work/shot.png", "x")), "R3"))

    @add("bash_globs_and_tilde")
    def _(c):
        c.write("work/a.md", "x\n")
        c.write("work/zz-big.md", size=50 * KB)
        c.write("notes/big.txt", size=50 * KB)
        return first(denied(c.bash("cat *.md"), "R3"), denied(c.bash("cat ~/notes/big.txt"), "R3"),
                     allowed(c.bash("cat a*.md")), allowed(c.bash("cat 'nothing*.md'")))

    @add("bash_more_prefixes_and_substitutions")
    def _(c):
        big = c.write("work/big.md", size=50 * KB)
        c.write("notes/big.txt", size=50 * KB)
        return first(*[denied(c.bash(cmd), "R3") for cmd in (
            f"time cat {big}", f"nohup cat {big}", f"timeout 5 cat {big}", f"timeout -s KILL 5 cat {big}", f"exec cat {big}",
            f"bash -lc 'cat {big}'", f"sh -ec 'cat {big}'", f"echo $(cat {big})", f"echo `cat {big}`",
            f"eval 'cat {big}'", f"eval cat {big}", "cat $HOME/notes/big.txt", "cat ${HOME}/notes/big.txt", "cat $PWD/big.md", "cat {a,big}.md")],
            allowed(c.bash("time echo hi")), allowed(c.bash(f"echo $(wc -l {big})")))

    @add("bash_tracks_cd")
    def _(c):
        c.write("brain/task.md", "x\n")
        c.write("work/task.md", "")
        os.remove(c.path("work", "task.md"))
        return first(denied(c.bash(f"cd {c.path('brain')} && cat task.md"), "R3"), denied(c.bash("cd ..; cd brain; cat task.md"), "R3"),
                     allowed(c.bash("cat task.md")))

    @add("bash_missing_image_denied")
    def _(c):
        return first(denied(c.bash("cat " + c.path("work", "missing.png")), "R3"), denied(c.bash("cat gone.PDF"), "R3"))

    @add("bash_missing_file_allowed")
    def _(c):
        return allowed(c.bash("cat " + c.path("work", "nope.md")))

    @add("bash_unparseable_still_judged")
    def _(c):
        big = c.write("work/big.md", size=50 * KB)
        small = c.write("work/small.md", "x\n")
        return first(denied(c.bash(f"cat {big} 'unterminated"), "R3"), allowed(c.bash(f"cat {small} 'unterminated")))

    @add("read_limit_not_finite_is_whole")
    def _(c):
        p = c.write("work/big.md", LINE * 1000)
        return first(*[denied(read(c, p, limit=v), "R3") for v in (float("inf"), float("-inf"), float("nan"))],
                     allowed(read(c, p, limit=10, offset=float("inf"))))

    @add("bash_transcripts")
    def _(c):
        t = c.write(".claude-x/projects/-p/s.jsonl", size=6 * 1024 * KB)
        cfg = c.write("cfg/projects/-p/s.jsonl", size=6 * 1024 * KB)
        small = c.write(".claude-x/projects/-p/small.jsonl", size=4 * 1024 * KB)
        outside = c.write("data/projects/-p/s.jsonl", size=6 * 1024 * KB)
        return first(*[denied(c.bash(f"{r} {t}"), "R3", "researcher") for r in (
            "grep foo", "egrep foo", "jq .", "tail -n 5", "head", "awk '{print}'", "sed -n 1p", "cut -c1-9", "strings")],
            denied(c.bash(f"grep x {cfg}"), "R3"), allowed(c.bash(f"grep x {small}")), allowed(c.bash(f"grep x {outside}")),
            allowed(c.bash(f"wc -l {t}")))

    @add("direct_mode_switches_off")
    def _(c):
        big = c.write("work/big.md", size=50 * KB)
        c.prompt("modo directo")
        return first(allowed(read(c, big)), allowed(read(c, c.write("w/p.png", "x"))), allowed(c.bash(f"cat {big}")))

    @add("subagent_free")
    def _(c):
        big = c.write("work/big.md", size=50 * KB)
        return first(allowed(c.tool("Read", {"file_path": big}, sub=True)), allowed(c.bash(f"cat {big}", sub=True)))

    return out


MUTANTS = ["size", "peek", "jsonl", "direct", "image"]

if __name__ == "__main__":
    sys.exit(H.suite_main(cases(), MUTANTS))
