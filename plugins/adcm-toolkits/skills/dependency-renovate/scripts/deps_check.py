#!/usr/bin/env python3
"""deps-check: the deterministic planner of the dependency-renovate skill.

Reads one code project through the dependency_manifest module of the sibling code-project-context-generator
skill, queries the registries read-only and plans one dependency run: a patch+minor wave, majors stacked one
family per wave, holds, never-auto packages and the owner decisions. Stdlib only, Python 3.8+, deterministic
(the only clock read is the --date default; lists are sorted). Every subcommand is read-only unless --write
is given, and without it prints `would write <path> (+a -b)`. It never installs, never runs `npm audit` or
`pnpm audit`, never prints a value of .npmrc or .env, and never touches the machine tooling. A write goes to a
temp file in the target folder that then replaces the target, so a symlink at the target is replaced, never
followed. Every token of a generated command is shell-quoted, and a package name or workspace path outside the
npm, composer or path patterns is dropped from its wave with a review line.

Usage
  deps-check preflight <repo> [--context PATH] [--expect-email ADDR] [--date D] [--offline] [--json]
  deps-check plan <repo> [--context PATH] [--offline] [--date YYYY-MM-DD] [--max-majors N]
                  [--prioritize a,b] [--routes auto|none] [--scratch DIR] [--json] [--write]
  deps-check changelog <repo> --plan FILE (--wave patch-minor|major:<family> | --check)
                  [--verify KEY=VALUE]... [--smoke FILE] [--notes FILE] [--path REL] [--format entry|mr]
                  [--offline] [--date D] [--json] [--write]
  deps-check context <repo> [--context PATH] [--plan FILE] [--file NAME] [--if-merged] [--scratch DIR]
                  [--offline] [--date D] [--json] [--write]
  deps-check status <repo> [--branches a,b] [--json]
  deps-check --version | --help

Subcommands
  preflight  can a run start? identity, clean tree, default branch not behind origin, no open run, the
             Reviewer @handle, the pinned Node installed under nvm, external verification paths, the
             context skill, the package-manager version. Each blocker adds one `Para ti:` line.
  plan       the run plan: outdated packages, advisories (bulk POST of the locked versions to
             <registry>/-/npm/v1/security/advisories/bulk), Node LTS status, policy, families, waves,
             bump commands and edits. --write saves <scratch>/plan.json.
  changelog  renders the dependency changelog entry of a wave from the plan and the lockfile on disk;
             entries are keyed by run-id <date>-<sha7 of the base> and wave sub-sections are merged
             idempotently. --format mr renders the MR description instead (<scratch>/mr/<wave>.md).
             --check compares the recorded rows with the lockfile (no --wave needed).
  context    renders dependencies.md for the code-project-context skill: only the bytes between the
             auto-generated markers are replaced; the Policy section is written only for a new file.
  status     the head pipeline of each dependency MR (glab mr view -F json, field head_pipeline only).

Flags
  <repo>             the project root (its git toplevel may be an ancestor)
  --context PATH     the code-project-context skill dir or its dependencies.md (default: the single
                     <container>/ai/*/plugins/*/skills/code-project-context-* whose SKILL.md names the repo)
  --expect-email ADDR  the expected commit identity (default: Delivery `Commit identity` of dependencies.md)
  --date YYYY-MM-DD  run date (default: today; the only clock read)
  --offline          no registry, advisory, schedule, PyPI, glab or ls-remote calls: DEPS: partial(offline)
  --max-majors N     majors planned this run (default: Delivery `Max majors per run`, else 3)
  --prioritize a,b   majors ordered right after the ones that close advisories
  --routes auto|none smoke routes: the Smoke table of dependencies.md rules; without it, / alone, or with
                     auto / plus up to 3 static GET routes of the code-project-context-generator scanner
                     (its api_surface); none = no smoke
  --scratch DIR      run dir (default: $TMPDIR/deps-renovate/<repo>/<run-id>); scratch dirs are created 0700,
                     and one owned by another user or writable by group or others is refused
  --plan FILE        a plan.json written by `plan --write`
  --wave ID          patch-minor or major:<family> (a wave of the plan)
  --verify KEY=VALUE verification result, repeatable (build=pass, e2e=pass 24/24 (base 24/24), ci:lint=pass)
  --smoke FILE       a deps-smoke diff.json
  --notes FILE       migration notes of a major (first 10 lines)
  --path REL         changelog path inside the repo (default: Delivery `Changelog`, else
                     docs/dependencies/CHANGELOG.md)
  --format entry|mr  changelog entry (default) or MR description
  --check            changelog: compare the recorded rows with the lockfile; exit 1 on mismatch
  --file NAME        context file name (default dependencies.md); a file that records another repo is
                     refused unless NAME is dependencies-<repo>.md
  --if-merged        context: render only when the base sha moved since the file was rendered
  --branches a,b     status: only the MRs of these source branches
  --json             one JSON object whose `text` equals the plain lines
  --write            the only write flag: plan.json, the changelog or MR file, or dependencies.md

Environment
  DEPS_CHECK_REGISTRY       npm registry base (default https://registry.npmjs.org)
  DEPS_CHECK_PYPI           PyPI JSON base (default https://pypi.org/pypi)
  DEPS_CHECK_NODE_SCHEDULE  Node release schedule JSON (default: the nodejs/Release schedule.json)
  DEPS_CHECK_NODE_INDEX     Node dist index JSON (default https://nodejs.org/dist/index.json)
  DEPS_CHECK_NVM_DIR        Node installs (default ~/.nvm/versions/node)
  Node: .nvmrc > .node-version > engines.node (highest install that satisfies) > devEngines, under
  DEPS_CHECK_NVM_DIR, never `nvm use`; env.path_prefix puts that bin first on PATH for every subprocess,
  with COREPACK_ENABLE_DOWNLOAD_PROMPT=0 and COREPACK_ENABLE_STRICT=1. Timeouts: 120 s per subprocess,
  15 s per HTTP call. A subprocess stdout is parsed as JSON whatever its exit code; a step that returns
  no JSON or times out becomes partial(<step>). Without network data the embedded Node LTS table
  (2026-10-25) is used.

Output
  At most 40 plain lines; the last one is the verdict.
    preflight  PREFLIGHT: ready | blocked(identity,reviewer,dirty,behind,open-run,node-missing,
               external-missing,context-ambiguous,pm-mismatch) | unparsed (...)
    plan       DEPS: current | outdated(n) majors(m) advisories(a) holds(h)[ never-auto(k)][ runtime(eol)]
               | partial(<steps>) ... | unparsed (...)
    changelog  CHANGELOG: ok | written <path> | would write <path> (+a -b) | mismatch(<names>) | unparsed (...)
    context    CONTEXT: current | written <path> | would write <path> (+a -b) | unparsed (...)
    status     STATUS: none | ok(!a,!b) | running(!a) failed(!b) conflict(!c) nopipeline(!d) | unparsed (...)
  Exit codes
    preflight  0 ready · 1 blocked · 2 unparsed (not a git repo, no manifest)
    plan       0 current · 1 needed or partial · 2 unparsed
    changelog  0 ok, written or would write · 1 mismatch (--check) or partial (audit after) · 2 unparsed
    context    0 current or written · 1 would write · 2 unparsed or the different-repo guard
    status     0 none or all green · 1 running, failed, conflict or no pipeline · 2 glab missing or failing
    64 is a usage error in every subcommand.
"""
import argparse
import concurrent.futures
import datetime
import difflib
import fnmatch
import glob
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
SKILLS = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir))
CPCG_SCRIPTS = os.path.join(SKILLS, "code-project-context-generator", "scripts")
CONTEXT_TEMPLATE = os.path.join(SKILLS, "code-project-context-generator", "templates", "dependencies.md.tmpl")
OWN_TEMPLATES = os.path.normpath(os.path.join(HERE, os.pardir, "templates"))
PLUGIN_JSON = os.path.normpath(os.path.join(SKILLS, os.pardir, ".claude-plugin", "plugin.json"))
if CPCG_SCRIPTS not in sys.path:
    sys.path.insert(0, CPCG_SCRIPTS)
try:
    from dependency_manifest import dependency_manifest
except ImportError:
    dependency_manifest = None

MAX_LINES = 40
SUBPROCESS_TIMEOUT = 120
HTTP_TIMEOUT = 15
WORKERS = 8
MAX_READ = 64 * 1024 * 1024
DEFAULT_REGISTRY = "https://registry.npmjs.org"
DEFAULT_PYPI = "https://pypi.org/pypi"
DEFAULT_SCHEDULE = "https://raw.githubusercontent.com/nodejs/Release/main/schedule.json"
DEFAULT_INDEX = "https://nodejs.org/dist/index.json"
BULK_PATH = "/-/npm/v1/security/advisories/bulk"
DEFAULT_CHANGELOG = "docs/dependencies/CHANGELOG.md"
DEFAULT_MIN_AGE = 3
DEFAULT_MAX_MAJORS = 3
NEVER_AUTO = ("node", "npm", "pnpm", "yarn", "corepack", "bun", "deno")
RULES = ("never-auto", "hold", "hold-major", "cap", "pin", "group", "min-age")
HOLD_ORDER = {"never-auto": 0, "hold": 1, "cap": 2, "hold-major": 3}
SEVERITY = {"critical": 4, "high": 3, "moderate": 2, "low": 1, "info": 0}
KIND_ORDER = {"prod": 0, "dev": 1, "peer": 2, "optional": 3}
SAVE_FLAG = {"prod": "--save-prod", "dev": "--save-dev", "peer": "--save-peer", "optional": "--save-optional"}
PROJECT_DIRS = ("projects", "p-engineering", "engineering")
BRAIN_POSITIONS = (("ai", "ai-brain"), ("ai-brain",), ("docs", "ai-brain"))
BRAIN_FILE = "execute.md"
CONTEXT_FILE = "dependencies.md"
START_MARK = "<!-- auto-generated:"
END_MARK = "<!-- end auto-generated -->"
CHANGELOG_HEADER = ("# Dependency changelog\n\n"
                    "One entry per dependency run, newest first (Keep a Changelog style). Written by `deps-check changelog`;\n"
                    "edit only the prose under an entry, never its rows.\n")
PENDING = "_pending — the owner sets it_"
STEP_ORDER = ("offline", "git", "pm-version", "outdated", "release-age", "audit", "registry", "node-schedule",
              "pypi", "composer", "mr-list", "routes", "migration-refs")
BLOCKER_ORDER = ("identity", "reviewer", "dirty", "behind", "open-run", "node-missing", "external-missing",
                 "context-ambiguous", "pm-mismatch")
PLAN_KEYS = ("tool", "version", "command", "repo", "date", "state", "partial", "git", "brain", "context", "env",
             "manifest", "runtimes", "packages", "transitive_advisories", "families", "ci", "docker",
             "verification", "smoke", "waves", "pending_majors", "holds", "never_auto", "para_ti", "counts",
             "review", "text")
VERDICT_WORD = {"preflight": "PREFLIGHT", "plan": "DEPS", "changelog": "CHANGELOG", "context": "CONTEXT",
                "status": "STATUS"}

FAMILIES = (
    ("next", ("next", "eslint-config-next", "@next/*")),
    ("react", ("react", "react-dom", "react-is", "@types/react", "@types/react-dom")),
    ("vitest", ("vitest", "@vitest/*")),
    ("playwright", ("@playwright/test", "playwright", "playwright-core")),
    ("typescript-eslint", ("typescript-eslint", "@typescript-eslint/*")),
    ("eslint", ("eslint", "@eslint/js")),
    ("storybook", ("storybook", "@storybook/*")),
    ("sentry", ("@sentry/*",)),
    ("tailwind", ("tailwindcss", "@tailwindcss/*")),
    ("jest", ("jest", "ts-jest", "babel-jest", "@types/jest")),
    ("prisma", ("prisma", "@prisma/client")),
    ("angular", ("@angular/*",)),
    ("nestjs", ("@nestjs/*",)),
    ("sass", ("sass", "sass-embedded")),
    ("babel", ("@babel/*",)),
)
LOOSE_FAMILIES = frozenset({"sentry", "babel", "angular", "nestjs", "storybook"})
MIGRATION_FAMILIES = {"tailwind": "tailwindcss 3 to 4 is a migration (config and CSS entry change)"}
FRAMEWORKS = frozenset({
    "express", "fastify", "koa", "@nestjs/core", "next", "react", "react-dom", "vue", "nuxt", "@angular/core",
    "svelte", "astro", "tailwindcss", "typescript", "webpack", "vite", "eslint", "jest", "vitest",
    "@playwright/test", "prisma", "@prisma/client", "drizzle-orm", "sequelize", "typeorm", "@supabase/supabase-js"})
LTS_DATE = "2026-10-25"
LTS_TABLE = (
    (18, "2022-04-19", "2022-10-25", "2023-10-18", "2025-04-30"),
    (19, "2022-10-18", None, "2023-04-01", "2023-06-01"),
    (20, "2023-04-18", "2023-10-24", "2024-10-22", "2026-04-30"),
    (21, "2023-10-17", None, "2024-04-01", "2024-06-01"),
    (22, "2024-04-24", "2024-10-29", "2025-10-21", "2027-04-30"),
    (23, "2024-10-16", None, "2025-04-01", "2025-06-01"),
    (24, "2025-05-06", "2025-10-28", "2026-10-20", "2028-04-30"),
    (25, "2025-10-15", None, "2026-04-01", "2026-06-01"),
    (26, "2026-05-05", "2026-10-28", "2027-10-20", "2029-04-30"),
    (27, "2027-04-22", "2027-10-20", None, "2030-04-30"),
)
LTS_CODENAMES = {"argon": 4, "boron": 6, "carbon": 8, "dubnium": 10, "erbium": 12, "fermium": 14,
                 "gallium": 16, "hydrogen": 18, "iron": 20, "jod": 22, "krypton": 24}
PARENT = os.pardir + "/"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def tool_version():
    try:
        with open(PLUGIN_JSON, encoding="utf-8") as fh:
            value = json.load(fh).get("version")
    except (OSError, ValueError, AttributeError):
        return "unknown"
    return value if isinstance(value, str) and value else "unknown"


def read_text(path, limit=MAX_READ):
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > limit:
            return None
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def read_json(path):
    text = read_text(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def as_dict(value):
    return value if isinstance(value, dict) else {}


def as_list(value):
    return value if isinstance(value, list) else []


def home_short(path):
    home = os.path.expanduser("~")
    if path and home and home != os.sep and (path == home or path.startswith(home + os.sep)):
        return "~" + path[len(home):]
    return path


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", str(name).lower().lstrip("@")).strip("-") or "x"


def unique(items):
    out = []
    for item in items:
        if item not in out:
            out.append(item)
    return out


def diff_counts(old, new):
    """(+added, -removed) line counts between two texts."""
    a, b = (old or "").splitlines(), (new or "").splitlines()
    added = removed = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            removed += i2 - i1
        if tag in ("replace", "insert"):
            added += j2 - j1
    return added, removed


def write_file(path, text, private=False):
    """Write `text` to a temp file in the target folder, then replace `path` with it (atomic; a symlink at
    `path` is replaced, never followed). A replaced regular file keeps its mode; private files are 0o600."""
    folder = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(folder):
        os.makedirs(folder, mode=0o700 if private else 0o777)
    try:
        st = os.lstat(path)
        mode = stat.S_IMODE(st.st_mode) if stat.S_ISREG(st.st_mode) else None
    except OSError:
        mode = None
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".deps-check-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.chmod(tmp, 0o600 if private else 0o644 if mode is None else mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def private_problem(path):
    """`path` when it exists and is not a directory owned by the current user that group and others cannot
    write; None when it is missing or private."""
    uid = os.getuid() if hasattr(os, "getuid") else None
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError:
        return path
    try:
        if stat.S_ISLNK(st.st_mode):
            if uid is not None and st.st_uid != uid:
                return path
            st = os.stat(path)
    except OSError:
        return path
    if not stat.S_ISDIR(st.st_mode) or (uid is not None and st.st_uid != uid) or st.st_mode & 0o022:
        return path
    return None


def scratch_problem(levels):
    return next((p for p in (private_problem(level) for level in levels) if p), None)


def make_private(levels):
    """Create the missing scratch levels with mode 0o700 and tighten the existing ones; the first level that
    turns out not to be private is returned, else None."""
    parent = os.path.dirname(levels[0])
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    for level in levels:
        try:
            os.mkdir(level, 0o700)
        except FileExistsError:
            if private_problem(level):
                return level
        os.chmod(level, 0o700)
    return None


def shell_path(path):
    """A shell-quoted path for an owner command, keeping a leading ~/ expandable."""
    short = home_short(path)
    if short == "~":
        return short
    if short.startswith("~/"):
        return "~/" + shlex.quote(short[2:])
    return shlex.quote(short)


def day(text):
    try:
        return datetime.date.fromisoformat(str(text)[:10])
    except ValueError:
        return None


def age_days(iso, date):
    published, today = day(iso or ""), day(date)
    if published is None or today is None:
        return None
    return (today - published).days


def md_cell(value):
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def md_row(*cells):
    return "|" + "|".join(" %s " % md_cell(c) if md_cell(c) else " " for c in cells) + "|"


def plural(n, word):
    many = word[:-1] + "ies" if word.endswith("y") else word + "s"
    return "%d %s" % (n, word if n == 1 else many)


# ---------------------------------------------------------------------------
# Versions and npm ranges (the subset of node-semver a plan needs)
# ---------------------------------------------------------------------------

_FULL = re.compile(r"^\s*[v=]?\s*(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]*)?\s*$")
_PART = re.compile(r"^[v=]?(\d+|[xX*])(?:\.(\d+|[xX*]))?(?:\.(\d+|[xX*]))?(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]*)?$")
_OP = re.compile(r"^(<=|>=|<|>|=|\^|~>|~)?(.*)$")


def parse_version(text):
    m = _FULL.match(str(text or ""))
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4) or "") if m else None


def vkey(v):
    if not v[3]:
        return (v[0], v[1], v[2], 1, ())
    return (v[0], v[1], v[2], 0, tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in v[3].split(".")))


def vstr(v):
    return "%d.%d.%d" % v[:3] + ("-" + v[3] if v[3] else "")


def line_of(v):
    return (v[0],) if v[0] > 0 else (0, v[1])


def bump_type(old, new):
    a, b = parse_version(old), parse_version(new)
    if a is None or b is None or vkey(a) == vkey(b):
        return "none"
    if line_of(a) != line_of(b):
        return "major"
    if a[0] > 0 and a[1] != b[1]:
        return "minor"
    return "patch"


def _partial(text):
    if text in ("", "*", "x", "X"):
        return (None, None, None, "")
    m = _PART.match(text)
    if not m:
        return None
    nums = [None if g is None or g in "xX*" else int(g) for g in m.group(1, 2, 3)]
    for i in (1, 2):
        if nums[i - 1] is None:
            nums[i] = None
    return (nums[0], nums[1], nums[2], m.group(4) or "")


def _fill(p):
    return (p[0] or 0, p[1] or 0, p[2] or 0, p[3])


def _desugar(op, p):
    major, minor, patch, pre = p
    if major is None:
        return [("<", (0, 0, 0, "0"))] if op in ("<", ">") else []
    if op in ("", "="):
        if patch is not None:
            return [("=", (major, minor, patch, pre))]
        if minor is not None:
            return [(">=", (major, minor, 0, "")), ("<", (major, minor + 1, 0, "0"))]
        return [(">=", (major, 0, 0, "")), ("<", (major + 1, 0, 0, "0"))]
    if op == "^":
        if major > 0 or minor is None:
            high = (major + 1, 0, 0, "0")
        elif minor > 0 or patch is None:
            high = (0, minor + 1, 0, "0")
        else:
            high = (0, 0, patch + 1, "0")
        return [(">=", _fill(p)), ("<", high)]
    if op in ("~", "~>"):
        high = (major + 1, 0, 0, "0") if minor is None else (major, minor + 1, 0, "0")
        return [(">=", _fill(p)), ("<", high)]
    if op == ">":
        if patch is not None:
            return [(">", (major, minor, patch, pre))]
        return [(">=", (major, minor + 1, 0, ""))] if minor is not None else [(">=", (major + 1, 0, 0, ""))]
    if op == ">=":
        return [(">=", _fill(p))]
    if op == "<":
        return [("<", (major, minor or 0, patch or 0, pre or ("0" if patch is None else "")))]
    if patch is not None:
        return [("<=", (major, minor, patch, pre))]
    return [("<", (major, minor + 1, 0, "0"))] if minor is not None else [("<", (major + 1, 0, 0, "0"))]


def _comparators(text):
    text = text.strip()
    hyphen = re.match(r"^(\S+)\s+-\s+(\S+)$", text)
    if hyphen:
        low, high = _partial(hyphen.group(1)), _partial(hyphen.group(2))
        if low is None or high is None:
            return None
        if high[0] is None:
            upper = []
        elif high[2] is not None:
            upper = [("<=", (high[0], high[1], high[2], high[3]))]
        elif high[1] is not None:
            upper = [("<", (high[0], high[1] + 1, 0, "0"))]
        else:
            upper = [("<", (high[0] + 1, 0, 0, "0"))]
        return [(">=", _fill(low))] + upper
    text = re.sub(r"(<=|>=|<|>|=|\^|~>?)\s+", r"\1", text)
    out = []
    for token in text.split():
        m = _OP.match(token)
        part = _partial(m.group(2))
        if part is None:
            return None
        out.extend(_desugar(m.group(1) or "", part))
    return out


def parse_range(text):
    text = str(text or "").strip()
    if re.match(r"^(?:npm|workspace|catalog|file|link|git|git\+\S+|https?|github):", text) or "/" in text:
        return None
    alts = []
    for part in text.split("||"):
        comps = _comparators(part)
        if comps is None:
            return None
        alts.append(comps)
    return alts


def _holds(op, key, bound):
    return {"=": key == bound, "<": key < bound, "<=": key <= bound, ">": key > bound, ">=": key >= bound}[op]


def satisfies(version, text):
    """True/False when `version` is in the npm range `text`, None when either does not parse."""
    v, alts = parse_version(version), parse_range(text)
    if v is None or alts is None:
        return None
    key = vkey(v)
    for comps in alts:
        if all(_holds(op, key, vkey(c)) for op, c in comps):
            if not v[3] or any(c[:3] == v[:3] and c[3] not in ("", "0") for _, c in comps):
                return True
    return False


def range_min(text):
    alts = parse_range(text)
    if not alts:
        return None
    best = None
    for comps in alts:
        low = (0, 0, 0, "")
        for op, c in comps:
            if op in (">=", "=") and vkey(c) > vkey(low):
                low = c
            elif op == ">" and vkey((c[0], c[1], c[2] + 1, "")) > vkey(low):
                low = (c[0], c[1], c[2] + 1, "")
        if best is None or vkey(low) < vkey(best):
            best = low
    return best


def fixed_in(vulnerable, version):
    """The first fixed version of the vulnerable range alternative that holds `version`; None when unknown."""
    v, alts = parse_version(version), parse_range(vulnerable)
    if v is None or not alts:
        return None
    key = vkey(v)
    for comps in alts:
        if all(_holds(op, key, vkey(c)) for op, c in comps):
            if any(op == "<=" for op, _ in comps):
                return None
            uppers = [c for op, c in comps if op == "<"]
            if not uppers:
                return None
            up = min(uppers, key=vkey)
            return vstr((up[0], up[1], up[2], "" if up[3] == "0" else up[3]))
    return None


def range_operator(spec):
    """'^', '~' or '' (exact) when the declared spec is a plain bumpable range, else None."""
    s = (spec or "").strip()
    m = re.match(r"^([\^~]?)v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$", s)
    if m:
        return m.group(1)
    m = re.match(r"^([\^~])v?\d+(?:\.\d+)?$", s)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Subprocesses and HTTP
# ---------------------------------------------------------------------------

def tool_env(bin_dir=None, offline=False):
    env = dict(os.environ)
    if bin_dir:
        env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
    env.update({"COREPACK_ENABLE_DOWNLOAD_PROMPT": "0", "COREPACK_ENABLE_STRICT": "1", "NO_UPDATE_NOTIFIER": "1",
                "npm_config_update_notifier": "false", "npm_config_fund": "false", "NO_COLOR": "1",
                "FORCE_COLOR": "0"})
    if offline:
        env["COREPACK_ENABLE_NETWORK"] = "0"
    return env


def run_text(argv, cwd, env, timeout=SUBPROCESS_TIMEOUT):
    """(returncode, stdout, problem): problem is missing|timeout|None."""
    try:
        p = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "", "timeout"
    except OSError:
        return None, "", "missing"
    return p.returncode, p.stdout.decode("utf-8", "replace"), None


def run_json(argv, cwd, env, timeout=SUBPROCESS_TIMEOUT):
    """(data, problem): stdout parsed as JSON whatever the exit code; problem is missing|timeout|not-json|None."""
    rc, out, problem = run_text(argv, cwd, env, timeout)
    if problem:
        return None, problem
    text = out.strip()
    if not text:
        return ({}, None) if rc == 0 else (None, "not-json")
    try:
        return json.loads(text), None
    except ValueError:
        start = min([i for i in (text.find("{"), text.find("[")) if i >= 0] or [-1])
        if start > 0:
            try:
                return json.loads(text[start:]), None
            except ValueError:
                pass
    return None, "not-json"


def http_json(url, body=None, timeout=HTTP_TIMEOUT):
    """(data, problem) of one GET (or POST of `body` as JSON); problem is error|not-json|None."""
    data = None if body is None else json.dumps(body, sort_keys=True).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="GET" if body is None else "POST", headers={
        "Accept": "application/json", "Content-Type": "application/json", "User-Agent": "deps-check"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(MAX_READ)
    except Exception:
        return None, "error"
    try:
        return json.loads(raw.decode("utf-8")), None
    except ValueError:
        return None, "not-json"


def registry_base():
    return os.environ.get("DEPS_CHECK_REGISTRY", DEFAULT_REGISTRY).rstrip("/")


def registry_url(name, version=None):
    path = urllib.parse.quote(name, safe="@")
    return registry_base() + "/" + path + ("/" + urllib.parse.quote(version, safe="") if version else "")


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------

class Git(object):
    def __init__(self, repo):
        self.repo = repo
        self.env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0", LC_ALL="C")

    def run(self, *args, **kw):
        try:
            p = subprocess.run(["git", "-C", self.repo] + list(args), stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env,
                               timeout=kw.get("timeout", SUBPROCESS_TIMEOUT))
        except (OSError, subprocess.TimeoutExpired):
            return None, ""
        return p.returncode, p.stdout.decode("utf-8", "replace")

    def out(self, *args):
        rc, out = self.run(*args)
        return out.strip() if rc == 0 else None

    def ok(self, *args):
        return self.run(*args)[0] == 0


def remote_host(url):
    """(host, forge) of a remote URL without its credentials."""
    if not url:
        return None, None
    m = re.match(r"^[\w.+-]+://(?:[^@/]*@)?([^/:]+)", url) or re.match(r"^(?:[^@/]+@)?([^:/]+):", url)
    host = m.group(1).lower() if m else None
    if host and "gitlab" in host:
        return host, "gitlab"
    if host and "github" in host:
        return host, "github"
    return host, None


def _default_branch(g, current):
    ref = g.out("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    if ref and ref.startswith("refs/remotes/origin/"):
        return ref[len("refs/remotes/origin/"):]
    for name in ("main", "master"):
        if g.ok("rev-parse", "--verify", "--quiet", "refs/heads/" + name):
            return name
    return current if current and current != "HEAD" else "main"


def _identity(g):
    rc, out = g.run("config", "--show-scope", "--show-origin", "--get", "user.email")
    scope = origin = email = None
    if rc == 0 and out.strip():
        parts = out.rstrip("\n").split("\t")
        if len(parts) >= 3:
            scope, origin, email = parts[0], parts[1], parts[2]
    elif rc not in (0, 1):
        rc2, out2 = g.run("config", "--show-origin", "--get", "user.email")
        if rc2 == 0 and "\t" in out2:
            origin, email = out2.rstrip("\n").split("\t", 1)
            scope = "local" if "/.git/" in origin or origin.endswith(".git/config") else "global"
    if origin and origin.startswith("file:"):
        origin = home_short(origin[5:])
    return {"email": email.strip() if email else None, "scope": scope, "origin": origin,
            "inherited_from_global": scope in ("global", "system")}


def git_state(repo, online):
    g = Git(repo)
    top = g.out("rev-parse", "--show-toplevel")
    if top is None:
        return None, g
    top = os.path.realpath(top)
    branch = g.out("rev-parse", "--abbrev-ref", "HEAD") or g.out("symbolic-ref", "--short", "HEAD")
    head = g.out("rev-parse", "--verify", "--quiet", "HEAD")
    default = _default_branch(g, branch)
    base = (g.out("rev-parse", "--verify", "--quiet", "refs/heads/" + default)
            or g.out("rev-parse", "--verify", "--quiet", "refs/remotes/origin/" + default) or head)
    status = g.out("status", "--porcelain", "--untracked-files=normal", "--", ".")
    dirty = [line for line in (status or "").splitlines() if line.strip()]
    url = g.out("remote", "get-url", "origin")
    host, forge = remote_host(url)
    origin_default = g.out("rev-parse", "--verify", "--quiet", "refs/remotes/origin/" + default)
    behind, behind_source, origin_sha = None, None, origin_default
    if online and url:
        rc, out = g.run("ls-remote", "origin", "refs/heads/" + default, timeout=60)
        sha = out.split()[0] if rc == 0 and out.split() else None
        if rc == 0:
            origin_sha = sha
            behind_source = "ls-remote"
            if sha is None or sha == base:
                behind = False
            elif not g.ok("cat-file", "-e", sha + "^{commit}"):
                behind = True
            else:
                behind = not g.ok("merge-base", "--is-ancestor", sha, base or "HEAD")
    if behind is None and origin_default and base:
        count = g.out("rev-list", "--count", base + ".." + origin_default)
        behind, behind_source = (count is not None and count != "0"), "origin/" + default
    local_deps = sorted((g.out("for-each-ref", "--format=%(refname:short)", "refs/heads/deps/") or "").split())
    remote_deps = []
    if online and url:
        rc, out = g.run("ls-remote", "--heads", "origin", "deps/*", timeout=60)
        if rc == 0:
            remote_deps = sorted(line.split("refs/heads/", 1)[1] for line in out.splitlines() if "refs/heads/" in line)
    real = os.path.realpath(repo)
    return {
        "toplevel": top,
        "toplevel_ancestor": top != real and not os.path.exists(os.path.join(repo, ".git")),
        "branch": branch,
        "default_branch": default,
        "head": head,
        "base": base,
        "base_ref": "%s@%s" % (default, base[:7]) if base else None,
        "dirty": bool(dirty),
        "dirty_count": len(dirty),
        "behind": behind,
        "behind_source": behind_source,
        "origin_sha": origin_sha,
        "remote": host,
        "forge": forge,
        "local_branches": local_deps,
        "remote_branches": remote_deps,
        "identity": _identity(g),
    }, g


def run_id(date, git):
    sha = (git or {}).get("base") or ""
    return "%s-%s" % (date, sha[:7] if sha else "nogit")


# ---------------------------------------------------------------------------
# Container, brain Reviewer and the context skill
# ---------------------------------------------------------------------------

REVIEWER_LINE = re.compile(r"^>\s*\*\*Reviewer:\*\*\s*(.*)$")
HANDLE = re.compile(r"(?<![\w.@])@([A-Za-z0-9][A-Za-z0-9_.-]*[A-Za-z0-9_]|[A-Za-z0-9])")
FORGE = re.compile(r"\b(gitlab|github)\b", re.I)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def containers(repo, top):
    out = []
    for start in unique([repo] + ([top] if top else [])):
        parent = os.path.dirname(start)
        out.append(os.path.dirname(parent) if os.path.basename(parent) in PROJECT_DIRS else parent)
    return unique(out)


def reviewer_of(value):
    m = HANDLE.search(value or "")
    forge = FORGE.search(value or "")
    return ("@" + m.group(1)) if m else None, forge.group(1).lower() if forge else None


def reviewer_text(rev):
    if not rev.get("handle"):
        return PENDING
    return "%s%s" % (rev["handle"], " (%s)" % rev["forge"] if rev.get("forge") else "")


def find_brain(repo, top):
    seen = []
    for start in unique([repo] + ([top] if top else [])):
        link = os.path.join(start, "ai-brain")
        if os.path.isdir(link):
            seen.append(os.path.realpath(link))
    for container in containers(repo, top):
        for pos in BRAIN_POSITIONS:
            cand = os.path.join(container, *pos)
            if os.path.isdir(cand):
                seen.append(os.path.realpath(cand))
    for brain in unique(seen):
        path = os.path.join(brain, BRAIN_FILE)
        text = read_text(path)
        if text is None:
            continue
        for no, line in enumerate(text.splitlines(), 1):
            m = REVIEWER_LINE.match(line)
            if m:
                handle, forge = reviewer_of(m.group(1))
                return {"path": brain, "file": path, "line": no, "value": m.group(1).strip(), "handle": handle,
                        "forge": forge}
        return {"path": brain, "file": path, "line": None, "value": None, "handle": None, "forge": None}
    return None


def find_context(repo, top, arg, file_name=None):
    """The context skill and its dependencies file: {state: found|missing|none|ambiguous|bad, ...}."""
    name = file_name or CONTEXT_FILE
    skill = file_path = None
    if arg:
        path = os.path.abspath(os.path.expanduser(arg))
        if os.path.isfile(path):
            folder = os.path.dirname(path)
            skill = os.path.dirname(folder) if os.path.basename(folder) == "references" else folder
            file_path = path
        elif os.path.isdir(path):
            skill = path
        else:
            return {"state": "bad", "skill": path, "file": None, "layout": None, "candidates": []}
    else:
        word = re.compile(r"(?<![\w.-])%s(?![\w-])" % re.escape(os.path.basename(os.path.realpath(repo))))
        hits = []
        for container in containers(repo, top):
            pattern = os.path.join(glob.escape(container), "ai", "*", "plugins", "*", "skills", "code-project-context-*")
            for cand in sorted(glob.glob(pattern)):
                text = read_text(os.path.join(cand, "SKILL.md"))
                if text and word.search(text):
                    hits.append(os.path.realpath(cand))
        hits = unique(hits)
        if len(hits) > 1:
            return {"state": "ambiguous", "skill": None, "file": None, "layout": None, "candidates": hits}
        if not hits:
            return {"state": "none", "skill": None, "file": None, "layout": None, "candidates": []}
        skill = hits[0]
    layout = "references" if os.path.isdir(os.path.join(skill, "references")) else "flat"
    if file_path is None:
        for rel in (name, os.path.join("references", name)):
            if os.path.isfile(os.path.join(skill, rel)):
                file_path = os.path.join(skill, rel)
                break
    return {"state": "found" if file_path else "missing", "skill": skill, "file": file_path, "layout": layout,
            "candidates": [skill]}


def context_target(ctx, file_name):
    """Where a new dependencies file goes: references/ of a custom layout, else the root of a flat skill."""
    if ctx.get("file"):
        return ctx["file"]
    name = file_name or CONTEXT_FILE
    if ctx.get("layout") == "references":
        return os.path.join(ctx["skill"], "references", name)
    return os.path.join(ctx["skill"], name)


# ---------------------------------------------------------------------------
# The human Policy section of dependencies.md
# ---------------------------------------------------------------------------

def _cells(line):
    body = line.strip()
    if not body.startswith("|"):
        return None
    body = body[1:-1] if body.endswith("|") and len(body) > 1 else body[1:]
    return [c.strip() for c in re.split(r"(?<!\\)\|", body)]


def parse_policy(text, date, label=CONTEXT_FILE):
    """Rules, Verification, Smoke and Delivery of the Policy section; review lines for rows it ignores."""
    out = empty_policy()
    lines = text.splitlines()
    for line in lines:
        m = re.match(r"^- \*\*Repo:\*\* `([^`]+)`", line)
        if m and out["repo"] is None:
            out["repo"] = m.group(1)
        m = re.match(r"^<!-- auto-generated:.*· (\S+@[0-9a-f]{7,}) —", line)
        if m and out["source_ref"] is None:
            out["source_ref"] = m.group(1)
    end = next((i for i, line in enumerate(lines) if line.strip() == END_MARK), -1)
    start = next((i for i in range(end + 1, len(lines)) if lines[i].strip() == "## Policy"), None)
    if start is None:
        return out
    section, header = None, None
    for no in range(start + 1, len(lines)):
        line = lines[no]
        if line.startswith("## "):
            break
        if line.startswith("### "):
            section, header = line[4:].strip().lower(), None
            continue
        if section == "delivery":
            m = re.match(r"^\s*-\s+([^:]+):\s*(.*)$", line)
            if m:
                out["delivery"][m.group(1).strip().lower()] = m.group(2).strip()
            continue
        if section not in ("rules", "verification", "smoke"):
            continue
        cells = _cells(line)
        if cells is None:
            header = None if not line.strip() else header
            continue
        if header is None:
            header = [c.lower() for c in cells]
            continue
        if all(re.match(r"^:?-{3,}:?$", c) for c in cells if c) and any(cells):
            continue
        if any("{{" in c for c in cells):
            continue
        where = "review: %s:%d" % (label, no + 1)
        if len(cells) != len(header):
            out["review"].append("%s %s row has %d cells, %d expected — row ignored" % (
                where, section, len(cells), len(header)))
            continue
        row = dict(zip(header, cells))
        row["line"] = no + 1
        if section == "rules":
            _rule_row(row, where, date, out)
        elif section == "verification":
            if row.get("step") and row.get("command"):
                out["verification"].append({"step": row["step"].strip("`").lower(),
                                            "command": row["command"].strip("`"), "where": row.get("where") or "",
                                            "notes": row.get("notes") or "", "line": no + 1})
            else:
                out["review"].append("%s verification row needs Step and Command — row ignored" % where)
        elif row.get("route", "").strip("`").startswith("/"):
            out["smoke"].append({"route": row["route"].strip("`"), "name": row.get("name") or "",
                                 "mask": row.get("mask (css selectors, comma-separated)", row.get("mask", "")) or ""})
        else:
            out["review"].append("%s smoke route must start with / — row ignored" % where)
    return out


def _rule_row(row, where, date, out):
    package, rule, value = row.get("package", "").strip("`"), row.get("rule", "").strip("`").lower(), row.get("value", "").strip("`")
    if not package:
        out["review"].append("%s rule row without Package — row ignored" % where)
        return
    if rule not in RULES:
        out["review"].append("%s unknown rule %r for %s — row ignored" % (where, rule, package))
        return
    if rule == "cap" and (not value or parse_range(value) is None):
        out["review"].append("%s cap of %s needs a range Value such as <7 — row ignored" % (where, package))
        return
    if rule == "group" and not value:
        out["review"].append("%s group of %s needs a group name — row ignored" % (where, package))
        return
    days = None
    if rule == "min-age":
        m = re.match(r"^(\d+)", value)
        if not m:
            out["review"].append("%s min-age of %s needs a number of days — row ignored" % (where, package))
            return
        days = int(m.group(1))
    review_by = (row.get("review by") or "").strip()
    if review_by and day(review_by) and day(date) and day(date) > day(review_by) and rule in ("hold", "hold-major", "cap", "never-auto"):
        out["review"].append("%s hold expired for %s (review by %s) — still held" % (where, package, review_by))
    out["rules"].append({"package": package, "rule": rule, "value": days if rule == "min-age" else (value or None),
                         "why": row.get("why") or "", "since": row.get("since") or "", "review_by": review_by,
                         "line": row["line"]})


def delivery_value(policy, key):
    value = (policy or {}).get("delivery", {}).get(key)
    if value is None:
        return None
    value = value.strip()
    if not value or value.startswith("_pending") or "{{" in value or value.lower() in ("none", "n/a", "-"):
        return None
    return value.strip("`")


# ---------------------------------------------------------------------------
# Node: installs under nvm, the LTS schedule, the package-manager version
# ---------------------------------------------------------------------------

def nvm_dir():
    return os.path.expanduser(os.environ.get("DEPS_CHECK_NVM_DIR") or os.path.join("~", ".nvm", "versions", "node"))


def installed_nodes(folder):
    out = []
    try:
        names = os.listdir(folder)
    except OSError:
        return out
    for name in names:
        v = parse_version(name)
        if v and not v[3] and os.path.isdir(os.path.join(folder, name, "bin")):
            out.append((v, name))
    return sorted(out, key=lambda item: vkey(item[0]))


def embedded_table():
    return {row[0]: {"start": row[1], "lts": row[2], "maintenance": row[3], "end": row[4]} for row in LTS_TABLE}


def node_schedule(online, partial):
    """({major: {start, lts, maintenance, end}}, {major: newest version}, source)."""
    table, latest, source = embedded_table(), {}, "embedded " + LTS_DATE
    if not online:
        return table, latest, source
    data, problem = http_json(os.environ.get("DEPS_CHECK_NODE_SCHEDULE", DEFAULT_SCHEDULE))
    index, problem2 = http_json(os.environ.get("DEPS_CHECK_NODE_INDEX", DEFAULT_INDEX))
    if problem or not isinstance(data, dict) or problem2 or not isinstance(index, list):
        partial.add("node-schedule")
    if isinstance(data, dict) and not problem:
        for key, row in data.items():
            m = re.match(r"^v(\d+)$", key)
            if m and isinstance(row, dict):
                table[int(m.group(1))] = {k: row.get(k) if isinstance(row.get(k), str) else None
                                          for k in ("start", "lts", "maintenance", "end")}
        source = "online"
    for row in index if isinstance(index, list) and not problem2 else []:
        v = parse_version(as_dict(row).get("version"))
        if v and not v[3] and (v[0] not in latest or vkey(v) > vkey(parse_version(latest[v[0]]))):
            latest[v[0]] = vstr(v)
    return table, latest, source


def node_status(major, date, table):
    row = table.get(major)
    if major is None or not row:
        return "unknown"
    if row.get("end") and date > row["end"]:
        return "eol"
    if row.get("maintenance") and date >= row["maintenance"]:
        return "maintenance"
    if row.get("lts") and date >= row["lts"]:
        return "active-lts"
    return "current"


def newest_lts(date, table):
    found = [m for m, row in table.items() if row.get("lts") and row["lts"] <= date and row.get("end") and row["end"] > date]
    return max(found) if found else None


def resolve_node(manifest, folder, date, table):
    pins = manifest["runtimes"]["node"]["pins"]
    by_source = {}
    for pin in pins:
        by_source.setdefault(pin["source"], pin["value"])
    order = (".nvmrc", ".node-version", "engines.node", "devEngines.runtime", ".tool-versions", "volta.node")
    source, value = next(((s, by_source[s]) for s in order if s in by_source), (None, None))
    installs = installed_nodes(folder)
    env = {"node_pin": value, "node_source": source, "node_version": None, "node_found": "none", "node_bin": None,
           "nvm_dir": folder, "path_prefix": "", "pin_major": None}
    if value is None:
        return env
    text = value.strip().lstrip("v")
    exact = parse_version(text)
    pick, found = None, "none"
    if source in ("engines.node", "devEngines.runtime") and exact is None:
        matching = [item for item in installs if satisfies(vstr(item[0]), value)]
        if matching:
            pick, found = matching[-1], "major"
        low = range_min(value)
        env["pin_major"] = pick[0][0] if pick else (low[0] if low else None)
    else:
        major = None
        if exact:
            major = exact[0]
            same = [item for item in installs if vkey(item[0]) == vkey(exact)]
            if same:
                pick, found = same[-1], "exact"
        else:
            m = re.match(r"^(\d+)(?:\.(\d+))?$", text)
            code = re.match(r"^lts/([a-z]+)$", text.lower())
            if m:
                major = int(m.group(1))
            elif code and code.group(1) in LTS_CODENAMES:
                major = LTS_CODENAMES[code.group(1)]
            elif text.lower() in ("lts/*", "lts"):
                major = newest_lts(date, table)
            elif text.lower() in ("node", "stable", "latest", "current") and installs:
                major = installs[-1][0][0]
        if pick is None and major is not None:
            same = [item for item in installs if item[0][0] == major]
            if same:
                pick, found = same[-1], "major"
        env["pin_major"] = major
    if pick:
        env["node_version"], env["node_found"] = vstr(pick[0]), found
        env["node_bin"] = os.path.join(folder, pick[1], "bin")
        env["path_prefix"] = "PATH=%s:$PATH" % shlex.quote(env["node_bin"])
    return env


def check_pm(repo, manifest, env, offline):
    pm = manifest["package_manager"]
    name = pm.get("name")
    declared = pm.get("version") if pm.get("source") == "packageManager" else None
    out = {"pm": name, "pm_declared": declared, "pm_version": None, "pm_found": "unchecked",
           "corepack": {"COREPACK_ENABLE_DOWNLOAD_PROMPT": "0", "COREPACK_ENABLE_STRICT": "1"}}
    if name not in ("npm", "pnpm", "yarn", "bun"):
        return out
    rc, stdout, _ = run_text([name, "--version"], repo, tool_env(env.get("node_bin"), offline), timeout=60)
    version = stdout.strip().splitlines()[-1].strip() if rc == 0 and stdout.strip() else None
    out["pm_version"] = version
    if not version:
        out["pm_found"] = "missing"
    elif declared and version != declared:
        out["pm_found"] = "mismatch"
    else:
        out["pm_found"] = "ok"
    return out


# ---------------------------------------------------------------------------
# Lockfile graph: every locked version (for the bulk advisory POST) and who requires what
# ---------------------------------------------------------------------------

class LockGraph(object):
    def __init__(self):
        self.versions = {}
        self.parents = {}
        self.locations = {}

    def add(self, node, name, version):
        if name and version and parse_version(version):
            self.versions.setdefault(name, set()).add(version)
            self.locations.setdefault((name, version), set()).add(node)

    def edge(self, parent, child):
        self.parents.setdefault(child, set()).add(parent)

    def direct_parents(self, name, version, roots):
        """Root packages (direct dependencies) whose dependency tree holds name@version."""
        seen, stack, found = set(), list(self.locations.get((name, version), ())), set()
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            for parent in self.parents.get(node, ()):
                if parent in roots:
                    found.add(roots[parent])
                stack.append(parent)
        return sorted(found)


def npm_lock_graph(repo, lock_rel):
    data = read_json(os.path.join(repo, lock_rel))
    graph, roots = LockGraph(), {}
    packages = as_dict(as_dict(data).get("packages"))
    if not packages:
        for name, entry in as_dict(as_dict(data).get("dependencies")).items():
            graph.add("node_modules/" + name, name, as_dict(entry).get("version"))
            roots["node_modules/" + name] = name
        return graph, roots, {}
    requires = {}
    for key, entry in packages.items():
        if not isinstance(entry, dict) or "node_modules/" not in key or entry.get("link"):
            continue
        name = entry.get("name") or key.rsplit("node_modules/", 1)[1]
        graph.add(key, name, entry.get("version"))
        if key.count("node_modules/") == 1 and key.startswith("node_modules/"):
            roots[key] = name
        deps = {}
        for field in ("dependencies", "optionalDependencies", "peerDependencies"):
            deps.update({k: v for k, v in as_dict(entry.get(field)).items() if isinstance(v, str)})
        requires[key] = deps
    for key, deps in requires.items():
        for child in deps:
            found = resolve_child(packages, key, child)
            if found:
                graph.edge(key, found)
    return graph, roots, requires


def resolve_child(packages, key, child):
    base = key
    while True:
        cand = base + "/node_modules/" + child
        if cand in packages:
            return cand
        if "node_modules/" not in base:
            return None
        base = base.rsplit("/node_modules/", 1)[0] if "/node_modules/" in base else ""
        if not base:
            top = "node_modules/" + child
            return top if top in packages else None


_PNPM_KEY = re.compile(r"^  ['\"]?/?((?:@[^/@'\"]+/)?[^@/'\"(]+)[@/]([^('\":]+)")


def pnpm_lock_graph(repo, lock_rel):
    graph, roots, requires = LockGraph(), {}, {}
    text = read_text(os.path.join(repo, lock_rel)) or ""
    section, current, group = None, None, None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if not raw.startswith(" "):
            section = raw.split(":", 1)[0].strip()
            current = group = None
            continue
        if section in ("packages", "snapshots"):
            if raw.startswith("  ") and not raw.startswith("   "):
                m = _PNPM_KEY.match(raw)
                current = None
                if m:
                    name, version = m.group(1), m.group(2).split("_", 1)[0]
                    current = name + "@" + version
                    graph.add(current, name, version)
                    requires.setdefault(current, {})
                group = None
            elif current and raw.startswith("    ") and not raw.startswith("     "):
                group = raw.strip().rstrip(":") if raw.strip().endswith(":") else None
            elif current and group in ("dependencies", "optionalDependencies") and raw.startswith("      "):
                m = re.match(r"^\s+['\"]?((?:@[^/'\"]+/)?[^:'\"]+)['\"]?:\s*['\"]?([^('\"\s]+)", raw)
                if m:
                    child = m.group(1) + "@" + m.group(2).split("_", 1)[0]
                    requires[current][m.group(1)] = m.group(2)
                    graph.edge(current, child)
        elif section == "importers":
            if raw.startswith("      ") and not raw.startswith("       "):
                m = re.match(r"^\s+['\"]?((?:@[^/'\"]+/)?[^:'\"]+)['\"]?:\s*$", raw)
                group = m.group(1) if m else None
            elif group and raw.strip().startswith("version:"):
                version = raw.split(":", 1)[1].strip().strip("'\"").split("(", 1)[0]
                if parse_version(version):
                    roots[group + "@" + version] = group
    return graph, roots, requires


# ---------------------------------------------------------------------------
# Online data: outdated, release times, advisories, registry manifests, PyPI, composer
# ---------------------------------------------------------------------------

def collect_outdated(repo, pm, workspaces, env, partial):
    """{name: {latest, wanted}} from `npm outdated` / `pnpm outdated` (exit 1 with JSON is success)."""
    if pm == "npm":
        argv = ["npm", "outdated", "--json"] + (["--workspaces", "--include-workspace-root"] if len(workspaces) > 1 else [])
    elif pm == "pnpm":
        argv = ["pnpm", "outdated", "-r", "--format", "json"]
    else:
        return {}
    data, problem = run_json(argv, repo, env)
    if problem or not isinstance(data, (dict, list)):
        partial.add("outdated")
        return {}
    out = {}
    items = data.items() if isinstance(data, dict) else [(as_dict(e).get("packageName") or as_dict(e).get("name"), e) for e in data]
    for name, entry in items:
        for one in entry if isinstance(entry, list) else [entry]:
            one = as_dict(one)
            if isinstance(name, str) and name not in out:
                out[name] = {"latest": one.get("latest"), "wanted": one.get("wanted")}
    return out


def collect_times(repo, names, env, partial):
    """{name: {version: iso}} from `npm view <name> time --json`, one call per candidate (threaded)."""
    def one(name):
        data, problem = run_json(["npm", "view", name, "time", "--json"], repo, env)
        if problem or not isinstance(data, dict) or "error" in data:
            return name, None, problem or "error"
        return name, {k: v for k, v in data.items() if k not in ("created", "modified") and isinstance(v, str)}, None
    out, failed = {}, 0
    names = sorted(set(names))
    if not names:
        return out
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for name, times, problem in pool.map(one, names):
            if times is None:
                failed += 1
            else:
                out[name] = times
    if failed == len(names):
        partial.add("release-age")
    return out


def collect_advisories(graph, partial):
    """[{id, severity, package, version, range, fixed_in, title}] for every locked version (bulk POST)."""
    body = {name: sorted(versions, key=lambda v: vkey(parse_version(v))) for name, versions in sorted(graph.versions.items())}
    if not body:
        return []
    data, problem = http_json(registry_base() + BULK_PATH, body=body)
    if problem or not isinstance(data, dict):
        partial.add("audit")
        return []
    out = []
    for name in sorted(data):
        for adv in as_list(data[name]):
            adv = as_dict(adv)
            rng = adv.get("vulnerable_versions") or adv.get("range")
            m = re.search(r"GHSA(?:-[0-9a-z]{4}){3}", str(adv.get("url") or adv.get("github_advisory_id") or ""), re.I)
            ident = "GHSA" + m.group(0)[4:].lower() if m else "npm:%s" % adv.get("id")
            for version in body.get(name, []):
                if not rng or satisfies(version, rng):
                    out.append({"id": ident, "severity": str(adv.get("severity") or "unknown").lower(),
                                "package": name, "version": version, "range": rng,
                                "fixed_in": fixed_in(rng, version) if rng else None,
                                "title": str(adv.get("title") or "")[:120]})
    return sorted(out, key=lambda a: (-SEVERITY.get(a["severity"], 0), a["id"], a["package"], vkey(parse_version(a["version"]))))


def collect_manifests(pairs, partial):
    """{(name, version): manifest} from GET <registry>/<name>/<version>."""
    out = {}
    pairs = sorted(set(pairs))
    if not pairs:
        return out

    def one(pair):
        data, problem = http_json(registry_url(pair[0], pair[1]))
        return pair, (data if isinstance(data, dict) and not problem else None)
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for pair, data in pool.map(one, pairs):
            out[pair] = data
    if all(v is None for v in out.values()):
        partial.add("registry")
    return out


def collect_refs(repo, pairs, env, partial):
    """{name: [urls]} from `npm view <name>@<target> repository.url homepage --json` for the majors."""
    def one(pair):
        data, problem = run_json(["npm", "view", "%s@%s" % pair, "repository.url", "homepage", "--json"], repo, env)
        urls = []
        if isinstance(data, dict) and not problem and "error" not in data:
            for key in ("repository.url", "homepage"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    urls.append(clean_url(value))
        elif isinstance(data, str) and not problem:
            urls.append(clean_url(data))
        return pair[0], unique([u for u in urls if u]), problem
    out, failed = {}, 0
    pairs = sorted(set(pairs))
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for name, urls, problem in pool.map(one, pairs):
            out[name] = urls
            failed += 1 if problem else 0
    if pairs and failed == len(pairs):
        partial.add("migration-refs")
    return out


def clean_url(url):
    url = re.sub(r"^git\+", "", url.strip())
    url = re.sub(r"^git://", "https://", url)
    url = re.sub(r"^ssh://git@", "https://", url)
    url = re.sub(r"\.git$", "", url)
    url = re.sub(r"#.*$", "", url)
    return url if re.match(r"^https?://", url) and "@" not in url.split("//", 1)[1].split("/", 1)[0] else None


def collect_pypi(names, partial):
    base = os.environ.get("DEPS_CHECK_PYPI", DEFAULT_PYPI).rstrip("/")
    out = {}
    for name in sorted(set(names)):
        data, problem = http_json("%s/%s/json" % (base, urllib.parse.quote(name)))
        if problem or not isinstance(data, dict):
            partial.add("pypi")
            continue
        out[name] = sorted((v for v in as_dict(data.get("releases")) if parse_version(v) and not parse_version(v)[3]),
                           key=lambda v: vkey(parse_version(v)))
    return out


def collect_composer(repo, env, partial):
    data, problem = run_json(["composer", "outdated", "--direct", "--format=json", "--no-interaction"], repo, env)
    if problem or not isinstance(data, dict):
        partial.add("composer")
        return {}
    out = {}
    for entry in as_list(data.get("installed")):
        entry = as_dict(entry)
        if isinstance(entry.get("name"), str):
            latest = str(entry.get("latest") or "").lstrip("v") or None
            safe = entry.get("latest-status") == "semver-safe-update"
            out[entry["name"]] = {"latest": latest, "wanted": latest if safe else None}
    return out


def glab_mrs(repo, offline, partial):
    """(opened MRs labelled dependencies, problem) from `glab mr list --label dependencies -F json`."""
    if offline:
        return None, "offline"
    data, problem = run_json(["glab", "mr", "list", "--label", "dependencies", "-F", "json"], repo, tool_env())
    if problem or not isinstance(data, list):
        partial.add("mr-list")
        return None, problem or "not-json"
    out = []
    for mr in data:
        mr = as_dict(mr)
        if str(mr.get("state") or "opened") == "opened" and mr.get("iid") is not None:
            out.append({"iid": mr.get("iid"), "branch": mr.get("source_branch"), "target": mr.get("target_branch"),
                        "draft": bool(mr.get("draft") or mr.get("work_in_progress"))})
    return sorted(out, key=lambda m: int(m["iid"]) if str(m["iid"]).isdigit() else 0), None


# ---------------------------------------------------------------------------
# Policy precedence: built-in never-auto > the Policy table > renovate.json packageRules > defaults
# ---------------------------------------------------------------------------

def _matches(rule, name):
    if name in rule.get("names", []):
        return True
    for pattern in rule.get("patterns", []):
        try:
            if re.search(pattern, name):
                return True
        except re.error:
            continue
    return False


def renovate_rules(bots):
    out = {"caps": [], "holds": [], "groups": [], "min_age": None, "review": []}
    for bot in bots:
        if bot["kind"] == "dependabot":
            out["review"].append("review: dependabot config present — not parsed (%s)" % bot["path"])
            continue
        if not bot["parsed"]:
            out["review"].append("review: %s present — not parsed" % bot["path"])
            continue
        out["caps"].extend((cap, bot["path"]) for cap in bot["caps"])
        for rule in bot["disabled"]:
            types = set(rule.get("update_types") or [])
            if not types or {"major", "minor", "patch"} <= types:
                out["holds"].append((rule, bot["path"], "hold"))
            elif "major" in types:
                out["holds"].append((rule, bot["path"], "hold-major"))
            else:
                out["review"].append("review: %s disables %s updates of %s — not mapped" % (
                    bot["path"], ", ".join(sorted(types)), ", ".join(rule.get("names") or rule.get("patterns") or [])))
        out["groups"].extend((group, bot["path"]) for group in bot["groups"])
        if bot["min_release_age_days"] is not None and out["min_age"] is None:
            out["min_age"] = bot["min_release_age_days"]
        for ext in bot["extends"]:
            out["review"].append("review: %s extends %s — not expanded" % (bot["path"], ext))
    return out


def rules_for(s, name):
    out = {"hold": None, "group": None, "min_age": None, "pin": False}
    if name in NEVER_AUTO:
        out["hold"] = {"rule": "never-auto", "value": None, "source": "built-in"}
    for row in s.policy["rules"]:
        if not fnmatch.fnmatchcase(name, row["package"]):
            continue
        if row["rule"] in HOLD_ORDER and out["hold"] is None:
            out["hold"] = {"rule": row["rule"], "value": row["value"], "source": s.policy_label}
        elif row["rule"] == "group" and out["group"] is None:
            out["group"] = row["value"]
        elif row["rule"] == "min-age" and out["min_age"] is None:
            out["min_age"] = row["value"]
        elif row["rule"] == "pin":
            out["pin"] = True
    for cap, path in s.renovate["caps"]:
        if out["hold"] is None and _matches(cap, name):
            out["hold"] = {"rule": "cap", "value": cap["allowed"], "source": path}
    for rule, path, kind in s.renovate["holds"]:
        if out["hold"] is None and _matches(rule, name):
            out["hold"] = {"rule": kind, "value": None, "source": path}
    for group, path in s.renovate["groups"]:
        if out["group"] is None and name in group.get("names", []):
            out["group"] = group["name"]
    return out


def cap_allows(cap, version):
    if cap is None:
        return True
    if len(cap) > 2 and cap.startswith("/") and cap.endswith("/"):
        try:
            return re.search(cap[1:-1], version) is not None
        except re.error:
            return True
    ok = satisfies(version, cap)
    return True if ok is None else ok


def family_of(name, direct, group=None):
    if group:
        return group
    for family, patterns in FAMILIES:
        if any(fnmatch.fnmatchcase(name, p) for p in patterns):
            return family
    if name == "@types/node":
        return "runtime-node"
    if name.startswith("@types/"):
        target = types_target(name)
        if target in direct:
            return family_of(target, ())
    return name


def types_target(name):
    base = name[len("@types/"):]
    return "@" + base.replace("__", "/", 1) if "__" in base else base


def grep_escape(text):
    return re.sub(r"([.^$*+?()\[\]{}|\\])", r"\\\1", text)


def import_count(g, name):
    if g is None:
        return 0
    n = grep_escape(name)
    rc, out = g.run("grep", "-l", "-E", "(from ['\"]%s(['\"/])|require\\(['\"]%s(['\"/]))" % (n, n), "--", ".")
    return len(out.splitlines()) if rc == 0 else 0


# ---------------------------------------------------------------------------
# Package evaluation
# ---------------------------------------------------------------------------

def pick(cands, times, date, min_age, vulns):
    """(target, bypassed): the newest candidate at least min_age days old; when it stays vulnerable, the oldest
    candidate outside every vulnerable range, younger or not."""
    if not cands:
        return None, False

    def age(c):
        return age_days(times.get(vstr(c)), date)

    def safe(c):
        return all(satisfies(vstr(c), a["range"]) is not True for a in vulns if a.get("range"))
    old = [c for c in cands if age(c) is None or age(c) >= min_age]
    best = old[-1] if old else None
    if vulns and (best is None or not safe(best)):
        fixing = [c for c in cands if safe(c)]
        if fixing:
            young = age(fixing[0]) is not None and age(fixing[0]) < min_age
            return fixing[0], young
    return best, False


def hold_text(hold):
    return "%s%s (%s)" % (hold["rule"], " " + str(hold["value"]) if hold["value"] else "", hold["source"])


def evaluate(s, e, info, runtime_major):
    rules = rules_for(s, e["name"])
    name, locked = e["name"], e["locked"]
    out = {"name": name, "workspace": e["workspace"], "kind": e["kind"], "declared": e["declared"],
           "locked": locked, "wanted": info.get("wanted"), "latest": info.get("latest"), "latest_in_major": None,
           "target": None, "bump_type": "none", "advisories": [], "held_by": rules["hold"], "never_auto": False,
           "family": family_of(name, s.direct, rules["group"]), "risk": None, "age_days": None, "wave": "current",
           "style": e["style"], "catalog": e.get("catalog"), "step": None, "major_target": None,
           "pin": rules["pin"], "blocked": None, "bypass": False}
    out["advisories"] = [{"id": a["id"], "severity": a["severity"], "range": a["range"], "fixed_in": a["fixed_in"]}
                         for a in s.advisories if a["package"] == name and a["version"] == locked]
    if rules["hold"] and rules["hold"]["rule"] == "never-auto":
        out["never_auto"], out["wave"] = True, "never-auto"
        return out
    lv = parse_version(locked)
    if lv is None or e["style"] in ("workspace", "url", "alias", "tag", "other") or e["kind"] == "peer":
        return out
    versions = [parse_version(v) for v in info.get("versions") or []]
    versions = sorted({v for v in versions if v and (not v[3] or lv[3])}, key=vkey)
    if not out["wanted"] and versions and e["declared"]:
        inside = [v for v in versions if satisfies(vstr(v), e["declared"])]
        out["wanted"] = vstr(inside[-1]) if inside else None
    cands = [v for v in versions if vkey(v) > vkey(lv)]
    inline = [c for c in cands if line_of(c) == line_of(lv)]
    later = sorted({line_of(c) for c in cands if line_of(c) > line_of(lv)})
    nextline = [c for c in cands if later and line_of(c) == later[0]]
    out["latest_in_major"] = vstr(inline[-1]) if inline else None
    hold = rules["hold"]
    if name == "@types/node" and runtime_major is not None:
        lines = [(runtime_major,)] if runtime_major > 0 else [(0, runtime_major)]
        if line_of(lv) != lines[0]:
            inline = []
        nextline = [c for c in cands if line_of(c) == lines[0]] if line_of(lv) < lines[0] else []
        if line_of(lv) == lines[0] and later:
            out["blocked"] = "follows the runtime (node %d)" % runtime_major
    if hold:
        before = (bool(inline), bool(nextline))
        if hold["rule"] == "hold":
            inline, nextline = [], []
        elif hold["rule"] == "hold-major":
            nextline = []
        elif hold["rule"] == "cap":
            inline = [c for c in inline if cap_allows(hold["value"], vstr(c))]
            nextline = [c for c in nextline if cap_allows(hold["value"], vstr(c))]
        if before != (bool(inline), bool(nextline)):
            out["blocked"] = hold_text(hold)
    min_age = rules["min_age"] if rules["min_age"] is not None else s.default_min_age
    vulns = [a for a in s.advisories if a["package"] == name and a["version"] == locked]
    times = info.get("times") or {}
    step, bypass = pick(inline, times, s.date, min_age, vulns)
    step_safe = step and all(satisfies(vstr(step), a["range"]) is not True for a in vulns if a.get("range"))
    major, bypass2 = pick(nextline, times, s.date, min_age, [] if step_safe else vulns)
    out["step"] = vstr(step) if step else None
    out["major_target"] = vstr(major) if major else None
    out["bypass"] = bypass or bypass2
    return out


def closes_of(target, advisories):
    return sorted({a["id"] for a in advisories if a.get("range") and satisfies(target, a["range"]) is False})


NODE_FIELDS = ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")


def ecosystems(s):
    """{(name, workspace): node|composer|python} from the manifest file that declares each entry."""
    out = {}
    for ws in s.manifest["workspaces"] or ["."]:
        pkg = as_dict(read_json(os.path.join(s.repo, "package.json" if ws == "." else os.path.join(ws, "package.json"))))
        for field in NODE_FIELDS:
            for name in as_dict(pkg.get(field)):
                out[(name, ws)] = "node"
    comp = as_dict(read_json(os.path.join(s.repo, "composer.json")))
    for field in ("require", "require-dev"):
        for name in as_dict(comp.get(field)):
            out.setdefault((name, "."), "composer")
    return {(e["name"], e["workspace"]): out.get((e["name"], e["workspace"]), "python") for e in s.manifest["packages"]}


def collect_package_data(s):
    """Online package facts: {name: {versions, times, latest, wanted}}, advisories and the lock graph."""
    m, pm = s.manifest, s.manifest["package_manager"]["name"]
    s.eco = ecosystems(s)
    node_pm = pm if pm in ("npm", "pnpm", "yarn", "bun") else "npm"
    roots_lock = [l for l in m["lockfiles"] if "/" not in l["path"]]
    lock = next((l for l in roots_lock if l["type"] in ("package-lock", "npm-shrinkwrap", "pnpm")), None)
    graph, roots = LockGraph(), {}
    if lock and lock["type"] == "pnpm":
        graph, roots, _ = pnpm_lock_graph(s.repo, lock["path"])
    elif lock:
        graph, roots, _ = npm_lock_graph(s.repo, lock["path"])
    for e in m["packages"]:
        if e["locked"] and e["name"] not in graph.versions and s.eco[(e["name"], e["workspace"])] == "node":
            graph.add("direct:" + e["name"], e["name"], e["locked"])
    s.graph, s.lock = graph, lock
    s.roots = {node: name for node, name in roots.items() if name in s.direct}
    info = {name: {"versions": [], "times": {}, "latest": None, "wanted": None} for name in s.direct}
    s.advisories = []
    if not s.online:
        return info
    node_names = sorted({e["name"] for e in m["packages"] if s.eco[(e["name"], e["workspace"])] == "node"
                         and e["style"] in ("range", "exact", "catalog") and e["kind"] != "peer"})
    outdated = collect_outdated(s.repo, node_pm, m["workspaces"], s.tenv, s.partial) if node_names else {}
    for name, row in outdated.items():
        if name in info:
            info[name]["latest"], info[name]["wanted"] = row.get("latest"), row.get("wanted")
    if graph.versions:
        s.advisories = collect_advisories(graph, s.partial)
    vulnerable = {a["package"] for a in s.advisories}
    wanted_names = [n for n in node_names if n in outdated or n in vulnerable]
    times = collect_times(s.repo, wanted_names, s.tenv, s.partial) if wanted_names else {}
    for name, stamps in times.items():
        info[name]["times"] = stamps
        info[name]["versions"] = list(stamps)
    for name in wanted_names:
        if not info[name]["versions"]:
            info[name]["versions"] = [v for v in (info[name]["wanted"], info[name]["latest"]) if parse_version(v)]
    if "composer" in s.eco.values():
        for name, row in collect_composer(s.repo, s.tenv, s.partial).items():
            if name in info:
                info[name].update(latest=row["latest"], versions=[row["latest"]] if row["latest"] else [])
    pins = [e["name"] for e in m["packages"] if e["style"] == "exact" and s.eco[(e["name"], e["workspace"])] == "python"]
    pins += [p["name"] for p in m["ci"]["pins"] if p["kind"] == "pip"]
    if pins:
        s.pypi = collect_pypi(pins, s.partial)
        for name, versions in s.pypi.items():
            if name in info:
                info[name]["versions"] = versions
    return info


def base_risk(e):
    if e["name"].startswith("@types/"):
        return 1
    if e["name"] in FRAMEWORKS:
        return 4
    return 2 if e["kind"] == "dev" else 3


def plan_packages(s, args):
    m = s.manifest
    info = s.info = collect_package_data(s)
    runtime_major = s.env.get("pin_major")
    entries = [evaluate(s, e, info.get(e["name"], {}), runtime_major) for e in m["packages"]]
    steps = {}
    for e in entries:
        if e["step"] and e["name"] not in steps:
            steps[e["name"]] = e["step"]
    s.transitive = transitive_advisories(s, entries, steps)
    families = {}
    for e in entries:
        families.setdefault(e["family"], []).append(e)
    majors, held_fams = [], {}
    grep_cache = {}
    for family in sorted(families):
        members = families[family]
        movers = [e for e in members if e["major_target"] and not e["never_auto"]]
        if not movers:
            continue
        core = [e for e in members if not e["name"].startswith("@types/") and not e["never_auto"]]
        blocked = [e for e in core if e["blocked"] and not e["major_target"]]
        core_movers = [e for e in movers if not e["name"].startswith("@types/")]
        if blocked and core_movers:
            held_fams[family] = blocked[0]["blocked"]
            for e in movers:
                e["major_target"], e["blocked"] = None, e["blocked"] or "family %s held" % family
            continue
        if core_movers:
            lines = {line_of(parse_version(e["major_target"])) for e in core_movers}
            lagging = [e for e in core if e not in core_movers and e["locked"] and parse_version(e["locked"])
                       and line_of(parse_version(e["locked"])) not in lines and e["latest"] is not None
                       and family not in LOOSE_FAMILIES]
            target_line = max(lines)
            for e in movers:
                if e["name"].startswith("@types/") and line_of(parse_version(e["major_target"])) > target_line:
                    e["major_target"], e["blocked"] = None, "follows %s" % family
            movers = [e for e in movers if e["major_target"]]
            reason = "family incomplete: %s" % ", ".join(sorted({e["name"] for e in lagging})) if lagging else None
        else:
            keep = []
            for e in movers:
                pair = next((x for x in entries if x["name"] == types_target(e["name"])), None)
                pair_line = None
                if pair and parse_version(pair["locked"]):
                    pair_line = line_of(parse_version(pair["major_target"] or pair["locked"]))
                if e["name"] == "@types/node" or (pair_line and line_of(parse_version(e["major_target"])) <= pair_line):
                    keep.append(e)
                else:
                    e["blocked"] = "follows %s" % types_target(e["name"])
            movers, reason = keep, None
        if not movers:
            continue
        for e in movers:
            if e["name"] not in grep_cache:
                grep_cache[e["name"]] = import_count(s.g, e["name"])
            e["risk"] = min(5, base_risk(e) + (1 if grep_cache[e["name"]] >= 20 else 0))
        fam_vulns = [a for a in s.advisories if any(a["package"] == e["name"] and a["version"] == e["locked"] for e in movers)]
        closes = sorted({i for e in movers for i in closes_of(e["major_target"], [a for a in fam_vulns if a["package"] == e["name"]])})
        sev = max([SEVERITY.get(a["severity"], 0) for a in fam_vulns if a["id"] in closes] or [-1])
        majors.append({"family": family, "members": movers, "risk": max(e["risk"] for e in movers), "closes": closes,
                       "sev": sev, "reason": reason})
    s.runtime = runtime_view(s)
    if s.runtime["decision"] == "wave":
        majors = [f for f in majors if f["family"] != "runtime-node"] + [runtime_family(s, entries)]
    prioritize = [p for p in (args.prioritize or s.priority) if p]

    def order(f):
        names = [f["family"]] + [e["name"] for e in f["members"]]
        index = min([prioritize.index(n) for n in names if n in prioritize] or [len(prioritize)])
        return (-f["sev"], index, f["risk"], f["family"])
    majors.sort(key=order)
    ready = [f for f in majors if not f["reason"]]
    planned = ready[:s.max_majors]
    pending = [f for f in majors if f not in planned]
    for f in planned:
        for e in f["members"]:
            e["wave"], e["target"] = "major:" + f["family"], e["major_target"]
    for e in entries:
        if e["wave"] != "current":
            pass
        elif e["step"]:
            e["wave"], e["target"] = "patch-minor", e["step"]
        elif e["major_target"]:
            e["wave"] = "pending"
        elif e["blocked"]:
            e["wave"] = "held" if e["held_by"] else "pending"
        if e["target"]:
            e["bump_type"] = bump_type(e["locked"], e["target"])
            e["age_days"] = age_days((info.get(e["name"], {}).get("times") or {}).get(e["target"]), s.date)
        elif e["major_target"]:
            e["bump_type"] = "major"
        if e["risk"] is None and (e["step"] or e["major_target"]):
            e["risk"] = base_risk(e)
    s.entries, s.planned, s.pending, s.held_fams = entries, planned, pending, held_fams
    s.families = families
    return entries


def transitive_advisories(s, entries, steps):
    direct = {(e["name"], e["locked"]) for e in entries}
    out = []
    for a in s.advisories:
        if (a["package"], a["version"]) in direct:
            continue
        via = s.graph.direct_parents(a["package"], a["version"], s.roots)
        out.append(dict(a, via=via, fix=None, parent=None, parent_target=None, override=None))
    pairs = [(p, steps[p]) for t in out for p in t["via"] if steps.get(p)]
    manifests = collect_manifests(pairs, s.partial) if pairs and s.online else {}
    for t in out:
        found = parse_version(t["fixed_in"])
        for parent in t["via"]:
            target = steps.get(parent)
            spec = as_dict(as_dict(manifests.get((parent, target))).get("dependencies")).get(t["package"])
            low = range_min(spec) if spec else None
            if target and floor_closes(low, found, t["range"]):
                t["fix"], t["parent"], t["parent_target"] = "parent", parent, target
                break
        if t["fix"] is None:
            current = parse_version(t["version"])
            if found and current and line_of(found) == line_of(current):
                t["fix"], t["override"] = "override", "^" + vstr(found)
            else:
                t["fix"] = "para-ti"
    return sorted(out, key=lambda t: (-SEVERITY.get(t["severity"], 0), t["id"], t["package"], t["version"]))


def floor_closes(low, fixed, vulnerable):
    if not low:
        return False
    if fixed:
        return vkey(low) >= vkey(fixed)
    return satisfies(vstr(low), vulnerable or "") is False


# ---------------------------------------------------------------------------
# Runtime, CI and Docker alignment
# ---------------------------------------------------------------------------

NODE_TAG = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:-([\w.-]+))?$")


def split_source(source):
    """(kind, file) of a pin source: `.nvmrc` stays plain, `ci-image:<file>` splits once."""
    head, _, file = source.partition(":")
    return head, file or None


def node_image(image):
    return image in ("node", "library/node", "docker.io/library/node", "docker.io/node")


def tag_major(tag):
    m = NODE_TAG.match(tag or "")
    if not m:
        return None, "floating"
    return int(m.group(1)), "full" if m.group(2) is not None else "major"


def runtime_view(s):
    env, m = s.env, s.manifest
    major = env.get("pin_major")
    row = s.table.get(major) or {}
    shadow = m["runtimes"]["node"].get("shadowed_by")
    images = []
    for img in m["ci"]["images"]:
        if node_image(img["image"]) and img["role"] != "service":
            tmaj, shape = tag_major(img["tag"])
            images.append({"file": img["file"], "job": img["job"], "ref": "%s:%s" % (img["image"], img["tag"]),
                           "major": tmaj, "shape": shape, "aligned": major is not None and tmaj == major})
    deploy = sorted({"docker:" + d["file"] for d in m["docker"] if node_image(d["image"])})
    strict = any(n["keys"].get("engine-strict") is True for n in m["npmrc"])
    if strict and any(p["source"] == "engines.node" for p in m["runtimes"]["node"]["pins"]):
        deploy.append("engines.node (engine-strict)")
    for img in m["ci"]["images"]:
        if node_image(img["image"]) and img["job"] and re.search(r"deploy|release|publish", img["job"], re.I):
            deploy.append("ci:%s %s" % (img["file"], img["job"]))
    status = node_status(major, s.date, s.table) if major is not None else "unknown"
    lts = newest_lts(s.date, s.table)
    decision = "none"
    if status == "eol":
        decision = "para-ti" if shadow or not deploy or lts is None or lts <= (major or 0) else "wave"
    pins = [dict(zip(("kind", "file"), split_source(p["source"])), value=p["value"]) for p in m["runtimes"]["node"]["pins"]]
    return {"language": "node", "pin": env.get("node_pin"), "source": env.get("node_source"), "major": major, "pins": pins,
            "status": status, "eol": row.get("end"), "lts": row.get("lts"), "maintenance": row.get("maintenance"),
            "newest_lts": lts, "latest_in_major": s.node_latest.get(major) if major is not None else None,
            "table": s.table_source, "installed": env.get("node_version"), "shadowed_by": shadow, "ci": images,
            "deploy": unique(deploy), "decision": decision}


def runtime_family(s, entries):
    rt = s.runtime
    new = rt["newest_lts"]
    value = s.node_latest.get(new) or str(new)
    edits = []
    pin_value = rt["pin"] or ""
    if rt["source"] in (".nvmrc", ".node-version"):
        edits.append({"file": rt["source"], "key": "value", "from": pin_value,
                      "to": value if parse_version(pin_value.lstrip("v")) else str(new)})
    for d in s.manifest["docker"]:
        if node_image(d["image"]):
            tmaj, shape = tag_major(d["tag"])
            if tmaj is not None and tmaj != new:
                edits.append({"file": d["file"], "key": "line %d" % d["line"], "from": "%s:%s" % (d["image"], d["tag"]),
                              "to": "%s:%s" % (d["image"], re.sub(r"^v?\d+", str(new), d["tag"]))})
    for img in rt["ci"]:
        if img["major"] is not None and img["major"] != new:
            image, tag = img["ref"].rsplit(":", 1)
            edits.append({"file": img["file"], "key": "%s.image" % (img["job"] or "image"), "from": img["ref"],
                          "to": "%s:%s" % (image, re.sub(r"^v?\d+", str(new), tag))})
    if any(p["source"] == "engines.node" for p in s.manifest["runtimes"]["node"]["pins"]):
        edits.append({"file": "package.json", "key": "engines.node", "from": next(
            p["value"] for p in s.manifest["runtimes"]["node"]["pins"] if p["source"] == "engines.node"),
            "to": ">=%d" % new, "note": "manual"})
    members = []
    known = [parse_version(v) for v in as_dict(s.info.get("@types/node")).get("versions") or []]
    line = sorted((v for v in known if v and not v[3] and v[0] == new), key=vkey)
    for e in entries:
        if e["name"] == "@types/node" and not e["never_auto"]:
            e["major_target"] = vstr(line[-1]) if line else "%d.0.0" % new
            e["risk"] = 5
            members.append(e)
    return {"family": "runtime-node", "members": members, "risk": 5, "closes": [], "sev": -1, "reason": None,
            "edits": edits, "runtime": "node %s → %d" % (rt["major"], new)}


def ci_alignment(s):
    """Items for the CI line and the patch-minor edits: node images to the pin major, the Playwright image to the
    locked @playwright/test, the supabase CLI pin to the devDependency; everything else is manual."""
    m, rt = s.manifest, s.runtime
    major = rt["major"]
    by_name = {}
    for e in s.entries:
        by_name.setdefault(e["name"], e)
    items, edits, manual = [], [], []
    for img in m["ci"]["images"]:
        ref = "%s:%s" % (img["image"], img["tag"]) if img["tag"] else img["image"]
        where = img["job"] or "image"
        if img["role"] == "service":
            manual.append("%s %s service %s" % (img["file"], where, ref))
            continue
        if node_image(img["image"]):
            tmaj, shape = tag_major(img["tag"])
            if major is not None and tmaj is not None and tmaj != major:
                if shape == "major" and s.runtime["decision"] != "wave":
                    to = "%s:%s" % (img["image"], re.sub(r"^v?\d+", str(major), img["tag"]))
                    edits.append({"file": img["file"], "key": "%s.image" % where, "from": ref, "to": to, "note": "align"})
                    items.append("%s ≠ node %d" % (ref, major))
                else:
                    manual.append("%s %s %s (full-version tag)" % (img["file"], where, ref))
            elif shape == "floating" and img["tag"]:
                manual.append("%s %s %s (floating tag)" % (img["file"], where, ref))
            continue
        if img["image"].endswith("/playwright") and img["tag"]:
            mt = re.match(r"^v(\d+\.\d+\.\d+)(.*)$", img["tag"])
            pw = by_name.get("@playwright/test") or by_name.get("playwright")
            if mt and pw and pw["locked"]:
                target = pw["step"] if pw["wave"] == "patch-minor" or (pw["step"] and pw["wave"].startswith("major:")) else pw["locked"]
                if mt.group(1) != pw["locked"]:
                    items.append("%s:v%s ≠ %s %s" % (img["image"], mt.group(1), pw["name"], pw["locked"]))
                if mt.group(1) != target:
                    edits.append({"file": img["file"], "key": "%s.image" % where, "from": ref,
                                  "to": "%s:v%s%s" % (img["image"], target, mt.group(2)), "note": "align"})
            continue
        manual.append("%s %s base image %s" % (img["file"], where, ref))
    for d in m["docker"]:
        ref = "%s:%s" % (d["image"], d["tag"]) if d["tag"] else d["image"]
        if node_image(d["image"]):
            tmaj, shape = tag_major(d["tag"])
            if major is not None and tmaj is not None and tmaj != major and s.runtime["decision"] != "wave":
                if shape == "major":
                    edits.append({"file": d["file"], "key": "line %d" % d["line"], "from": ref,
                                  "to": "%s:%s" % (d["image"], re.sub(r"^v?\d+", str(major), d["tag"])), "note": "align"})
                    items.append("%s:%d %s ≠ node %d" % (d["file"], d["line"], ref, major))
                else:
                    manual.append("%s:%d %s (full-version tag)" % (d["file"], d["line"], ref))
        elif d["tag"] is not None or d["image"]:
            manual.append("%s:%d base image %s" % (d["file"], d["line"], ref))
    supa = by_name.get("supabase")
    for pin in m["ci"]["pins"]:
        if pin["kind"] == "supabase-cli" and supa and supa["locked"]:
            target = supa["step"] or supa["locked"]
            if pin["version"] != target:
                edits.append({"file": pin["file"], "key": "line %d" % pin["line"], "from": "supabase %s" % pin["version"],
                              "to": "supabase %s" % target, "note": "align"})
                items.append("%s:%d supabase %s ≠ devDependency %s" % (pin["file"], pin["line"], pin["version"], supa["locked"]))
        elif pin["kind"] == "pip":
            versions = [parse_version(v) for v in s.pypi.get(pin["name"], [])]
            cur = parse_version(pin["version"])
            same = [v for v in versions if v and cur and line_of(v) == line_of(cur) and vkey(v) > vkey(cur)]
            if same:
                edits.append({"file": pin["file"], "key": "line %d" % pin["line"], "from": "%s==%s" % (pin["name"], pin["version"]),
                              "to": "%s==%s" % (pin["name"], vstr(same[-1])), "note": "pypi"})
    manual.extend("%s action %s@%s" % (a["file"], a["uses"], a["ref"]) for a in m["ci"]["actions"])
    return items, edits, manual


# ---------------------------------------------------------------------------
# Shared state of preflight and plan
# ---------------------------------------------------------------------------

class State(object):
    pass


def empty_policy():
    return {"rules": [], "verification": [], "smoke": [], "delivery": {}, "review": [], "repo": None,
            "source_ref": None}


def gather(repo, args, schedule=True):
    s = State()
    s.repo, s.args = repo, args
    s.name = os.path.basename(os.path.realpath(repo))
    s.date = args.date
    s.online = not args.offline
    s.partial = {"offline"} if args.offline else set()
    s.review, s.para_ti = [], []
    s.manifest = dependency_manifest(repo)
    s.direct = sorted({e["name"] for e in s.manifest["packages"]})
    s.git, s.g = git_state(repo, s.online)
    if s.git is None:
        s.partial.add("git")
        s.g = None
    top = s.git["toplevel"] if s.git else None
    s.brain = find_brain(repo, top)
    s.ctx = find_context(repo, top, getattr(args, "context", None), getattr(args, "file", None))
    s.policy_label = os.path.basename(s.ctx["file"]) if s.ctx.get("file") else CONTEXT_FILE
    text = read_text(s.ctx["file"]) if s.ctx.get("file") else None
    s.policy = parse_policy(text, s.date, s.policy_label) if text is not None else empty_policy()
    s.table, s.node_latest, s.table_source = node_schedule(s.online and schedule, s.partial)
    s.env = resolve_node(s.manifest, nvm_dir(), s.date, s.table)
    s.env.update(check_pm(repo, s.manifest, s.env, args.offline))
    if s.env["pm_declared"] and s.env["pm_found"] in ("mismatch", "missing"):
        s.partial.add("pm-version")
    s.tenv = tool_env(s.env.get("node_bin"), args.offline)
    s.renovate = renovate_rules(s.manifest["bots"])
    handle, forge = (s.brain or {}).get("handle"), (s.brain or {}).get("forge")
    source = "brain" if handle else None
    if not handle:
        handle, forge = reviewer_of(delivery_value(s.policy, "reviewer"))
        source = s.policy_label if handle else None
    s.reviewer = {"handle": handle, "forge": forge, "source": source}
    expected = getattr(args, "expect_email", None) or delivery_value(s.policy, "commit identity")
    m = EMAIL.search(expected or "")
    s.expected = m.group(0) if m else None
    max_majors = getattr(args, "max_majors", None)
    if max_majors is None:
        d = re.match(r"^\d+$", delivery_value(s.policy, "max majors per run") or "")
        max_majors = int(d.group(0)) if d else DEFAULT_MAX_MAJORS
    s.max_majors = max_majors
    s.priority = [p.strip().strip("`") for p in (delivery_value(s.policy, "priority majors") or "").split(",") if p.strip()]
    s.default_min_age = s.renovate["min_age"] if s.renovate["min_age"] is not None else DEFAULT_MIN_AGE
    s.advisories, s.transitive, s.entries, s.planned, s.pending = [], [], [], [], []
    s.graph, s.roots, s.lock, s.pypi, s.info, s.eco = LockGraph(), {}, None, {}, {}, {}
    s.dropped = []
    return s


def identity_view(s):
    ident = (s.git or {}).get("identity") or {}
    email = ident.get("email")
    if not email:
        state = "unknown"
    elif s.expected:
        state = "ok" if email.lower() == s.expected.lower() else "mismatch"
    else:
        state = "ok" if ident.get("scope") in ("local", "worktree") else "unknown"
    return dict(ident, expected=s.expected, state=state)


def verification_view(s):
    m = s.manifest
    out = {k: dict(m["verification"][k]) for k in ("build", "typecheck", "lint", "test", "e2e")}
    overrides = []
    for row in s.policy["verification"]:
        step = row["step"]
        if step in out:
            out[step] = {"command": row["command"], "source": s.policy_label, "note": row["notes"] or None}
        overrides.append(row)
    out["ci"] = [dict(c) for c in m["verification"]["ci"]]
    out["overrides"] = overrides
    pkg = as_dict(read_json(os.path.join(s.repo, "package.json")))
    scripts = as_dict(pkg.get("scripts"))
    external = []
    commands = [(k, out[k]["command"]) for k in ("build", "typecheck", "lint", "test", "e2e") if out[k]["command"]]
    commands += [("ci", c["command"]) for c in out["ci"]]
    for step, command in commands:
        for path in external_paths(command, scripts):
            real = os.path.normpath(os.path.join(s.repo, path))
            item = {"step": step, "command": command, "path": path, "exists": os.path.exists(real)}
            if item not in external:
                external.append(item)
    out["external"] = external
    return out


def external_paths(command, scripts, depth=0):
    found = []
    for tok in re.split(r"[\s=:;|&()<>\"']+", command or ""):
        if (tok == os.pardir or tok.startswith(PARENT)) and tok not in found:
            found.append(tok)
    if depth < 3:
        for m in re.finditer(r"\b(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?([\w:.-]+)", command or ""):
            name = m.group(1)
            if name in scripts and isinstance(scripts[name], str):
                found.extend(p for p in external_paths(scripts[name], scripts, depth + 1) if p not in found)
    return found


def smoke_view(s, routes_arg):
    rows = s.policy["smoke"]
    if rows:
        routes, source = [dict(r) for r in rows], s.policy_label
    elif routes_arg == "none":
        routes, source = [], "none"
    elif routes_arg == "auto":
        found = auto_routes(s.repo)
        if found is None:
            s.partial.add("routes")
            routes, source = [{"route": "/", "name": "home", "mask": ""}], "default"
        else:
            routes, source = [{"route": r, "name": "home" if r == "/" else r.strip("/"), "mask": ""} for r in found], "auto"
    else:
        routes, source = [{"route": "/", "name": "home", "mask": ""}], "default"
    return {"source": source, "routes": routes, "server": delivery_value(s.policy, "server"),
            "shot_command": delivery_value(s.policy, "shot command"), "node_pin": s.env.get("node_version") or s.env.get("node_pin")}


ASSET = re.compile(r"^/(?:static|assets|public|images|img|css|js|fonts|media|favicon)(?:/|$)|\.[A-Za-z0-9]{1,5}$")


def auto_routes(repo):
    try:
        from pathlib import Path
        import scan_project
        result = scan_project.ProjectScanner(Path(repo)).scan()
        endpoints = result["api_surface"]["endpoints"]
    except Exception:
        return None
    picked = []
    for e in endpoints:
        path = str(e.get("path") or "")
        if str(e.get("method")).upper() not in ("GET", "ANY", "ALL") or not path.startswith("/") or path == "/":
            continue
        if any(ch in path for ch in ":{[*(") or re.match(r"^/(?:api|health)(?:/|$)", path) or ASSET.search(path):
            continue
        if path not in picked:
            picked.append(path)
        if len(picked) == 3:
            break
    return ["/"] + picked


# ---------------------------------------------------------------------------
# Waves: commands and edits
# ---------------------------------------------------------------------------

def new_spec(declared, target, exact):
    op = range_operator(declared)
    if exact or op == "":
        return target
    if op in ("^", "~"):
        return op + target
    return None


def catalog_key(e):
    return "catalog.%s" % e["name"] if e["catalog"] in (None, "default") else "catalogs.%s.%s" % (e["catalog"], e["name"])


def requirement_file(s, name):
    for rel in sorted(f for f in os.listdir(s.repo) if fnmatch.fnmatchcase(f, "requirements*.txt")):
        for line in (read_text(os.path.join(s.repo, rel)) or "").splitlines():
            if re.match(r"^%s\s*(?:\[[^\]]*\])?\s*==" % re.escape(name), line.strip(), re.I):
                return rel
    return "pyproject.toml" if os.path.isfile(os.path.join(s.repo, "pyproject.toml")) else "requirements.txt"


NPM_NAME = re.compile(r"^(@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*$")
COMPOSER_NAME = re.compile(r"^[a-z0-9]([_.-]?[a-z0-9]+)*/[a-z0-9](([_.]|-{1,2})?[a-z0-9]+)*$")
WORKSPACE_PATH = re.compile(r"^[A-Za-z0-9._/-]+$")


def unsafe_token(e, eco):
    """(why, token) when the name or workspace of an entry may not go into a shell command, else None."""
    if eco == "composer" and not COMPOSER_NAME.match(e["name"]):
        return "not a valid composer package name", e["name"]
    if eco == "node" and not NPM_NAME.match(e["name"]):
        return "not a valid npm package name", e["name"]
    ws = e["workspace"]
    if ws != "." and (not WORKSPACE_PATH.match(ws) or os.pardir in ws.split("/")):
        return "not a valid workspace path", ws
    return None


def safe_moves(s, moves, wave_id):
    """The moves whose package name and workspace path pass the strict patterns; each other one leaves the
    wave, is held and gets one review line."""
    keep = []
    for e, target in moves:
        why = unsafe_token(e, s.eco.get((e["name"], e["workspace"]), "node"))
        if why is None:
            keep.append((e, target))
            continue
        line = "review: %r dropped from %s: %s" % (why[1], wave_id, why[0])
        if line not in s.dropped:
            s.dropped.append(line)
        e.update(wave="held", target=None, bump_type="none", age_days=None, blocked="%s (dropped)" % why[0])
    return keep


def wave_commands(s, moves):
    """[{cwd, run}] and [{file, key, from, to}] that move each package to its target."""
    pm = s.manifest["package_manager"]["name"]
    node_pm = pm if pm in ("npm", "pnpm", "yarn", "bun") else "npm"
    workspace_file = os.path.isfile(os.path.join(s.repo, "pnpm-workspace.yaml"))
    groups, edits, catalog = {}, [], {}
    catalogs = s.manifest["catalogs"]
    for e, target in moves:
        eco = s.eco.get((e["name"], e["workspace"]), "node")
        if eco == "python":
            edits.append({"file": requirement_file(s, e["name"]), "key": e["name"], "from": e["declared"],
                          "to": "==" + target, "note": "pin"})
            continue
        if e["style"] == "catalog":
            entry = as_dict(as_dict(catalogs.get(e["catalog"] or "default")).get(e["name"]))
            spec = new_spec(entry.get("spec"), target, e["pin"])
            catalog[catalog_key(e)] = {"file": "pnpm-workspace.yaml", "key": catalog_key(e), "from": entry.get("spec"),
                                       "to": spec or target}
            continue
        exact = e["pin"] or range_operator(e["declared"]) == ""
        spec = new_spec(e["declared"], target, e["pin"])
        if spec is None:
            field = {"prod": "dependencies", "dev": "devDependencies", "peer": "peerDependencies",
                     "optional": "optionalDependencies"}.get(e["kind"], "dependencies")
            edits.append({"file": "package.json" if e["workspace"] == "." else e["workspace"] + "/package.json",
                          "key": "%s.%s" % (field, e["name"]), "from": e["declared"], "to": ">=" + target, "note": "manual"})
            continue
        groups.setdefault((eco, e["workspace"], e["kind"], exact), []).append("%s@%s" % (e["name"], spec))
    commands = []
    q = shlex.quote
    for (eco, ws, kind, exact), specs in sorted(groups.items(), key=lambda kv: (
            kv[0][0], kv[0][1] != ".", kv[0][1], KIND_ORDER.get(kv[0][2], 9), kv[0][3])):
        specs = sorted(set(specs))
        quoted = " ".join(q(x) for x in specs)
        tool = "composer" if eco == "composer" else node_pm
        if tool == "pnpm":
            where = ("pnpm add -w" if workspace_file else "pnpm add") if ws == "." else "pnpm --filter %s add" % q("./" + ws)
            flag = {"dev": " -D", "optional": " -O", "peer": " --save-peer"}.get(kind, "")
            run = "%s%s%s %s" % (where, flag, " --save-exact" if exact else "", quoted)
        elif tool == "composer":
            pairs = [x.rsplit("@", 1) for x in specs]
            run = "composer require%s %s --no-update && composer update %s --with-dependencies" % (
                " --dev" if kind == "dev" else "", " ".join(q("%s:%s" % (n, v)) for n, v in pairs),
                " ".join(q(n) for n in sorted(n for n, _ in pairs)))
        elif tool == "npm":
            run = "npm install %s%s%s %s" % (SAVE_FLAG.get(kind, "--save-prod"), " --save-exact" if exact else "",
                                            "" if ws == "." else " --workspace " + q(ws), quoted)
        else:
            edits.extend({"file": "package.json", "key": x.rsplit("@", 1)[0], "from": None, "to": x.rsplit("@", 1)[1],
                          "note": "manual (%s)" % tool} for x in specs)
            continue
        commands.append({"cwd": ".", "run": run})
    edits.extend(catalog[k] for k in sorted(catalog))
    if catalog:
        commands.append(install_cmd("pnpm"))
    return commands, edits


def override_edits(s, items):
    pm = s.manifest["package_manager"]["name"]
    existing = {o["name"]: o for o in s.manifest["overrides"]}
    best = {}
    for t in items:
        if t["fix"] == "override":
            cur = best.get(t["package"])
            if cur is None or vkey(parse_version(t["override"][1:])) > vkey(parse_version(cur[1:])):
                best[t["package"]] = t["override"]
    edits = []
    for name in sorted(best):
        if pm == "pnpm":
            file, key = ("pnpm-workspace.yaml", "overrides.%s" % name) if os.path.isfile(
                os.path.join(s.repo, "pnpm-workspace.yaml")) else ("package.json", "pnpm.overrides.%s" % name)
        elif pm == "yarn":
            file, key = "package.json", "resolutions.%s" % name
        else:
            file, key = "package.json", "overrides.%s" % name
        edits.append({"file": file, "key": key, "from": (existing.get(name) or {}).get("spec"), "to": best[name],
                      "note": "override"})
    return edits


def install_cmd(pm):
    return {"cwd": ".", "run": {"pnpm": "pnpm install", "yarn": "yarn install", "bun": "bun install"}.get(pm, "npm install")}


def build_waves(s):
    date = s.date
    pm = s.manifest["package_manager"]["name"]
    pm_moves = [(e, e["step"]) for e in s.entries if e["step"] and not e["never_auto"] and e["wave"] != "held"]
    pm_moves = safe_moves(s, pm_moves, "patch-minor")
    kept = {e["name"] for e, _ in pm_moves}
    items, ci_edits, manual = ci_alignment(s)
    s.ci_items, s.ci_manual = items, manual
    ov_edits = override_edits(s, s.transitive)
    waves = []
    default = (s.git or {}).get("default_branch") or "main"
    if pm_moves or ci_edits or ov_edits:
        commands, edits = wave_commands(s, pm_moves)
        edits = edits + ci_edits + ov_edits
        if ov_edits and install_cmd(pm) not in commands:
            commands.append(install_cmd(pm))
        closes = set()
        for e, target in pm_moves:
            closes.update(closes_of(target, e["advisories"]))
        closes.update(t["id"] for t in s.transitive if t["fix"] == "override" or (t["fix"] == "parent" and t["parent"] in kept))
        waves.append({"id": "patch-minor", "branch": "deps/%s-patch-minor" % date, "base": default,
                      "packages": sorted({e["name"] for e, _ in pm_moves}),
                      "from_to": [{"name": e["name"], "workspace": e["workspace"], "kind": e["kind"], "from": e["locked"],
                                   "to": t} for e, t in sorted(pm_moves, key=lambda x: (
                                       KIND_ORDER.get(x[0]["kind"], 9), x[0]["name"], x[0]["workspace"]))],
                      "commands": commands, "edits": edits, "closes": sorted(closes),
                      "risk": max([e["risk"] or 1 for e, _ in pm_moves] or [1]), "migration_refs": []})
    refs = {}
    pairs = [(e["name"], e["major_target"]) for f in s.planned for e in f["members"] if e["major_target"]]
    if s.online and pairs:
        refs = collect_refs(s.repo, pairs, s.tenv, s.partial)
    base = waves[-1]["branch"] if waves else default
    planned = []
    for f in s.planned:
        moves = safe_moves(s, [(e, e["major_target"]) for e in f["members"]], "major:" + f["family"])
        if not moves and not f.get("edits"):
            continue
        planned.append(f)
        commands, edits = wave_commands(s, moves)
        edits = edits + f.get("edits", [])
        if f.get("edits") and not commands:
            commands = [install_cmd(pm)]
        branch = "deps/%s-major-%s" % (date, slug(f["family"]))
        mig = unique([u for e in f["members"] for u in refs.get(e["name"], [])])
        if f["family"] in MIGRATION_FAMILIES:
            mig.append(MIGRATION_FAMILIES[f["family"]])
        waves.append({"id": "major:" + f["family"], "branch": branch, "base": base,
                      "packages": sorted({e["name"] for e, _ in moves}),
                      "from_to": [{"name": e["name"], "workspace": e["workspace"], "kind": e["kind"],
                                   "from": e["step"] or e["locked"], "to": t}
                                  for e, t in sorted(moves, key=lambda x: (x[0]["name"], x[0]["workspace"]))],
                      "commands": commands, "edits": edits, "closes": f["closes"], "risk": f["risk"],
                      "migration_refs": mig})
        base = branch
    s.planned = planned
    return waves


# ---------------------------------------------------------------------------
# The plan: assembly, digest and verdict
# ---------------------------------------------------------------------------

def scratch_levels(s, arg):
    """The scratch dirs a run uses, outermost first: --scratch DIR alone, else the default root, the repo
    folder and the run dir."""
    if arg:
        return [os.path.abspath(os.path.expanduser(arg))]
    root = os.path.join(tempfile.gettempdir(), "deps-renovate")
    return [root, os.path.join(root, s.name), os.path.join(root, s.name, run_id(s.date, s.git))]


def holds_view(s):
    seen, out = set(), []
    for e in s.entries:
        hold = e["held_by"]
        if hold and hold["rule"] in ("hold", "cap", "hold-major") and e["name"] not in seen:
            seen.add(e["name"])
            out.append({"name": e["name"], "rule": hold["rule"], "value": hold["value"], "source": hold["source"],
                        "blocked": e["blocked"]})
    return sorted(out, key=lambda h: (HOLD_ORDER.get(h["rule"], 9), h["name"]))


def never_auto_view(s):
    seen, out = set(), []
    shadow = as_dict(s.manifest["runtimes"]["node"].get("shadowed_by"))
    for e in s.entries:
        if e["never_auto"] and e["name"] not in seen:
            seen.add(e["name"])
            if shadow.get("package") == e["name"]:
                reason = "npm binary package that shadows the runtime for npm scripts (node_modules/.bin/node)"
            elif e["name"] in NEVER_AUTO:
                reason = "toolchain binary declared as a dependency"
            else:
                reason = "never-auto rule (%s)" % (e["held_by"] or {}).get("source", s.policy_label)
            out.append({"name": e["name"], "declared": e["declared"], "locked": e["locked"], "reason": reason,
                        "source": (e["held_by"] or {}).get("source")})
    return sorted(out, key=lambda n: n["name"])


def pending_view(s):
    out = {}
    for f in s.pending:
        reason = f["reason"] or "cap %d majors per run" % s.max_majors
        for e in f["members"]:
            row = out.setdefault((e["name"], e["step"] or e["locked"], e["major_target"]), {
                "name": e["name"], "family": f["family"], "from": e["step"] or e["locked"], "to": e["major_target"],
                "reason": reason, "workspaces": []})
            row["workspaces"].append(e["workspace"])
    names = {k[0] for k in out}
    for e in s.entries:
        if e["wave"] == "pending" and e["name"] not in names and e["major_target"] is None and e["blocked"]:
            row = out.setdefault((e["name"], e["locked"], None), {"name": e["name"], "family": e["family"], "from": e["locked"],
                                                                  "to": None, "reason": e["blocked"], "workspaces": []})
            row["workspaces"].append(e["workspace"])
    return list(out.values())


def counts_view(s, waves, holds, never):
    pm_wave = next((w for w in waves if w["id"] == "patch-minor"), None)
    moved = [e for e in s.entries if e["wave"] in ("patch-minor", "pending") or e["wave"].startswith("major:")]
    ids = {a["id"] for a in s.advisories}
    names = {f["name"] for f in (pm_wave or {}).get("from_to", [])}
    prod = {f["name"] for f in (pm_wave or {}).get("from_to", []) if f["kind"] == "prod"}
    return {"packages": len({e["name"] for e in s.entries}), "outdated": len({e["name"] for e in moved}),
            "patch_minor": len(names), "prod": len(prod), "dev": len(names - prod),
            "edits": len((pm_wave or {}).get("edits", [])),
            "majors": len(s.planned) + len(s.pending), "majors_this_run": len(s.planned),
            "pending_majors": len(s.pending), "advisories": len(ids),
            "advisories_closed": len({i for w in waves for i in w["closes"]}),
            "holds": len(holds), "never_auto": len(never)}


def para_ti_view(s, never, waves):
    out = []
    for n in never:
        out.append("%s %s (locked %s) — never-auto: %s — owner decision" % (n["name"], n["declared"], n["locked"], n["reason"]))
    rt = s.runtime
    if rt["status"] == "eol" and rt["decision"] != "wave":
        if rt["shadowed_by"]:
            why = "%s shadows the runtime: deciding on it comes first" % rt["shadowed_by"]["package"]
        elif not rt["deploy"]:
            why = "deploy runtime not declared in the repo"
        else:
            why = "declared in %s" % ", ".join(rt["deploy"])
        out.append("runtime node %s (%s) — eol %s; %s — owner decision (newest LTS %s)" % (
            rt["pin"], rt["source"], rt["eol"], why, rt["newest_lts"]))
    for t in s.transitive:
        if t["fix"] == "para-ti":
            out.append("%s %s %s@%s via %s — no fix in the same major — owner decision" % (
                t["id"], t["severity"], t["package"], t["version"], ", ".join(t["via"]) or "unknown parent"))
    if s.pending:
        out.append("majors pending (%s): %s" % ("cap %d per run" % s.max_majors, ", ".join(unique(
            "%s %s→%s" % (e["name"], e["step"] or e["locked"], e["major_target"]) for f in s.pending for e in f["members"]))))
    for item in verification_view(s)["external"]:
        if not item["exists"]:
            out.append("verification needs %s (%s): check it out next to the repo" % (item["path"], item["step"]))
    if s.env["pm_declared"] and s.env["pm_found"] != "ok":
        out.append("packageManager %s@%s but `%s --version` printed %s under %s — fix corepack or the PATH" % (
            s.env["pm"], s.env["pm_declared"], s.env["pm"], s.env["pm_version"] or "nothing",
            s.env["path_prefix"] or "the default PATH"))
    return out


def step_rank(step):
    return STEP_ORDER.index(step) if step in STEP_ORDER else 99


def review_lines(s, extra=()):
    out = []
    if "offline" in s.partial:
        out.append("review: offline: registry, advisory, schedule and MR lookups skipped (Node table %s)" % LTS_DATE)
    for step in sorted(s.partial - {"offline"}, key=step_rank):
        out.append("review: partial(%s): %s" % (step, {
            "git": "not a git repo: base, branches and identity unknown",
            "pm-version": "the package-manager version does not match packageManager",
            "outdated": "outdated returned no JSON or timed out",
            "release-age": "release times unavailable",
            "audit": "the bulk advisory POST failed",
            "registry": "registry manifests unavailable",
            "node-schedule": "Node schedule unavailable, embedded table used",
            "pypi": "PyPI lookups failed", "composer": "composer outdated failed",
            "mr-list": "glab mr list failed", "routes": "the cpcg scanner is unavailable",
            "migration-refs": "migration references unavailable"}.get(step, step)))
    out.extend(s.dropped)
    out.extend(s.policy["review"])
    out.extend(s.renovate["review"])
    out.extend(extra)
    for note in s.manifest["notes"]:
        out.append("review: manifest: %s" % note)
    return out


def plan_lines(s, waves, counts, holds, never, scratch_line, review):
    m, env, rt = s.manifest, s.env, s.runtime
    lock = next((l for l in m["lockfiles"] if "/" not in l["path"]), None)
    pmver = env.get("pm_version") or env.get("pm_declared") or "?"
    head = "DEPS %s · %s %s (%s) · base %s · date %s" % (
        s.name, m["package_manager"]["name"] or "none", pmver,
        "%s v%s" % (lock["path"], lock["version"]) if lock else "no lockfile",
        (s.git or {}).get("base_ref") or "none", s.date)
    if rt["pin"]:
        status = "eol %s" % rt["eol"] if rt["status"] == "eol" else "%s · EOL %s" % (rt["status"], rt["eol"] or "?")
        node_ci = "none"
        if rt["ci"]:
            node_ci = "%s %s" % (rt["ci"][0]["ref"], "aligned" if all(i["aligned"] for i in rt["ci"]) else "mismatch")
        runtime = "RUNTIME node %s (%s) · %s · newest LTS %s · CI %s" % (
            rt["pin"], rt["source"], status, rt["newest_lts"] or "?", node_ci)
    else:
        runtime = "RUNTIME node none (no pin) · newest LTS %s" % (rt["newest_lts"] or "?")
    if rt["shadowed_by"]:
        runtime += " · SHADOWED by %s@%s" % (rt["shadowed_by"]["package"], rt["shadowed_by"]["locked"] or rt["shadowed_by"]["declared"])
    ctx = s.ctx
    if ctx["state"] in ("ambiguous", "bad"):
        where = ctx["state"]
    else:
        where = os.path.basename(ctx["skill"]) if ctx.get("skill") else "none"
    context = "CONTEXT %s · %s %s · policy rules %d" % (where, s.policy_label, "found" if ctx.get("file") else "missing",
                                                      len(s.policy["rules"]))
    ver = verification_view(s)

    def step(k):
        v = ver[k]
        return v["command"] or ("n/a (placeholder)" if v["note"] == "placeholder" else "n/a")
    ci_cmds = unique(c["command"] for c in ver["ci"])
    verify = "VERIFY " + " · ".join("%s=%s" % (k, step(k)) for k in ("build", "typecheck", "lint", "test", "e2e"))
    verify += " · ci=%s" % (", ".join(ci_cmds[:3]) + (" +%d" % (len(ci_cmds) - 3) if len(ci_cmds) > 3 else "") if ci_cmds else "n/a")
    pm_wave = next((w for w in waves if w["id"] == "patch-minor"), None)
    wave_head = "WAVE patch-minor %d (prod %d · dev %d) · closes %s" % (
        counts["patch_minor"], counts["prod"], counts["dev"], plural(len(pm_wave["closes"]) if pm_wave else 0, "advisory"))
    if pm_wave and pm_wave["edits"]:
        wave_head += " · edits %d" % len(pm_wave["edits"])
    rows = []
    if pm_wave:
        merged = {}
        for f in pm_wave["from_to"]:
            merged.setdefault((f["name"], f["from"], f["to"], f["kind"]), []).append(f["workspace"])
        rows = ["  %s %s→%s [%s%s]" % (k[0], k[1], k[2], k[3], " · %d workspaces" % len(ws) if len(ws) > 1 else "")
                for k, ws in merged.items()]
        rows += ["  %s %s %s→%s [%s]" % (x["file"], x["key"], short_ref(x["from"]), short_ref(x["to"]), x.get("note") or "edit")
                 for x in pm_wave["edits"]]
    major_items = [major_item(w, rt) for w in waves if w["id"].startswith("major:")]
    major_line = "MAJORS %d (this run %d of cap %d)%s · pending %d" % (
        counts["majors"], counts["majors_this_run"], s.max_majors,
        (": " + ", ".join(major_items[:5]) + (" +%d" % (len(major_items) - 5) if len(major_items) > 5 else "")) if major_items else "",
        counts["pending_majors"])
    adv = unique("%s %s %s → %s" % (a["id"], a["severity"], a["package"], advisory_fix(s, a)) for a in s.advisories)
    hold_items = ["%s %s" % (h["name"], hold_text(h)) for h in holds]
    never_items = ["%s %s" % (n["name"], n["declared"]) for n in never]
    ci_line = "CI images %d%s · actions %d manual · docker %d" % (
        len(m["ci"]["images"]), " (%s)" % ", ".join(s.ci_items[:3]) + (" +%d" % (len(s.ci_items) - 3) if len(s.ci_items) > 3 else "")
        if s.ci_items else "", len(m["ci"]["actions"]), len(m["docker"]))
    verdict = plan_verdict(s, counts)[0]

    def render(n_rows, n_adv, n_hold, n_review):
        shown = rows[:n_rows] + (["  … +%d more (use --json)" % (len(rows) - n_rows)] if len(rows) > n_rows else [])
        lines = [head, runtime, context, verify, wave_head] + shown + [major_line]
        lines.append("ADVISORIES %d%s" % (len({a["id"] for a in s.advisories}), inline(adv, n_adv)))
        lines.append("HOLDS %d%s" % (len(holds), inline(hold_items, n_hold)))
        lines.append("NEVER-AUTO %d%s" % (len(never), inline(never_items, 3, " → Para ti")))
        lines.append(ci_line)
        if scratch_line:
            lines.append(scratch_line)
        lines += review[:n_review] + (["review: … +%d more (use --json)" % (len(review) - n_review)] if len(review) > n_review else [])
        return lines + [verdict]
    limits = [12, 4, 3, 3]
    lines = render(*limits)
    for i in range(4):
        while len(lines) > MAX_LINES and limits[i] > 0:
            limits[i] -= 1
            lines = render(*limits)
    return lines


def advisory_fix(s, a):
    fix = next((t for t in s.transitive if t["id"] == a["id"] and t["package"] == a["package"] and t["version"] == a["version"]), None)
    if fix:
        if fix["fix"] == "parent":
            return "%s %s" % (fix["parent"], fix["parent_target"])
        if fix["fix"] == "override":
            return "override %s" % fix["override"]
        return "Para ti"
    e = next((e for e in s.entries if e["name"] == a["package"] and e["locked"] == a["version"]), None)
    if e and e["target"] and a["id"] in closes_of(e["target"], [a]):
        return "%s %s" % (a["package"], e["target"])
    return "fixed in %s" % a["fixed_in"] if a["fixed_in"] else "no fix known"


def major_item(w, rt):
    family = w["id"].split(":", 1)[1]
    if family == "runtime-node":
        return "runtime node %s→%s" % (rt["major"], rt["newest_lts"])
    moves = unique((f["name"], f["from"], f["to"]) for f in w["from_to"])
    if len(moves) == 1 and moves[0][0] == family:
        return "%s %s→%s" % moves[0]
    shown = ", ".join("%s %s→%s" % m for m in moves[:2]) + (" +%d" % (len(moves) - 2) if len(moves) > 2 else "")
    return "%s: %s" % (family, shown)


def inline(items, n, suffix=""):
    if not items:
        return ""
    shown = items[:n]
    text = ": " + ", ".join(shown) if shown else ""
    if len(items) > n:
        text += (" " if shown else ": ") + "+%d more" % (len(items) - n)
    return text + (suffix if shown else "")


def short_ref(ref):
    if not ref:
        return "none"
    ref = str(ref)
    return ref.rsplit(":", 1)[1] if ":" in ref and "/" in ref.split(":", 1)[0] else ref


def plan_verdict(s, counts):
    tail = "outdated(%d) majors(%d) advisories(%d) holds(%d)" % (counts["outdated"], counts["majors"],
                                                                 counts["advisories"], counts["holds"])
    if counts["never_auto"]:
        tail += " never-auto(%d)" % counts["never_auto"]
    if s.runtime["status"] == "eol":
        tail += " runtime(eol)"
    if s.partial:
        steps = sorted(s.partial, key=step_rank)
        return "DEPS: partial(%s) %s" % (",".join(steps), tail), 1
    work = counts["outdated"] or counts["majors"] or counts["advisories"] or counts["edits"] or s.runtime["status"] == "eol"
    return ("DEPS: " + tail, 1) if work else ("DEPS: current", 0)


def plan_skeleton(repo, date, version):
    data = {k: None for k in PLAN_KEYS}
    data.update(tool="deps-check", version=version, command="plan",
                repo={"name": os.path.basename(os.path.abspath(repo)), "path": os.path.abspath(repo)},
                date=date, state="unparsed", partial=[], packages=[], transitive_advisories=[], families=[], docker=[],
                waves=[], pending_majors=[], holds=[], never_auto=[], para_ti=[], counts={}, review=[], text=[])
    return data


def canonical_plan(data):
    return json.dumps({k: v for k, v in data.items() if k != "text"}, ensure_ascii=False, indent=2, sort_keys=True)


def run_plan(args):
    repo = os.path.abspath(os.path.expanduser(args.repo))
    version = tool_version()
    data = plan_skeleton(repo, args.date, version)

    def fail(reason):
        return emit(args, data, ["DEPS %s" % home_short(repo), "DEPS: unparsed (%s)" % reason], 2)
    if dependency_manifest is None:
        return fail("dependency_manifest module not found next to the code-project-context-generator skill")
    if not os.path.isdir(repo):
        return fail("repo not found: %s" % repo)
    s = gather(repo, args)
    m = s.manifest
    if m["package_manager"]["name"] is None and not m["packages"]:
        return fail("no dependency manifest in %s" % home_short(repo))
    plan_packages(s, args)
    waves = build_waves(s)
    holds, never = holds_view(s), never_auto_view(s)
    counts = counts_view(s, waves, holds, never)
    smoke = smoke_view(s, args.routes)
    levels = scratch_levels(s, args.scratch)
    scratch = levels[-1]
    plan_path = os.path.join(scratch, "plan.json")
    bad = scratch_problem(levels)
    if bad:
        return fail("scratch dir not private: %s" % home_short(bad))
    extra = []
    git = s.git or {}
    if git.get("branch") and git.get("default_branch") and git["branch"] != git["default_branch"]:
        extra.append("review: on branch %s, not the default %s — the plan reads the working tree" % (git["branch"], git["default_branch"]))
    if git.get("local_branches"):
        extra.append("review: local-branches %s" % ", ".join(git["local_branches"][:3]))
    if s.ci_manual:
        extra.append("review: CI manual %d (%s)" % (len(s.ci_manual), "; ".join(s.ci_manual[:2]) + (" …" if len(s.ci_manual) > 2 else "")))
    unknown_age = [e["name"] for e in s.entries if e["target"] and e["age_days"] is None and s.online]
    if unknown_age:
        extra.append("review: release age unknown for %s" % plural(len(set(unknown_age)), "package"))
    if s.ctx["state"] == "ambiguous":
        extra.append("review: context-ambiguous: %s — pass --context" % ", ".join(os.path.basename(c) for c in s.ctx["candidates"]))
    para = para_ti_view(s, never, waves)
    review = review_lines(s, extra)
    _, code = plan_verdict(s, counts)
    families = [{"family": f, "members": sorted({e["name"] for e in members}),
                 "risk": max([e["risk"] or 1 for e in members] or [1]),
                 "held": s.held_fams.get(f)} for f, members in sorted(s.families.items())
                if len({e["name"] for e in members}) > 1 or any(e["major_target"] or e["wave"].startswith("major:") for e in members)]
    data.update({
        "state": "partial" if s.partial else ("current" if code == 0 else "needed"),
        "partial": sorted(s.partial, key=step_rank),
        "git": s.git, "brain": s.brain,
        "context": dict(s.ctx, policy_rules=len(s.policy["rules"]), delivery=s.policy["delivery"], label=s.policy_label,
                        reviewer=s.reviewer, expected_identity=s.expected, scratch=scratch),
        "env": s.env, "manifest": m,
        "runtimes": {"node": s.runtime, "python": m["runtimes"]["python"], "php": m["runtimes"]["php"],
                     "deno": m["runtimes"]["deno"]},
        "packages": [{k: e[k] for k in ("name", "workspace", "kind", "declared", "locked", "wanted", "latest",
                                        "latest_in_major", "target", "bump_type", "advisories", "held_by", "never_auto",
                                        "family", "risk", "age_days", "wave", "step", "major_target", "style",
                                        "catalog", "pin", "blocked")} for e in s.entries],
        "transitive_advisories": s.transitive, "families": families,
        "ci": {"provider": m["ci"]["provider"], "mr_pipelines": m["ci"]["mr_pipelines"], "items": s.ci_items,
               "manual": s.ci_manual, "images": m["ci"]["images"],
               "actions": [dict(a, latest="manual") for a in m["ci"]["actions"]], "pins": m["ci"]["pins"]},
        "docker": m["docker"], "verification": verification_view(s), "smoke": smoke, "waves": waves,
        "pending_majors": pending_view(s), "holds": holds, "never_auto": never, "para_ti": para, "counts": counts,
        "review": review})
    body = canonical_plan(data)
    old = read_json(plan_path)
    if args.write:
        scratch_line = "PLAN written %s" % home_short(plan_path)
    else:
        added, removed = diff_counts(canonical_plan(old) if isinstance(old, dict) else None, body)
        scratch_line = "PLAN would write %s (+%d -%d)" % (home_short(plan_path), added, removed)
    lines = plan_lines(s, waves, counts, holds, never, scratch_line, review)
    data["text"] = lines
    if args.write:
        bad = make_private(levels)
        if bad:
            return fail("scratch dir not private: %s" % home_short(bad))
        write_file(plan_path, json.dumps(data, ensure_ascii=False, indent=2) + "\n", private=True)
    return emit(args, data, lines, code)


# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------

def run_preflight(args):
    repo = os.path.abspath(os.path.expanduser(args.repo))
    base = {"tool": "deps-check", "version": tool_version(), "command": "preflight",
            "repo": {"name": os.path.basename(repo), "path": repo}, "date": args.date, "state": "unparsed",
            "blockers": []}

    def fail(reason):
        return emit(args, base, ["PREFLIGHT %s" % home_short(repo), "PREFLIGHT: unparsed (%s)" % reason], 2)
    if dependency_manifest is None:
        return fail("dependency_manifest module not found next to the code-project-context-generator skill")
    if not os.path.isdir(repo):
        return fail("repo not found: %s" % repo)
    s = gather(repo, args, schedule=False)
    if s.git is None:
        return fail("not a git repo")
    if s.manifest["package_manager"]["name"] is None and not s.manifest["packages"]:
        return fail("no dependency manifest")
    git, env, blockers, para, review = s.git, s.env, [], [], []
    ident = identity_view(s)
    who = "<the repo identity>" if not s.expected else shlex.quote(s.expected)
    if ident["state"] != "ok":
        blockers.append("identity")
        para.append("Para ti: git -C %s config user.email %s" % (shell_path(repo), who))
    if not ident["email"]:
        id_desc = "user.email not set"
    elif ident["inherited_from_global"]:
        id_desc = "user.email inherited from global (%s)" % (ident["origin"] or ident["scope"])
    else:
        id_desc = "user.email %s" % ("repo-local" if ident["scope"] in ("local", "worktree") else ident["scope"] or "set")
    if ident["state"] == "mismatch":
        id_desc += " ≠ expected"
    id_line = "IDENTITY %s · expected %s → %s" % (id_desc, s.expected or "unknown", "ok" if ident["state"] == "ok" else "blocked")
    rev = s.reviewer
    if rev["handle"]:
        where = ("%s:%s" % (home_short(s.brain["file"]), s.brain["line"])) if rev["source"] == "brain" else rev["source"]
        rev_line = "REVIEWER %s %s → ok" % (where, reviewer_text(rev))
    else:
        blockers.append("reviewer")
        if s.brain and s.brain.get("line"):
            value = s.brain["value"] if len(s.brain["value"]) <= 60 else s.brain["value"][:59] + "…"
            rev_line = "REVIEWER brain %s:%d \"%s\" · no @handle → blocked" % (home_short(s.brain["file"]), s.brain["line"], value)
        elif s.brain:
            rev_line = "REVIEWER brain %s · no Reviewer line → blocked" % home_short(s.brain["file"])
        else:
            rev_line = "REVIEWER no brain and no Delivery Reviewer → blocked"
        para.append("Para ti: the Reviewer @handle (gitlab|github): the brain Reviewer line or `- Reviewer: @handle` in Delivery")
    if git["dirty"]:
        blockers.append("dirty")
        para.append("Para ti: commit or stash the %s in %s" % (plural(git["dirty_count"], "change"), home_short(repo)))
    if git["behind"]:
        blockers.append("behind")
        para.append("Para ti: git -C %s pull --ff-only (%s is behind origin)" % (shell_path(repo), git["default_branch"]))
    mrs, problem = glab_mrs(repo, args.offline, s.partial)
    if mrs:
        blockers.append("open-run")
        para.append("Para ti: merge or close the open dependency MRs first: %s" % ", ".join("!%s" % mr["iid"] for mr in mrs))
    if env["node_pin"] and env["node_found"] == "none":
        blockers.append("node-missing")
        para.append("Para ti: install Node %s under nvm (the skill never installs runtimes)" % env["node_pin"])
    ver = verification_view(s)
    missing = [x for x in ver["external"] if not x["exists"]]
    if missing:
        blockers.append("external-missing")
        para.append("Para ti: check out %s next to the repo (needed by %s)" % (missing[0]["path"], missing[0]["step"]))
    ctx = s.ctx
    if ctx["state"] == "ambiguous":
        blockers.append("context-ambiguous")
        para.append("Para ti: pass --context with one of %s" % ", ".join(home_short(c) for c in ctx["candidates"]))
    if env["pm_declared"] and env["pm_found"] != "ok":
        blockers.append("pm-mismatch")
        para.append("Para ti: packageManager %s@%s, `%s --version` printed %s — fix corepack or the PATH" % (
            env["pm"], env["pm_declared"], env["pm"], env["pm_version"] or "nothing"))
    stale = False
    if s.policy.get("source_ref") and git.get("origin_sha"):
        stale = not git["origin_sha"].startswith(s.policy["source_ref"].rsplit("@", 1)[1])
    head = "PREFLIGHT %s · %s (default %s) · %s · head %s" % (
        s.name, git["branch"], git["default_branch"], "dirty(%d)" % git["dirty_count"] if git["dirty"] else "clean",
        (git["head"] or "none")[:7])
    if ctx["state"] == "ambiguous":
        ctx_line = "CONTEXT ambiguous: %s → blocked" % ", ".join(os.path.basename(c) for c in ctx["candidates"])
    elif ctx["state"] == "bad":
        ctx_line = "CONTEXT %s not found" % home_short(ctx["skill"])
        review.append("review: --context %s does not exist" % home_short(ctx["skill"]))
    elif ctx["skill"]:
        ctx_line = "CONTEXT %s · layout %s · %s %s" % (os.path.basename(ctx["skill"]), ctx["layout"], s.policy_label,
                                                       "found" if ctx["file"] else "missing (offer in phase 5)")
        if stale:
            ctx_line += " · context: stale (base sha ≠ origin/%s)" % git["default_branch"]
    else:
        ctx_line = "CONTEXT none · %s missing" % CONTEXT_FILE
    shadow = s.manifest["runtimes"]["node"].get("shadowed_by")
    if env["node_pin"]:
        node_line = "NODE pin %s (%s) · nvm %s%s" % (env["node_pin"], env["node_source"], env["node_found"],
                                                     " v%s" % env["node_version"] if env["node_version"] else "")
    else:
        node_line = "NODE no pin · PATH node"
    if shadow:
        node_line += " · SHADOWED by dependency %s@%s (node_modules/.bin/node)" % (shadow["package"], shadow["locked"] or shadow["declared"])
    lines = [head, id_line, rev_line, ctx_line, node_line]
    if env["pm_declared"] or env["pm_found"] == "missing":
        lines.append("PM %s %s · packageManager %s → %s" % (env["pm"], env["pm_version"] or "missing", env["pm_declared"] or "none",
                                                           "ok" if env["pm_found"] == "ok" else "mismatch"))
    ext = "".join(" → external %s (%s)" % (x["path"], "present" if x["exists"] else "missing") for x in ver["external"][:2])
    ci_cmds = unique(c["command"] for c in ver["ci"])
    lines.append("VERIFY build=%s · ci=%s%s" % (ver["build"]["command"] or "n/a", ", ".join(ci_cmds[:3]) or "n/a", ext))
    imgs = [i for i in s.manifest["ci"]["images"] if i["role"] != "service"]
    ci_desc = ", ".join(s.manifest["ci"]["files"][:2]) or "none"
    if imgs:
        first = imgs[0]
        ci_desc += " %s %s" % (first["job"] or "default", "%s:%s" % (first["image"], first["tag"]) if first["tag"] else first["image"])
    open_desc = "not checked (%s)" % problem if mrs is None else (", ".join("!%s" % m["iid"] for m in mrs) or "none")
    lines.append("CI %s · MR pipelines %s · remote %s · open MRs %s · deps/* local %d remote %d" % (
        ci_desc, "yes" if s.manifest["ci"]["mr_pipelines"] else "no", git["remote"] or "none", open_desc,
        len(git["local_branches"]), len(git["remote_branches"])))
    if git["local_branches"]:
        review.append("review: local-branches %s (delete them after the run)" % ", ".join(git["local_branches"][:3]))
    if git["remote_branches"] and not mrs:
        review.append("review: remote deps/* branches without an MR: %s" % ", ".join(git["remote_branches"][:3]))
    if git["branch"] != git["default_branch"]:
        review.append("review: on branch %s; the run starts from %s" % (git["branch"], git["default_branch"]))
    review = review + s.policy["review"]
    lines += review[:3] + (["review: … +%d more (use --json)" % (len(review) - 3)] if len(review) > 3 else [])
    lines += para
    blockers = [b for b in BLOCKER_ORDER if b in blockers]
    verdict = "PREFLIGHT: blocked(%s)" % ",".join(blockers) if blockers else "PREFLIGHT: ready"
    lines.append(verdict)
    base.update(state="blocked" if blockers else "ready", blockers=blockers, git=dict(git, identity=ident),
                brain=s.brain, context=dict(ctx, stale=stale, label=s.policy_label), env=env,
                reviewer=s.reviewer, verification=ver, open_mrs=mrs, para_ti=[p[len("Para ti: "):] for p in para],
                review=review)
    return emit(args, base, lines, 1 if blockers else 0)


# ---------------------------------------------------------------------------
# changelog
# ---------------------------------------------------------------------------

ENTRY_HEAD = re.compile(r"^## (\d{4}-\d{2}-\d{2}) — dependency run · base `([^`]*)@([0-9a-f]{7,40})`\s*$")


def load_plan(path):
    data = read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("waves"), list) or not isinstance(data.get("packages"), list):
        return None
    return data


def fill(template, values):
    out = []
    for line in template.splitlines():
        key = line.strip()
        if key.startswith("{{") and key.endswith("}}") and key[2:-2] in values:
            value = values[key[2:-2]]
            if isinstance(value, list):
                out.extend(value)
            elif value:
                out.append(value)
            continue
        out.append(re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: str(values.get(m.group(1), m.group(0))), line))
    return "\n".join(out) + "\n"


def split_entries(text):
    lines = text.splitlines()
    first = next((i for i, line in enumerate(lines) if line.startswith("## ")), len(lines))
    entries = []
    for line in lines[first:]:
        if line.startswith("## "):
            m = ENTRY_HEAD.match(line)
            entries.append([(m.group(1), m.group(3)[:7]) if m else ("?", line), [line]])
        else:
            entries[-1][1].append(line)
    return lines[:first], entries


def parse_entry(lines):
    out = {"summary": None, "sections": {}, "order": []}
    current = None
    for line in lines[1:]:
        if line.startswith("### "):
            title = line[4:]
            current = "changed" if title.startswith("Changed") else title.strip().lower()
            out["sections"][current] = {"title": title, "rows": [], "prose": []}
            out["order"].append(current)
            continue
        if current is None:
            if line.strip() and out["summary"] is None:
                out["summary"] = line
            continue
        if line.startswith("- "):
            out["sections"][current]["rows"].append(line)
        elif line.strip():
            out["sections"][current]["prose"].append(line)
    return out


def wave_label(wave_id):
    return "patch-minor" if wave_id == "patch-minor" else "major " + wave_id.split(":", 1)[1]


def later_from(plan, wave_id, present):
    """{(name, workspace): from} of the first applied wave after wave_id that moves each package again."""
    out, after = {}, False
    for w in plan["waves"]:
        if w["id"] == wave_id:
            after = True
            continue
        if after and w["id"] in present:
            for f in w["from_to"]:
                out.setdefault((f["name"], f["workspace"]), f["from"])
    return out


def package_rows(wave, locked_now, later):
    rows, dropped = [], []
    for f in wave["from_to"]:
        key = (f["name"], f["workspace"])
        to = later.get(key) or locked_now.get(key)
        if to is None or to == f["from"]:
            dropped.append(f)
            continue
        ws = "" if f["workspace"] == "." else " [%s]" % f["workspace"]
        rows.append("- %s %s → %s (%s)%s" % (f["name"], f["from"], to, f["kind"], ws))
    return rows, dropped


def major_row(wave, rows, notes):
    parts = [r[2:].split(" (", 1)[0] for r in rows]
    if not parts:
        return None
    head = parts[0] + "".join(" + " + p.split(" ", 1)[0] + " → " + p.rsplit(" ", 1)[-1] for p in parts[1:])
    return "- %s · branch `%s` · migration: %s" % (head, wave["branch"], notes or "see the MR")


def notes_text(path):
    if not path:
        return None
    text = read_text(path)
    if text is None:
        return None
    lines = [re.sub(r"^\s*[-*]\s+", "", l).strip() for l in text.splitlines() if l.strip() and not l.startswith("#")]
    return "; ".join(lines[:10]) or None


def smoke_summary(path):
    data = read_json(path) if path else None
    routes = as_list(as_dict(data).get("routes"))
    if not routes:
        return None
    groups = {}
    for r in routes:
        r = as_dict(r)
        verdict = str(r.get("verdict") or "unknown")
        label = r.get("route")
        if verdict == "changed" and isinstance(r.get("ratio"), (int, float)):
            label = "%s %.2f%%" % (label, r["ratio"] * 100)
        groups.setdefault(verdict, []).append(str(label))
    out = []
    for verdict in ("changed", "resized", "missing", "unstable"):
        if verdict in groups:
            out.append("%s(%s)" % (verdict, ", ".join(groups[verdict])))
    if "same" in groups:
        out.append("same(%d)" % len(groups["same"]))
    return " ".join(out)


def verify_row(wave_id, pairs, smoke):
    items = ["%s %s" % tuple(p.split("=", 1)) for p in pairs]
    if smoke:
        items.append("smoke " + smoke)
    return "- %s: %s" % (wave_label(wave_id), " · ".join(items) if items else "not recorded")


def held_rows(plan, dropped_rows):
    rows = []
    for n in plan.get("never_auto") or []:
        rows.append("- %s %s (locked %s) — never-auto: %s — owner decision" % (n["name"], n["declared"], n["locked"], n["reason"]))
    rt = as_dict(as_dict(plan.get("runtimes")).get("node"))
    if rt.get("status") == "eol" and rt.get("decision") != "wave":
        rows.append("- runtime node %s (%s) — eol %s — owner decision (newest LTS %s)" % (
            rt.get("pin"), rt.get("source"), rt.get("eol"), rt.get("newest_lts")))
    for h in plan.get("holds") or []:
        rows.append("- %s — %s" % (h["name"], hold_text(h)))
    for p in plan.get("pending_majors") or []:
        rows.append("- %s %s → %s — pending (%s)" % (p["name"], p["from"], p["to"] or "?", p["reason"]))
    pending = {p["name"] for p in plan.get("pending_majors") or []}
    for p in plan.get("packages") or []:
        if p.get("blocked") and not p.get("held_by") and p["name"] not in pending:
            rows.append("- %s %s — %s" % (p["name"], p["declared"], p["blocked"]))
    rows.extend(dropped_rows)
    return unique(rows) or ["- none"]


def audit_after(repo, man, offline, partial):
    if offline:
        return None, "offline"
    lock = next((l for l in man["lockfiles"] if "/" not in l["path"] and l["type"] in ("package-lock", "npm-shrinkwrap", "pnpm")), None)
    if not lock:
        return [], None
    graph = (pnpm_lock_graph if lock["type"] == "pnpm" else npm_lock_graph)(repo, lock["path"])[0]
    before = set(partial)
    found = collect_advisories(graph, partial)
    return (None, "failed") if "audit" in partial - before else (found, None)


def audit_counts(after):
    c = {k: len({a["id"] for a in after if a["severity"] == k}) for k in ("critical", "high", "moderate", "low")}
    return "critical %d · high %d · moderate %d · low %d" % (c["critical"], c["high"], c["moderate"], c["low"])


def security_rows(plan, present, after, problem, date):
    base = {}
    for p in plan["packages"]:
        for a in p.get("advisories") or []:
            base.setdefault(a["id"], (a["severity"], p["name"], a.get("fixed_in")))
    for t in plan.get("transitive_advisories") or []:
        base.setdefault(t["id"], (t["severity"], t["package"], t.get("fixed_in")))
    rows = []
    if after is not None:
        open_ids = {a["id"] for a in after}
        closed = sorted(i for i in base if i not in open_ids)
        label = "Closed"
    else:
        closed = sorted({i for w in plan["waves"] if w["id"] in present for i in w["closes"]} & set(base))
        label = "Closed (expected)"
    for ident in closed:
        sev, pkg, fix = base[ident]
        rows.append("- %s: %s (%s · %s · fixed in %s)" % (label, ident, sev, pkg, fix or "?"))
    if not rows:
        rows.append("- Closed: none")
    if after is not None:
        ids = sorted({a["id"] for a in after})
        rows.append("- Audit after (bulk advisories, %s): %s · open: %s" % (date, audit_counts(after), ", ".join(ids[:6]) or "none"))
    else:
        rows.append("- Audit after: not run (%s)" % problem)
    return rows


def summary_line(changed_rows, major_rows, after, problem):
    pkgs = len([r for r in changed_rows if not r.startswith("- edit ") and r != "- none"])
    fams = [re.match(r"^- (\S+)", r).group(1) for r in major_rows if r != "- none" and re.match(r"^- (\S+)", r)]
    audit = audit_counts(after) if after is not None else "not run (%s)" % problem
    pm = "Patch and minor: %s in 1 MR" % plural(pkgs, "package") if changed_rows and changed_rows != ["- none"] else "Patch and minor: none"
    mj = "majors: %s (%s)" % (plural(len(fams), "MR"), ", ".join(fams)) if fams else "majors: none"
    return "%s · %s · audit after: %s" % (pm, mj, audit)


def edit_rows(wave):
    return ["- edit %s %s: %s → %s (%s)" % (e["file"], e["key"], e.get("from") or "none", e["to"], e.get("note") or "edit")
            for e in wave.get("edits") or []]


def present_waves(plan, old):
    """Waves whose rows the entry already records: the patch-minor package rows, a major row by its branch."""
    sec = lambda name: old["sections"].get(name, {"rows": []})["rows"]
    present = set()
    for w in plan["waves"]:
        if w["id"] == "patch-minor" and [r for r in sec("changed") if r != "- none"]:
            present.add(w["id"])
        if w["id"] != "patch-minor" and any("· branch `%s`" % w["branch"] in r for r in sec("majors")):
            present.add(w["id"])
    return present


def recorded_notes(old, branch):
    for row in old["sections"].get("majors", {"rows": []})["rows"]:
        if "· branch `%s`" % branch in row and "· migration: " in row:
            return row.split("· migration: ", 1)[1]
    return None


def render_entry(plan, wave, existing, locked_now, args, after, problem):
    """The entry of this run: the rows of every applied wave re-derived from the lockfile, the notes and
    verification rows of the other waves kept, the prose under each section kept."""
    tmpl = read_text(os.path.join(OWN_TEMPLATES, "changelog-entry.md.tmpl"))
    if tmpl is None:
        raise RuntimeError("changelog-entry template missing")
    old = parse_entry(existing) if existing else {"summary": None, "sections": {}, "order": []}
    sec = lambda name: old["sections"].get(name, {"rows": [], "prose": []})
    present = present_waves(plan, old) | {wave["id"]}
    changed, majors, dropped = [], [], []
    for w in plan["waves"]:
        if w["id"] not in present:
            continue
        rows, gone = package_rows(w, locked_now, later_from(plan, w["id"], present))
        dropped += ["- %s %s — planned %s, not applied (dropped from %s)" % (f["name"], f["from"], f["to"], w["id"]) for f in gone]
        if w["id"] == "patch-minor":
            changed = rows + edit_rows(w)
        else:
            row = major_row(w, rows, notes_text(args.notes) if w["id"] == wave["id"] else recorded_notes(old, w["branch"]))
            if row:
                majors.append(row)
    label = wave_label(wave["id"])
    labels = {wave_label(w["id"]): i for i, w in enumerate(plan["waves"])}
    verify = [r for r in sec("verification")["rows"] if not r.startswith("- %s:" % label) and r != "- none"]
    verify.append(verify_row(wave["id"], args.verify or [], smoke_summary(args.smoke)))
    verify.sort(key=lambda r: labels.get(r[2:].split(":", 1)[0], len(labels)))
    security = security_rows(plan, present, after, problem, args.date)
    pm_wave = next((w for w in plan["waves"] if w["id"] == "patch-minor"), None)
    git = as_dict(plan.get("git"))
    values = {"DATE": plan["date"], "BASE_REF": git.get("base_ref") or "none@0000000",
              "SUMMARY_LINE": summary_line(changed or ["- none"], majors or ["- none"], after, problem),
              "BRANCH": pm_wave["branch"] if pm_wave else "none",
              "CHANGED_ROWS": (changed or ["- none"]) + sec("changed")["prose"],
              "SECURITY_ROWS": security + sec("security")["prose"],
              "MAJOR_ROWS": (majors or ["- none"]) + sec("majors")["prose"],
              "HELD_ROWS": held_rows(plan, dropped) + sec("held and pending")["prose"],
              "VERIFY_ROWS": verify + sec("verification")["prose"]}
    return fill(tmpl, values).rstrip("\n").split("\n")


CONFLICT = re.compile(r"^(<{7}|\|{7}|={7}|>{7})(?: |$)")


def resolve_conflicts(text):
    """(ours, theirs) of a file holding git conflict markers; (text, None) when it holds none."""
    lines = text.splitlines()
    if not any(CONFLICT.match(line) for line in lines):
        return text, None
    ours, theirs, state = [], [], None
    for line in lines:
        mark = CONFLICT.match(line)
        if mark and mark.group(1)[0] == "<":
            state = "ours"
        elif mark and mark.group(1)[0] == "|" and state == "ours":
            state = "base"
        elif mark and mark.group(1)[0] == "=" and state in ("ours", "base"):
            state = "theirs"
        elif mark and mark.group(1)[0] == ">" and state == "theirs":
            state = None
        else:
            if state in (None, "ours"):
                ours.append(line)
            if state in (None, "theirs"):
                theirs.append(line)
    return "\n".join(ours) + "\n", "\n".join(theirs) + "\n"


def row_key(section, row):
    m = re.search(r"· branch `([^`]+)`", row) if section == "majors" else re.match(r"^- ([^:]+):", row)
    return m.group(1) if m else row


def merge_entries(ours, theirs):
    """One entry from both sides of a conflict: theirs first, plus the rows and prose only ours records."""
    if ours is None or theirs is None:
        return theirs or ours
    a, b = parse_entry(ours), parse_entry(theirs)
    out = list(theirs)
    for name in a["order"]:
        mine, other = a["sections"][name], b["sections"].get(name)
        if other is None:
            continue
        keys = {row_key(name, row) for row in other["rows"]}
        extra = []
        if name in ("majors", "verification"):
            extra = [row for row in mine["rows"] if row_key(name, row) not in keys]
        extra += [line for line in mine["prose"] if line not in other["prose"]]
        if extra:
            title = "### " + other["title"]
            at = out.index(title) + 1
            while at < len(out) and not out[at].startswith("### ") and not out[at].startswith("## "):
                at += 1
            while at > 0 and not out[at - 1].strip():
                at -= 1
            out[at:at] = extra
    return out


def check_rows(plan, existing, locked_now, git_obj):
    if not existing:
        return ["entry"]
    old = parse_entry(existing)
    sec = lambda name: old["sections"].get(name, {"rows": []})["rows"]
    present = present_waves(plan, old)
    names = set()
    for w in plan["waves"]:
        if w["id"] not in present:
            if git_obj is not None and git_obj.ok("rev-parse", "--verify", "--quiet", "refs/heads/" + w["branch"]) \
                    and git_obj.ok("merge-base", "--is-ancestor", w["branch"], "HEAD"):
                names.add(w["id"])
            continue
        rows, _ = package_rows(w, locked_now, later_from(plan, w["id"], present))
        if w["id"] == "patch-minor":
            actual = {r for r in sec("changed") if not r.startswith("- edit ") and r != "- none"}
            for r in set(rows) ^ actual:
                names.add(r[2:].split(" ", 1)[0])
        else:
            want = major_row(w, rows, None)
            got = next((r for r in sec("majors") if "· branch `%s`" % w["branch"] in r), None)
            if want is None or got is None or want.split(" · branch ")[0] != got.split(" · branch ")[0]:
                names.update(f["name"] for f in w["from_to"])
    return sorted(names)


def render_mr(plan, wave, locked_now, args, after, problem):
    tmpl = read_text(os.path.join(OWN_TEMPLATES, "mr-description.md.tmpl"))
    if tmpl is None:
        raise RuntimeError("mr-description template missing")
    rows, dropped = package_rows(wave, locked_now, {})
    changed = rows + (edit_rows(wave) if wave["id"] == "patch-minor" else []) or ["- none"]
    if wave["id"] == "patch-minor":
        title = "Dependencies: patch and minor bumps (%s)" % plan["date"]
    else:
        f = wave["from_to"][0] if wave["from_to"] else {"from": "?", "to": "?"}
        title = "Dependencies: major %s %s → %s (%s)" % (wave["id"].split(":", 1)[1], f["from"], f["to"], plan["date"])
    ctx = as_dict(plan.get("context"))
    rev = as_dict(ctx.get("reviewer"))
    reviewer = reviewer_text(rev)
    closes = set(wave["closes"])
    sec_rows = [r for r in security_rows(plan, {wave["id"]}, after, problem, args.date)
                if not r.startswith("- Closed") or any(i in r for i in closes)] or ["- none"]
    if not any(r.startswith("- Closed") for r in sec_rows):
        sec_rows.insert(0, "- Closed: none")
    smoke = read_json(args.smoke) if args.smoke else None
    smoke_rows = []
    for r in (as_dict(r) for r in as_list(as_dict(smoke).get("routes"))):
        ratio = " %.2f%%" % (r["ratio"] * 100) if isinstance(r.get("ratio"), (int, float)) else ""
        smoke_rows.append("- `%s` %s%s" % (r.get("route"), r.get("verdict"), ratio))
    smoke_rows = smoke_rows or ["- not recorded"]
    verify = ["- %s: %s" % tuple(p.split("=", 1)) for p in (args.verify or [])] or ["- not recorded"]
    notes = read_text(args.notes) if args.notes else None
    note_rows = [l for l in (notes or "").splitlines() if l.strip()][:10] or ["- none"]
    path = changelog_path(plan, args)
    values = {"TITLE": title,
              "SUMMARY_LINE": "%s · closes %s · base `%s`" % (
                  plural(len(rows), "package"), plural(len(closes), "advisory"), wave["base"]),
              "MERGE_ORDER": " → ".join("`%s`" % w["branch"] for w in plan["waves"]),
              "STACKED_ON": "`%s`" % wave["base"], "REVIEWER": reviewer, "CHANGED_ROWS": changed,
              "SECURITY_ROWS": sec_rows, "NOTES": note_rows, "VERIFY_ROWS": verify, "SMOKE_ROWS": smoke_rows,
              "HELD_ROWS": held_rows(plan, ["- %s %s — planned %s, not applied" % (f["name"], f["from"], f["to"]) for f in dropped]),
              "CHANGELOG_PATH": path, "DATE": plan["date"]}
    return fill(tmpl, values)


def changelog_path(plan, args):
    if args.path:
        return args.path
    value = as_dict(as_dict(plan.get("context")).get("delivery")).get("changelog") or ""
    value = value.strip().strip("`")
    if value and not value.startswith("_pending") and "{{" not in value and not os.path.isabs(value) and os.pardir not in value.split("/"):
        return value
    return DEFAULT_CHANGELOG


def run_changelog(args):
    repo = os.path.abspath(os.path.expanduser(args.repo))
    base = {"tool": "deps-check", "version": tool_version(), "command": "changelog",
            "repo": {"name": os.path.basename(repo), "path": repo}, "date": args.date, "state": "unparsed"}

    def fail(reason):
        return emit(args, base, ["CHANGELOG %s" % home_short(repo), "CHANGELOG: unparsed (%s)" % reason], 2)
    if dependency_manifest is None:
        return fail("dependency_manifest module not found next to the code-project-context-generator skill")
    if not os.path.isdir(repo):
        return fail("repo not found: %s" % repo)
    plan = load_plan(os.path.abspath(os.path.expanduser(args.plan)))
    if plan is None:
        return fail("no plan: %s is missing or not a plan.json" % home_short(args.plan))
    waves = {w["id"]: w for w in plan["waves"]}
    if args.wave and args.wave not in waves:
        return fail("bad wave %s; the plan has %s" % (args.wave, ", ".join(waves) or "no waves"))
    man = dependency_manifest(repo)
    locked_now = {(e["name"], e["workspace"]): e["locked"] for e in man["packages"]}
    path = changelog_path(plan, args)
    full = os.path.join(repo, *path.split("/"))
    raw = text = read_text(full)
    key = (plan["date"], (as_dict(plan.get("git")).get("base") or "")[:7] or "0000000")
    ours, theirs = resolve_conflicts(text) if text is not None else (None, None)
    if theirs is not None:
        text = theirs
    header, entries = split_entries(text) if text is not None else ([], [])
    existing = next((lines for k, lines in entries if k == key), None)
    if theirs is not None:
        mine = next((lines for k, lines in split_entries(ours)[1] if k == key), None)
        existing = merge_entries(mine, existing)
    rid = "%s-%s" % key
    base.update(run_id=rid, path=path)
    if args.check:
        g = Git(repo)
        names = check_rows(plan, existing, locked_now, g if g.ok("rev-parse", "--git-dir") else None)
        lines = ["CHANGELOG %s · run %s · %s" % (s_name(repo), rid, path),
                 "CHECK waves %s" % ", ".join(w["id"] for w in plan["waves"]) if plan["waves"] else "CHECK no waves"]
        verdict = "CHANGELOG: mismatch(%s)" % ",".join(names) if names else "CHANGELOG: ok"
        base.update(state="mismatch" if names else "ok", mismatch=names)
        return emit(args, base, lines + [verdict], 1 if names else 0)
    wave = waves[args.wave]
    partial = set()
    after, problem = audit_after(repo, man, args.offline, partial)
    if args.format == "mr":
        scratch = os.path.dirname(os.path.abspath(os.path.expanduser(args.plan)))
        levels = [scratch, os.path.join(scratch, "mr")]
        bad = scratch_problem(levels)
        if bad:
            return fail("scratch dir not private: %s" % home_short(bad))
        target = os.path.join(levels[1], slug(wave["id"].replace(":", "-")) + ".md")
        new = render_mr(plan, wave, locked_now, args, after, problem)
        old = read_text(target)
        shown = home_short(target)
    else:
        entry = render_entry(plan, wave, existing, locked_now, args, after, problem)
        if text is None or not text.startswith("# Dependency changelog"):
            head_lines = CHANGELOG_HEADER.rstrip("\n").split("\n")
            rest = text.rstrip("\n").split("\n") if text else []
            header, entries = split_entries("\n".join(rest)) if rest else ([], [])
            header = head_lines + [""] + [l for l in header if l.strip()]
        out_entries = [lines for k, lines in entries]
        rendered = entry + [""]
        if existing is not None:
            idx = next(i for i, (k, _) in enumerate(entries) if k == key)
            out_entries[idx] = rendered
        else:
            out_entries.insert(0, rendered)
        blocks = "\n".join("\n".join(e).rstrip("\n") + "\n" for e in out_entries).replace("\n\n\n", "\n\n")
        body = "\n".join(header).rstrip("\n") + "\n\n" + blocks
        new = body.rstrip("\n") + "\n"
        old, target, shown = raw, full, path
    if old == new:
        verdict, code = "CHANGELOG: ok", 0
    elif args.write:
        if args.format == "mr":
            bad = make_private(levels[1:])
            if bad:
                return fail("scratch dir not private: %s" % home_short(bad))
        write_file(target, new, private=args.format == "mr")
        verdict, code = "CHANGELOG: written %s" % shown, 0
    else:
        added, removed = diff_counts(old, new)
        verdict, code = "CHANGELOG: would write %s (+%d -%d)" % (shown, added, removed), 0
    if problem == "failed":
        verdict, code = verdict + " · partial(audit)", 1
    elif problem == "offline":
        verdict, code = verdict + " · partial(offline)", 1
    lines = ["CHANGELOG %s · run %s · wave %s · %s" % (s_name(repo), rid, wave["id"], "mr" if args.format == "mr" else path),
             "ROWS %s · audit after %s" % (plural(len(package_rows(wave, locked_now, {})[0]), "package"),
                                           "not run (%s)" % problem if problem else "open %d" % len({a["id"] for a in after or []})),
             verdict]
    base.update(state="ok" if code == 0 else "partial", run_id=rid, wave=wave["id"], target=target)
    return emit(args, base, lines, code)


def s_name(repo):
    return os.path.basename(os.path.realpath(repo))


# ---------------------------------------------------------------------------
# context
# ---------------------------------------------------------------------------

def context_values(s, plan, mrs, mr_problem, is_new):
    m, git = s.manifest, s.git or {}
    rt = runtime_view(s)
    pm = m["package_manager"]
    pm_text = pm["name"] or "none"
    if pm.get("version"):
        pm_text += " %s (%s)" % (pm["version"], pm["source"])
    elif pm.get("source") and pm["source"] != "none":
        pm_text += " (%s)" % pm["source"]
    locks = ", ".join("`%s` v%s" % (l["path"], l["version"]) if l["version"] else "`%s`" % l["path"] for l in m["lockfiles"]) or "none"
    pins = ", ".join(unique("`%s` (%s)" % (p["value"], p["source"]) for p in m["runtimes"]["node"]["pins"])) or "none"
    if rt["shadowed_by"]:
        pins += " · shadowed by `%s@%s`" % (rt["shadowed_by"]["package"], rt["shadowed_by"]["locked"] or rt["shadowed_by"]["declared"])
    if rt["pin"]:
        status = "node %s %s%s · newest LTS %s" % (rt["major"], rt["status"], " (EOL %s)" % rt["eol"] if rt["eol"] else "",
                                                   rt["newest_lts"] or "?")
        if rt["ci"]:
            status += " · CI %s %s" % (rt["ci"][0]["ref"], "aligned" if all(i["aligned"] for i in rt["ci"]) else "mismatch")
    else:
        status = "no node pin"
    merged = {}
    for e in m["packages"]:
        k = (e["name"], e["kind"], e["declared"], e["locked"], e["style"])
        merged.setdefault(k, []).append(e["workspace"])
    rows = [md_row(k[0], k[1], ", ".join(ws), k[2], k[3] or "—", k[4])
            for k, ws in sorted(merged.items(), key=lambda kv: (KIND_ORDER.get(kv[0][1], 9), kv[0][0], kv[1]))]
    ov = ["- Overrides: " + (", ".join("`%s` → `%s` (%s)" % (o["name"], o["spec"], o["source"]) for o in m["overrides"]) or "none"),
          "- Patched: " + (", ".join("`%s` (%s)" % (p["name"], p["path"]) for p in m["patched"]) or "none")]
    inst = m["install_scripts"]
    if inst:
        ov.append("- Install scripts: allow %s · deny %s (%s)" % (", ".join(inst["allow"]) or "none",
                                                               ", ".join(inst["deny"]) or "none", inst["source"]))
    else:
        ov.append("- Install scripts: no policy")
    direct = set(s.direct)
    fams = {}
    for name in sorted(direct):
        fams.setdefault(family_of(name, direct, rules_for(s, name)["group"]), []).append(name)
    fam_rows = ["- %s: %s" % (f, ", ".join(names)) for f, names in sorted(fams.items()) if len(names) > 1 or f == "runtime-node"]
    bots = []
    for bot in m["bots"]:
        if not bot["parsed"]:
            bots.append("- `%s` (%s, presence only — not parsed)" % (bot["path"], bot["kind"]))
            continue
        parts = []
        if bot["extends"]:
            parts.append("extends %s" % ", ".join(bot["extends"]))
        if bot["min_release_age_days"] is not None:
            parts.append("min release age %s" % plural(bot["min_release_age_days"], "day"))
        if bot["caps"]:
            parts.append("caps " + ", ".join("%s %s" % (", ".join(c["names"] or c["patterns"]), c["allowed"]) for c in bot["caps"]))
        if bot["disabled"]:
            parts.append("disabled " + ", ".join("%s%s" % (", ".join(d["names"] or d["patterns"]), " (%s)" % ", ".join(
                d["update_types"]) if d["update_types"] else "") for d in bot["disabled"]))
        if bot["groups"]:
            parts.append("groups " + ", ".join("%s (%s)" % (g["name"], ", ".join(g["names"] or g["patterns"])) for g in bot["groups"]))
        bots.append("- `%s` (renovate): %s" % (bot["path"], " · ".join(parts) or "defaults"))
    ci = m["ci"]
    tag = lambda x: ":" + x["tag"] if x["tag"] else ""
    ci_rows = ["- Provider %s · files %s · MR pipelines %s" % (
        ci["provider"], ", ".join("`%s`" % f for f in ci["files"]) or "none", "yes" if ci["mr_pipelines"] else "no")]
    if ci["images"]:
        ci_rows.append("- Images: " + " · ".join("%s `%s%s` (%s)" % (i["job"] or "default", i["image"], tag(i), i["role"])
                                                 for i in ci["images"]))
    if ci["audit_jobs"]:
        ci_rows.append("- Audit jobs: " + " · ".join("%s (%s%s)" % (a["job"], a["tool"], ", allow failure" if a["allow_failure"] else "")
                                                     for a in ci["audit_jobs"]))
    ci_rows.append("- Actions: " + (" · ".join("`%s@%s`" % (a["uses"], a["ref"]) for a in ci["actions"]) or "none"))
    ci_rows.append("- CI pins: " + (" · ".join("%s %s %s (%s:%d)" % (p["kind"], p["name"], p["version"], p["file"], p["line"])
                                               for p in ci["pins"]) or "none"))
    ci_rows.append("- Docker: " + (" · ".join("`%s`:%d `%s%s`%s" % (d["file"], d["line"], d["image"], tag(d),
                                                                    " (%s)" % d["stage"] if d["stage"] else "")
                                              for d in m["docker"]) or "none"))
    ver = verification_view(s)
    vrows = []
    for k in ("build", "typecheck", "lint", "test", "e2e"):
        v = ver[k]
        vrows.append(md_row(k, v["command"] or "—", v["source"] or "—", v["note"] or ""))
    for c in ver["ci"]:
        vrows.append(md_row("ci", c["command"], c["job"], ", ".join(
            "%s (%s)" % (x["path"], "present" if x["exists"] else "missing") for x in c["external"])))
    present = [e for e in m["packages"] if e["name"] in NEVER_AUTO]
    shadow = as_dict(rt["shadowed_by"])
    never = "%s (as dependencies) — present here: %s" % (", ".join(NEVER_AUTO), ", ".join(
        "`%s %s`%s" % (e["name"], e["declared"], " (locked %s, shadows the runtime)" % e["locked"] if shadow.get("package") == e["name"] else "")
        for e in present) or "none")
    branches = []
    by_branch = {w["branch"]: w for w in as_list(as_dict(plan).get("waves"))}
    for mr in mrs or []:
        w = by_branch.get(mr["branch"])
        vers = ", ".join("%s %s" % (f["name"], f["to"]) for f in (w or {}).get("from_to", [])[:3])
        more = len((w or {}).get("from_to", [])) - 3
        tail = " · " + vers + (" (+%d)" % more if more > 0 else "") if vers else ""
        branches.append("- !%s `%s` → %s%s" % (mr["iid"], mr["branch"], mr["target"], tail))
    if mrs is None and plan:
        for w in as_list(plan.get("waves")):
            vers = ", ".join("%s %s" % (f["name"], f["to"]) for f in w["from_to"][:3])
            branches.append("- `%s` → %s (MR not checked: %s)%s" % (w["branch"], w["base"], mr_problem, " · " + vers if vers else ""))
    values = {"PROJECT_NAME": s.name, "SCAN_DATE": s.date, "TOOL_VERSION": tool_version(),
              "SOURCE_REF": git.get("base_ref") or "none@0000000", "REPO_NAME": s.name,
              "DEFAULT_BRANCH": git.get("default_branch") or "none", "PACKAGE_MANAGER": pm_text, "LOCKFILES": locks,
              "WORKSPACES": ", ".join("`%s`" % w for w in m["workspaces"]) or "none", "RUNTIME_PINS": pins,
              "RUNTIME_STATUS": status, "DEPENDENCY_ROWS": rows, "OVERRIDES": ov, "FAMILIES": fam_rows or ["none"],
              "BOT_CONFIG": bots or ["none"], "CI_CONTAINERS": ci_rows, "VERIFY_ROWS": vrows, "NEVER_AUTO": never,
              "OPEN_BRANCHES": branches or ["none"]}
    if is_new:
        policy_rows = []
        for e in sorted({e["name"]: e for e in present}.values(), key=lambda e: e["name"]):
            why = ("npm binary package that shadows the runtime for npm scripts" if shadow.get("package") == e["name"]
                   else "toolchain binary as a dependency")
            policy_rows.append(md_row(e["name"], "never-auto", "", why, s.date, ""))
        smoke = as_dict(as_dict(plan).get("smoke"))
        routes = as_list(smoke.get("routes")) or [{"route": "/", "name": "home", "mask": ""}]
        rev = as_dict(as_dict(as_dict(plan).get("context")).get("reviewer")) or s.reviewer
        expected = as_dict(as_dict(plan).get("context")).get("expected_identity") or s.expected
        values.update({"POLICY_ROWS": policy_rows,
                       "SMOKE_ROWS": [md_row(r.get("route"), r.get("name"), r.get("mask")) for r in routes],
                       "SMOKE_SERVER": smoke.get("server") or PENDING, "SHOT_COMMAND": smoke.get("shot_command") or "built-in (deps-smoke)",
                       "CHANGELOG_PATH": "`%s`" % DEFAULT_CHANGELOG,
                       "REVIEWER": reviewer_text(rev),
                       "COMMIT_IDENTITY": expected or PENDING,
                       "PRIORITY_MAJORS": ", ".join(as_list(as_dict(plan).get("prioritize"))) or "none", "DELIVERY_NOTES": "none"})
    return values


def run_context(args):
    repo = os.path.abspath(os.path.expanduser(args.repo))
    base = {"tool": "deps-check", "version": tool_version(), "command": "context",
            "repo": {"name": os.path.basename(repo), "path": repo}, "date": args.date, "state": "unparsed"}

    def fail(reason, code=2):
        return emit(args, base, ["CONTEXT %s" % home_short(repo), "CONTEXT: unparsed (%s)" % reason], code)
    if dependency_manifest is None:
        return fail("dependency_manifest module not found next to the code-project-context-generator skill")
    if not os.path.isdir(repo):
        return fail("repo not found: %s" % repo)
    template = read_text(CONTEXT_TEMPLATE)
    if template is None:
        return fail("the dependencies.md template of code-project-context-generator is missing")
    plan = None
    if args.plan:
        plan = load_plan(os.path.abspath(os.path.expanduser(args.plan)))
        if plan is None:
            return fail("no plan: %s is missing or not a plan.json" % home_short(args.plan))
    s = gather(repo, args, schedule=False)
    if s.manifest["package_manager"]["name"] is None and not s.manifest["packages"]:
        return fail("no dependency manifest")
    ctx = s.ctx
    if ctx["state"] == "bad":
        return fail("--context %s does not exist" % home_short(ctx["skill"]))
    if ctx["state"] == "ambiguous":
        return fail("context-ambiguous: %s — pass --context" % ", ".join(os.path.basename(c) for c in ctx["candidates"]))
    if ctx["skill"]:
        target = context_target(ctx, args.file)
        layout = ctx["layout"]
    else:
        levels = scratch_levels(s, args.scratch)
        bad = scratch_problem(levels)
        if bad:
            return fail("scratch dir not private: %s" % home_short(bad))
        target, layout = os.path.join(levels[-1], args.file or CONTEXT_FILE), "scratch"
    old = read_text(target)
    if old is not None:
        old_policy = parse_policy(old, s.date)
        recorded = old_policy.get("repo")
        if recorded and recorded != s.name:
            return fail("%s records repo %s, not %s — use --file dependencies-%s.md" % (
                os.path.basename(target), recorded, s.name, s.name))
        if START_MARK not in old or END_MARK not in old:
            return fail("%s has no auto-generated markers" % os.path.basename(target))
        if args.if_merged:
            ref = old_policy.get("source_ref")
            if ref and s.git and ref == s.git.get("base_ref"):
                lines = ["CONTEXT %s · %s · base %s unchanged" % (s.name, home_short(target), ref), "CONTEXT: current"]
                base.update(state="current", target=target)
                return emit(args, base, lines, 0)
    mrs, problem = glab_mrs(repo, args.offline, s.partial)
    values = context_values(s, plan, mrs, problem, old is None)
    rendered = fill(template, values)
    if old is None:
        new = rendered
    else:
        r_lines, o_lines = rendered.split("\n"), old.split("\n")
        rs = next(i for i, l in enumerate(r_lines) if l.startswith(START_MARK))
        re_ = next(i for i, l in enumerate(r_lines) if l.strip() == END_MARK)
        os_ = next(i for i, l in enumerate(o_lines) if l.startswith(START_MARK))
        oe = next(i for i in range(os_, len(o_lines)) if o_lines[i].strip() == END_MARK)
        new = "\n".join(o_lines[:os_] + r_lines[rs:re_ + 1] + o_lines[oe + 1:])
    deps = len(values["DEPENDENCY_ROWS"])
    lines = ["CONTEXT %s · skill %s · %s (%s, layout %s)" % (s.name, os.path.basename(ctx["skill"]) if ctx["skill"] else "none",
                                                          home_short(target), "new" if old is None else "existing", layout),
             "SNAPSHOT %s · %s · base %s · runtime %s" % (values["PACKAGE_MANAGER"], values["LOCKFILES"].replace("`", ""),
                                                          values["SOURCE_REF"], values["RUNTIME_STATUS"]),
             "ROWS dependencies %d · verify %d · open branches %d%s" % (deps, len(values["VERIFY_ROWS"]),
                                                                        len([b for b in values["OPEN_BRANCHES"] if b != "none"]),
                                                                        " · policy seeded (new file)" if old is None else " · policy kept")]
    if old == new:
        verdict, code, state = "CONTEXT: current", 0, "current"
    elif args.write:
        if layout == "scratch":
            bad = make_private(levels)
            if bad:
                return fail("scratch dir not private: %s" % home_short(bad))
        write_file(target, new, private=layout == "scratch")
        verdict, code, state = "CONTEXT: written %s" % home_short(target), 0, "written"
    else:
        added, removed = diff_counts(old, new)
        verdict, code, state = "CONTEXT: would write %s (+%d -%d)" % (home_short(target), added, removed), 1, "would-write"
    base.update(state=state, target=target, layout=layout, open_branches=mrs)
    return emit(args, base, lines + [verdict], code)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

RUNNING = ("created", "waiting_for_resource", "preparing", "pending", "running", "scheduled", "manual")
FAILED = ("failed", "canceled", "cancelled")


def run_status(args):
    repo = os.path.abspath(os.path.expanduser(args.repo))
    base = {"tool": "deps-check", "version": tool_version(), "command": "status",
            "repo": {"name": os.path.basename(repo), "path": repo}, "state": "unparsed", "mrs": []}

    def fail(reason):
        return emit(args, base, ["STATUS %s" % home_short(repo), "STATUS: unparsed (%s)" % reason], 2)
    if not os.path.isdir(repo):
        return fail("repo not found: %s" % repo)
    env = tool_env()
    if shutil.which("glab", path=env.get("PATH")) is None:
        return fail("glab missing")
    rc, _, problem = run_text(["glab", "auth", "status"], repo, env, timeout=60)
    if problem or rc != 0:
        return fail("glab unauthenticated")
    if args.branches:
        ids = [b.strip() for b in args.branches.split(",") if b.strip()]
    else:
        listed, problem = run_json(["glab", "mr", "list", "--label", "dependencies", "-F", "json"], repo, env)
        if problem or not isinstance(listed, list):
            return fail("glab mr list failed")
        ids = [str(as_dict(mr).get("iid")) for mr in listed if str(as_dict(mr).get("state") or "opened") == "opened"]
    mrs = []
    for ident in ids:
        data, problem = run_json(["glab", "mr", "view", ident, "-F", "json"], repo, env)
        if problem or not isinstance(data, dict):
            return fail("glab mr view %s failed" % ident)
        pipe = data.get("head_pipeline")
        status = str(as_dict(pipe).get("status")) if isinstance(pipe, dict) else None
        mrs.append({"iid": data.get("iid"), "branch": data.get("source_branch"), "target": data.get("target_branch"),
                    "draft": bool(data.get("draft") or data.get("work_in_progress")), "pipeline": status,
                    "conflicts": bool(data.get("has_conflicts"))})
    mrs.sort(key=lambda m: int(m["iid"]) if str(m["iid"]).isdigit() else 0)
    lines = ["STATUS %s · %s" % (s_name(repo), plural(len(mrs), "dependency MR"))]
    lines += ["MR !%s %s → %s · %s · pipeline %s · conflicts %s" % (m["iid"], m["branch"], m["target"],
                                                                   "draft" if m["draft"] else "ready", m["pipeline"] or "none",
                                                                   "yes" if m["conflicts"] else "no") for m in mrs[:MAX_LINES - 3]]
    groups = {"running": [], "failed": [], "conflict": [], "nopipeline": []}
    for m in mrs:
        tag = "!%s" % m["iid"]
        if m["conflicts"]:
            groups["conflict"].append(tag)
        if m["pipeline"] is None:
            groups["nopipeline"].append(tag)
        elif m["pipeline"] in FAILED:
            groups["failed"].append(tag)
        elif m["pipeline"] not in ("success", "skipped"):
            groups["running"].append(tag)
    bad = " ".join("%s(%s)" % (k, ",".join(v)) for k, v in groups.items() if v)
    if not mrs:
        verdict, code, state = "STATUS: none", 0, "none"
    elif bad:
        verdict, code, state = "STATUS: " + bad, 1, "blocked"
    else:
        verdict, code, state = "STATUS: ok(%s)" % ",".join("!%s" % m["iid"] for m in mrs), 0, "ok"
    base.update(state=state, mrs=mrs)
    return emit(args, base, lines + [verdict], code)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def emit(args, data, lines, code):
    lines = cap_lines(lines)
    data["text"] = lines
    print(json.dumps(data, ensure_ascii=False, indent=2) if getattr(args, "json", False) else "\n".join(lines))
    return code


def cap_lines(lines):
    if len(lines) <= MAX_LINES:
        return lines
    return lines[:MAX_LINES - 2] + ["… +%d lines (use --json)" % (len(lines) - MAX_LINES + 1), lines[-1]]


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(64, "%s\n%s: error: %s\n" % (self.format_usage().rstrip(), self.prog, message))


def iso_date(text):
    if day(text) is None or not re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        raise argparse.ArgumentTypeError("not a YYYY-MM-DD date: %r" % text)
    return text


def wave_id(text):
    if text == "patch-minor" or re.match(r"^major:[A-Za-z0-9@][\w@./-]*$", text):
        return text
    raise argparse.ArgumentTypeError("a wave is patch-minor or major:<family>: %r" % text)


def build_parser():
    ap = Parser(prog="deps-check", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                allow_abbrev=False)
    ap.add_argument("--version", action="version", version="deps_check.py " + tool_version())
    sub = ap.add_subparsers(dest="command", metavar="{preflight,plan,changelog,context,status}", parser_class=Parser)
    sub.required = True
    common = dict(formatter_class=argparse.RawDescriptionHelpFormatter, allow_abbrev=False)

    def date_flag(p):
        p.add_argument("--date", type=iso_date, help="run date YYYY-MM-DD (default: today)")

    p = sub.add_parser("preflight", help="can a run start", description="can a dependency run start", **common)
    p.add_argument("repo")
    p.add_argument("--context", metavar="PATH")
    p.add_argument("--expect-email", metavar="ADDR")
    date_flag(p)
    p.add_argument("--offline", action="store_true")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("plan", help="the run plan", description="the dependency run plan", **common)
    p.add_argument("repo")
    p.add_argument("--context", metavar="PATH")
    p.add_argument("--offline", action="store_true")
    date_flag(p)
    p.add_argument("--max-majors", type=int, metavar="N")
    p.add_argument("--prioritize", metavar="a,b")
    p.add_argument("--routes", choices=("auto", "none"))
    p.add_argument("--scratch", metavar="DIR")
    p.add_argument("--json", action="store_true")
    p.add_argument("--write", action="store_true")
    p = sub.add_parser("changelog", help="the changelog entry or MR description of a wave",
                       description="the dependency changelog entry or MR description of a wave", **common)
    p.add_argument("repo")
    p.add_argument("--plan", required=True, metavar="FILE")
    p.add_argument("--wave", type=wave_id, metavar="ID")
    p.add_argument("--verify", action="append", metavar="KEY=VALUE")
    p.add_argument("--smoke", metavar="FILE")
    p.add_argument("--notes", metavar="FILE")
    p.add_argument("--path", metavar="REL")
    p.add_argument("--format", choices=("entry", "mr"), default="entry")
    p.add_argument("--check", action="store_true")
    p.add_argument("--offline", action="store_true")
    date_flag(p)
    p.add_argument("--json", action="store_true")
    p.add_argument("--write", action="store_true")
    p = sub.add_parser("context", help="render dependencies.md", description="render dependencies.md of the context skill", **common)
    p.add_argument("repo")
    p.add_argument("--context", metavar="PATH")
    p.add_argument("--plan", metavar="FILE")
    p.add_argument("--file", metavar="NAME")
    p.add_argument("--if-merged", action="store_true")
    p.add_argument("--scratch", metavar="DIR")
    p.add_argument("--offline", action="store_true")
    date_flag(p)
    p.add_argument("--json", action="store_true")
    p.add_argument("--write", action="store_true")
    p = sub.add_parser("status", help="the head pipeline of each dependency MR",
                       description="the head pipeline of each dependency MR", **common)
    p.add_argument("repo")
    p.add_argument("--branches", metavar="a,b")
    p.add_argument("--json", action="store_true")
    return ap


def validate(ap, args):
    if getattr(args, "date", "x") is None:
        args.date = datetime.date.today().isoformat()
    if args.command == "plan":
        if args.max_majors is not None and args.max_majors < 0:
            ap.error("--max-majors must be 0 or more")
        args.prioritize = [p.strip() for p in (args.prioritize or "").split(",") if p.strip()]
    if args.command == "changelog":
        if not args.check and not args.wave:
            ap.error("changelog needs --wave (or --check)")
        if args.check and (args.write or args.format == "mr"):
            ap.error("--check compares only: no --write, no --format mr")
        for pair in args.verify or []:
            if "=" not in pair or not pair.split("=", 1)[0].strip():
                ap.error("--verify takes KEY=VALUE, got %r" % pair)
        if args.path and (os.path.isabs(args.path) or os.pardir in re.split(r"[\\/]+", args.path)):
            ap.error("--path must be relative to the repo, without %s" % os.pardir)
    if args.command == "context" and args.file and (os.sep in args.file or "/" in args.file or not args.file.endswith(".md")):
        ap.error("--file is a file name ending in .md")


RUN = {"preflight": run_preflight, "plan": run_plan, "changelog": run_changelog, "context": run_context,
       "status": run_status}


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = None
    try:
        ap = build_parser()
        args = ap.parse_args(argv)
        validate(ap, args)
        return RUN[args.command](args)
    except Exception as exc:
        word = VERDICT_WORD.get(getattr(args, "command", None), "DEPS")
        line = "%s: unparsed (internal error: %s)" % (word, type(exc).__name__[:30])
        if args is not None and getattr(args, "json", False):
            print(json.dumps({"tool": "deps-check", "version": tool_version(), "command": args.command,
                              "state": "unparsed", "text": [line]}, ensure_ascii=False, indent=2))
        else:
            print(line)
        return 2


if __name__ == "__main__":
    sys.exit(main())
