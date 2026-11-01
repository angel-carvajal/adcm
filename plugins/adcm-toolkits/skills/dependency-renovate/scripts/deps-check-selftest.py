#!/usr/bin/env python3
"""deps-check-selftest - behavioural tests for deps_check.py (stdlib only, no network).

Usage:
  python3 deps-check-selftest.py [--checker PATH] [--only NAME] [--keep]

Each case builds one throwaway `tempfile` tree: an Acme container (`acme/projects/<repo>`, its brain and its
context skills), copies of fixtures/npm-basic or synthetic projects as git repos with a local bare `origin`,
a fake nvm dir whose Node installs hold fake `node`, `npm` and `pnpm`, fake `glab` and `composer` on a private
PATH, and a local HTTP server on 127.0.0.1 for the registry, the bulk advisory endpoint, PyPI and the Node
schedule and index. The checker runs as a subprocess with HOME=<tmp>, a minimal environment and the
DEPS_CHECK_* seams pointing at those fakes, so no case reaches the network or a real tool. It prints
`PASS|FAIL|SKIP <case> [- why]` per case and the tally line last; exit 1 when any case FAILs.

Every read-only run is asserted twice (plain + --json with the same flags): exit code, <= 40 plain lines,
the verdict line consistent with the exit code, json.text == the plain lines, and the trees untouched.
"""
import argparse
import hashlib
import http.server
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import urllib.parse

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
FIXTURE = os.path.normpath(os.path.join(HERE, os.pardir, "fixtures", "npm-basic"))
DATE = "2026-10-25"
PLAN_KEYS = ["tool", "version", "command", "repo", "date", "state", "partial", "git", "brain", "context", "env",
             "manifest", "runtimes", "packages", "transitive_advisories", "families", "ci", "docker",
             "verification", "smoke", "waves", "pending_majors", "holds", "never_auto", "para_ti", "counts",
             "review", "text"]
VERDICT = {"preflight": "PREFLIGHT", "plan": "DEPS", "changelog": "CHANGELOG", "context": "CONTEXT", "status": "STATUS"}
BRAIN_EXEC = "acme/ai/ai-brain/execute.md"
REVIEWER_OK = "> **Reviewer:** @reviewer-handle (gitlab) · merge policy: wait"
REVIEWER_NAME = "> **Reviewer:** Acme Dev (A) · forge: gitlab · merge policy: wait"
CONTEXT_SKILL = "acme/ai/acme-ai-platform/plugins/acme-eng/skills/code-project-context-acme"
FAKE_TOOL = r'''
import json, os, sys
tool, args = sys.argv[1], sys.argv[2:]
with open(os.environ["FAKE_CONFIG"], encoding="utf-8") as fh:
    cfg = json.load(fh)
with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"tool": tool, "argv": args, "cwd": os.getcwd(),
                         "path0": os.environ.get("PATH", "").split(os.pathsep)[0],
                         "env": {k: os.environ.get(k) for k in ("COREPACK_ENABLE_STRICT", "COREPACK_ENABLE_DOWNLOAD_PROMPT",
                                                                "COREPACK_ENABLE_NETWORK")}}) + "\n")
spec = cfg.get(tool, {})


def out(value, code=0):
    sys.stdout.write(value if isinstance(value, str) else json.dumps(value))
    sys.stdout.flush()
    sys.exit(code)


def reply(key, default):
    r = spec.get(key)
    if r is None:
        out(default, 0)
    out(r.get("stdout", ""), r.get("exit", 0))


if args[:1] == ["--version"]:
    out(str(spec.get("version", "0.0.0")) + "\n")
if tool in ("npm", "pnpm"):
    if "outdated" in args:
        reply("outdated", {})
    if "audit" in args:
        reply("audit", {})
    if args[:1] == ["view"] and len(args) > 1:
        if "time" in args:
            data = spec.get("times", {}).get(args[1])
            out(data, 0) if data else out({"error": {"code": "E404", "summary": "not found"}}, 1)
        if "repository.url" in args:
            out(spec.get("refs", {}).get(args[1], {}), 0)
if tool == "glab":
    if args[:2] == ["auth", "status"]:
        sys.exit(spec.get("auth", 0))
    if args[:2] == ["mr", "list"]:
        out(spec.get("mr_list", []), spec.get("mr_list_exit", 0))
    if args[:2] == ["mr", "view"] and len(args) > 2:
        data = spec.get("mr_view", {}).get(args[2])
        out(data, 0) if data else out("no merge request\n", 1)
if tool == "composer" and "outdated" in args:
    reply("outdated", {"installed": []})
sys.exit(0)
'''


class Skip(Exception):
    pass


# ------------------------------------------------------------------ harness
def read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    return path


def file_digest(path):
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return "?"


def snap(*roots):
    out = {}
    for root in roots:
        for dp, dn, fn in os.walk(root):
            dn[:] = [d for d in dn if d != ".git"]
            for f in fn:
                p = os.path.join(dp, f)
                out[p] = file_digest(p)
    return out


class R(object):
    def __init__(self, p):
        self.rc, self.out, self.err = p.returncode, p.stdout, p.stderr
        self.lines = p.stdout.splitlines()
        self.last = self.lines[-1] if self.lines else ""
        try:
            data = json.loads(p.stdout)
        except ValueError:
            data = None
        self.data = data if isinstance(data, dict) else None


class Server(object):
    def __init__(self):
        self.get, self.bulk, self.bulk_raw, self.requests = {}, {}, None, []
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def answer(self, code, body):
                data = body.encode("utf-8") if isinstance(body, str) else json.dumps(body).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                path = urllib.parse.unquote(self.path)
                server.requests.append(("GET", path, None))
                if path in server.get:
                    return self.answer(200, server.get[path])
                return self.answer(404, {"error": "not found"})

            def do_POST(self):
                size = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(size).decode("utf-8")
                try:
                    body = json.loads(raw)
                except ValueError:
                    body = None
                server.requests.append(("POST", self.path, body))
                if self.path != "/-/npm/v1/security/advisories/bulk":
                    return self.answer(404, {"error": "not found"})
                if server.bulk_raw is not None:
                    return self.answer(200, server.bulk_raw)
                return self.answer(200, {k: v for k, v in server.bulk.items() if isinstance(body, dict) and k in body})

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def url(self, path=""):
        return "http://127.0.0.1:%d%s" % (self.port, path)

    def posts(self):
        return [r for r in self.requests if r[0] == "POST"]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class Ctx(object):
    def __init__(self, checker, root):
        self.checker, self.root = checker, root
        for d in ("home", "tmp", "bin", "nvm", "fakes", "gitbin", "remotes"):
            os.makedirs(self.path(d), exist_ok=True)
        self.server = Server()
        self.config = {"npm": {"version": "10.8.2"}, "pnpm": {"version": "10.4.1"}, "glab": {"mr_list": []},
                       "composer": {"version": "2.8.1"}, "node": {"version": "v20.11.0"}}
        write(self.path("fakes/fake_tool.py"), FAKE_TOOL)
        git = shutil.which("git")
        os.symlink(git, self.path("gitbin/git"))
        for tool in ("npm", "pnpm", "glab", "composer", "node"):
            self.tool(self.path("bin"), tool)
        self.node_install("20.11.0")
        self.env = {"PATH": os.pathsep.join([self.path("bin"), self.path("gitbin"), "/usr/bin", "/bin"]),
                    "HOME": self.path("home"), "TMPDIR": self.path("tmp"), "LANG": "C", "LC_ALL": "C",
                    "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
                    "GIT_CONFIG_NOSYSTEM": "1", "XDG_CONFIG_HOME": self.path("home/.config"),
                    "FAKE_CONFIG": self.path("fakes/config.json"), "FAKE_LOG": self.path("fakes/log.jsonl"),
                    "DEPS_CHECK_REGISTRY": self.server.url(), "DEPS_CHECK_PYPI": self.server.url("/pypi"),
                    "DEPS_CHECK_NODE_SCHEDULE": self.server.url("/schedule.json"),
                    "DEPS_CHECK_NODE_INDEX": self.server.url("/index.json"), "DEPS_CHECK_NVM_DIR": self.path("nvm"),
                    "no_proxy": "*", "NO_PROXY": "*"}
        self.save()
        for name in ("schedule.json", "index.json"):
            self.server.get["/" + name] = json.loads(read(os.path.join(FIXTURE, "stubs", name)))

    def path(self, rel):
        return os.path.join(self.root, *rel.split("/"))

    def tool(self, folder, name):
        p = write(os.path.join(folder, name), '#!/bin/sh\nexec "%s" "%s" %s "$@"\n' % (
            sys.executable, self.path("fakes/fake_tool.py"), name))
        os.chmod(p, 0o755)

    def node_install(self, version, tools=("node", "npm", "pnpm")):
        folder = self.path("nvm/v%s/bin" % version)
        os.makedirs(folder, exist_ok=True)
        for name in tools:
            self.tool(folder, name)

    def save(self):
        write(self.path("fakes/config.json"), json.dumps(self.config))

    def log(self):
        text = read(self.path("fakes/log.jsonl")) or ""
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def clear_log(self):
        write(self.path("fakes/log.jsonl"), "")

    def run(self, *args, **kw):
        cmd = [sys.executable, kw.get("checker") or self.checker] + [str(a) for a in args]
        env = dict(self.env, **kw.get("env", {}))
        for key in kw.get("unset", ()):
            env.pop(key, None)
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
                           cwd=kw.get("cwd") or self.root, timeout=kw.get("timeout", 240))
        return R(p)

    def git(self, repo, *args, **kw):
        env = dict(self.env)
        p = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True, env=env, timeout=60)
        if kw.get("check", True) and p.returncode != 0:
            raise RuntimeError("git %s failed: %s" % (" ".join(args), p.stderr.strip()[:200]))
        return p.stdout.strip()

    def commit(self, repo, message="change", email="dev@example.com"):
        self.git(repo, "add", "-A")
        self.git(repo, "-c", "user.email=" + email, "-c", "user.name=Dev", "commit", "-q", "--allow-empty", "-m", message)
        return self.git(repo, "rev-parse", "HEAD")

    def init_git(self, repo, origin=False, email=None):
        self.git(repo, "-c", "init.defaultBranch=main", "init", "-q")
        if email:
            self.git(repo, "config", "user.email", email)
        self.commit(repo, "initial")
        if origin:
            bare = self.path("remotes/%s.git" % os.path.basename(repo))
            subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", "--bare", bare], env=self.env, check=True)
            self.git(repo, "remote", "add", "origin", bare)
            self.git(repo, "push", "-q", "origin", "main")
            self.git(repo, "remote", "set-head", "origin", "main")
        return repo

    def fixture(self, name="acme-site", git=True, origin=False, email="dev@example.com", where="acme/projects"):
        repo = self.path("%s/%s" % (where, name))
        shutil.copytree(FIXTURE, repo)
        if git:
            self.init_git(repo, origin=origin, email=email)
        return repo

    def stubs(self):
        """The fixture stubs wired into the fakes and the local server."""
        load = lambda n: json.loads(read(os.path.join(FIXTURE, "stubs", n)))
        self.config["npm"].update(times=load("npm-view-time.json"), refs=load("npm-view-refs.json"),
                                  outdated={"stdout": load("npm-outdated.json"), "exit": 1},
                                  audit={"stdout": load("npm-audit.json"), "exit": 1})
        self.save()
        self.server.bulk = load("advisories-bulk.json")
        for key, value in load("registry-manifests.json").items():
            self.server.get["/" + key] = value
        self.server.get["/schedule.json"] = load("schedule.json")
        self.server.get["/index.json"] = load("index.json")

    def brain(self, reviewer=REVIEWER_OK, rel=BRAIN_EXEC):
        body = "# Acme brain\n\n> **Protocol:** test\n%s\n\nBody.\n" % reviewer
        return write(self.path(rel), body)

    def skill(self, rel=CONTEXT_SKILL, names=("acme-site",), layout="flat"):
        folder = self.path(rel)
        write(os.path.join(folder, "SKILL.md"), "---\nname: %s\n---\n# Context\n\nRepos: %s.\n" % (
            os.path.basename(folder), ", ".join("`%s`" % n for n in names)))
        if layout == "references":
            os.makedirs(os.path.join(folder, "references"), exist_ok=True)
        return folder

    def close(self):
        self.server.close()


class Check(object):
    def __init__(self):
        self.problems = []
        self.tag = ""

    def ok(self, cond, what):
        if not cond:
            self.problems.append(self.tag + what)

    def eq(self, got, want, what):
        if got != want:
            self.problems.append("%s%s: got %r, want %r" % (self.tag, what, got, want))

    def has(self, hay, needle, what):
        text = "\n".join(hay) if isinstance(hay, list) else (hay or "")
        if needle not in text:
            self.problems.append("%s%s: %r not in %r" % (self.tag, what, needle, text[:160]))

    def hasnt(self, hay, needle, what):
        text = "\n".join(hay) if isinstance(hay, list) else (hay or "")
        if needle in text:
            self.problems.append("%s%s: %r unexpectedly in output" % (self.tag, what, needle))


def verdict_ok(cmd, rc, last):
    word = VERDICT[cmd]
    if rc == 2:
        return last.startswith(word + ": unparsed")
    return last.startswith(word + ": ")


def both(ctx, t, *args, **kw):
    """Plain + --json with the same flags; checks the shared contract and returns (plain R, json dict)."""
    rc = kw.get("rc", 0)
    cmd = args[0]
    trees = kw.get("trees") or []
    before = snap(*trees) if trees else None
    plain = ctx.run(*args, **{k: v for k, v in kw.items() if k in ("env", "unset", "cwd")})
    js = ctx.run(*(list(args) + ["--json"]), **{k: v for k, v in kw.items() if k in ("env", "unset", "cwd")})
    t.eq(plain.rc, rc, "%s plain exit code (last %r)" % (cmd, plain.last[:90]))
    t.eq(js.rc, rc, "%s --json exit code" % cmd)
    t.ok(len(plain.lines) <= 40, "%s prints %d lines, cap 40" % (cmd, len(plain.lines)))
    t.ok(verdict_ok(cmd, rc, plain.last), "%s verdict line %r for exit %d" % (cmd, plain.last[:90], rc))
    if js.data is None:
        t.ok(False, "%s --json stdout is not one JSON object: %r" % (cmd, js.out[:80]))
        return plain, {}
    t.eq(js.data.get("text"), plain.lines, "%s json text == plain lines" % cmd)
    if cmd == "plan":
        t.eq(list(js.data), PLAN_KEYS, "plan --json keys")
    if before is not None:
        t.eq(snap(*trees), before, "%s left the trees untouched" % cmd)
    return plain, js.data


def dig(d, *path):
    for k in path:
        if isinstance(d, dict):
            d = d.get(k)
        elif isinstance(d, list) and isinstance(k, int) and len(d) > k:
            d = d[k]
        else:
            return None
    return d


def pkg(data, name, ws="."):
    return next((p for p in data.get("packages") or [] if p["name"] == name and p["workspace"] == ws), {})


def wave(data, ident):
    return next((w for w in data.get("waves") or [] if w["id"] == ident), None)


def npm_project(ctx, repo, deps, extra=None, name=None, pm_field=None, scripts=None):
    """package.json + package-lock.json v3 from {name: (kind, declared, locked)}."""
    pkg_json = {"name": name or os.path.basename(repo), "version": "1.0.0", "private": True,
                "scripts": scripts or {"build": "tsc"}}
    groups = {"prod": "dependencies", "dev": "devDependencies", "optional": "optionalDependencies"}
    for dep, (kind, declared, _) in sorted(deps.items()):
        pkg_json.setdefault(groups[kind], {})[dep] = declared
    if pm_field:
        pkg_json["packageManager"] = pm_field
    packages = {"": {k: v for k, v in pkg_json.items() if k in ("name", "version", "dependencies", "devDependencies")}}
    for dep, (kind, _, locked) in sorted(deps.items()):
        entry = {"version": locked}
        if kind == "dev":
            entry["dev"] = True
        packages["node_modules/" + dep] = entry
    for key, entry in (extra or {}).items():
        packages[key] = entry
    write(os.path.join(repo, "package.json"), json.dumps(pkg_json, indent=2) + "\n")
    write(os.path.join(repo, "package-lock.json"), json.dumps(
        {"name": pkg_json["name"], "version": "1.0.0", "lockfileVersion": 3, "requires": True, "packages": packages},
        indent=2) + "\n")
    return repo


def bump_lock(repo, versions, specs=None):
    """Simulate an install: new locked versions in package-lock.json and, optionally, new specs in package.json."""
    lock = json.loads(read(os.path.join(repo, "package-lock.json")))
    for dep, version in versions.items():
        lock["packages"].setdefault("node_modules/" + dep, {})["version"] = version
    write(os.path.join(repo, "package-lock.json"), json.dumps(lock, indent=2) + "\n")
    if specs:
        data = json.loads(read(os.path.join(repo, "package.json")))
        for dep, spec in specs.items():
            for group in ("dependencies", "devDependencies"):
                if dep in data.get(group, {}):
                    data[group][dep] = spec
        write(os.path.join(repo, "package.json"), json.dumps(data, indent=2) + "\n")


def iso(day):
    return "%sT10:00:00.000Z" % day


# ------------------------------------------------------------------ cases: CLI and preflight
FLAGS = ("--context", "--expect-email", "--date", "--offline", "--json", "--max-majors", "--prioritize", "--routes",
         "--scratch", "--write", "--plan", "--wave", "--verify", "--smoke", "--notes", "--path", "--format", "--check",
         "--file", "--if-merged", "--branches", "--version", "--help")


def case_help_and_usage_64(ctx, t):
    r = ctx.run("--help")
    t.eq(r.rc, 0, "--help exit code")
    for word in ("preflight", "plan", "changelog", "context", "status") + FLAGS:
        t.has(r.out, word, "--help documents %s" % word)
    for sub in ("preflight", "plan", "changelog", "context", "status"):
        t.eq(ctx.run(sub, "--help").rc, 0, "%s --help exit code" % sub)
    repo = ctx.fixture()
    for args in (("bogus",), (), ("plan",), ("changelog", repo), ("changelog", repo, "--plan", "x.json"),
                 ("plan", repo, "--date", "2026-13-01"), ("plan", repo, "--routes", "maybe"),
                 ("changelog", repo, "--plan", "x.json", "--wave", "nope"), ("plan", repo, "--max-majors", "-1"),
                 ("changelog", repo, "--plan", "x.json", "--wave", "patch-minor", "--path", os.pardir + "/x.md"),
                 ("changelog", repo, "--plan", "x.json", "--check", "--write"), ("context", repo, "--file", "a/b.md"),
                 ("plan", repo, "--writ")):
        t.eq(ctx.run(*args).rc, 64, "usage error %r" % (args,))
    plugin_json = os.path.normpath(os.path.join(os.path.dirname(ctx.checker), os.pardir, os.pardir, os.pardir,
                                                ".claude-plugin", "plugin.json"))
    want = (json.loads(read(plugin_json) or "{}").get("version") if os.path.isfile(plugin_json) else None) or "unknown"
    r = ctx.run("--version")
    t.eq((r.rc, r.out.strip()), (0, "deps_check.py " + want), "--version reads plugin.json at runtime")
    copy = ctx.path("plug/skills/dependency-renovate/scripts/deps_check.py")
    write(copy, read(ctx.checker))
    t.eq(ctx.run("--version", checker=copy).out.strip(), "deps_check.py unknown", "no plugin.json gives unknown")
    write(ctx.path("plug/.claude-plugin/plugin.json"), json.dumps({"name": "x", "version": "9.9.9"}))
    t.eq(ctx.run("--version", checker=copy).out.strip(), "deps_check.py 9.9.9", "version follows plugin.json")


def case_unparsed_not_repo(ctx, t):
    plain, data = both(ctx, t, "plan", ctx.path("nope"), "--date", DATE, rc=2)
    t.has(plain.last, "DEPS: unparsed (repo not found", "missing repo")
    t.eq(sorted(data), sorted(PLAN_KEYS), "an unparsed plan still has the 28 keys")
    os.makedirs(ctx.path("empty"))
    plain, _ = both(ctx, t, "plan", ctx.path("empty"), "--offline", "--date", DATE, rc=2)
    t.has(plain.last, "DEPS: unparsed (no dependency manifest", "empty dir")
    repo = ctx.fixture(git=False)
    plain, _ = both(ctx, t, "preflight", repo, "--date", DATE, rc=2)
    t.eq(plain.last, "PREFLIGHT: unparsed (not a git repo)", "preflight without git")
    plain, _ = both(ctx, t, "changelog", repo, "--plan", ctx.path("missing.json"), "--wave", "patch-minor", rc=2)
    t.has(plain.last, "CHANGELOG: unparsed (no plan", "changelog without a plan")
    plain, _ = both(ctx, t, "context", ctx.path("empty"), "--offline", rc=2)
    t.has(plain.last, "CONTEXT: unparsed (no dependency manifest", "context on an empty dir")


def ready_repo(ctx, email="dev@example.com"):
    repo = ctx.fixture(origin=True, email=email)
    ctx.brain()
    return repo


def case_preflight_ready(ctx, t):
    repo = ready_repo(ctx)
    plain, data = both(ctx, t, "preflight", repo, "--expect-email", "dev@example.com", "--date", DATE, rc=0,
                       trees=[repo])
    t.eq(plain.last, "PREFLIGHT: ready", "verdict")
    t.has(plain.lines, "IDENTITY user.email repo-local · expected dev@example.com → ok", "identity line")
    t.has(plain.lines, "@reviewer-handle (gitlab) → ok", "reviewer line")
    t.has(plain.lines, "NODE pin 20.11.0 (.nvmrc) · nvm exact v20.11.0", "node line")
    t.has(plain.lines, "SHADOWED by dependency node@25.7.0", "shadowing package shown")
    t.has(plain.lines, "MR pipelines yes", "MR pipelines detected")
    t.eq(data.get("blockers"), [], "json blockers")
    t.ok(not any(l.startswith("Para ti:") for l in plain.lines), "no Para ti lines when ready")


def case_preflight_identity_mismatch_and_global(ctx, t):
    repo = ready_repo(ctx, email="other@example.com")
    plain, data = both(ctx, t, "preflight", repo, "--expect-email", "dev@example.com", "--date", DATE, rc=1)
    t.eq(plain.last, "PREFLIGHT: blocked(identity)", "mismatch verdict")
    t.has(plain.lines, "≠ expected", "mismatch shown")
    t.has(plain.lines, "Para ti: git -C", "owner command")
    t.has(plain.lines, "config user.email dev@example.com", "owner command names the expected identity")
    t.eq(dig(data, "git", "identity", "state"), "mismatch", "json identity state")
    ctx.git(repo, "config", "--unset", "user.email")
    write(ctx.path("home/.gitconfig"), "[user]\n\temail = global@example.com\n\tname = Global\n")
    plain, data = both(ctx, t, "preflight", repo, "--date", DATE, rc=1)
    t.eq(plain.last, "PREFLIGHT: blocked(identity)", "global identity, nothing expected")
    t.has(plain.lines, "user.email inherited from global (~/.gitconfig) · expected unknown → blocked", "global line")
    t.eq(dig(data, "git", "identity", "inherited_from_global"), True, "json inherited_from_global")
    ctx.git(repo, "config", "user.email", "dev@example.com")
    plain, _ = both(ctx, t, "preflight", repo, "--date", DATE, rc=0)
    t.eq(plain.last, "PREFLIGHT: ready", "a repo-local identity passes when none is expected")
    skill = ctx.skill()
    write(os.path.join(skill, "dependencies.md"), delivery_file("acme-site", identity="other@example.com"))
    plain, _ = both(ctx, t, "preflight", repo, "--date", DATE, rc=1)
    t.eq(plain.last, "PREFLIGHT: blocked(identity)", "Delivery Commit identity is the expected one")
    t.has(plain.lines, "expected other@example.com", "expected from Delivery")


def delivery_file(repo_name, identity="dev@example.com", reviewer="@delivery-handle (gitlab)", rules="", smoke="",
                  sha="0000000", extra_delivery=""):
    return ("# %s — Dependencies\n\nIntro.\n\n<!-- auto-generated: scan %s · deps-check 0.0.0 · main@%s — do not edit;"
            " refresh with deps-check context -->\n\n## Snapshot\n\n- **Repo:** `%s` · default branch `main`\n\n"
            "<!-- end auto-generated -->\n\n## Policy\n\nHuman text.\n\n### Rules\n\n"
            "| Package | Rule | Value | Why | Since | Review by |\n|---|---|---|---|---|---|\n%s\n"
            "### Verification\n\n| Step | Command | Where | Notes |\n|---|---|---|---|\n\n### Smoke\n\n"
            "| Route | Name | Mask (CSS selectors, comma-separated) |\n|---|---|---|\n%s\n### Delivery\n\n"
            "- Server: `npm start`\n- Shot command: built-in\n- Changelog: `docs/dependencies/CHANGELOG.md`\n"
            "- Reviewer: %s\n- Commit identity: %s\n- Max majors per run: 3\n- Priority majors: none\n"
            "- Notes: none\n%s") % (repo_name, DATE, sha, repo_name, rules, smoke, reviewer, identity, extra_delivery)


def case_preflight_dirty(ctx, t):
    repo = ready_repo(ctx)
    with open(os.path.join(repo, "README.md"), "a", encoding="utf-8") as fh:
        fh.write("\nlocal edit\n")
    plain, data = both(ctx, t, "preflight", repo, "--expect-email", "dev@example.com", "--date", DATE, rc=1)
    t.eq(plain.last, "PREFLIGHT: blocked(dirty)", "tracked change")
    t.has(plain.lines[0], "dirty(1)", "head line counts the change")
    ctx.git(repo, "checkout", "--", "README.md")
    write(os.path.join(repo, "notes.txt"), "untracked\n")
    plain, _ = both(ctx, t, "preflight", repo, "--expect-email", "dev@example.com", "--date", DATE, rc=1)
    t.eq(plain.last, "PREFLIGHT: blocked(dirty)", "untracked file")


def case_preflight_reviewer_canonical_vs_name(ctx, t):
    repo = ctx.fixture(origin=True)
    ctx.brain(REVIEWER_NAME)
    plain, data = both(ctx, t, "preflight", repo, "--expect-email", "dev@example.com", "--date", DATE, rc=1)
    t.eq(plain.last, "PREFLIGHT: blocked(reviewer)", "a name is not a handle")
    t.has(plain.lines, "REVIEWER brain %s:4" % ctx.path(BRAIN_EXEC), "brain file and line shown")
    t.has(plain.lines, '"Acme Dev (A) · forge: gitlab · merge policy: wait" · no @handle → blocked', "value quoted")
    ctx.brain(REVIEWER_OK)
    plain, data = both(ctx, t, "preflight", repo, "--expect-email", "dev@example.com", "--date", DATE, rc=0)
    t.eq(dig(data, "reviewer", "handle"), "@reviewer-handle", "canonical handle")
    t.eq(dig(data, "reviewer", "forge"), "gitlab", "forge")
    ctx.brain(REVIEWER_NAME)
    skill = ctx.skill()
    write(os.path.join(skill, "dependencies.md"), delivery_file("acme-site"))
    plain, data = both(ctx, t, "preflight", repo, "--date", DATE, rc=0)
    t.eq(dig(data, "reviewer", "handle"), "@delivery-handle", "Delivery Reviewer when the brain has no handle")
    t.eq(dig(data, "reviewer", "source"), "dependencies.md", "reviewer source")
    shutil.rmtree(ctx.path("acme/ai/ai-brain"))
    os.remove(os.path.join(skill, "dependencies.md"))
    ctx.brain("> **Reviewer:** @linked-handle (github)", rel="elsewhere/brain/execute.md")
    os.symlink(ctx.path("elsewhere/brain"), os.path.join(repo, "ai-brain"))
    with open(os.path.join(repo, ".git", "info", "exclude"), "a", encoding="utf-8") as fh:
        fh.write("ai-brain\n")
    plain, data = both(ctx, t, "preflight", repo, "--expect-email", "dev@example.com", "--date", DATE, rc=0)
    t.eq(dig(data, "reviewer", "handle"), "@linked-handle", "brain through the repo ai-brain symlink")
    os.remove(os.path.join(repo, "ai-brain"))
    ctx.brain("> **Reviewer:** @docs-handle (gitlab)", rel="acme/docs/ai-brain/execute.md")
    plain, data = both(ctx, t, "preflight", repo, "--expect-email", "dev@example.com", "--date", DATE, rc=0)
    t.eq(dig(data, "reviewer", "handle"), "@docs-handle", "brain at the docs/ai-brain position")


def case_preflight_context_flat_references_ambiguous(ctx, t):
    repo = ready_repo(ctx)
    flat = ctx.skill()
    write(os.path.join(flat, "dependencies.md"), delivery_file("acme-site", reviewer="@reviewer-handle (gitlab)"))
    plain, data = both(ctx, t, "preflight", repo, "--expect-email", "dev@example.com", "--date", DATE, rc=0)
    t.has(plain.lines, "CONTEXT code-project-context-acme · layout flat · dependencies.md found", "flat layout")
    shutil.rmtree(flat)
    refs = ctx.skill(layout="references")
    write(os.path.join(refs, "references", "dependencies.md"), delivery_file("acme-site"))
    plain, data = both(ctx, t, "preflight", repo, "--expect-email", "dev@example.com", "--date", DATE, rc=0)
    t.has(plain.lines, "layout references · dependencies.md found", "references layout")
    t.eq(dig(data, "context", "file"), os.path.join(os.path.realpath(refs), "references", "dependencies.md"), "json context file")
    other = ctx.skill(rel="acme/ai/acme-ai-common/plugins/acme-ops/skills/code-project-context-ops")
    plain, data = both(ctx, t, "preflight", repo, "--expect-email", "dev@example.com", "--date", DATE, rc=1)
    t.eq(plain.last, "PREFLIGHT: blocked(context-ambiguous)", "two skills name the repo")
    t.has(plain.lines, "Para ti: pass --context", "owner hint")
    plain, data = both(ctx, t, "preflight", repo, "--context", other, "--expect-email", "dev@example.com", "--date",
                       DATE, rc=0)
    t.has(plain.lines, "CONTEXT code-project-context-ops · layout flat · dependencies.md missing", "--context wins")


def case_preflight_open_run(ctx, t):
    repo = ready_repo(ctx)
    ctx.config["glab"]["mr_list"] = [{"iid": 7, "source_branch": "deps/2026-10-20-patch-minor", "target_branch": "main",
                                      "state": "opened", "labels": ["dependencies"], "draft": True}]
    ctx.save()
    plain, data = both(ctx, t, "preflight", repo, "--expect-email", "dev@example.com", "--date", DATE, rc=1)
    t.eq(plain.last, "PREFLIGHT: blocked(open-run)", "an opened dependency MR blocks")
    t.has(plain.lines, "Para ti: merge or close the open dependency MRs first: !7", "owner hint")
    t.ok(any(e["tool"] == "glab" and e["argv"][:4] == ["mr", "list", "--label", "dependencies"] for e in ctx.log()),
         "open-run comes from glab mr list --label dependencies")
    ctx.config["glab"]["mr_list"] = []
    ctx.save()
    ctx.git(repo, "branch", "deps/2026-10-20-patch-minor")
    ctx.git(repo, "push", "-q", "origin", "deps/2026-10-20-patch-minor")
    plain, data = both(ctx, t, "preflight", repo, "--expect-email", "dev@example.com", "--date", DATE, rc=0)
    t.eq(plain.last, "PREFLIGHT: ready", "a remote branch without an MR does not block")
    t.has(plain.lines, "review: local-branches deps/2026-10-20-patch-minor", "local branch warning")
    t.eq(dig(data, "git", "remote_branches"), ["deps/2026-10-20-patch-minor"], "remote deps branches listed")
    plain, _ = both(ctx, t, "preflight", repo, "--expect-email", "dev@example.com", "--date", DATE, "--offline", rc=0)
    t.has(plain.lines, "open MRs not checked (offline)", "offline skips glab")


def case_preflight_behind(ctx, t):
    repo = ready_repo(ctx)
    other = ctx.path("clone")
    subprocess.run(["git", "clone", "-q", ctx.path("remotes/acme-site.git"), other], env=ctx.env, check=True)
    write(os.path.join(other, "CHANGES.md"), "upstream\n")
    ctx.commit(other, "upstream")
    ctx.git(other, "push", "-q", "origin", "main")
    plain, data = both(ctx, t, "preflight", repo, "--expect-email", "dev@example.com", "--date", DATE, rc=1)
    t.eq(plain.last, "PREFLIGHT: blocked(behind)", "origin moved ahead")
    t.has(plain.lines, "pull --ff-only", "owner command")
    plain, _ = both(ctx, t, "preflight", repo, "--expect-email", "dev@example.com", "--date", DATE, "--offline", rc=0)
    t.eq(plain.last, "PREFLIGHT: ready", "offline compares the local origin ref only")


def case_external_missing(ctx, t):
    repo = ready_repo(ctx)
    data = json.loads(read(os.path.join(repo, "package.json")))
    data["scripts"]["build"] = "bash %s && tsc -p tsconfig.json" % (os.pardir + "/acme-infra/check.sh")
    write(os.path.join(repo, "package.json"), json.dumps(data, indent=2) + "\n")
    ctx.commit(repo, "external build step")
    ctx.git(repo, "push", "-q", "origin", "main")
    plain, data = both(ctx, t, "preflight", repo, "--expect-email", "dev@example.com", "--date", DATE, rc=1)
    t.eq(plain.last, "PREFLIGHT: blocked(external-missing)", "missing sibling path")
    t.has(plain.lines, "external %s/acme-infra/check.sh (missing)" % os.pardir, "path shown")
    write(ctx.path("acme/projects/acme-infra/check.sh"), "exit 0\n")
    plain, _ = both(ctx, t, "preflight", repo, "--expect-email", "dev@example.com", "--date", DATE, rc=0)
    t.has(plain.lines, "(present)", "present once checked out")


def case_node_resolution_order(ctx, t):
    for v in ("20.20.0", "22.22.0", "24.22.1"):
        ctx.node_install(v)
    repo = ctx.fixture()

    def env_of(*args):
        plain, data = both(ctx, t, "plan", repo, "--offline", "--date", DATE, *args, rc=1)
        return data.get("env") or {}
    write(os.path.join(repo, ".node-version"), "22\n")
    e = env_of()
    t.eq((e.get("node_source"), e.get("node_version"), e.get("node_found")), (".nvmrc", "20.11.0", "exact"), ".nvmrc first")
    t.eq(e.get("path_prefix"), "PATH=%s:$PATH" % ctx.path("nvm/v20.11.0/bin"), "path_prefix")
    os.remove(os.path.join(repo, ".nvmrc"))
    e = env_of()
    t.eq((e.get("node_source"), e.get("node_version"), e.get("node_found")), (".node-version", "22.22.0", "major"), ".node-version next")
    os.remove(os.path.join(repo, ".node-version"))
    data = json.loads(read(os.path.join(repo, "package.json")))
    data["engines"] = {"node": ">=20 <23"}
    data["devEngines"] = {"runtime": {"name": "node", "version": "^24"}}
    write(os.path.join(repo, "package.json"), json.dumps(data, indent=2) + "\n")
    e = env_of()
    t.eq((e.get("node_source"), e.get("node_version")), ("engines.node", "22.22.0"), "engines: highest install that satisfies")
    del data["engines"]
    write(os.path.join(repo, "package.json"), json.dumps(data, indent=2) + "\n")
    e = env_of()
    t.eq((e.get("node_source"), e.get("node_version")), ("devEngines.runtime", "24.22.1"), "devEngines last")
    del data["devEngines"]
    write(os.path.join(repo, "package.json"), json.dumps(data, indent=2) + "\n")
    write(os.path.join(repo, ".nvmrc"), "lts/iron\n")
    e = env_of()
    t.eq((e.get("pin_major"), e.get("node_version")), (20, "20.20.0"), "lts/<codename> maps to its major")
    write(os.path.join(repo, ".nvmrc"), "21.0.0\n")
    e = env_of()
    t.eq((e.get("node_found"), e.get("path_prefix")), ("none", ""), "pin not installed: PATH as is")
    ctx.commit(repo, "pins")
    ctx.brain()
    plain, _ = both(ctx, t, "preflight", repo, "--offline", "--expect-email", "dev@example.com", "--date", DATE, rc=1)
    t.eq(plain.last, "PREFLIGHT: blocked(node-missing)", "node-missing blocker")
    t.ok(not any(e.get("argv", [])[:1] == ["use"] for e in ctx.log()), "never nvm use")


# ------------------------------------------------------------------ cases: plan
def case_plan_offline_fixture(ctx, t):
    repo = ctx.fixture()
    ctx.stubs()
    ctx.clear_log()
    plain, data = both(ctx, t, "plan", repo, "--offline", "--date", DATE, rc=1, trees=[repo])
    text = plain.lines
    t.has(text, "RUNTIME node 20.11.0 (.nvmrc) · eol 2026-04-30 · newest LTS 24 · CI node:20 aligned · SHADOWED by node@25.7.0", "runtime line")
    t.has(text, "NEVER-AUTO 1: node ^25.7.0 → Para ti", "never-auto line")
    t.has(text, "mcr.microsoft.com/playwright:v1.55.0 ≠ @playwright/test 1.58.2", "CI image mismatch")
    t.ok(any(l.startswith("HOLDS 4: typescript cap <6 (renovate.json)") for l in text), "holds line")
    t.ok(plain.last.startswith("DEPS: partial(offline) "), "partial(offline) verdict")
    t.ok(plain.last.endswith("never-auto(1) runtime(eol)"), "verdict suffixes")
    t.eq(data.get("partial"), ["offline"], "json partial")
    t.eq(ctx.server.requests, [], "offline makes no HTTP call")
    calls = [e["argv"] for e in ctx.log() if e["tool"] in ("npm", "pnpm", "glab")]
    t.ok(all(a == ["--version"] for a in calls), "offline runs only --version, got %r" % calls[:3])
    t.eq(dig(data, "runtimes", "node", "decision"), "para-ti", "runtime decision with the shadowing package")
    t.eq([n["name"] for n in data.get("never_auto") or []], ["node"], "never_auto")
    t.eq(dig(data, "smoke", "node_pin"), "20.11.0", "smoke node pin derives from env")


def case_plan_online_stubbed_waves(ctx, t):
    repo = ctx.fixture()
    ctx.stubs()
    ctx.config["npm"]["outdated"]["exit"] = 0
    ctx.save()
    scratch = ctx.path("scratch")
    plain, data = both(ctx, t, "plan", repo, "--date", DATE, rc=1, trees=[repo])
    t.eq(plain.last, "DEPS: outdated(6) majors(2) advisories(1) holds(4) never-auto(1) runtime(eol)", "verdict")
    pm = wave(data, "patch-minor") or {}
    t.eq([(f["name"], f["from"], f["to"]) for f in pm.get("from_to", [])],
         [("express", "4.21.2", "4.22.3"), ("@playwright/test", "1.58.2", "1.64.0"), ("@types/express", "4.17.23", "4.17.25"),
          ("@types/node", "20.19.9", "20.19.25"), ("@types/react", "18.3.27", "18.3.28")], "patch-minor moves")
    t.eq([c["run"] for c in pm.get("commands", [])],
         ["npm install --save-prod 'express@^4.22.3'",
          "npm install --save-dev '@playwright/test@^1.64.0' '@types/express@^4.17.25' '@types/node@^20.19.25' '@types/react@^18.3.28'"],
         "patch-minor commands")
    t.eq(shlex.split(dig(pm, "commands", 0, "run") or ""), ["npm", "install", "--save-prod", "express@^4.22.3"],
         "the quoted command keeps its argv")
    t.ok({"file": ".gitlab-ci.yml", "key": "e2e.image", "from": "mcr.microsoft.com/playwright:v1.55.0-jammy",
          "to": "mcr.microsoft.com/playwright:v1.64.0-jammy", "note": "align"} in pm.get("edits", []), "Playwright image follows")
    t.eq(pm.get("closes"), ["GHSA-2222-3333-4444"], "closes the transitive advisory through express")
    t.eq([w["id"] for w in data.get("waves") or []], ["patch-minor", "major:helmet", "major:express"], "wave order")
    t.eq([(w["branch"], w["base"]) for w in data["waves"]],
         [("deps/2026-10-25-patch-minor", "main"), ("deps/2026-10-25-major-helmet", "deps/2026-10-25-patch-minor"),
          ("deps/2026-10-25-major-express", "deps/2026-10-25-major-helmet")], "linear stack")
    ex = wave(data, "major:express") or {}
    t.eq([(f["name"], f["from"], f["to"]) for f in ex.get("from_to", [])],
         [("@types/express", "4.17.25", "5.0.6"), ("express", "4.22.3", "5.3.0")], "family moves together")
    t.ok("https://express.example.com/migration-5" in ex.get("migration_refs", []), "migration refs from npm view")
    t.eq(pkg(data, "@playwright/test").get("age_days"), 15, "min-age picked the 15-day-old 1.64.0")
    t.eq(pkg(data, "typescript").get("wave"), "held", "typescript capped")
    t.eq(pkg(data, "react").get("wave"), "held", "react major disabled")
    t.eq(pkg(data, "@types/node").get("blocked"), "follows the runtime (node 20)", "@types/node follows the runtime")
    ta = (data.get("transitive_advisories") or [{}])[0]
    t.eq((ta.get("package"), ta.get("via"), ta.get("fix"), ta.get("parent_target")),
         ("body-parser", ["express"], "parent", "4.22.3"), "transitive fix through the parent")
    post = ctx.server.posts()
    t.ok(post and post[0][2].get("body-parser") == ["1.20.3"], "bulk POST carries the locked transitive versions")
    t.ok(not any("audit" in e["argv"] for e in ctx.log()), "never runs npm audit")
    r = ctx.run("plan", repo, "--date", DATE, "--scratch", scratch, "--write")
    t.eq(r.rc, 1, "--write exit code")
    t.has(r.lines, "PLAN written", "written line")
    saved = json.loads(read(os.path.join(scratch, "plan.json")) or "{}")
    t.eq(list(saved), PLAN_KEYS, "plan.json keys")
    t.eq(os.listdir(scratch), ["plan.json"], "--write writes plan.json only")
    t.eq(ctx.git(repo, "status", "--porcelain"), "", "the repo stays clean")


def synth(ctx, name, deps, times=None, outdated=None, bulk=None, files=None, git=True, pm_field=None, scripts=None):
    """A synthetic npm project with its stubs: deps {name: (kind, declared, locked)}, times {name: {v: day}}."""
    repo = npm_project(ctx, ctx.path("acme/projects/" + name), deps, pm_field=pm_field, scripts=scripts)
    for rel, body in (files or {}).items():
        write(os.path.join(repo, rel), body)
    times = times or {}
    ctx.config["npm"]["times"] = {n: dict({v: iso(d) for v, d in vs.items()}, created=iso("2020-01-01"), modified=iso("2026-10-01"))
                                  for n, vs in times.items()}
    rows = outdated or {}
    for n, vs in times.items():
        if n not in rows and n in deps:
            newest = sorted(vs, key=lambda v: [int(x) for x in v.split("-")[0].split(".")])[-1]
            if newest != deps[n][2]:
                rows[n] = (deps[n][2], deps[n][2], newest)
    ctx.config["npm"]["outdated"] = {"stdout": {n: {"current": c, "wanted": w, "latest": l} for n, (c, w, l) in rows.items()}, "exit": 1}
    ctx.save()
    ctx.server.bulk = bulk or {}
    if git:
        ctx.init_git(repo)
    return repo


OLD = "2026-01-01"


def case_majors_cap_order_security_prioritize(ctx, t):
    deps = {"alpha": ("dev", "^1.0.0", "1.0.0"), "bravo": ("prod", "^1.0.0", "1.0.0"),
            "express": ("prod", "^4.0.0", "4.0.0"), "delta": ("prod", "^1.4.0", "1.4.0"), "echo": ("prod", "^1.0.0", "1.0.0")}
    times = {n: {deps[n][2]: OLD, ("5.0.0" if n == "express" else "2.0.0"): OLD} for n in deps}
    bulk = {"delta": [{"id": 9, "url": "https://advisories.example.com/GHSA-cccc-dddd-ffff", "severity": "critical",
                       "vulnerable_versions": "<2.0.0", "title": "fixture"}]}
    repo = synth(ctx, "acme-majors", deps, times, bulk=bulk)
    plain, data = both(ctx, t, "plan", repo, "--date", DATE, "--max-majors", "2", "--prioritize", "echo", rc=1)
    t.eq([w["id"] for w in data.get("waves") or []], ["major:delta", "major:echo"], "security first, then --prioritize")
    t.eq([p["name"] for p in data.get("pending_majors") or []], ["alpha", "bravo", "express"], "the rest by ascending risk")
    t.eq([pkg(data, n).get("risk") for n in ("alpha", "bravo", "express")], [2, 3, 4], "risk per kind and framework")
    t.has(plain.lines, "MAJORS 5 (this run 2 of cap 2): delta 1.4.0→2.0.0, echo 1.0.0→2.0.0 · pending 3", "majors line")
    t.has(data.get("para_ti"), "majors pending (cap 2 per run)", "pending majors go to Para ti")
    t.eq(dig(wave(data, "major:delta"), "closes"), ["GHSA-cccc-dddd-ffff"], "the delta major closes its advisory")


def case_one_major_step(ctx, t):
    deps = {"uuid": ("prod", "^13.0.2", "13.0.2"), "zeta": ("prod", "^1.2.0", "1.2.0")}
    times = {"uuid": {"13.0.2": OLD, "14.0.0": OLD, "14.0.3": OLD, "15.1.0": OLD},
             "zeta": {"1.2.0": OLD, "3.0.0": OLD, "3.1.0": OLD}}
    repo = synth(ctx, "acme-steps", deps, times)
    plain, data = both(ctx, t, "plan", repo, "--date", DATE, rc=1)
    t.eq(pkg(data, "uuid").get("target"), "14.0.3", "one step: the latest of the next major")
    t.eq(pkg(data, "zeta").get("target"), "3.1.0", "a skipped major goes to the next existing line")
    t.eq(dig(wave(data, "major:uuid"), "commands", 0, "run"), "npm install --save-prod 'uuid@^14.0.3'", "major command")


def case_min_age_and_security_bypass(ctx, t):
    deps = {"kilo": ("prod", "^2.0.0", "2.0.0"), "lima": ("prod", "^3.0.0", "3.0.0"), "mike": ("prod", "^1.0.0", "1.0.0")}
    times = {"kilo": {"2.0.0": OLD, "2.1.0": "2026-09-25", "2.2.0": "2026-10-24"},
             "lima": {"3.0.0": OLD, "3.0.5": "2026-10-24", "3.1.0": "2026-10-25"},
             "mike": {"1.0.0": OLD, "1.1.0": "2026-10-20"}}
    bulk = {"lima": [{"id": 3, "url": "https://advisories.example.com/GHSA-2345-6789-cfgh", "severity": "high",
                      "vulnerable_versions": "<3.0.5"}]}
    skill = ctx.skill(names=("acme-age",))
    repo = synth(ctx, "acme-age", deps, times, bulk=bulk)
    write(os.path.join(skill, "dependencies.md"), delivery_file("acme-age", rules="| mike | min-age | 10 | slow | %s | |\n" % DATE))
    plain, data = both(ctx, t, "plan", repo, "--date", DATE, rc=1)
    t.eq(pkg(data, "kilo").get("target"), "2.1.0", "the 1-day-old 2.2.0 waits (default 3 days)")
    t.eq((pkg(data, "lima").get("target"), pkg(data, "lima").get("age_days")), ("3.0.5", 1), "a security fix skips min-age")
    t.eq(pkg(data, "mike").get("target"), None, "the Policy min-age of 10 days holds the 5-day-old release")
    t.eq(dig(wave(data, "patch-minor"), "closes"), ["GHSA-2345-6789-cfgh"], "the bypassed fix closes the advisory")


def case_policy_table_rules_and_bad_row(ctx, t):
    names = ("kilo", "lima", "mike", "november", "oscar", "papa", "romeo", "sierra", "tango", "uniform")
    deps = {n: ("prod", "^1.0.0", "1.0.0") for n in names}
    deps["november"] = ("prod", "1.0.0", "1.0.0")
    times = {n: {"1.0.0": OLD, "1.1.0": OLD, "2.0.0": OLD, "3.0.0": OLD} for n in names}
    skill = ctx.skill(names=("acme-policy",))
    repo = synth(ctx, "acme-policy", deps, times)
    rules = ("| kilo | hold | | frozen by the owner | 2026-01-01 | 2026-12-31 |\n"
             "| lima | hold-major | | API break | 2026-01-01 | |\n"
             "| mike | cap | <2 | plugin needs 1.x | 2026-01-01 | |\n"
             "| november | pin | | audited build | 2026-01-01 | |\n"
             "| oscar | group | ui-kit | released together | 2026-01-01 | |\n"
             "| papa | group | ui-kit | released together | 2026-01-01 | |\n"
             "| romeo | never-auto | | vendored binary | 2026-01-01 | |\n"
             "| sierra | bogus | | | | |\n"
             "| tango | hold | | waiting | 2026-01-01 | 2026-02-01 |\n"
             "| uniform | cap | | missing value | | |\n"
             "| broken row |\n")
    write(os.path.join(skill, "dependencies.md"), delivery_file("acme-policy", rules=rules))
    plain, data = both(ctx, t, "plan", repo, "--date", DATE, "--max-majors", "5", rc=1)
    t.eq((pkg(data, "kilo").get("wave"), dig(pkg(data, "kilo"), "held_by", "rule")), ("held", "hold"), "hold")
    t.eq((pkg(data, "lima").get("target"), pkg(data, "lima").get("wave")), ("1.1.0", "patch-minor"), "hold-major keeps the minor")
    t.eq(pkg(data, "mike").get("major_target"), None, "cap <2 blocks the major")
    t.ok("--save-exact november@1.1.0" in " ".join(c["run"] for c in dig(wave(data, "patch-minor"), "commands") or []), "pin keeps exact")
    t.eq((pkg(data, "oscar").get("family"), pkg(data, "papa").get("family")), ("ui-kit", "ui-kit"), "group = one family")
    t.ok(wave(data, "major:ui-kit") is not None and sorted(wave(data, "major:ui-kit")["packages"]) == ["oscar", "papa"], "group wave")
    t.eq(pkg(data, "romeo").get("wave"), "never-auto", "never-auto from the Policy table")
    review = data.get("review") or []
    t.ok(any(re.search(r"dependencies\.md:\d+ unknown rule 'bogus' for sierra — row ignored", r) for r in review), "unknown rule")
    t.ok(any("hold expired for tango (review by 2026-02-01) — still held" in r for r in review), "expired hold")
    t.eq(pkg(data, "tango").get("wave"), "held", "an expired hold stays held")
    t.ok(any("cap of uniform needs a range" in r for r in review), "cap without a value")
    t.ok(any("rules row has 1 cells" in r for r in review), "malformed row")
    t.eq(pkg(data, "sierra").get("wave"), "major:sierra", "an ignored row leaves the package to the defaults")


def case_renovate_caps_honoured(ctx, t):
    names = ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf")
    deps = {n: ("prod", "^2.0.0", "2.0.0") for n in names}
    times = {n: {"2.0.0": OLD, "2.1.0": OLD, "3.0.0": OLD, "4.0.0": OLD} for n in names}
    times["golf"] = {"2.0.0": OLD, "2.1.0": "2026-10-20"}
    renovate = {"extends": ["config:base"], "minimumReleaseAge": "7 days", "packageRules": [
        {"matchPackageNames": ["alpha", "foxtrot"], "allowedVersions": "<3"},
        {"matchPackageNames": ["bravo"], "matchUpdateTypes": ["major"], "enabled": False},
        {"matchPackageNames": ["charlie"], "enabled": False},
        {"matchPackageNames": ["delta", "echo"], "groupName": "duo"}]}
    skill = ctx.skill(names=("acme-renovate",))
    repo = synth(ctx, "acme-renovate", deps, times, files={"renovate.json": json.dumps(renovate, indent=2) + "\n"})
    write(os.path.join(skill, "dependencies.md"), delivery_file("acme-renovate", rules="| foxtrot | cap | <5 | ok | %s | |\n" % DATE))
    plain, data = both(ctx, t, "plan", repo, "--date", DATE, "--max-majors", "5", rc=1)
    t.eq(dig(pkg(data, "alpha"), "held_by"), {"rule": "cap", "value": "<3", "source": "renovate.json"}, "renovate cap")
    t.eq((pkg(data, "alpha").get("major_target"), pkg(data, "alpha").get("target")), (None, "2.1.0"), "capped below 3")
    t.eq(dig(pkg(data, "bravo"), "held_by", "rule"), "hold-major", "disabled majors")
    t.eq((dig(pkg(data, "charlie"), "held_by", "rule"), pkg(data, "charlie").get("wave")), ("hold", "held"), "disabled")
    t.ok(wave(data, "major:duo") is not None, "groupName makes one family")
    t.eq(dig(pkg(data, "foxtrot"), "held_by", "source"), "dependencies.md", "the Policy table beats renovate.json")
    t.eq(pkg(data, "foxtrot").get("target"), "3.0.0", "foxtrot may take 3.x under the Policy cap")
    t.eq(pkg(data, "golf").get("target"), None, "minimumReleaseAge 7 days holds the 5-day-old release")
    t.ok(any("renovate.json extends config:base — not expanded" in r for r in data.get("review") or []), "extends noted")
    holds = [h["name"] for h in data.get("holds") or []]
    t.eq(holds, ["charlie", "alpha", "foxtrot", "bravo"], "holds ordered hold, cap, hold-major")


def case_families_move_together(ctx, t):
    deps = {"react": ("prod", "^18.2.0", "18.2.0"), "react-dom": ("prod", "^18.2.0", "18.2.0"),
            "@types/react": ("dev", "^18.2.0", "18.2.0"), "vitest": ("dev", "^2.0.0", "2.0.0"),
            "@vitest/coverage-v8": ("dev", "^2.0.0", "2.0.0"), "next": ("prod", "^14.0.0", "14.0.0"),
            "eslint-config-next": ("dev", "^14.0.0", "14.0.0")}
    times = {"react": {"18.2.0": OLD, "19.0.0": OLD}, "react-dom": {"18.2.0": OLD, "19.0.0": OLD},
             "@types/react": {"18.2.0": OLD, "19.0.1": OLD}, "vitest": {"2.0.0": OLD, "3.0.0": OLD},
             "@vitest/coverage-v8": {"2.0.0": OLD, "3.0.0": OLD}, "next": {"14.0.0": OLD, "15.0.0": OLD},
             "eslint-config-next": {"14.0.0": OLD, "14.0.4": OLD}}
    repo = synth(ctx, "acme-families", deps, times)
    plain, data = both(ctx, t, "plan", repo, "--date", DATE, "--max-majors", "5", rc=1)
    t.eq(sorted(dig(wave(data, "major:react"), "packages") or []), ["@types/react", "react", "react-dom"], "react family")
    t.eq(sorted(dig(wave(data, "major:vitest"), "packages") or []), ["@vitest/coverage-v8", "vitest"], "vitest family")
    t.eq(wave(data, "major:next"), None, "next waits for eslint-config-next")
    nxt = next((p for p in data.get("pending_majors") or [] if p["name"] == "next"), {})
    t.eq(nxt.get("reason"), "family incomplete: eslint-config-next", "pending reason")
    fams = {f["family"]: f["members"] for f in data.get("families") or []}
    t.eq(fams.get("react"), ["@types/react", "react", "react-dom"], "families listed")


def case_types_node_follows_runtime(ctx, t):
    deps = {"@types/node": ("dev", "^20.10.0", "20.10.0")}
    times = {"@types/node": {"20.10.0": OLD, "20.19.0": OLD, "22.5.0": OLD, "24.1.0": OLD}}
    repo = synth(ctx, "acme-types", deps, times, files={".nvmrc": "20.11.0\n"})
    plain, data = both(ctx, t, "plan", repo, "--date", DATE, rc=1)
    t.eq((pkg(data, "@types/node").get("target"), pkg(data, "@types/node").get("wave")), ("20.19.0", "patch-minor"), "same major")
    t.eq(pkg(data, "@types/node").get("blocked"), "follows the runtime (node 20)", "majors wait for the runtime")
    t.eq([w["id"] for w in data.get("waves") or []], ["patch-minor"], "no @types/node major")
    ctx.node_install("22.22.0")
    write(os.path.join(repo, ".nvmrc"), "22\n")
    plain, data = both(ctx, t, "plan", repo, "--date", DATE, rc=1)
    t.eq(dig(wave(data, "major:runtime-node"), "from_to", 0, "to"), "22.5.0", "@types/node aligns up to the runtime")


def case_ci_alignment_items(ctx, t):
    deps = {"@playwright/test": ("dev", "^1.50.0", "1.52.0"), "supabase": ("dev", "^2.10.0", "2.10.0"),
            "@types/node": ("dev", "^20.10.0", "20.10.0")}
    ci = ("stages: [test]\n\nbuild:\n  image: node:18\n  script:\n    - npm run build\n\n"
          "lint:\n  image: node:22.11.0\n  script:\n    - npm run lint\n\n"
          "unit:\n  image: node:18.19.0\n  services:\n    - postgres:16\n  script:\n    - npm test\n\n"
          "e2e:\n  image: mcr.microsoft.com/playwright:v1.50.0-noble\n  script:\n    - npx playwright test\n\n"
          "db:\n  image: node:22\n  script:\n    - npx supabase@1.200.0 db lint\n")
    files = {".nvmrc": "22.11.0\n", ".gitlab-ci.yml": ci, "Dockerfile": "FROM node:18-alpine\nRUN echo ok\n"}
    repo = synth(ctx, "acme-ci", deps, {}, files=files)
    plain, data = both(ctx, t, "plan", repo, "--offline", "--date", DATE, rc=1)
    edits = dig(wave(data, "patch-minor"), "edits") or []
    pairs = [(e["file"], e["key"], e["from"], e["to"]) for e in edits]
    t.ok((".gitlab-ci.yml", "build.image", "node:18", "node:22") in pairs, "node image aligned to the pin")
    t.ok(("Dockerfile", "line 1", "node:18-alpine", "node:22-alpine") in pairs, "Dockerfile FROM aligned")
    t.ok((".gitlab-ci.yml", "e2e.image", "mcr.microsoft.com/playwright:v1.50.0-noble",
          "mcr.microsoft.com/playwright:v1.52.0-noble") in pairs, "Playwright image follows the lock")
    t.ok(any(e["from"] == "supabase 1.200.0" and e["to"] == "supabase 2.10.0" for e in edits), "supabase CLI pin")
    t.ok(not any(e["from"] == "node:22.11.0" for e in edits), "an aligned full-version tag is left alone")
    manual = dig(data, "ci", "manual") or []
    t.ok(any("service postgres:16" in m for m in manual), "service image is manual")
    t.ok(any("node:18.19.0 (full-version tag)" in m for m in manual), "full-version mismatch is manual")
    t.has(plain.lines, "CI images 6 (node:18 ≠ node 22, mcr.microsoft.com/playwright:v1.50.0 ≠ @playwright/test 1.52.0", "CI line")
    write(os.path.join(repo, ".nvmrc"), "20.11.0\n")
    plain, data = both(ctx, t, "plan", repo, "--offline", "--date", DATE, rc=1)
    rt = wave(data, "major:runtime-node") or {}
    pairs = [(e["file"], e["key"], e["from"], e["to"]) for e in rt.get("edits", [])]
    t.eq(dig(data, "runtimes", "node", "decision"), "wave", "eol + a Dockerfile deploy runtime + no shadowing package: a runtime wave")
    t.ok((".nvmrc", "value", "20.11.0", "24") in pairs, "the runtime wave moves .nvmrc to the newest LTS")
    t.ok(("Dockerfile", "line 1", "node:18-alpine", "node:24-alpine") in pairs, "and the Dockerfile")
    t.ok((".gitlab-ci.yml", "build.image", "node:18", "node:24") in pairs, "and the CI node images")
    t.eq([(f["name"], f["to"]) for f in rt.get("from_to", [])], [("@types/node", "24.0.0")], "@types/node moves with it")
    t.ok(not any(e["key"] == "build.image" for e in dig(wave(data, "patch-minor"), "edits") or []), "no patch-minor align then")


def case_npm_outdated_exit1_ok(ctx, t):
    repo = ctx.fixture()
    ctx.stubs()
    ctx.config["npm"]["outdated"]["exit"] = 1
    ctx.save()
    plain, data = both(ctx, t, "plan", repo, "--date", DATE, rc=1)
    t.ok("outdated" not in (data.get("partial") or []), "exit 1 with JSON is a success")
    t.eq(pkg(data, "express").get("latest"), "5.3.0", "outdated data used")
    t.eq(data.get("state"), "needed", "state needed, not partial")


def case_audit_garbage_partial(ctx, t):
    repo = ctx.fixture()
    ctx.stubs()
    ctx.server.bulk_raw = "<html>upstream error</html>"
    ctx.config["npm"]["outdated"] = {"stdout": "npm ERR! something went wrong\n", "exit": 1}
    ctx.save()
    plain, data = both(ctx, t, "plan", repo, "--date", DATE, rc=1)
    t.ok(plain.last.startswith("DEPS: partial(outdated,audit) "), "garbage gives partial(outdated,audit): %r" % plain.last)
    t.eq(data.get("state"), "partial", "json state")


def pnpm_repo(ctx, name="acme-mono", manager="pnpm@10.4.1", extra_snap=""):
    repo = ctx.path("acme/projects/" + name)
    write(os.path.join(repo, "package.json"), json.dumps({
        "name": name, "private": True, "packageManager": manager,
        "scripts": {"build": "pnpm -r build"},
        "dependencies": {"express": "^4.21.0"}, "devDependencies": {"typescript": "catalog:"}}, indent=2) + "\n")
    write(os.path.join(repo, "pnpm-workspace.yaml"), "packages:\n  - packages/*\n\ncatalog:\n  # one TypeScript for every workspace\n  typescript: ^5.3.0\n")
    write(os.path.join(repo, "packages/ui/package.json"), json.dumps({
        "name": "@acme/ui", "version": "1.0.0", "devDependencies": {"vitest": "^2.0.0"}}, indent=2) + "\n")
    lock = ("lockfileVersion: '9.0'\n\nsettings:\n  autoInstallPeers: true\n\ncatalogs:\n  default:\n    typescript:\n"
            "      specifier: ^5.3.0\n      version: 5.9.3\n\nimporters:\n\n  .:\n    dependencies:\n      express:\n"
            "        specifier: ^4.21.0\n        version: 4.21.2\n    devDependencies:\n      typescript:\n"
            "        specifier: 'catalog:'\n        version: 5.9.3\n\n  packages/ui:\n    devDependencies:\n      vitest:\n"
            "        specifier: ^2.0.0\n        version: 2.0.0\n\npackages:\n\n  body-parser@1.20.3:\n"
            "    resolution: {integrity: sha512-x}\n\n  express@4.21.2:\n    resolution: {integrity: sha512-y}\n\n"
            "  typescript@5.9.3:\n    resolution: {integrity: sha512-z}\n\n  vitest@2.0.0:\n    resolution: {integrity: sha512-w}\n\n"
            "snapshots:\n\n  body-parser@1.20.3: {}\n\n  express@4.21.2:\n    dependencies:\n      body-parser: 1.20.3\n%s\n"
            "  typescript@5.9.3: {}\n\n  vitest@2.0.0: {}\n") % extra_snap
    write(os.path.join(repo, "pnpm-lock.yaml"), lock)
    ctx.init_git(repo)
    return repo


def pnpm_stubs(ctx, exit_code=1):
    ctx.config["pnpm"]["outdated"] = {"stdout": {
        "express": {"current": "4.21.2", "wanted": "4.22.3", "latest": "5.3.0", "dependencyType": "dependencies"},
        "typescript": {"current": "5.9.3", "wanted": "5.9.3", "latest": "5.9.4", "dependencyType": "devDependencies"},
        "vitest": {"current": "2.0.0", "wanted": "2.1.0", "latest": "2.1.0", "dependencyType": "devDependencies"}},
        "exit": exit_code}
    ctx.config["pnpm"]["audit"] = {"stdout": {"advisories": {"1": {"module_name": "body-parser", "severity": "high"}},
                                              "metadata": {"vulnerabilities": {"high": 1}}}, "exit": 1}
    ctx.config["npm"]["times"] = {"express": {"4.21.2": iso(OLD), "4.22.3": iso(OLD), "5.3.0": iso(OLD)},
                                  "typescript": {"5.9.3": iso(OLD), "5.9.4": iso(OLD)},
                                  "vitest": {"2.0.0": iso(OLD), "2.1.0": iso(OLD)}}
    ctx.save()
    ctx.server.bulk = {"body-parser": [{"id": 1, "url": "https://advisories.example.com/GHSA-2222-3333-4444",
                                        "severity": "high", "vulnerable_versions": "<1.20.4"}]}


def case_pnpm10_bulk_fallback(ctx, t):
    repo = pnpm_repo(ctx)
    pnpm_stubs(ctx)
    plain, data = both(ctx, t, "plan", repo, "--date", DATE, rc=1)
    t.eq(dig(data, "manifest", "package_manager", "name"), "pnpm", "pnpm project")
    body = (ctx.server.posts() or [(None, None, {})])[0][2] or {}
    t.eq((body.get("body-parser"), body.get("express")), (["1.20.3"], ["4.21.2"]), "bulk POST from pnpm-lock packages")
    ta = (data.get("transitive_advisories") or [{}])[0]
    t.eq((ta.get("id"), ta.get("via")), ("GHSA-2222-3333-4444", ["express"]), "via the snapshot edge")
    t.ok("audit" not in (data.get("partial") or []), "advisories without pnpm audit")
    t.ok(not any(e["tool"] == "pnpm" and "audit" in e["argv"] for e in ctx.log()), "pnpm audit never runs")


def case_pnpm_outdated_exit1_ok(ctx, t):
    repo = pnpm_repo(ctx)
    pnpm_stubs(ctx, exit_code=1)
    plain, data = both(ctx, t, "plan", repo, "--date", DATE, rc=1)
    t.ok("outdated" not in (data.get("partial") or []), "pnpm outdated exit 1 with JSON is a success")
    t.ok(any(e["tool"] == "pnpm" and e["argv"][:2] == ["outdated", "-r"] for e in ctx.log()), "pnpm outdated -r ran")
    t.eq(pkg(data, "vitest", "packages/ui").get("target"), "2.1.0", "workspace package planned")


def case_lts_boundaries(ctx, t):
    repo = synth(ctx, "acme-lts", {"lodash": ("prod", "^4.17.21", "4.17.21")}, {}, files={".nvmrc": "20.11.0\n"})
    cases = [("20.11.0", "2026-04-30", "maintenance", 24), ("20.11.0", "2026-05-01", "eol", 24),
             ("24", "2026-10-19", "active-lts", 24), ("24", "2026-10-20", "maintenance", 24),
             ("26", "2026-10-27", "current", 24), ("26", "2026-10-28", "active-lts", 26)]
    for pin, date, status, lts in cases:
        write(os.path.join(repo, ".nvmrc"), pin + "\n")
        for online in (False, True):
            if online:
                ctx.stubs()
            plain, data = both(ctx, t, "plan", repo, "--date", date, *(() if online else ("--offline",)),
                               rc=1 if (not online or status == "eol") else 0)
            node = dig(data, "runtimes", "node") or {}
            t.eq((node.get("status"), node.get("newest_lts")), (status, lts), "node %s at %s (%s)" % (pin, date, "online" if online else "embedded"))


def case_commands_generation_styles(ctx, t):
    deps = {"a": ("prod", "^1.0.0", "1.0.0"), "b": ("prod", "2.0.0", "2.0.0"), "c": ("dev", "~3.0.0", "3.0.0"),
            "d": ("dev", "4.0.0", "4.0.0"), "e": ("prod", ">=1.0.0 <2", "1.0.0")}
    times = {"a": {"1.0.0": OLD, "1.2.0": OLD}, "b": {"2.0.0": OLD, "2.1.0": OLD}, "c": {"3.0.0": OLD, "3.0.5": OLD},
             "d": {"4.0.0": OLD, "4.0.1": OLD}, "e": {"1.0.0": OLD, "1.5.0": OLD}}
    repo = synth(ctx, "acme-cmds", deps, times)
    plain, data = both(ctx, t, "plan", repo, "--date", DATE, rc=1)
    pm = wave(data, "patch-minor") or {}
    t.eq([c["run"] for c in pm.get("commands", [])],
         ["npm install --save-prod 'a@^1.2.0'", "npm install --save-prod --save-exact b@2.1.0",
          "npm install --save-dev 'c@~3.0.5'", "npm install --save-dev --save-exact d@4.0.1"], "npm commands keep ^ ~ exact")
    t.ok({"file": "package.json", "key": "dependencies.e", "from": ">=1.0.0 <2", "to": ">=1.5.0", "note": "manual"}
         in pm.get("edits", []), "a complex range becomes a manual edit")
    mono = pnpm_repo(ctx)
    pnpm_stubs(ctx)
    plain, data = both(ctx, t, "plan", mono, "--date", DATE, rc=1)
    pm = wave(data, "patch-minor") or {}
    runs = [c["run"] for c in pm.get("commands", [])]
    t.eq(runs, ["pnpm add -w 'express@^4.22.3'", "pnpm --filter ./packages/ui add -D 'vitest@^2.1.0'", "pnpm install"],
         "pnpm commands")
    t.ok({"file": "pnpm-workspace.yaml", "key": "catalog.typescript", "from": "^5.3.0", "to": "^5.9.4"} in pm.get("edits", []),
         "catalog entries are edits on pnpm-workspace.yaml")
    comp = npm_project(ctx, ctx.path("acme/projects/acme-php"), {"left-pad": ("prod", "^1.0.0", "1.0.0")})
    write(os.path.join(comp, "composer.json"), json.dumps({"require": {"php": "^8.2", "acme/lib": "^2.0"}}, indent=2) + "\n")
    write(os.path.join(comp, "composer.lock"), json.dumps({"packages": [{"name": "acme/lib", "version": "2.0.0"}], "packages-dev": []}) + "\n")
    write(os.path.join(comp, "requirements.txt"), "flask==2.0.1\n")
    ctx.init_git(comp)
    ctx.config["composer"]["outdated"] = {"stdout": {"installed": [{"name": "acme/lib", "version": "2.0.0", "latest": "2.1.0",
                                                                    "latest-status": "semver-safe-update"}]}, "exit": 0}
    ctx.config["npm"]["times"] = {"left-pad": {"1.0.0": iso(OLD), "1.3.0": iso(OLD)}}
    ctx.config["npm"]["outdated"] = {"stdout": {"left-pad": {"current": "1.0.0", "wanted": "1.3.0", "latest": "1.3.0"}}, "exit": 1}
    ctx.save()
    ctx.server.get["/pypi/flask/json"] = {"info": {"version": "3.0.0"}, "releases": {"2.0.1": [], "2.0.3": [], "3.0.0": [], "3.1.0rc1": []}}
    plain, data = both(ctx, t, "plan", comp, "--date", DATE, rc=1)
    pm = wave(data, "patch-minor") or {}
    t.eq([c["run"] for c in pm.get("commands", [])],
         ["composer require 'acme/lib:^2.1.0' --no-update && composer update acme/lib --with-dependencies",
          "npm install --save-prod 'left-pad@^1.3.0'"], "each ecosystem gets its own tool in a mixed repo")
    t.ok({"file": "requirements.txt", "key": "flask", "from": "==2.0.1", "to": "==2.0.3", "note": "pin"} in pm.get("edits", []),
         "a pip pin moves by an edit (PyPI)")
    t.eq(dig(wave(data, "major:flask"), "edits", 0, "to"), "==3.0.0", "the pip major is its own wave")


def case_output_cap_300_packages(ctx, t):
    deps = {"pkg-%03d" % i: ("prod", "^1.0.0", "1.0.0") for i in range(300)}
    times = {n: {"1.0.0": OLD, "1.1.0": OLD} for n in deps}
    repo = synth(ctx, "acme-big", deps, times)
    plain, data = both(ctx, t, "plan", repo, "--date", DATE, rc=1)
    t.has(plain.lines, "  … +288 more (use --json)", "wave rows shed")
    t.eq(len(data.get("packages") or []), 300, "json keeps every package")
    t.eq(len(dig(wave(data, "patch-minor"), "from_to") or []), 300, "json keeps every move")
    t.eq(plain.last, "DEPS: outdated(300) majors(0) advisories(0) holds(0)", "verdict")


def case_plan_without_git_partial(ctx, t):
    repo = ctx.fixture(git=False)
    plain, data = both(ctx, t, "plan", repo, "--offline", "--date", DATE, rc=1, trees=[repo])
    t.ok(plain.last.startswith("DEPS: partial(offline,git) "), "partial(git), never unparsed: %r" % plain.last)
    t.eq(data.get("git"), None, "git: null")
    t.has(plain.lines[0], "base none", "no base")
    plain, _ = both(ctx, t, "context", repo, "--offline", "--date", DATE, "--scratch", ctx.path("s"), rc=1)
    t.ok(plain.last.startswith("CONTEXT: would write"), "context renders without git")
    plain, _ = both(ctx, t, "preflight", repo, "--date", DATE, rc=2)
    t.eq(plain.last, "PREFLIGHT: unparsed (not a git repo)", "preflight stays unparsed")
    mono = ctx.path("acme/projects/acme-mono")
    os.makedirs(mono)
    ctx.init_git(mono)
    shutil.copytree(FIXTURE, os.path.join(mono, "apps", "site"))
    ctx.commit(mono, "app")
    plain, data = both(ctx, t, "plan", os.path.join(mono, "apps", "site"), "--offline", "--date", DATE, rc=1)
    t.eq(dig(data, "git", "toplevel_ancestor"), True, "toplevel_ancestor when the repo has no .git of its own")
    t.ok("git" not in (data.get("partial") or []), "an ancestor toplevel is a git repo")


def case_pm_version_mismatch(ctx, t):
    repo = ctx.fixture(origin=True)
    ctx.brain()
    data = json.loads(read(os.path.join(repo, "package.json")))
    data["packageManager"] = "npm@10.9.0"
    write(os.path.join(repo, "package.json"), json.dumps(data, indent=2) + "\n")
    ctx.commit(repo, "packageManager")
    ctx.git(repo, "push", "-q", "origin", "main")
    ctx.clear_log()
    plain, data = both(ctx, t, "plan", repo, "--offline", "--date", DATE, rc=1)
    t.eq((dig(data, "env", "pm_declared"), dig(data, "env", "pm_version"), dig(data, "env", "pm_found")),
         ("10.9.0", "10.8.2", "mismatch"), "pm version checked against packageManager")
    t.ok("pm-version" in (data.get("partial") or []), "partial(pm-version)")
    call = next((e for e in ctx.log() if e["tool"] == "npm" and e["argv"] == ["--version"]), {})
    t.eq(call.get("env", {}).get("COREPACK_ENABLE_STRICT"), "1", "COREPACK_ENABLE_STRICT exported")
    t.eq(call.get("env", {}).get("COREPACK_ENABLE_DOWNLOAD_PROMPT"), "0", "COREPACK_ENABLE_DOWNLOAD_PROMPT exported")
    t.eq(call.get("path0"), ctx.path("nvm/v20.11.0/bin"), "--version runs under env.path_prefix")
    t.eq(call.get("cwd"), os.path.realpath(repo), "--version runs in the repo")
    plain, _ = both(ctx, t, "preflight", repo, "--expect-email", "dev@example.com", "--date", DATE, rc=1)
    t.eq(plain.last, "PREFLIGHT: blocked(pm-mismatch)", "pm-mismatch blocker")
    mono = pnpm_repo(ctx, manager="pnpm@10.4.1")
    ctx.config["pnpm"]["version"] = "9.15.0"
    ctx.save()
    plain, data = both(ctx, t, "plan", mono, "--offline", "--date", DATE, rc=1)
    t.eq(dig(data, "env", "pm_found"), "mismatch", "pnpm mismatch")


def case_routes_auto(ctx, t):
    app = ("const express = require('express');\nconst app = express();\nconst router = express.Router();\n"
           "app.get('/', home);\napp.get('/about', about);\nrouter.get('/pricing', pricing);\napp.get('/api/items', items);\n"
           "app.get('/members/:id', user);\napp.post('/contact', contact);\napp.get('/health', health);\n"
           "app.get('/logo.png', logo);\napp.get('/blog', blog);\napp.get('/extra', extra);\n")
    repo = synth(ctx, "acme-routes", {"express": ("prod", "^4.21.0", "4.21.2")}, {}, files={"src/routes/pages.js": app})
    plain, data = both(ctx, t, "plan", repo, "--offline", "--date", DATE, "--routes", "auto", rc=1)
    t.eq([r["route"] for r in dig(data, "smoke", "routes") or []], ["/", "/about", "/pricing", "/blog"], "auto routes")
    t.eq(dig(data, "smoke", "source"), "auto", "source auto")
    plain, data = both(ctx, t, "plan", repo, "--offline", "--date", DATE, "--routes", "none", rc=1)
    t.eq(dig(data, "smoke", "routes"), [], "no smoke")
    skill = ctx.skill(names=("acme-routes",))
    write(os.path.join(skill, "dependencies.md"), delivery_file("acme-routes", smoke="| /compare | compare | .clock |\n"))
    plain, data = both(ctx, t, "plan", repo, "--offline", "--date", DATE, "--routes", "auto", rc=1)
    t.eq([(r["route"], r["mask"]) for r in dig(data, "smoke", "routes") or []], [("/compare", ".clock")], "the Smoke table rules")


# ------------------------------------------------------------------ cases: changelog, context, status
PM_LOCK = {"express": "4.22.3", "@playwright/test": "1.64.0", "@types/express": "4.17.25", "@types/node": "20.19.25",
           "@types/react": "18.3.28", "body-parser": "1.20.4"}
PM_SPECS = {"express": "^4.22.3", "@playwright/test": "^1.64.0", "@types/express": "^4.17.25", "@types/node": "^20.19.25",
            "@types/react": "^18.3.28"}
CHANGELOG = "docs/dependencies/CHANGELOG.md"


def planned(ctx, origin=False):
    """The fixture as a git repo with the online plan written to <tmp>/S/plan.json."""
    repo = ctx.fixture(origin=origin)
    ctx.brain()
    ctx.stubs()
    scratch = ctx.path("S")
    r = ctx.run("plan", repo, "--date", DATE, "--scratch", scratch, "--write")
    if r.rc != 1 or not os.path.isfile(os.path.join(scratch, "plan.json")):
        raise RuntimeError("plan --write failed: %r" % r.last)
    return repo, os.path.join(scratch, "plan.json")


def apply_patch_minor(ctx, repo, branch=True):
    if branch:
        ctx.git(repo, "switch", "-q", "-c", "deps/2026-10-25-patch-minor")
    bump_lock(repo, PM_LOCK, PM_SPECS)


def changelog(ctx, repo, plan, *args, **kw):
    return ctx.run("changelog", repo, "--plan", plan, "--date", DATE, *args, **kw)


def case_changelog_new_file_and_idempotent(ctx, t):
    repo, plan = planned(ctx)
    apply_patch_minor(ctx, repo)
    r = changelog(ctx, repo, plan, "--wave", "patch-minor", "--verify", "build=pass", "--verify", "e2e=pass 3/3 (base 3/3)")
    t.eq(r.rc, 0, "would write exit code")
    t.ok(r.last.startswith("CHANGELOG: would write %s (+" % CHANGELOG), "would write first: %r" % r.last)
    t.ok(not os.path.exists(os.path.join(repo, CHANGELOG)), "nothing written without --write")
    r = changelog(ctx, repo, plan, "--wave", "patch-minor", "--verify", "build=pass", "--verify", "e2e=pass 3/3 (base 3/3)", "--write")
    t.eq((r.rc, r.last), (0, "CHANGELOG: written %s" % CHANGELOG), "written")
    text = read(os.path.join(repo, CHANGELOG)) or ""
    t.ok(text.startswith("# Dependency changelog\n\nOne entry per dependency run, newest first"), "file header")
    sha = ctx.git(repo, "rev-parse", "--short=7", "main")
    t.has(text, "## 2026-10-25 — dependency run · base `main@%s`" % sha, "heading keyed by the run-id")
    t.has(text, "### Changed — patch and minor · branch `deps/2026-10-25-patch-minor`", "branch heading")
    t.has(text, "- express 4.21.2 → 4.22.3 (prod)", "changed row")
    t.has(text, "- edit .gitlab-ci.yml e2e.image: mcr.microsoft.com/playwright:v1.55.0-jammy → mcr.microsoft.com/playwright:v1.64.0-jammy (align)", "edit row")
    t.has(text, "- Closed: GHSA-2222-3333-4444 (high · body-parser · fixed in 1.20.4)", "closed advisory")
    t.has(text, "- Audit after (bulk advisories, 2026-10-25): critical 0 · high 0 · moderate 0 · low 0 · open: none", "audit after")
    t.has(text, "- patch-minor: build pass · e2e pass 3/3 (base 3/3)", "verify row")
    t.has(text, "- node ^25.7.0 (locked 25.7.0) — never-auto:", "held row")
    t.has(text, "Patch and minor: 5 packages in 1 MR · majors: none · audit after: critical 0", "summary line")
    r = changelog(ctx, repo, plan, "--wave", "patch-minor", "--verify", "build=pass", "--verify", "e2e=pass 3/3 (base 3/3)", "--write")
    t.eq((r.rc, r.last), (0, "CHANGELOG: ok"), "idempotent")
    t.eq(read(os.path.join(repo, CHANGELOG)), text, "same bytes")
    r = changelog(ctx, repo, plan, "--wave", "patch-minor", "--offline", "--write")
    t.eq(r.rc, 1, "offline audit after is partial")
    t.ok(r.last.endswith("· partial(offline)"), "partial(offline) suffix")


def case_changelog_major_append(ctx, t):
    repo, plan = planned(ctx)
    apply_patch_minor(ctx, repo)
    changelog(ctx, repo, plan, "--wave", "patch-minor", "--verify", "build=pass", "--write")
    path = os.path.join(repo, CHANGELOG)
    write(path, (read(path) or "").replace("- patch-minor: build pass\n", "- patch-minor: build pass\nReviewer note kept by hand.\n"))
    ctx.commit(repo, "patch-minor")
    ctx.git(repo, "switch", "-q", "-c", "deps/2026-10-25-major-helmet")
    bump_lock(repo, {"helmet": "8.3.0"}, {"helmet": "^8.3.0"})
    notes = write(ctx.path("S/notes/helmet.md"), "# helmet\n- CSP defaults changed\n- security-headers spec green\n")
    r = changelog(ctx, repo, plan, "--wave", "major:helmet", "--notes", notes, "--verify", "build=pass", "--write")
    t.eq(r.rc, 0, "major written")
    text = read(path) or ""
    t.has(text, "- helmet 7.2.0 → 8.3.0 · branch `deps/2026-10-25-major-helmet` · migration: CSP defaults changed; security-headers spec green", "major row")
    t.has(text, "- express 4.21.2 → 4.22.3 (prod)", "patch-minor rows kept")
    t.has(text, "Reviewer note kept by hand.", "human prose kept")
    t.has(text, "- major helmet: build pass", "major verify row")
    t.ok(text.index("- patch-minor: build pass") < text.index("- major helmet: build pass"), "verify rows in wave order")
    t.has(text, "majors: 1 MR (helmet)", "summary counts the major")
    r = changelog(ctx, repo, plan, "--wave", "major:helmet", "--notes", notes, "--verify", "build=pass", "--write")
    t.eq(r.last, "CHANGELOG: ok", "major append is idempotent")


def case_changelog_path_override_and_check_mismatch(ctx, t):
    repo, plan = planned(ctx)
    apply_patch_minor(ctx, repo)
    r = changelog(ctx, repo, plan, "--wave", "patch-minor", "--path", "CHANGES/deps.md", "--write")
    t.eq(r.last, "CHANGELOG: written CHANGES/deps.md", "--path override")
    t.ok(not os.path.exists(os.path.join(repo, CHANGELOG)), "the default path stays untouched")
    before = snap(repo)
    r = changelog(ctx, repo, plan, "--check", "--path", "CHANGES/deps.md")
    t.eq((r.rc, r.last), (0, "CHANGELOG: ok"), "--check without --wave")
    t.eq(snap(repo), before, "--check writes nothing")
    path = os.path.join(repo, "CHANGES/deps.md")
    write(path, (read(path) or "").replace("- express 4.21.2 → 4.22.3 (prod)", "- express 4.21.2 → 4.22.9 (prod)"))
    r = changelog(ctx, repo, plan, "--check", "--path", "CHANGES/deps.md")
    t.eq((r.rc, r.last), (1, "CHANGELOG: mismatch(express)"), "a tampered row is a mismatch")
    r = changelog(ctx, repo, plan, "--check")
    t.eq((r.rc, r.last), (1, "CHANGELOG: mismatch(entry)"), "no entry at the default path")


def case_mr_format(ctx, t):
    repo, plan = planned(ctx)
    apply_patch_minor(ctx, repo)
    target = os.path.join(os.path.dirname(plan), "mr", "patch-minor.md")
    r = changelog(ctx, repo, plan, "--wave", "patch-minor", "--format", "mr", "--verify", "build=pass")
    t.ok(r.last.startswith("CHANGELOG: would write ") and "mr/patch-minor.md" in r.last, "would write the MR body: %r" % r.last)
    t.ok(not os.path.exists(target), "nothing written without --write")
    r = changelog(ctx, repo, plan, "--wave", "patch-minor", "--format", "mr", "--verify", "build=pass", "--write")
    body = read(target) or ""
    t.ok(body.startswith("## Dependencies: patch and minor bumps (2026-10-25)"), "title")
    t.has(body, "**Reviewer:** @reviewer-handle (gitlab) — Claude never merges this MR.", "reviewer line")
    t.has(body, "**Merge order:** `deps/2026-10-25-patch-minor` → `deps/2026-10-25-major-helmet` → `deps/2026-10-25-major-express`", "merge order")
    t.has(body, "**Stacked on:** `main`", "stacked on")
    t.has(body, "- build: pass", "verification rows")
    t.has(body, "Changelog: `%s` (entry 2026-10-25)." % CHANGELOG, "changelog pointer")
    t.ok("{{" not in body, "every placeholder rendered")


def case_changelog_run_id_keyed(ctx, t):
    repo, plan_a = planned(ctx)
    sha_a = ctx.git(repo, "rev-parse", "--short=7", "main")
    changelog(ctx, repo, plan_a, "--wave", "patch-minor", "--write")
    ctx.commit(repo, "changelog A")
    sha_b = ctx.git(repo, "rev-parse", "--short=7", "main")
    r = ctx.run("plan", repo, "--date", DATE, "--scratch", ctx.path("S2"), "--write")
    plan_b = ctx.path("S2/plan.json")
    changelog(ctx, repo, plan_b, "--wave", "patch-minor", "--write")
    text = read(os.path.join(repo, CHANGELOG)) or ""
    heads = re.findall(r"^## 2026-10-25 — dependency run · base `main@([0-9a-f]+)`", text, re.M)
    t.eq(heads, [sha_b, sha_a], "one entry per run-id, newest first")
    apply_patch_minor(ctx, repo)
    changelog(ctx, repo, plan_a, "--wave", "patch-minor", "--write")
    text2 = read(os.path.join(repo, CHANGELOG)) or ""
    t.eq(re.findall(r"^## 2026-10-25 — dependency run · base `main@([0-9a-f]+)`", text2, re.M), [sha_b, sha_a], "rewrites in place")
    t.eq(text2.split("## 2026-10-25 — dependency run · base `main@%s`" % sha_a)[0],
         text.split("## 2026-10-25 — dependency run · base `main@%s`" % sha_a)[0], "the other run-id entry is untouched")


def case_changelog_stack_fix_propagation(ctx, t):
    repo, plan = planned(ctx)
    apply_patch_minor(ctx, repo)
    changelog(ctx, repo, plan, "--wave", "patch-minor", "--verify", "build=pass", "--write")
    ctx.commit(repo, "patch-minor")
    ctx.git(repo, "switch", "-q", "-c", "deps/2026-10-25-major-helmet")
    bump_lock(repo, {"helmet": "8.3.0"}, {"helmet": "^8.3.0"})
    changelog(ctx, repo, plan, "--wave", "major:helmet", "--verify", "build=pass", "--write")
    ctx.commit(repo, "major helmet")
    ctx.git(repo, "switch", "-q", "deps/2026-10-25-patch-minor")
    bump_lock(repo, {"@playwright/test": "1.58.2"}, {"@playwright/test": "^1.55.0"})
    r = changelog(ctx, repo, plan, "--wave", "patch-minor", "--verify", "build=pass", "--verify", "e2e=pass", "--write")
    t.eq(r.last, "CHANGELOG: written %s" % CHANGELOG, "fix re-rendered on wave N")
    ctx.commit(repo, "fix: drop the playwright bump")
    ctx.git(repo, "switch", "-q", "deps/2026-10-25-major-helmet")
    merge = subprocess.run(["git", "-C", repo, "-c", "user.email=dev@example.com", "-c", "user.name=Dev", "merge", "--no-ff",
                            "-m", "merge fix", "deps/2026-10-25-patch-minor"], capture_output=True, text=True, env=ctx.env)
    conflicted = merge.returncode != 0
    if conflicted:
        unmerged = ctx.git(repo, "diff", "--name-only", "--diff-filter=U")
        t.eq(unmerged.split(), [CHANGELOG], "only the changelog conflicts")
    r = changelog(ctx, repo, plan, "--wave", "major:helmet", "--verify", "build=pass", "--write")
    t.eq(r.rc, 0, "changelog --write on wave N+1 after the merge")
    text = read(os.path.join(repo, CHANGELOG)) or ""
    t.ok(not re.search(r"^(<{7}|={7}|>{7})", text, re.M), "no conflict markers left")
    t.hasnt(text, "- @playwright/test 1.58.2 → 1.64.0", "the dropped bump is gone on wave N+1")
    t.has(text, "- @playwright/test 1.58.2 — planned 1.64.0, not applied (dropped from patch-minor)", "dropped row")
    t.has(text, "- helmet 7.2.0 → 8.3.0 · branch `deps/2026-10-25-major-helmet`", "wave N+1 row kept")
    t.has(text, "- patch-minor: build pass · e2e pass", "the fixed verification of wave N propagated")
    if conflicted:
        ctx.git(repo, "add", CHANGELOG)
        ctx.git(repo, "-c", "user.email=dev@example.com", "-c", "user.name=Dev", "commit", "-q", "--no-edit")
    else:
        ctx.commit(repo, "changelog after merge")
    r = changelog(ctx, repo, plan, "--wave", "major:helmet", "--verify", "build=pass", "--write")
    t.eq(r.last, "CHANGELOG: ok", "idempotent after the propagation")
    r = changelog(ctx, repo, plan, "--check")
    t.eq((r.rc, r.last), (0, "CHANGELOG: ok"), "--check on the tip")


def case_context_flat_write_preserves_policy(ctx, t):
    repo = ctx.fixture()
    skill = ctx.skill()
    path = os.path.join(skill, "dependencies.md")
    original = delivery_file("acme-site", rules="| lodash | hold | | kept by hand | 2026-01-01 | |\n")
    write(path, original)
    tail = original.split("<!-- end auto-generated -->", 1)[1]
    plain, _ = both(ctx, t, "context", repo, "--context", skill, "--offline", "--date", DATE, rc=1, trees=[skill, repo])
    t.ok(plain.last.startswith("CONTEXT: would write"), "preview first")
    r = ctx.run("context", repo, "--context", skill, "--offline", "--date", DATE, "--write")
    t.eq(r.rc, 0, "written exit code")
    text = read(path) or ""
    t.eq(text.split("<!-- end auto-generated -->", 1)[1], tail, "the Policy section keeps its bytes")
    t.ok(text.startswith("# acme-site — Dependencies\n\nIntro.\n"), "the title and intro keep their bytes")
    t.has(text, "| express | prod | . | ^4.21.0 | 4.21.2 | range |", "dependency row")
    t.has(text, "| pdf-lib | prod | . | 1.17.1 | 1.17.1 | exact |", "exact style")
    t.ok(text.index("| express | prod") < text.index("| @playwright/test | dev"), "rows sorted by kind, then name")
    plain, _ = both(ctx, t, "context", repo, "--context", skill, "--offline", "--date", DATE, rc=0)
    t.eq(plain.last, "CONTEXT: current", "a second render is current")


def case_context_references_layout(ctx, t):
    repo = ctx.fixture()
    skill = ctx.skill(layout="references")
    target = os.path.join(skill, "references", "dependencies.md")
    plain, _ = both(ctx, t, "context", repo, "--context", skill, "--offline", "--date", DATE, rc=1)
    t.ok(plain.last.startswith("CONTEXT: would write ") and plain.last.count("references/dependencies.md"), "references target")
    r = ctx.run("context", repo, "--context", skill, "--offline", "--date", DATE, "--write")
    text = read(target) or ""
    t.eq(r.rc, 0, "written")
    t.has(text, "- **Repo:** `acme-site` · default branch `main`", "repo identity line")
    t.has(text, "| node | never-auto | | npm binary package that shadows the runtime for npm scripts | 2026-10-25 | |", "seeded Policy row")
    t.has(text, "| / | home | |", "seeded Smoke row")
    t.has(text, "- Changelog: `docs/dependencies/CHANGELOG.md`", "seeded Delivery")
    t.ok("{{" not in text, "every placeholder rendered")


def case_context_repo_guard(ctx, t):
    repo = ctx.fixture()
    skill = ctx.skill()
    write(os.path.join(skill, "dependencies.md"), delivery_file("other-repo"))
    plain, _ = both(ctx, t, "context", repo, "--context", skill, "--offline", "--date", DATE, rc=2)
    t.has(plain.last, "records repo other-repo", "different-repo guard")
    t.has(plain.last, "use --file dependencies-acme-site.md", "the way out")
    r = ctx.run("context", repo, "--context", skill, "--file", "dependencies-acme-site.md", "--offline", "--date", DATE, "--write")
    t.eq(r.rc, 0, "--file dependencies-<repo>.md writes")
    t.ok(os.path.isfile(os.path.join(skill, "dependencies-acme-site.md")), "per-repo file created")


def case_context_open_branches_rendered(ctx, t):
    repo, plan = planned(ctx, origin=True)
    skill = ctx.skill()
    main_sha = ctx.git(repo, "rev-parse", "--short=7", "main")
    ctx.config["glab"]["mr_list"] = [
        {"iid": 11, "source_branch": "deps/2026-10-25-patch-minor", "target_branch": "main", "state": "opened"},
        {"iid": 12, "source_branch": "deps/2026-10-25-major-helmet", "target_branch": "deps/2026-10-25-patch-minor", "state": "opened"}]
    ctx.save()
    apply_patch_minor(ctx, repo)
    ctx.commit(repo, "patch-minor")
    r = ctx.run("context", repo, "--context", skill, "--plan", plan, "--date", DATE, "--write")
    text = read(os.path.join(skill, "dependencies.md")) or ""
    t.eq(r.rc, 0, "written on the wave branch")
    t.has(text, "· deps-check ", "marker line")
    t.has(text, "main@%s — do not edit" % main_sha, "SOURCE_REF is the base, not the branch tip")
    t.has(text, "- !11 `deps/2026-10-25-patch-minor` → main · express 4.22.3, @playwright/test 1.64.0, @types/express 4.17.25 (+2)", "open MR row")
    t.has(text, "- !12 `deps/2026-10-25-major-helmet` → deps/2026-10-25-patch-minor · helmet 8.3.0", "stacked MR row")
    r = ctx.run("context", repo, "--context", skill, "--plan", plan, "--date", DATE, "--if-merged", "--write")
    t.eq((r.rc, r.last), (0, "CONTEXT: current"), "--if-merged with the base unchanged")
    ctx.git(repo, "switch", "-q", "main")
    ctx.git(repo, "-c", "user.email=dev@example.com", "-c", "user.name=Dev", "merge", "-q", "--no-ff", "-m", "merge !11",
            "deps/2026-10-25-patch-minor")
    ctx.git(repo, "push", "-q", "origin", "main")
    ctx.config["glab"]["mr_list"] = []
    ctx.save()
    plain, _ = both(ctx, t, "preflight", repo, "--context", skill, "--expect-email", "dev@example.com", "--date", DATE, rc=0)
    t.has(plain.lines, "context: stale (base sha ≠ origin/main)", "preflight reports a stale context")
    r = ctx.run("context", repo, "--context", skill, "--date", DATE, "--if-merged", "--write")
    t.eq(r.rc, 0, "--if-merged re-renders after the merge")
    text = read(os.path.join(skill, "dependencies.md")) or ""
    t.has(text, "main@%s — do not edit" % ctx.git(repo, "rev-parse", "--short=7", "main"), "new base")
    t.has(text, "## Open dependency branches\n\nnone\n", "no open branches after the merge")
    plain, _ = both(ctx, t, "preflight", repo, "--context", skill, "--expect-email", "dev@example.com", "--date", DATE, rc=0)
    t.hasnt(plain.lines, "context: stale", "fresh again")


def case_status_head_pipeline_only(ctx, t):
    repo = ctx.fixture()
    base = {"source_branch": "deps/2026-10-25-patch-minor", "target_branch": "main", "draft": True, "has_conflicts": False}
    ctx.config["glab"]["mr_list"] = [{"iid": 5, "state": "opened"}, {"iid": 6, "state": "opened"}]
    ctx.config["glab"]["mr_view"] = {"5": dict(base, iid=5, head_pipeline={"status": "failed"}, pipeline={"status": "success"}),
                                     "6": dict(base, iid=6, head_pipeline={"status": "success"})}
    ctx.save()
    plain, data = both(ctx, t, "status", repo, rc=1)
    t.eq(plain.last, "STATUS: failed(!5)", "only head_pipeline counts")
    ctx.config["glab"]["mr_view"]["5"]["head_pipeline"] = {"status": "success"}
    ctx.save()
    plain, _ = both(ctx, t, "status", repo, rc=0)
    t.eq(plain.last, "STATUS: ok(!5,!6)", "all green")
    ctx.config["glab"]["mr_view"]["5"]["head_pipeline"] = None
    ctx.config["glab"]["mr_view"]["6"].update(has_conflicts=True, head_pipeline={"status": "running"})
    ctx.save()
    plain, _ = both(ctx, t, "status", repo, rc=1)
    t.eq(plain.last, "STATUS: running(!6) conflict(!6) nopipeline(!5)", "running, conflict and no pipeline")
    ctx.config["glab"]["mr_view"]["deps/x"] = dict(base, iid=9, head_pipeline={"status": "success"})
    ctx.save()
    plain, _ = both(ctx, t, "status", repo, "--branches", "deps/x", rc=0)
    t.eq(plain.last, "STATUS: ok(!9)", "--branches views by source branch")
    ctx.config["glab"]["mr_list"] = []
    ctx.save()
    plain, _ = both(ctx, t, "status", repo, rc=0)
    t.eq(plain.last, "STATUS: none", "no dependency MR")
    os.remove(ctx.path("bin/glab"))
    plain, _ = both(ctx, t, "status", repo, rc=2)
    t.eq(plain.last, "STATUS: unparsed (glab missing)", "glab missing")


def case_no_writes_without_flag(ctx, t):
    repo, plan = planned(ctx)
    skill = ctx.skill(layout="references")
    trees = [repo, skill, os.path.dirname(plan)]
    before = snap(*trees)
    for args in (("plan", repo, "--date", DATE, "--scratch", ctx.path("S3")),
                 ("changelog", repo, "--plan", plan, "--wave", "patch-minor", "--date", DATE),
                 ("changelog", repo, "--plan", plan, "--wave", "patch-minor", "--format", "mr", "--date", DATE),
                 ("context", repo, "--context", skill, "--plan", plan, "--date", DATE)):
        r = ctx.run(*args)
        t.ok("would write" in r.out, "%s prints would write" % args[0])
    t.eq(snap(*trees), before, "no write without --write")
    t.ok(not os.path.exists(ctx.path("S3")), "no scratch dir without --write")


def case_no_secret_leak(ctx, t):
    repo = ctx.fixture()
    ctx.stubs()
    secrets = ("npm_SECRETTOKEN123", "hunter2pass", "SECRETENV456", "SECRETCLI000")
    write(os.path.join(repo, ".npmrc"), "registry=https://acme:hunter2pass@registry.example.com/\n"
          "//registry.example.com/:_authToken=npm_SECRETTOKEN123\nsave-exact=true\n")
    write(os.path.join(repo, ".env"), "API_KEY=SECRETENV456\n")
    ci = read(os.path.join(repo, ".gitlab-ci.yml")).replace("    - npm run build\n", "    - npm run build --token=SECRETCLI000\n")
    write(os.path.join(repo, ".gitlab-ci.yml"), ci)
    ctx.commit(repo, "secrets")
    ctx.brain()
    skill = ctx.skill()
    outs = []
    for args in (("plan", repo, "--date", DATE), ("plan", repo, "--date", DATE, "--offline", "--json"),
                 ("preflight", repo, "--date", DATE, "--json"), ("context", repo, "--context", skill, "--date", DATE, "--json")):
        outs.append(ctx.run(*args).out)
    ctx.run("plan", repo, "--date", DATE, "--scratch", ctx.path("S"), "--write")
    outs.append(read(ctx.path("S/plan.json")) or "")
    for secret in secrets:
        t.ok(not any(secret in o for o in outs), "%s never printed nor written" % secret)
    t.ok(any("registry.example.com" in o for o in outs), "the registry host is still reported")


def case_deterministic(ctx, t):
    repo = ctx.fixture()
    ctx.stubs()
    skill = ctx.skill()
    for args in (("plan", repo, "--date", DATE), ("plan", repo, "--date", DATE, "--json"),
                 ("context", repo, "--context", skill, "--date", DATE, "--offline", "--json")):
        a, b = ctx.run(*args), ctx.run(*args)
        t.eq(a.out, b.out, "%s output is byte-stable" % " ".join(args[:1] + args[2:]))


def helper(ctx, repo, argv):
    code = ("import importlib.util, json, sys\n"
            "spec = importlib.util.spec_from_file_location('deps_check_under_test', sys.argv[1])\n"
            "m = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(m)\n"
            "data, problem = m.run_json(json.loads(sys.argv[3]), sys.argv[2], m.tool_env())\n"
            "print(json.dumps({'problem': problem, 'data': data}))\n")
    p = subprocess.run([sys.executable, "-B", "-c", code, ctx.checker, repo, json.dumps(argv)], capture_output=True,
                       text=True, env=ctx.env, timeout=60)
    try:
        return json.loads(p.stdout)
    except ValueError:
        return {"problem": "harness: %s" % p.stderr.strip()[-160:], "data": None}


def case_npm_audit_exit1_with_vulns_ok(ctx, t):
    repo = ctx.fixture()
    ctx.stubs()
    got = helper(ctx, repo, ["npm", "audit", "--json"])
    t.eq(got.get("problem"), None, "exit 1 with JSON stdout is parsed")
    t.eq(dig(got, "data", "vulnerabilities", "body-parser", "fixAvailable", "version"), "4.22.3", "the report survives")
    ctx.clear_log()
    plain, data = both(ctx, t, "plan", repo, "--date", DATE, rc=1)
    t.ok(not any("audit" in e["argv"] for e in ctx.log() if e["tool"] in ("npm", "pnpm")), "plan never invokes npm audit")
    t.ok(any(r[1] == "/-/npm/v1/security/advisories/bulk" for r in ctx.server.posts()), "advisories by the bulk POST")


def case_pnpm_audit_exit1_ok(ctx, t):
    repo = pnpm_repo(ctx)
    pnpm_stubs(ctx)
    got = helper(ctx, repo, ["pnpm", "audit", "--json"])
    t.eq(got.get("problem"), None, "pnpm audit exit 1 with JSON is parsed")
    t.eq(dig(got, "data", "metadata", "vulnerabilities", "high"), 1, "the report survives")
    got = helper(ctx, repo, ["pnpm", "--version"])
    t.eq(got.get("problem"), "not-json", "plain text stdout is not JSON")
    ctx.config["pnpm"]["outdated"] = {"stdout": "", "exit": 1}
    ctx.save()
    t.eq(helper(ctx, repo, ["pnpm", "outdated"]).get("problem"), "not-json", "empty stdout with exit 1 is not JSON")


def case_commands_shell_safe(ctx, t):
    deps = {"react": ("prod", "18.3.0", "18.3.0"), "@types/node": ("dev", "20.11.0", "20.11.0"),
            "evil;touch pwned": ("prod", "^1.0.0", "1.0.0"), "left-pad": ("prod", "^1.0.0", "1.0.0"),
            "right-pad": ("prod", "^1.0.0", "1.0.0")}
    repo = npm_project(ctx, ctx.path("acme/projects/acme-shell"), {k: v for k, v in deps.items() if k not in ("left-pad", "right-pad")},
                       extra={"node_modules/left-pad": {"version": "1.0.0"}, "node_modules/right-pad": {"version": "1.0.0"}})
    data = json.loads(read(os.path.join(repo, "package.json")))
    data["workspaces"] = ["apps/*"]
    write(os.path.join(repo, "package.json"), json.dumps(data, indent=2) + "\n")
    bad_ws = "apps/w$(touch pwned)"
    for ws, dep in (("apps/web", "left-pad"), (bad_ws, "right-pad")):
        write(os.path.join(repo, ws, "package.json"), json.dumps({"name": dep + "-app", "version": "1.0.0",
                                                                  "dependencies": {dep: "^1.0.0"}}, indent=2) + "\n")
    write(os.path.join(repo, "composer.json"), json.dumps({"require": {"acme/lib": "^2.0", "Acme/Lib;id": "^1.0"}}, indent=2) + "\n")
    write(os.path.join(repo, "composer.lock"), json.dumps({"packages": [{"name": "acme/lib", "version": "2.0.0"},
                                                                        {"name": "Acme/Lib;id", "version": "1.0.0"}]}) + "\n")
    ctx.init_git(repo)
    old = {"react": ("18.3.0", "18.3.1"), "@types/node": ("20.11.0", "20.11.1"), "evil;touch pwned": ("1.0.0", "1.1.0"),
           "left-pad": ("1.0.0", "1.3.0"), "right-pad": ("1.0.0", "1.3.0")}
    ctx.config["npm"]["times"] = {n: {a: iso(OLD), b: iso(OLD)} for n, (a, b) in old.items()}
    ctx.config["npm"]["outdated"] = {"stdout": {n: {"current": a, "wanted": b, "latest": b} for n, (a, b) in old.items()}, "exit": 1}
    ctx.config["composer"]["outdated"] = {"stdout": {"installed": [
        {"name": "acme/lib", "version": "2.0.0", "latest": "2.1.0", "latest-status": "semver-safe-update"},
        {"name": "Acme/Lib;id", "version": "1.0.0", "latest": "1.1.0", "latest-status": "semver-safe-update"}]}, "exit": 0}
    ctx.save()
    plain, data = both(ctx, t, "plan", repo, "--date", DATE, rc=1)
    runs = [c["run"] for w in data.get("waves") or [] for c in w["commands"]]
    t.ok("npm install --save-prod --save-exact react@18.3.1" in runs, "a plain token comes out unchanged: %r" % runs)
    t.ok("npm install --save-dev --save-exact @types/node@20.11.1" in runs, "a scoped exact token comes out unchanged")
    web = next((r for r in runs if "--workspace" in r), "")
    t.eq(web, "npm install --save-prod --workspace apps/web 'left-pad@^1.3.0'", "a safe workspace path stays unquoted")
    t.eq(shlex.split(web), ["npm", "install", "--save-prod", "--workspace", "apps/web", "left-pad@^1.3.0"], "argv intact")
    t.ok("composer require 'acme/lib:^2.1.0' --no-update && composer update acme/lib --with-dependencies" in runs, "composer quoted")
    joined = "\n".join(runs)
    for needle in ("evil", "pwned", "touch", "$(", "Lib;id"):
        t.ok(needle not in joined, "no command carries %r" % needle)
    review = data.get("review") or []
    for line in ("review: 'evil;touch pwned' dropped from patch-minor: not a valid npm package name",
                 "review: 'apps/w$(touch pwned)' dropped from patch-minor: not a valid workspace path",
                 "review: 'Acme/Lib;id' dropped from patch-minor: not a valid composer package name"):
        t.eq(review.count(line), 1, "one review line: %s" % line)
    t.has(plain.lines, "review: 'evil;touch pwned' dropped from patch-minor", "the digest shows the dropped name")
    t.eq((pkg(data, "evil;touch pwned").get("wave"), pkg(data, "right-pad", bad_ws).get("wave")), ("held", "held"),
         "dropped entries are held")
    t.ok(all(f["name"] not in ("evil;touch pwned", "Acme/Lib;id") and f["workspace"] != bad_ws
             for w in data.get("waves") or [] for f in w["from_to"]), "dropped entries leave the wave")
    t.ok(not os.path.exists(os.path.join(repo, "pwned")) and not os.path.exists(ctx.path("pwned")), "nothing ran")


def case_scratch_private_atomic_write(ctx, t):
    repo = ctx.fixture()
    root = ctx.path("tmp/deps-renovate")
    sha = ctx.git(repo, "rev-parse", "--short=7", "main")
    run_dir = os.path.join(root, "acme-site", "%s-%s" % (DATE, sha))
    plan = os.path.join(run_dir, "plan.json")
    mode = lambda p: stat.S_IMODE(os.stat(p).st_mode)
    os.makedirs(root)
    os.chmod(root, 0o755)
    r = ctx.run("plan", repo, "--offline", "--date", DATE, "--write")
    t.eq(r.rc, 1, "plan --write exit code (last %r)" % r.last[:90])
    t.eq([mode(p) for p in (root, os.path.dirname(run_dir), run_dir)], [0o700] * 3, "scratch root and run dirs are 0o700")
    t.eq(mode(plan), 0o600, "plan.json is private")
    victim = write(ctx.path("victim.txt"), "keep these bytes\n")
    os.remove(plan)
    os.symlink(victim, plan)
    r = ctx.run("plan", repo, "--offline", "--date", DATE, "--write")
    t.ok(not os.path.islink(plan) and json.loads(read(plan) or "{}").get("command") == "plan", "the symlink was replaced")
    t.eq(read(victim), "keep these bytes\n", "the old symlink target keeps its bytes")
    victim2 = write(ctx.path("victim2.txt"), "changelog victim\n")
    log = os.path.join(repo, "docs", "dependencies", "CHANGELOG.md")
    os.makedirs(os.path.dirname(log))
    os.symlink(victim2, log)
    r = ctx.run("changelog", repo, "--plan", plan, "--wave", "patch-minor", "--offline", "--date", DATE, "--write")
    t.ok(r.rc == 1 and r.last.startswith("CHANGELOG: written docs/dependencies/CHANGELOG.md"), "changelog written: %r" % r.last)
    t.ok(not os.path.islink(log) and (read(log) or "").startswith("# Dependency changelog"), "changelog symlink replaced")
    t.eq(read(victim2), "changelog victim\n", "its old target keeps its bytes")
    r = ctx.run("changelog", repo, "--plan", plan, "--wave", "patch-minor", "--format", "mr", "--offline", "--date", DATE, "--write")
    t.eq((mode(os.path.join(run_dir, "mr")), mode(os.path.join(run_dir, "mr", "patch-minor.md"))), (0o700, 0o600), "mr dir private")
    skill = ctx.skill()
    victim3 = write(ctx.path("victim3.md"), delivery_file("acme-site"))
    os.symlink(victim3, os.path.join(skill, "dependencies.md"))
    r = ctx.run("context", repo, "--context", skill, "--offline", "--date", DATE, "--write")
    target = os.path.join(skill, "dependencies.md")
    t.ok(r.rc == 0 and not os.path.islink(target) and "| express | prod |" in (read(target) or ""), "context symlink replaced")
    t.eq(read(victim3), delivery_file("acme-site"), "the context symlink target keeps its bytes")
    shutil.rmtree(skill)
    for bits in (0o770, 0o777):
        os.chmod(root, bits)
        for extra in ((), ("--write",)):
            plain, data = both(ctx, t, "plan", repo, "--offline", "--date", DATE, *extra, rc=2)
            t.eq(plain.last, "DEPS: unparsed (scratch dir not private: %s)" % root, "%o root refused %r" % (bits, extra))
        plain, _ = both(ctx, t, "context", repo, "--offline", "--date", DATE, rc=2)
        t.eq(plain.last, "CONTEXT: unparsed (scratch dir not private: %s)" % root, "%o root refused by context" % bits)
    os.chmod(root, 0o700)
    loose = ctx.path("loose")
    os.makedirs(loose)
    os.chmod(loose, 0o775)
    plain, _ = both(ctx, t, "plan", repo, "--offline", "--date", DATE, "--scratch", loose, "--write", rc=2)
    t.eq(plain.last, "DEPS: unparsed (scratch dir not private: %s)" % loose, "a group-writable --scratch is refused")
    os.chmod(run_dir, 0o770)
    r = ctx.run("changelog", repo, "--plan", plan, "--wave", "patch-minor", "--format", "mr", "--offline", "--date", DATE, "--write")
    t.eq((r.rc, r.last), (2, "CHANGELOG: unparsed (scratch dir not private: %s)" % run_dir), "a group-writable plan dir is refused")


CASES = [
    ("help_and_usage_64", case_help_and_usage_64),
    ("unparsed_not_repo", case_unparsed_not_repo),
    ("preflight_ready", case_preflight_ready),
    ("preflight_identity_mismatch_and_global", case_preflight_identity_mismatch_and_global),
    ("preflight_dirty", case_preflight_dirty),
    ("preflight_reviewer_canonical_vs_name", case_preflight_reviewer_canonical_vs_name),
    ("preflight_context_flat_references_ambiguous", case_preflight_context_flat_references_ambiguous),
    ("preflight_open_run", case_preflight_open_run),
    ("plan_offline_fixture", case_plan_offline_fixture),
    ("plan_online_stubbed_waves", case_plan_online_stubbed_waves),
    ("majors_cap_order_security_prioritize", case_majors_cap_order_security_prioritize),
    ("one_major_step", case_one_major_step),
    ("min_age_and_security_bypass", case_min_age_and_security_bypass),
    ("policy_table_rules_and_bad_row", case_policy_table_rules_and_bad_row),
    ("renovate_caps_honoured", case_renovate_caps_honoured),
    ("families_move_together", case_families_move_together),
    ("types_node_follows_runtime", case_types_node_follows_runtime),
    ("ci_alignment_items", case_ci_alignment_items),
    ("npm_outdated_exit1_ok", case_npm_outdated_exit1_ok),
    ("audit_garbage_partial", case_audit_garbage_partial),
    ("pnpm10_bulk_fallback", case_pnpm10_bulk_fallback),
    ("lts_boundaries", case_lts_boundaries),
    ("commands_generation_styles", case_commands_generation_styles),
    ("changelog_new_file_and_idempotent", case_changelog_new_file_and_idempotent),
    ("changelog_major_append", case_changelog_major_append),
    ("changelog_path_override_and_check_mismatch", case_changelog_path_override_and_check_mismatch),
    ("mr_format", case_mr_format),
    ("context_flat_write_preserves_policy", case_context_flat_write_preserves_policy),
    ("context_references_layout", case_context_references_layout),
    ("context_repo_guard", case_context_repo_guard),
    ("no_writes_without_flag", case_no_writes_without_flag),
    ("output_cap_300_packages", case_output_cap_300_packages),
    ("no_secret_leak", case_no_secret_leak),
    ("deterministic", case_deterministic),
    ("changelog_stack_fix_propagation", case_changelog_stack_fix_propagation),
    ("npm_audit_exit1_with_vulns_ok", case_npm_audit_exit1_with_vulns_ok),
    ("pnpm_outdated_exit1_ok", case_pnpm_outdated_exit1_ok),
    ("pnpm_audit_exit1_ok", case_pnpm_audit_exit1_ok),
    ("plan_without_git_partial", case_plan_without_git_partial),
    ("pm_version_mismatch", case_pm_version_mismatch),
    ("context_open_branches_rendered", case_context_open_branches_rendered),
    ("status_head_pipeline_only", case_status_head_pipeline_only),
    ("changelog_run_id_keyed", case_changelog_run_id_keyed),
    ("node_resolution_order", case_node_resolution_order),
    ("routes_auto", case_routes_auto),
    ("external_missing", case_external_missing),
    ("preflight_behind", case_preflight_behind),
    ("commands_shell_safe", case_commands_shell_safe),
    ("scratch_private_atomic_write", case_scratch_private_atomic_write),
]


def run_case(fn, checker, keep):
    root = os.path.realpath(tempfile.mkdtemp(prefix="deps-check-selftest-"))
    t = Check()
    ctx = None
    try:
        ctx = Ctx(checker, root)
        fn(ctx, t)
        verdict, why = ("FAIL", "; ".join(p[:160] for p in t.problems[:6])) if t.problems else ("PASS", "")
    except Skip as s:
        verdict, why = "SKIP", str(s)
    except Exception as exc:
        verdict, why = "FAIL", "harness error: %r" % (exc,)
    finally:
        if ctx is not None:
            ctx.close()
        if keep:
            print("  kept %s" % root)
        else:
            shutil.rmtree(root, ignore_errors=True)
    return verdict, why


def main():
    ap = argparse.ArgumentParser(description="Behavioural tests for deps_check.py")
    ap.add_argument("--checker", default=os.path.join(HERE, "deps_check.py"))
    ap.add_argument("--only", help="run a single case by name")
    ap.add_argument("--keep", action="store_true", help="leave the temp trees on disk")
    args = ap.parse_args()
    checker = os.path.abspath(os.path.expanduser(args.checker))
    if not os.path.isfile(checker):
        print("checker not found: %s" % checker)
        return 2
    if shutil.which("git") is None:
        print("git not found")
        return 2
    cases = [c for c in CASES if not args.only or c[0] == args.only]
    if not cases:
        print("unknown case %r; known: %s" % (args.only, ", ".join(n for n, _ in CASES)))
        return 2
    tally = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    for name, fn in cases:
        verdict, why = run_case(fn, checker, args.keep)
        tally[verdict] += 1
        print("%s %s%s" % (verdict, name, " — " + why if why else ""))
        sys.stdout.flush()
    print("%d PASS · %d FAIL · %d SKIP (of %d)" % (tally["PASS"], tally["FAIL"], tally["SKIP"], len(cases)))
    return 1 if tally["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
