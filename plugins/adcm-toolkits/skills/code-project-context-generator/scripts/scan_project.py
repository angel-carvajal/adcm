#!/usr/bin/env python3
"""
Code Project Scanner — Analyzes a code project and produces a structured JSON
with stack, folder tree, entry points, conventions, and domain terms.

The output is designed to feed the generation of a
`code-project-context-[project-name]` skill with lazy-loading.

Usage:
    python3 scan_project.py <project_path> [--output report.json] [--max-depth 4]
                            [--pretty] [--update path,path]

The scanner is stack-agnostic — it detects Node/TS, PHP, Python, Go, Rust, Java, Ruby.

Two blocks serve the lazy brain: `usage_map` (shared surfaces and who consumes them) and
`map` (candidates for the brain map: reusable `utilities`, repeated `patterns` and
`where_to_look` pointers). With --update the JSON also gains an `update` block naming the
affected folders, usage-map surfaces and map rows (`update.affected_map_rows`: utilities as
`symbol@path`, patterns by name), so a delta refresh revisits only those.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from dependency_manifest import attach_dependency_manifest, dependency_update_targets
except ImportError:
    attach_dependency_manifest = dependency_update_targets = None

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SKIP_DIRS = {
    ".git", ".hg", ".svn",
    "node_modules", "vendor", "bower_components",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".venv", "venv", "env", ".env.d",
    "dist", "build", "out", "target", ".next", ".nuxt", ".svelte-kit",
    "coverage", ".nyc_output",
    ".idea", ".vscode", ".vs",
    "storage", "tmp", "temp",
    ".terraform",
    ".gradle", ".m2",
    "DerivedData",
}

CONFIG_FILES = {
    # JS/TS
    "package.json": "node",
    "package-lock.json": "node",
    "pnpm-lock.yaml": "node",
    "yarn.lock": "node",
    "tsconfig.json": "typescript",
    "next.config.js": "next",
    "next.config.ts": "next",
    "next.config.mjs": "next",
    "vite.config.js": "vite",
    "vite.config.ts": "vite",
    "nuxt.config.js": "nuxt",
    "nuxt.config.ts": "nuxt",
    "angular.json": "angular",
    "vue.config.js": "vue",
    "svelte.config.js": "svelte",
    "astro.config.mjs": "astro",
    "remix.config.js": "remix",
    "tailwind.config.js": "tailwind",
    "tailwind.config.ts": "tailwind",
    "jest.config.js": "jest",
    "jest.config.ts": "jest",
    "vitest.config.ts": "vitest",
    "playwright.config.ts": "playwright",
    "cypress.config.js": "cypress",
    "cypress.config.ts": "cypress",
    # PHP
    "composer.json": "composer",
    "composer.lock": "composer",
    "phpunit.xml": "phpunit",
    "artisan": "laravel",
    # Python
    "requirements.txt": "pip",
    "pyproject.toml": "python",
    "Pipfile": "pipenv",
    "poetry.lock": "poetry",
    "setup.py": "python",
    "manage.py": "django",
    "pytest.ini": "pytest",
    # Go
    "go.mod": "go",
    "go.sum": "go",
    # Rust
    "Cargo.toml": "rust",
    "Cargo.lock": "rust",
    # Ruby
    "Gemfile": "ruby",
    "Gemfile.lock": "ruby",
    "Rakefile": "rake",
    # Java / Kotlin
    "pom.xml": "maven",
    "build.gradle": "gradle",
    "build.gradle.kts": "gradle",
    "settings.gradle": "gradle",
    # Infra
    "Dockerfile": "docker",
    "docker-compose.yml": "docker-compose",
    "docker-compose.yaml": "docker-compose",
    ".dockerignore": "docker",
    "Procfile": "heroku",
    "serverless.yml": "serverless",
    "terraform.tf": "terraform",
    "main.tf": "terraform",
    # CI/CD
    ".gitlab-ci.yml": "gitlab-ci",
    # Env
    ".env.example": "env",
    ".env.sample": "env",
    # Linters / formatters
    ".eslintrc.json": "eslint",
    ".eslintrc.js": "eslint",
    ".prettierrc": "prettier",
    ".prettierrc.json": "prettier",
    "biome.json": "biome",
    ".editorconfig": "editorconfig",
    "pylintrc": "pylint",
    ".ruff.toml": "ruff",
    "mypy.ini": "mypy",
    # Docs
    "README.md": "readme",
    "CHANGELOG.md": "changelog",
    "CONTRIBUTING.md": "docs",
    "LICENSE": "license",
}

# Extension → language mapping
EXT_LANG = {
    ".ts": "typescript", ".tsx": "typescript-jsx",
    ".js": "javascript", ".jsx": "javascript-jsx", ".mjs": "javascript", ".cjs": "javascript",
    ".py": "python",
    ".php": "php",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".java": "java", ".kt": "kotlin", ".scala": "scala",
    ".cs": "csharp",
    ".swift": "swift", ".m": "objc", ".mm": "objc",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".hpp": "cpp", ".cc": "cpp",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".sql": "sql",
    ".html": "html", ".htm": "html",
    ".css": "css", ".scss": "scss", ".sass": "sass", ".less": "less",
    ".vue": "vue", ".svelte": "svelte", ".astro": "astro",
    ".yml": "yaml", ".yaml": "yaml",
    ".json": "json", ".toml": "toml", ".xml": "xml",
    ".md": "markdown", ".mdx": "mdx",
    ".graphql": "graphql", ".gql": "graphql",
    ".proto": "protobuf",
}

# Folder purpose heuristics by folder name
FOLDER_PURPOSE_HINTS = {
    # Web/App
    "src": "main source code",
    "app": "application (entrypoint or app modules)",
    "lib": "reusable internal libraries",
    "pkg": "internal packages (Go convention)",
    "packages": "monorepo: packages",
    "apps": "monorepo: apps",
    "public": "static assets served as-is",
    "static": "static assets",
    "assets": "resources (images, fonts, etc.)",
    # Frontend
    "components": "reusable UI components",
    "pages": "pages/routes (Next, Nuxt, etc.)",
    "routes": "route definitions",
    "views": "views/screens",
    "layouts": "page layouts",
    "hooks": "custom React hooks",
    "composables": "Vue composables",
    "stores": "global state (Redux, Pinia, Zustand)",
    "styles": "global styles",
    "templates": "templates",
    # Backend
    "controllers": "HTTP controllers",
    "services": "business logic",
    "models": "data models / ORM",
    "entities": "domain entities",
    "repositories": "persistence access",
    "handlers": "event/request handlers",
    "middleware": "HTTP middleware",
    "middlewares": "HTTP middleware",
    "api": "API layer",
    "graphql": "GraphQL schema and resolvers",
    "resolvers": "GraphQL resolvers",
    "dto": "data transfer objects",
    "schemas": "validation schemas",
    "validators": "input validation",
    "policies": "policies/authorization",
    "guards": "route/auth guards",
    "jobs": "background jobs/queues",
    "workers": "async process workers",
    "tasks": "scheduled tasks",
    "commands": "CLI commands",
    "events": "events and listeners",
    "listeners": "event listeners",
    "notifications": "notifications",
    # Database
    "migrations": "database migrations",
    "seeders": "initial data seeders",
    "seeds": "database seeds",
    "fixtures": "test data",
    "factories": "factories for tests/seeds",
    # Config
    "config": "per-environment configuration",
    "configs": "configuration",
    "env": "environment variables",
    # Tests
    "test": "tests",
    "tests": "tests",
    "__tests__": "tests (Jest convention)",
    "spec": "test specs",
    "e2e": "end-to-end tests",
    "integration": "integration tests",
    "unit": "unit tests",
    # Infra / DevOps
    "docker": "Docker configuration",
    "infra": "infrastructure as code",
    "infrastructure": "infrastructure as code",
    "terraform": "Terraform modules",
    "k8s": "Kubernetes manifests",
    "kubernetes": "Kubernetes manifests",
    "helm": "Helm charts",
    ".github": "GitHub workflows and configs",
    ".gitlab": "GitLab configs",
    "ci": "CI configuration",
    "scripts": "administrative scripts/helpers",
    "tools": "internal tools",
    # Docs
    "docs": "documentation",
    "doc": "documentation",
    "documentation": "documentation",
    # Assets/Media
    "images": "images",
    "img": "images",
    "fonts": "typographic fonts",
    "locales": "i18n files",
    "i18n": "internationalization",
    "translations": "translations",
    # Utilities
    "utils": "generic utilities",
    "helpers": "helpers",
    "common": "shared code",
    "shared": "code shared across modules",
    "core": "core/base functionality",
    "types": "TypeScript types",
    "interfaces": "TypeScript interfaces",
    "constants": "constants",
    "enums": "enumerations",
}

# Extensions that count as "code" (for detecting conventions)
CODE_EXTS = {".ts", ".tsx", ".js", ".jsx", ".py", ".php", ".go", ".rs", ".rb", ".java", ".kt",
             ".cs", ".swift", ".c", ".cpp", ".vue", ".svelte", ".astro"}

# Folders whose contents are "shared surfaces": code consumed from elsewhere in the
# project. Exports defined here get a consumer census in `usage_map`.
SHARED_DIR_HINTS = {"shared", "lib", "libs", "packages", "components", "ui", "common",
                    "core", "utils", "helpers", "dpl", "design-system", "widgets"}

# Shared code for the map only: widening SHARED_DIR_HINTS would rewrite every documented usage map.
MAP_SHARED_HINTS = SHARED_DIR_HINTS | {"services", "api", "hooks", "models", "clients",
                                       "stores", "composables"}

# Test support code (page objects, fixtures, mocks) keeps ordinary file names inside these folders.
MAP_TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "e2e", "__mocks__"}

# A folder holding one of these manifests is an application of its own, not shared code.
APP_MANIFESTS = {"package.json", "composer.json", "go.mod", "pyproject.toml", "Cargo.toml"}

# An `api` folder directly under one of these holds route handlers, not a shared client layer.
ROUTE_TREE_PARENTS = {"app", "pages", "routes"}

# Symbols too generic to census (would match everywhere)
USAGE_STOPWORDS = {"default", "index", "types", "props", "main", "config", "utils",
                   "constants", "helpers", "common", "shared", "component", "module",
                   "service", "client", "server", "provider", "context", "state",
                   "data", "error", "value", "result", "options", "params", "styles"}

# Files consuming a shared surface are counted per symbol, listing up to:
USAGE_MAX_CONSUMER_PATHS = 15
USAGE_MAX_SURFACES = 50
USAGE_MAX_FILE_BYTES = 400_000

# The caps keep the brain map short enough to read before writing code.
MAP_MAX_UTILITIES = 40
MAP_MAX_PATTERNS = 20
MAP_MAX_EVIDENCE = 5
MAP_MAX_WHERE = 30
MAP_MAX_DOCS = 20
MAP_SIGNATURE_MAX = 80

# Utility kinds, most reusable first; the order also ranks rows when a cap cuts the list.
MAP_KINDS = ("abstract-class", "base-class", "generic-class", "generic-fn",
             "hook", "composable", "service", "helper")

# Language group by extension: it picks the declaration patterns that apply to a file.
MAP_LANG = {".ts": "ts", ".tsx": "ts", ".js": "ts", ".jsx": "ts", ".vue": "ts",
            ".svelte": "ts", ".astro": "ts", ".php": "php", ".java": "jvm", ".kt": "jvm",
            ".cs": "jvm", ".py": "py", ".go": "go"}

_NAME = r"(?P<name>[A-Za-z_$][\w$]*)"
_MODIFIERS = "public|protected|internal|private|static|final|sealed|open|data"
_ABSTRACT_RX = re.compile(
    r"^[ \t]*(?:export\s+)?(?:default\s+)?"
    r"(?:(?:" + _MODIFIERS + r")\s+)*"
    r"abstract\s+(?:partial\s+)?class\s+" + _NAME, re.M)
_BASE_RX = re.compile(r"\bclass\s+(?P<name>(?:Base|Abstract)[A-Z][\w$]*)")

# Declarations that make an export worth reusing, per language group, in MAP_KINDS order.
MAP_DECL_RX = {
    "ts": [
        ("abstract-class", _ABSTRACT_RX),
        ("base-class", _BASE_RX),
        ("generic-class", re.compile(
            r"\bexport\s+(?:default\s+)?(?:abstract\s+)?class\s+" + _NAME + r"\s*<")),
        ("generic-fn", re.compile(
            r"\bexport\s+(?:default\s+)?(?:async\s+)?function\s+" + _NAME + r"\s*<")),
        ("generic-fn", re.compile(
            r"\bexport\s+const\s+" + _NAME + r"\s*(?::[^=\n]{1,200})?=\s*(?:async\s+)?<")),
        ("hook", re.compile(
            r"\bexport\s+(?:default\s+)?(?:function|const)\s+(?P<name>use[A-Z][\w$]*)")),
        ("service", re.compile(
            r"@Injectable\s*\([^)]{0,200}\)\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+" + _NAME)),
        ("helper", re.compile(
            r"\bexport\s+(?:default\s+)?(?:async\s+)?function\s+(?P<name>[a-z][\w$]*)\s*[(<]")),
        ("helper", re.compile(
            r"\bexport\s+const\s+(?P<name>[a-z][\w$]*)\s*(?::[^=\n]{1,200})?="
            r"\s*(?:async\s+)?(?:\(|[A-Za-z_$][\w$]*\s*=>|function\b)")),
    ],
    "php": [("abstract-class", _ABSTRACT_RX), ("base-class", _BASE_RX)],
    "jvm": [("abstract-class", _ABSTRACT_RX), ("base-class", _BASE_RX)],
    "py": [
        ("abstract-class", re.compile(
            r"^class\s+" + _NAME + r"\s*\([^)\n]*\b(?:ABC|ABCMeta|Protocol)\b", re.M)),
        ("base-class", _BASE_RX),
        ("generic-class", re.compile(r"^class\s+" + _NAME + r"\s*\([^)\n]*\bGeneric\[", re.M)),
        ("helper", re.compile(r"^(?:async\s+)?def\s+(?P<name>[a-z]\w*)\s*\(", re.M)),
    ],
    "go": [("generic-fn", re.compile(r"^func\s+" + _NAME + r"\s*\[", re.M))],
}

# A class and what it extends. Kotlin and C# write the base after a colon, which cannot tell a base
# class from an interface, so only the `extends` keyword (and Python's base list) is read.
CLASS_HEAD_RX = re.compile(
    r"^[ \t]*(?:export\s+)?(?:default\s+)?"
    r"(?:(?:" + _MODIFIERS + r"|abstract|partial)\s+)*"
    r"class\s+(?!(?:extends|implements)\b)" + _NAME, re.M)
# The words that can stand between the start of a declaration and its name (`export default abstract class`),
# looked for at most DECL_LOOKBACK characters back.
DECL_HEAD_RX = re.compile(
    r"(?:(?<![\w$])(?:export|default|async|abstract|partial|class|function|const|def|func|"
    + _MODIFIERS + r")\s+)*$")
DECL_LOOKBACK = 64
EXTENDS_RX = re.compile(r"\s*extends\s+(?P<base>[A-Za-z_$\\][\w$.\\]*)")
ARROW_HEAD_RX = re.compile(r"[ \t]*(?::[^=\n]{1,200})?=[ \t]*(?:async\s+)?")
PY_CLASS_RX = re.compile(r"^class\s+(?P<name>[A-Za-z_]\w*)\s*(?:\((?P<bases>[^)\n]*)\))?", re.M)
PY_BASES_RX = re.compile(r"[ \t]*\(([^)\n]*)\)")
PY_NON_BASES = {"object", "ABC", "ABCMeta", "Protocol", "Generic"}

# TypeScript's built-in utility types: a hand-written variant of one of these is a missed reuse.
UTILITY_TYPES = ("Awaited", "Exclude", "Extract", "InstanceType", "NonNullable", "Omit",
                 "Parameters", "Partial", "Pick", "Readonly", "Record", "Required", "ReturnType")
UTILITY_TYPE_RX = re.compile(r"\b(" + "|".join(UTILITY_TYPES) + r")\s*<")

# The last word of a file name says what role it plays (providers.service.ts, ProviderForm.vue).
SHAPE_ROLES = ("service", "api", "store", "schema", "columns", "list", "form", "detail",
               "repository", "controller", "dto")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _symbol_ok(name: str) -> bool:
    """True for a name worth censusing: long enough, not a generic word, shaped like an identifier."""
    return (len(name) >= 4 and name.lower() not in USAGE_STOPWORDS
            and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", name) is not None)


def census_cmd(sym: str) -> str:
    """Shell one-liner that recounts the files mentioning `sym`, leaving out build and coverage output."""
    return (f"grep -rl '{sym}' . --exclude-dir=node_modules "
            "--exclude-dir=.git --exclude-dir=coverage --exclude-dir=reports "
            "--exclude-dir=dist --exclude-dir=.next | wc -l")


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _balanced(text: str, i: int, open_ch: str, close_ch: str, limit: int = 400) -> int:
    """Offset just past the bracket pair opening at text[i], or -1 when it does not close.

    The `>` of an arrow is not a closer and a `;` ends the search, so a comparison such as
    `a < b` cannot swallow the code after it.
    """
    depth = 0
    for j in range(i, min(len(text), i + limit)):
        ch = text[j]
        if ch == open_ch:
            depth += 1
        elif ch == close_ch and not (open_ch == "<" and text[j - 1] == "="):
            depth -= 1
            if depth == 0:
                return j + 1
        elif ch == ";":
            return -1
    return -1


def _type_params(text: str, i: int, open_ch: str = "<", close_ch: str = ">"):
    """Type parameters opening right after offset `i`: (`T extends Id`, offset past the clause)."""
    j = i
    while j < len(text) and text[j] in " \t":
        j += 1
    if j >= len(text) or text[j] != open_ch:
        return "", i
    end = _balanced(text, j, open_ch, close_ch)
    if end < 0:
        return "", i
    return _collapse(text[j + 1:end - 1]), end


def _generics_after(text: str, i: int, group: str) -> str:
    """Type parameters declared right after the name that ends at offset `i`."""
    if group == "py":
        bases = PY_BASES_RX.match(text, i)
        inner = bases.group(1) if bases else ""
        at = inner.find("Generic[")
        if at < 0:
            return ""
        start = at + len("Generic")
        end = _balanced(inner, start, "[", "]")
        return _collapse(inner[start + 1:end - 1]) if end > 0 else ""
    if group == "go":
        return _type_params(text, i, "[", "]")[0]
    if group == "ts":
        head = ARROW_HEAD_RX.match(text, i)  # `export const f = <T,>(...)` opens its type parameters after `=`
        i = head.end() if head else i
    return _type_params(text, i)[0]


def _signature(text: str, pos: int) -> str:
    """The declaration whose name sits at offset `pos`, from its first modifier to the end of its line.

    Whitespace is collapsed and the text cut at MAP_SIGNATURE_MAX. A declaration in the middle of a
    long line, or behind a long comment, still starts its own signature.
    """
    low = max(0, pos - DECL_LOOKBACK)
    newline = text.rfind("\n", low, pos)
    head = text[low if newline < 0 else newline + 1:pos]
    start = pos - len(head) + DECL_HEAD_RX.search(head).start()
    limit = start + 4 * MAP_SIGNATURE_MAX
    end = text.find("\n", pos, limit)
    line = re.sub(r"\s*[{:]$", "", _collapse(text[start:limit if end < 0 else end]))
    return line if len(line) <= MAP_SIGNATURE_MAX else line[:MAP_SIGNATURE_MAX - 1].rstrip() + "…"


def _split_bases(text: str) -> list[str]:
    """Split a Python base list on its top-level commas."""
    parts, depth, current = [], 0, ""
    for ch in text:
        depth += (ch in "([{") - (ch in ")]}")
        if ch == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += ch
    parts.append(current)
    return [p.strip() for p in parts if p.strip()]


def _classes_in(text: str, group: str):
    """Yield one dict per class declared in `text`: name, signature, generics and base names."""
    if group == "py":
        for hit in PY_CLASS_RX.finditer(text):
            bases = []
            for token in _split_bases(hit.group("bases") or ""):
                name = token.split("[", 1)[0].strip()
                if "=" not in token and name.rsplit(".", 1)[-1] not in PY_NON_BASES:
                    bases.append(name)
            yield {"name": hit.group("name"), "signature": _signature(text, hit.start("name")),
                   "generics": _generics_after(text, hit.end("name"), group), "bases": bases}
    elif group in ("ts", "php", "jvm"):
        for hit in CLASS_HEAD_RX.finditer(text):
            generics, after = _type_params(text, hit.end("name"))
            ext = EXTENDS_RX.match(text, after)
            base = ext.group("base").rsplit("\\", 1)[-1] if ext else None
            yield {"name": hit.group("name"), "signature": _signature(text, hit.start("name")),
                   "generics": generics, "bases": [base] if base else []}


def _shape_role(rel: str):
    """The role named by the last word of a file name (`providers.service.ts` is a service), else None."""
    stem = rel.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    words = re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+", stem)
    return words[-1].lower() if words and words[-1].lower() in SHAPE_ROLES else None


def _is_test_file(path: str) -> bool:
    """True for a file named like a test: *.test.*, *.spec.*, *_test.go, test_*.py, PHPUnit's *Test.php ...

    The testing block counts these files, and the map leaves them out: test code is neither a
    reusable export nor evidence of a pattern.
    """
    fname = os.path.basename(path)
    flow = fname.lower()
    ext = Path(fname).suffix.lower()
    # PHPUnit uses PascalCase `*Test.php`; avoid matching latest.php etc.
    return (".test." in flow or ".spec." in flow
            or flow.endswith(("_test.go", "_test.py", "_test.rb", "_spec.rb"))
            or (flow.startswith("test_") and ext == ".py")
            or (ext == ".php" and (fname.endswith("Test.php") or flow.endswith("_test.php"))))


def _map_excluded(rel: str) -> bool:
    """True for a file the map leaves out: one named like a test, or one inside a MAP_TEST_DIRS folder.

    Folders match by whole name, so `contest/` and `latest/` stay in.
    """
    return _is_test_file(rel) or not MAP_TEST_DIRS.isdisjoint(rel.split("/")[:-1])


def _within(rel: str, folders) -> bool:
    """True when the project-relative path `rel` is one of `folders` or lies below one."""
    return any(rel == f or rel.startswith(f + "/") for f in folders)


def _walkable(dirnames) -> list[str]:
    """The subfolders a walk descends into: none in SKIP_DIRS and none hidden."""
    return [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]


class _Row(dict):
    """A map row. `members` lists every file behind it; it is not a key, so the JSON never shows it."""


def _pattern(members, **row) -> dict:
    """A pattern row with the files behind it."""
    out = _Row(row)
    out.members = tuple(members)
    return out


def _cap_patterns(rows: list) -> list:
    """The rows to emit once more than MAP_MAX_PATTERNS qualify.

    The types row stays; the other slots go to families and shapes by turns, each ordered by size then
    name, so a project with many families still reports its shapes.
    """
    ranked = {kind: sorted((r for r in rows if r["kind"] == kind), key=lambda r: (-r["count"], r["name"]))
              for kind in ("family", "shape")}
    kept = [r for r in rows if r["kind"] == "types"][:1]
    for turn in range(max(len(q) for q in ranked.values())):
        kept.extend(q[turn] for q in ranked.values() if turn < len(q))
    order = {"family": 0, "shape": 1, "types": 2}
    return sorted(kept[:MAP_MAX_PATTERNS], key=lambda r: (order[r["kind"]], -r["count"], r["name"]))


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

class ProjectScanner:
    def __init__(self, root: Path, max_depth: int = 4, skip=()):
        """`skip` holds resolved directory paths that the docs sweep of the map leaves out."""
        self.root = root
        self.max_depth = max_depth
        self.skip = tuple(skip)
        self.result = {
            "meta": {
                "root": str(root),
                "name": root.name,
                "files_scanned": 0,
                "total_size_bytes": 0,
            },
            "stack": {
                "languages": {},         # ext count per language
                "frameworks": [],        # detected
                "runtimes": [],          # node, python, php, etc
                "package_managers": [],  # npm, pnpm, composer, pip, etc
            },
            "dependencies": {
                "node": {},
                "composer": {},
                "python": [],
                "go": [],
                "rust": [],
                "ruby": [],
            },
            "entry_points": {
                "scripts": {},           # package.json scripts, composer scripts
                "docker": [],            # Dockerfiles found
                "ci": [],                # CI configs
                "main_files": [],        # main.py, index.ts, artisan, manage.py
            },
            "configs": [],               # list of config files found
            "tree": {},                  # nested tree
            "folders": [],               # flat list with metadata
            "conventions": [],           # detected
            "domain_terms": [],          # glossary candidates
            "docs": [],                  # READMEs and docs found
            "api_surface": {             # detected endpoints/routes (Pipeline)
                "style": None,           # rest | graphql | mixed | None
                "endpoints": [],         # [{method, path, source}]
                "openapi": [],           # spec files found
                "count": 0,
            },
            "data_models": {             # entities/schema (Pipeline)
                "orm": None,
                "entities": [],          # detected model/entity names
                "migrations_count": 0,
                "schema_files": [],
            },
            "config_env": {              # .env.example vars (Pipeline; NO values)
                "files": [],
                "vars": [],              # [{name, comment, sensitive}]
            },
            "testing": {                 # test strategy (Pipeline)
                "frameworks": [],
                "test_dirs": [],
                "test_file_count": 0,
                "coverage_config": False,
                "ci_runs_tests": False,
            },
            "usage_map": {               # shared surfaces → consumer census
                "shared_roots": [],      # folders treated as shared code
                "surfaces": [],          # [{symbol, defined_in, consumers_count,
                                         #   consumers (sample), census_cmd}]
                "count": 0,
            },
            "map": {                     # reuse candidates for the lazy brain map
                "utilities": [],         # [{symbol, path, kind, signature, generics,
                                         #   consumers_count, exemplar}]
                "patterns": [],          # [{name, kind, status, evidence_paths, count,
                                         #   base, exemplar}]
                "where_to_look": [],     # [{topic, path}]
                "count": 0,              # rows across the three lists
            },
        }
        self._symbol_counter: Counter[str] = Counter()
        # candidate files collected during the walk, processed by the detectors
        self._route_files: list[Path] = []
        self._model_files: list[Path] = []
        self._schema_files: list[Path] = []
        self._openapi_files: list[Path] = []
        self._test_dirs: set[str] = set()
        self._source_files: list[tuple[Path, str]] = []  # (abs path, rel str) for usage_map

    # ---- main entry ----
    def scan(self) -> dict:
        if not self.root.exists():
            raise FileNotFoundError(f"Root does not exist: {self.root}")

        self._walk()
        self._detect_frameworks()
        self._build_tree()
        self._extract_domain_terms()
        self._detect_conventions()
        self._detect_api_surface()
        self._detect_data_models()
        self._detect_test_strategy()
        self._detect_usage_map()
        self._detect_map()
        if attach_dependency_manifest:
            attach_dependency_manifest(self.root, self.result, SKIP_DIRS)
        return self.result

    # ---- walker ----
    def _walk(self):
        for dirpath, dirnames, filenames in os.walk(self.root):
            # relative depth
            rel = Path(dirpath).relative_to(self.root)
            depth = 0 if str(rel) == "." else len(rel.parts)

            # filter subdirs
            dirnames[:] = _walkable(dirnames)
            # but let through relevant dot folders (.github, .gitlab)
            dirnames_lower_check = []
            for d in os.listdir(dirpath):
                full = os.path.join(dirpath, d)
                if os.path.isdir(full) and d in (".github", ".gitlab"):
                    if d not in dirnames:
                        dirnames.append(d)

            if depth > self.max_depth:
                dirnames[:] = []
                continue

            folder_info = {
                "path": str(rel) if str(rel) != "." else ".",
                "depth": depth,
                "file_count": 0,
                "size_bytes": 0,
                "extensions": Counter(),
                "config_files": [],
                "purpose_hint": self._infer_purpose(rel.name if str(rel) != "." else self.root.name),
            }

            for fname in filenames:
                fpath = Path(dirpath) / fname
                try:
                    size = fpath.stat().st_size
                except OSError:
                    continue

                self.result["meta"]["files_scanned"] += 1
                self.result["meta"]["total_size_bytes"] += size
                folder_info["file_count"] += 1
                folder_info["size_bytes"] += size

                ext = fpath.suffix.lower()
                if ext in EXT_LANG:
                    lang = EXT_LANG[ext]
                    folder_info["extensions"][ext] += 1
                    self.result["stack"]["languages"].setdefault(lang, 0)
                    self.result["stack"]["languages"][lang] += 1

                # config files
                if fname in CONFIG_FILES:
                    kind = CONFIG_FILES[fname]
                    folder_info["config_files"].append(fname)
                    self.result["configs"].append({
                        "path": str(fpath.relative_to(self.root)),
                        "kind": kind,
                    })
                    self._handle_config(fpath, kind)

                # Dockerfile variants
                if fname.startswith("Dockerfile"):
                    self.result["entry_points"]["docker"].append(str(fpath.relative_to(self.root)))

                # heuristic main files
                if fname in ("main.py", "manage.py", "artisan", "server.js", "server.ts",
                             "index.ts", "index.js", "app.py", "main.go", "main.rs", "main.ts"):
                    self.result["entry_points"]["main_files"].append(str(fpath.relative_to(self.root)))

                # docs
                if fname.lower() in ("readme.md", "readme.rst", "readme.txt", "readme"):
                    self.result["docs"].append(str(fpath.relative_to(self.root)))

                # collect symbols for glossary (only at reasonable depth)
                if depth <= 3 and ext in CODE_EXTS:
                    self._collect_symbols(fpath)

                # collect source files for the usage-map census
                if ext in CODE_EXTS and size <= USAGE_MAX_FILE_BYTES:
                    self._source_files.append((fpath, str(fpath.relative_to(self.root))))

                # collect candidate files for the auto-derived sections
                self._classify_file(fpath, rel, fname, ext)

            # CI in .github/workflows
            if rel.name == "workflows" and rel.parent.name == ".github":
                for fname in filenames:
                    if fname.endswith((".yml", ".yaml")):
                        self.result["entry_points"]["ci"].append(
                            str((Path(dirpath) / fname).relative_to(self.root)))

            folder_info["extensions"] = dict(folder_info["extensions"])
            if folder_info["file_count"] > 0 or str(rel) != ".":
                self.result["folders"].append(folder_info)

    # ---- heuristics ----
    def _infer_purpose(self, folder_name: str) -> str | None:
        fn = folder_name.lower()
        return FOLDER_PURPOSE_HINTS.get(fn)

    def _handle_config(self, path: Path, kind: str):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return

        if kind == "node" and path.name == "package.json":
            try:
                data = json.loads(text)
                self.result["dependencies"]["node"] = {
                    "deps": data.get("dependencies", {}),
                    "devDeps": data.get("devDependencies", {}),
                    "name": data.get("name"),
                    "version": data.get("version"),
                }
                if "scripts" in data:
                    self.result["entry_points"]["scripts"].update(
                        {f"npm:{k}": v for k, v in data["scripts"].items()})
                if "npm" not in self.result["stack"]["package_managers"]:
                    self.result["stack"]["package_managers"].append("npm")
                if "node" not in self.result["stack"]["runtimes"]:
                    self.result["stack"]["runtimes"].append("node")
            except json.JSONDecodeError:
                pass

        elif kind == "composer" and path.name == "composer.json":
            try:
                data = json.loads(text)
                self.result["dependencies"]["composer"] = {
                    "require": data.get("require", {}),
                    "require-dev": data.get("require-dev", {}),
                    "name": data.get("name"),
                }
                if "scripts" in data:
                    self.result["entry_points"]["scripts"].update(
                        {f"composer:{k}": str(v) for k, v in data["scripts"].items()})
                if "composer" not in self.result["stack"]["package_managers"]:
                    self.result["stack"]["package_managers"].append("composer")
                if "php" not in self.result["stack"]["runtimes"]:
                    self.result["stack"]["runtimes"].append("php")
            except json.JSONDecodeError:
                pass

        elif kind == "pip" and path.name == "requirements.txt":
            deps = [line.strip() for line in text.splitlines()
                    if line.strip() and not line.strip().startswith("#")]
            self.result["dependencies"]["python"].extend(deps)
            if "pip" not in self.result["stack"]["package_managers"]:
                self.result["stack"]["package_managers"].append("pip")
            if "python" not in self.result["stack"]["runtimes"]:
                self.result["stack"]["runtimes"].append("python")

        elif kind == "python" and path.name == "pyproject.toml":
            # lightweight parsing without tomllib
            deps = re.findall(r'^\s*"([^"]+)"\s*,?\s*$', text, re.MULTILINE)
            self.result["dependencies"]["python"].extend(deps[:50])
            if "python" not in self.result["stack"]["runtimes"]:
                self.result["stack"]["runtimes"].append("python")
            if "poetry" in text.lower() and "poetry" not in self.result["stack"]["package_managers"]:
                self.result["stack"]["package_managers"].append("poetry")

        elif kind == "go" and path.name == "go.mod":
            deps = re.findall(r'^\s*([\w./\-]+)\s+v[\d.]', text, re.MULTILINE)
            self.result["dependencies"]["go"] = deps
            if "go" not in self.result["stack"]["runtimes"]:
                self.result["stack"]["runtimes"].append("go")

        elif kind == "rust" and path.name == "Cargo.toml":
            deps = re.findall(r'^([\w\-]+)\s*=', text, re.MULTILINE)
            self.result["dependencies"]["rust"] = deps
            if "rust" not in self.result["stack"]["runtimes"]:
                self.result["stack"]["runtimes"].append("rust")

        elif kind == "ruby" and path.name == "Gemfile":
            deps = re.findall(r"gem\s+['\"]([\w\-]+)['\"]", text)
            self.result["dependencies"]["ruby"] = deps
            if "ruby" not in self.result["stack"]["runtimes"]:
                self.result["stack"]["runtimes"].append("ruby")

        elif kind == "env":
            # Parse .env.example / .env.sample: variable NAMES only (never values).
            rel = str(path.relative_to(self.root))
            self.result["config_env"]["files"].append(rel)
            pending_comment = None
            for line in text.splitlines():
                s = line.strip()
                if not s:
                    pending_comment = None
                    continue
                if s.startswith("#"):
                    pending_comment = s.lstrip("#").strip()
                    continue
                m = re.match(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$", s)
                if not m:
                    continue
                name = m.group(1)
                inline = m.group(2)
                # Extract an inline comment WITHOUT ever capturing the value:
                #  - quoted value  →  comment is whatever follows the closing quote
                #  - single-token unquoted value  →  `token # comment`
                #  - anything ambiguous (multi-word unquoted value, `#` inside the
                #    value, URL fragment) → no inline comment; fall back to the
                #    preceding full-line `#` comment.
                comment = None
                qm = re.match(r"""\s*(['"]).*?\1\s*(?:#\s*(.*))?$""", inline)
                if qm:
                    comment = (qm.group(2) or "").strip() or None
                else:
                    um = re.match(r"\s*\S+\s+#\s*(.+)$", inline)
                    if um:
                        comment = um.group(1).strip() or None
                comment = comment or pending_comment
                pending_comment = None
                if comment and not re.search(r"[A-Za-z0-9]", comment):
                    comment = None  # drop divider/punctuation-only lines
                sensitive = bool(re.search(
                    r"(KEY|SECRET|TOKEN|PASS(WORD)?|DSN|CREDENTIAL|PRIVATE|API|AUTH)",
                    name, re.I))
                if not any(v["name"] == name for v in self.result["config_env"]["vars"]):
                    self.result["config_env"]["vars"].append(
                        {"name": name, "comment": comment, "sensitive": sensitive})

    def _detect_frameworks(self):
        node_deps = {}
        if self.result["dependencies"]["node"]:
            node_deps.update(self.result["dependencies"]["node"].get("deps", {}))
            node_deps.update(self.result["dependencies"]["node"].get("devDeps", {}))

        composer_deps = {}
        if self.result["dependencies"]["composer"]:
            composer_deps.update(self.result["dependencies"]["composer"].get("require", {}))
            composer_deps.update(self.result["dependencies"]["composer"].get("require-dev", {}))

        python_deps = " ".join(self.result["dependencies"]["python"]).lower()

        detected = []

        # Frontend JS
        if "next" in node_deps: detected.append("Next.js")
        if "react" in node_deps: detected.append("React")
        if "vue" in node_deps: detected.append("Vue")
        if "nuxt" in node_deps: detected.append("Nuxt")
        if "@angular/core" in node_deps: detected.append("Angular")
        if "svelte" in node_deps: detected.append("Svelte")
        if "astro" in node_deps: detected.append("Astro")
        if "remix" in str(node_deps).lower(): detected.append("Remix")
        # Backend JS
        if "express" in node_deps: detected.append("Express")
        if "fastify" in node_deps: detected.append("Fastify")
        if "@nestjs/core" in node_deps: detected.append("NestJS")
        if "koa" in node_deps: detected.append("Koa")
        # Testing JS
        if "jest" in node_deps: detected.append("Jest")
        if "vitest" in node_deps: detected.append("Vitest")
        if "cypress" in node_deps: detected.append("Cypress")
        if "playwright" in node_deps or "@playwright/test" in node_deps: detected.append("Playwright")
        # DB / ORM JS
        if "prisma" in node_deps or "@prisma/client" in node_deps: detected.append("Prisma")
        if "typeorm" in node_deps: detected.append("TypeORM")
        if "sequelize" in node_deps: detected.append("Sequelize")
        if "drizzle-orm" in node_deps: detected.append("Drizzle")
        # CSS
        if "tailwindcss" in node_deps: detected.append("Tailwind")
        # State
        if "redux" in node_deps or "@reduxjs/toolkit" in node_deps: detected.append("Redux")
        if "zustand" in node_deps: detected.append("Zustand")

        # PHP
        if any(k.startswith("laravel/") for k in composer_deps): detected.append("Laravel")
        if any(k.startswith("symfony/") for k in composer_deps): detected.append("Symfony")
        if "phpunit/phpunit" in composer_deps: detected.append("PHPUnit")

        # Python
        if "django" in python_deps: detected.append("Django")
        if "fastapi" in python_deps: detected.append("FastAPI")
        if "flask" in python_deps: detected.append("Flask")
        if "pytest" in python_deps: detected.append("pytest")
        if "sqlalchemy" in python_deps: detected.append("SQLAlchemy")

        # Go frameworks (via detectable imports)
        go_deps = " ".join(self.result["dependencies"]["go"]).lower()
        if "gin-gonic/gin" in go_deps: detected.append("Gin")
        if "labstack/echo" in go_deps: detected.append("Echo")
        if "gofiber" in go_deps: detected.append("Fiber")

        self.result["stack"]["frameworks"] = sorted(set(detected))

    # ---- tree ----
    def _build_tree(self):
        tree: dict = {}
        for folder in self.result["folders"]:
            path = folder["path"]
            if path == ".":
                continue
            parts = path.split(os.sep)
            node = tree
            for p in parts:
                node = node.setdefault(p, {})
        self.result["tree"] = tree

    # ---- symbols / glossary ----
    def _collect_symbols(self, path: Path):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return
        # patterns: class, function, interface, type, model definitions
        patterns = [
            r"(?:class|interface|type|enum)\s+([A-Z][A-Za-z0-9_]+)",
            r"(?:function|def|fn)\s+([a-z_][A-Za-z0-9_]+)",
            r"(?:const|let|var)\s+([A-Z][A-Za-z0-9_]+)\s*=",
        ]
        for pat in patterns:
            for m in re.finditer(pat, text):
                name = m.group(1)
                if len(name) >= 4 and not name.startswith("_"):
                    self._symbol_counter[name] += 1

    def _extract_domain_terms(self):
        # Top 30 most frequent symbols, excluding generic names
        generic = {
            "Component", "Page", "Service", "Controller", "Model", "Props",
            "State", "Config", "Options", "Params", "Request", "Response",
            "Handler", "Context", "Provider", "Error", "Result", "Data",
            "Item", "List", "Map", "Set", "Array", "Object", "String", "Number",
            "Boolean", "Promise", "Observable", "Subject", "Event", "Value",
            "Test", "Spec", "Mock", "Stub", "Factory", "Builder",
        }
        top = [(name, count) for name, count in self._symbol_counter.most_common(60)
               if name not in generic and count >= 3]
        self.result["domain_terms"] = top[:30]

    # ---- conventions ----
    def _detect_conventions(self):
        conventions = []
        folder_names = {f["path"].split(os.sep)[0] for f in self.result["folders"] if f["path"] != "."}

        # Monorepo
        if "packages" in folder_names or "apps" in folder_names:
            conventions.append("Monorepo (packages/apps)")
        # MVC/Laravel
        if {"app"}.issubset(folder_names) and "artisan" in [c["path"].split("/")[-1] for c in self.result["configs"]]:
            conventions.append("Laravel MVC (app/Http, app/Models, etc.)")
        # Next.js App Router vs Pages Router
        if "Next.js" in self.result["stack"]["frameworks"]:
            if any(f["path"].startswith("app") for f in self.result["folders"]):
                conventions.append("Next.js App Router")
            if any(f["path"].startswith("pages") for f in self.result["folders"]):
                conventions.append("Next.js Pages Router")
        # Services + Controllers pattern
        if "services" in folder_names and ("controllers" in folder_names or "routes" in folder_names):
            conventions.append("Controllers → Services (logic in services/)")
        # Feature-based
        feature_dirs = [f for f in self.result["folders"]
                        if f["depth"] == 2 and f["path"].startswith(("src", "app"))
                        and f["purpose_hint"] is None]
        if len(feature_dirs) >= 3:
            conventions.append("Feature-based folders (src/feature-x, src/feature-y)")
        # Co-located tests
        if any(".test." in c["path"] or ".spec." in c["path"] for c in self.result["configs"]):
            conventions.append("Tests co-located next to the code (*.test.*, *.spec.*)")
        # TypeScript strict
        ts_configs = [c for c in self.result["configs"] if c["path"].endswith("tsconfig.json")]
        if ts_configs:
            conventions.append("TypeScript configured")
        # Docker
        if self.result["entry_points"]["docker"]:
            conventions.append(f"Dockerized ({len(self.result['entry_points']['docker'])} Dockerfile(s))")
        # CI
        if self.result["entry_points"]["ci"]:
            conventions.append(f"CI configured ({len(self.result['entry_points']['ci'])} workflow(s))")

        self.result["conventions"] = conventions

    # ---- candidate-file classification (feeds the auto-derived sections) ----
    def _classify_file(self, fpath: Path, rel: Path, fname: str, ext: str):
        folder = (rel.name or "").lower()
        parts = {p.lower() for p in rel.parts}
        frel = "/" + str(fpath.relative_to(self.root)).replace(os.sep, "/")
        flow = fname.lower()

        # routes / endpoints
        if len(self._route_files) < 80:
            is_route = (
                ("routes" in parts and ext == ".php")                       # Laravel
                or flow in ("route.ts", "route.js", "route.tsx", "route.jsx")  # Next.js app
                or ("/pages/api/" in frel or "/app/api/" in frel) and ext in (".ts", ".js", ".tsx", ".jsx")
                or (folder in ("routes", "controllers") and ext in CODE_EXTS)
                or (folder == "api" and ext in (".py", ".ts", ".js", ".php", ".go"))
                or flow.endswith((".controller.ts", ".controller.js", ".controller.tsx", ".controller.jsx"))  # NestJS
            )
            if is_route:
                self._route_files.append(fpath)

        # data models / entities
        if len(self._model_files) < 80:
            if (folder in ("models", "entities") and ext in (".php", ".py", ".ts", ".js", ".rb")) \
                    or flow == "models.py":
                self._model_files.append(fpath)

        # schema files (capped like the other collections; graphql is judged by
        # content later — collecting one client query file must not flip the style)
        if len(self._schema_files) < 80 and (
                flow == "schema.prisma" or ext in (".graphql", ".gql") or flow == "schema.sql"):
            self._schema_files.append(fpath)

        # openapi / swagger specs
        if re.match(r"(openapi|swagger)\.(json|ya?ml)$", flow):
            self._openapi_files.append(fpath)

        # test files
        if _is_test_file(fname):
            self.result["testing"]["test_file_count"] += 1
            self._test_dirs.add(str(rel) if str(rel) != "." else ".")

    # ---- API surface ----
    def _detect_api_surface(self):
        api = self.result["api_surface"]
        endpoints: list[dict] = []
        seen: set = set()

        def add(method: str, path_: str, source: str):
            key = (method.upper(), path_)
            if key in seen or len(endpoints) >= 150:
                return
            seen.add(key)
            endpoints.append({"method": method.upper(), "path": path_, "source": source})

        for fpath in self._route_files:
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            src = str(fpath.relative_to(self.root)).replace(os.sep, "/")
            for m in re.finditer(r"Route::(get|post|put|patch|delete|any|options)\s*\(\s*['\"]([^'\"]+)['\"]", text):
                add(m.group(1), m.group(2), src)
            for m in re.finditer(r"Route::(apiResource|resource)\s*\(\s*['\"]([^'\"]+)['\"]", text):
                add("RESOURCE", m.group(2), src)
            for m in re.finditer(r"\b(?:app|router|route)\.(get|post|put|patch|delete|all)\s*\(\s*['\"]([^'\"]+)['\"]", text):
                add(m.group(1), m.group(2), src)
            for m in re.finditer(r"@(Get|Post|Put|Patch|Delete)\(\s*['\"]?([^'\")]*)['\"]?\s*\)", text):
                add(m.group(1), "/" + m.group(2).lstrip("/"), src)
            for m in re.finditer(r"@(?:app|router)\.(get|post|put|patch|delete)\s*\(\s*['\"]([^'\"]+)['\"]", text):
                add(m.group(1), m.group(2), src)
            for m in re.finditer(r"@(?:app|bp|blueprint)\.route\s*\(\s*['\"]([^'\"]+)['\"]", text):
                add("ANY", m.group(1), src)
            if "/api/" in "/" + src or fpath.name.startswith("route."):
                for m in re.finditer(r"export\s+(?:async\s+)?(?:function|const)\s+(GET|POST|PUT|PATCH|DELETE)\b", text):
                    add(m.group(1), "/" + src, src)

        # GraphQL only if a collected .graphql/.gql file is an SDL *schema* (has a
        # root type or a `schema {` block) — not just a client query/fragment file.
        has_graphql = False
        for p in self._schema_files:
            if p.suffix.lower() not in (".graphql", ".gql"):
                continue
            try:
                gtext = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if re.search(r"\btype\s+(Query|Mutation|Subscription)\b|\bschema\s*\{", gtext):
                has_graphql = True
                break

        api["endpoints"] = endpoints
        api["count"] = len(endpoints)
        api["openapi"] = [str(p.relative_to(self.root)).replace(os.sep, "/") for p in self._openapi_files]
        has_rest = bool(endpoints) or bool(api["openapi"])
        api["style"] = ("mixed" if has_rest and has_graphql
                        else "graphql" if has_graphql
                        else "rest" if has_rest else None)

    # ---- data models ----
    def _detect_data_models(self):
        dm = self.result["data_models"]
        entities: list[str] = []
        orm = None

        def add_entity(name: str):
            if name and name not in entities and len(entities) < 200:
                entities.append(name)

        for fpath in self._schema_files:
            if fpath.name != "schema.prisma":
                continue
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            orm = orm or "Prisma"
            for m in re.finditer(r"^\s*model\s+(\w+)\s*\{", text, re.M):
                add_entity(m.group(1))

        for fpath in self._model_files:
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            is_php = fpath.suffix.lower() == ".php"
            for m in re.finditer(r"class\s+(\w+)\s+extends\s+(?:Model|Authenticatable|Pivot)\b", text):
                add_entity(m.group(1)); orm = orm or ("Eloquent" if is_php else "Sequelize")
            for m in re.finditer(r"class\s+(\w+)\s*\(\s*[\w.]*models\.Model", text):
                add_entity(m.group(1)); orm = orm or "Django ORM"
            for m in re.finditer(r"class\s+(\w+)\s*\(\s*(?:Base|db\.Model)\b", text):
                add_entity(m.group(1)); orm = orm or "SQLAlchemy"
            if "@Entity" in text:
                orm = orm or "TypeORM"
                for m in re.finditer(r"export\s+class\s+(\w+)", text):
                    add_entity(m.group(1))
            for m in re.finditer(r"(?:mongoose\.model|new\s+Schema)\s*\(\s*['\"](\w+)['\"]", text):
                add_entity(m.group(1)); orm = orm or "Mongoose"

        mig = 0
        for folder in self.result["folders"]:
            if folder["path"].split(os.sep)[-1].lower() == "migrations":
                mig += folder["file_count"]
        dm["orm"] = orm
        dm["entities"] = entities
        dm["migrations_count"] = mig
        dm["schema_files"] = [str(p.relative_to(self.root)).replace(os.sep, "/") for p in self._schema_files]

    # ---- testing strategy ----
    def _detect_test_strategy(self):
        t = self.result["testing"]
        test_fw = {"Jest", "Vitest", "Cypress", "Playwright", "PHPUnit", "pytest"}
        frameworks = [f for f in self.result["stack"]["frameworks"] if f in test_fw]
        # Also derive from config files directly — robust in modular monorepos where
        # per-module manifests overwrite the top-level framework detection.
        cfg_kind_to_fw = {"phpunit": "PHPUnit", "jest": "Jest", "vitest": "Vitest",
                          "cypress": "Cypress", "playwright": "Playwright", "pytest": "pytest"}
        for c in self.result["configs"]:
            fw = cfg_kind_to_fw.get(c["kind"])
            if fw and fw not in frameworks:
                frameworks.append(fw)
        composer = self.result["dependencies"].get("composer") or {}
        comp_all = {}
        if composer:
            comp_all.update(composer.get("require", {}))
            comp_all.update(composer.get("require-dev", {}))
        if "pestphp/pest" in comp_all and "Pest" not in frameworks:
            frameworks.append("Pest")
        t["frameworks"] = frameworks

        t["test_dirs"] = sorted(self._test_dirs)[:30]

        cov_kinds = {"jest", "vitest", "phpunit", "cypress", "playwright"}
        cov_names = {"pytest.ini", "tox.ini", ".coveragerc", "phpunit.xml"}
        configs = self.result["configs"]
        if any(c["kind"] in cov_kinds for c in configs) or any(
                os.path.basename(c["path"]) in cov_names for c in configs):
            t["coverage_config"] = True

        ci_files = list(self.result["entry_points"]["ci"])
        ci_files += [c["path"] for c in configs if c["kind"] == "gitlab-ci"]
        for ci in ci_files:
            try:
                text = (self.root / ci).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if re.search(r"\b(test|pytest|phpunit|jest|vitest|pest|playwright|coverage)\b", text, re.I):
                t["ci_runs_tests"] = True
                break

    def _shared_roots(self, hints, guard=False):
        """Shallowest folders named in `hints` that hold files of their own.

        With `guard`, a folder that is a whole application is dropped: one with a manifest of
        its own, anything inside apps/<app>/, or an `api` folder inside a route tree.
        """
        candidates = []
        for f in self.result["folders"]:
            path = f["path"]
            if path == "." or f["file_count"] == 0:
                continue
            name = Path(path).name.lower()
            if name not in hints:
                continue
            if guard:
                ancestors = [p.lower() for p in Path(path).parent.parts]
                parent = ancestors[-1] if ancestors else ""
                if (APP_MANIFESTS.intersection(f["config_files"]) or "apps" in ancestors
                        or (name == "api" and parent in ROUTE_TREE_PARENTS)):
                    continue
            candidates.append(path)
        # keep the shallowest roots; a shared dir nested in another adds nothing
        roots: list[str] = []
        for path in sorted(set(candidates), key=lambda p: (p.count("/"), p)):
            if not _within(path, roots):
                roots.append(path)
        return roots

    def _census(self, symbols, skip, files=None, rank=None):
        """Count the source files that mention each symbol and sample their paths.

        `skip(rel, sym)` is True for a file that must not count as a consumer of `sym`; `files`
        defaults to every source file in scan order. `rank(rel)`, lower first, picks the consumer a
        symbol leads with. Returns (counts, consumers, lead): files per symbol, up to
        USAGE_MAX_CONSUMER_PATHS paths per symbol in `files` order, and the best-ranked consumer
        of each symbol among all of them (the first one on a tie; empty without `rank`).
        """
        consumers: dict[str, list[str]] = {s: [] for s in symbols}
        counts: Counter[str] = Counter()
        best: dict[str, tuple] = {}
        if not symbols:
            return counts, consumers, {}
        for fpath, rel in (self._source_files if files is None else files):
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            ranked = None
            for sym in symbols:
                if sym not in text or skip(rel, sym):
                    continue
                counts[sym] += 1
                if len(consumers[sym]) < USAGE_MAX_CONSUMER_PATHS:
                    consumers[sym].append(rel)
                if rank:
                    ranked = rank(rel) if ranked is None else ranked
                    if sym not in best or ranked < best[sym][0]:
                        best[sym] = (ranked, rel)
        return counts, consumers, {sym: rel for sym, (_, rel) in best.items()}

    # ---- usage map: shared surfaces → consumer census ----
    def _detect_usage_map(self):
        """Find symbols exported from shared folders and census who consumes them.

        This is what makes impact analysis cheap downstream: "this component is
        rendered by 10 more pages" becomes a lookup, not a re-derivation.
        """
        um = self.result["usage_map"]

        roots = self._shared_roots(SHARED_DIR_HINTS)
        um["shared_roots"] = roots
        if not roots or not self._source_files:
            return

        export_patterns = [
            re.compile(r"export\s+(?:default\s+)?(?:abstract\s+)?(?:async\s+)?"
                       r"(?:function|class|const|interface|type|enum)\s+([A-Za-z_][A-Za-z0-9_]*)"),
            re.compile(r"selector:\s*['\"]([a-z][a-z0-9-]{3,})['\"]"),
            re.compile(r"^(?:export\s+)?(?:abstract\s+)?class\s+([A-Z][A-Za-z0-9_]{3,})", re.M),
        ]
        named_exports = re.compile(r"export\s*\{([^}]+)\}")

        defined: dict[str, str] = {}  # symbol → defining rel path (first seen)

        def add_symbol(name: str, rel: str):
            name = name.strip()
            if name in defined or not _symbol_ok(name):
                return
            defined[name] = rel

        for fpath, rel in self._source_files:
            if not _within(rel, roots):
                continue
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for rx in export_patterns:
                for m in rx.finditer(text):
                    add_symbol(m.group(1), rel)
            for m in named_exports.finditer(text):
                for part in m.group(1).split(","):
                    add_symbol(part.strip().split(" as ")[-1], rel)

        if not defined:
            return

        counts, consumers, _ = self._census(sorted(defined), lambda rel, sym: _within(rel, roots))

        surfaces = []
        for sym, n in counts.most_common(USAGE_MAX_SURFACES):
            surfaces.append({
                "symbol": sym,
                "defined_in": defined[sym],
                "consumers_count": n,
                "consumers": consumers[sym],
                "census_cmd": census_cmd(sym),
            })
        um["surfaces"] = surfaces
        um["count"] = len(surfaces)

    # ---- map: reuse candidates for the brain map ----
    def _detect_map(self):
        """Candidate rows for the lazy brain map: reusable utilities, repeated patterns, where docs live.

        Every emitted list is sorted, so the same tree always yields the same rows.
        """
        m = self.result["map"]
        # sorted copy: first-seen picks must not follow listing order; the usage census keeps scan order
        files = sorted(self._source_files, key=lambda item: item[1])
        # only the map-only roots drop nested applications, so `shared` stays the usage map's roots
        shared = self._shared_roots(SHARED_DIR_HINTS)
        mapped = self._shared_roots(MAP_SHARED_HINTS - SHARED_DIR_HINTS, guard=True)
        nested_apps = [f["path"] for f in self.result["folders"]
                       if APP_MANIFESTS.intersection(f["config_files"]) and _within(f["path"], mapped)]

        def under(rel: str) -> bool:
            return _within(rel, shared) or (_within(rel, mapped) and not _within(rel, nested_apps))

        classes, decls, type_counts, type_files = self._map_read(under, files)
        local = {c["name"] for c in classes}
        extenders: dict[str, dict[tuple, dict]] = defaultdict(dict)
        for c in classes:
            for base in c["bases"]:
                if base in local and base != c["name"]:
                    extenders[base][(c["name"], c["rel"])] = c
        families = {base: [found[k] for k in sorted(found)]
                    for base, found in sorted(extenders.items()) if len(found) >= 2}
        m["utilities"] = self._map_utilities(under, classes, decls, families, files)
        m["patterns"] = self._map_patterns(classes, local, families, type_counts, type_files, files)
        m["where_to_look"] = self._map_where()
        m["count"] = len(m["utilities"]) + len(m["patterns"]) + len(m["where_to_look"])

    def _map_read(self, under, files):
        """Read each non-test source of `files` once; `under(rel)` says whether a file sits in a shared root.

        Returns every class with its bases, the MAP_DECL_RX declarations (functions only under
        shared roots) and how often, and where, TypeScript utility types are used.
        """
        composables = bool({"Vue", "Nuxt"}.intersection(self.result["stack"]["frameworks"]))
        classes: list[dict] = []
        decls: dict[tuple, dict] = {}
        type_counts: Counter[str] = Counter()
        type_files: Counter[str] = Counter()
        for fpath, rel in files:
            ext = fpath.suffix.lower()
            group = MAP_LANG.get(ext)
            if group is None or _map_excluded(rel):
                continue
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            shared = under(rel)
            as_composable = composables or "composables" in rel.split("/")
            classes.extend(dict(c, rel=rel) for c in _classes_in(text, group))
            for kind, rx in MAP_DECL_RX.get(group, ()):
                if not shared and kind in ("generic-fn", "hook", "helper"):
                    continue
                row_kind = "composable" if kind == "hook" and as_composable else kind
                for hit in rx.finditer(text):
                    name = hit.group("name")
                    held = decls.get((name, rel))
                    if not _symbol_ok(name) or (
                            held and MAP_KINDS.index(held["kind"]) <= MAP_KINDS.index(row_kind)):
                        continue
                    decls[(name, rel)] = {
                        "symbol": name, "path": rel, "kind": row_kind,
                        "signature": _signature(text, hit.start("name")),
                        "generics": _generics_after(text, hit.end("name"), group)}
            if ext in (".ts", ".tsx"):
                for hit in UTILITY_TYPE_RX.finditer(text):
                    type_counts[hit.group(1)] += 1
                    type_files[rel] += 1
        return classes, decls, type_counts, type_files

    def _map_utilities(self, under, classes, decls, families, files):
        """Reusable exports under shared roots, plus every class that heads a family."""
        cands = {key: d for key, d in decls.items() if under(d["path"]) or d["symbol"] in families}
        for c in classes:
            key = (c["name"], c["rel"])
            if c["name"] in families and key not in cands and _symbol_ok(c["name"]):
                cands[key] = {"symbol": c["name"], "path": c["rel"], "kind": "base-class",
                              "signature": c["signature"], "generics": c["generics"]}
        defining: dict[str, set] = defaultdict(set)
        for d in cands.values():
            defining[d["symbol"]].add(d["path"])

        def lead(rel: str) -> int:
            """Lower leads: 0 a consumer to copy from (not a test, outside the shared roots), 1 a non-test
            inside them, 2 a test, by name or by folder."""
            return 2 if _map_excluded(rel) else int(under(rel))

        counts, _, exemplars = self._census(
            sorted(defining), lambda rel, sym: rel in defining[sym], files, lead)

        rows = []
        for key in sorted(cands):
            d = cands[key]
            n = counts[d["symbol"]]
            if d["kind"] == "helper" and n < 2:
                continue
            rows.append({"symbol": d["symbol"], "path": d["path"], "kind": d["kind"],
                         "signature": d["signature"], "generics": d["generics"],
                         "consumers_count": n, "exemplar": exemplars.get(d["symbol"])})
        rows.sort(key=lambda r: (MAP_KINDS.index(r["kind"]), -r["consumers_count"],
                                 r["symbol"], r["path"]))
        return rows[:MAP_MAX_UTILITIES]

    def _map_patterns(self, classes, local, families, type_counts, type_files, files):
        """Families sharing a local base, file shapes that repeat, and TypeScript utility types in use.

        A row lists at most MAP_MAX_EVIDENCE paths but keeps every file behind it as `members`.
        """
        bases_by_file: dict[str, set] = defaultdict(set)
        defined_in: dict[str, set] = defaultdict(set)
        for c in classes:
            bases_by_file[c["rel"]].update(b for b in c["bases"] if b in local)
            defined_in[c["name"]].add(c["rel"])
        rows = []
        for base, found in families.items():
            paths = sorted({c["rel"] for c in found})
            rows.append(_pattern(paths, name=f"family:{base}", kind="family", status="applied",
                                 evidence_paths=paths[:MAP_MAX_EVIDENCE], count=len(found),
                                 base=base, exemplar=paths[0]))
        roles: dict[str, set] = defaultdict(set)
        for _, rel in files:
            role = _shape_role(rel)
            if role and not _map_excluded(rel):
                roles[role].add(rel)
        for role in sorted(roles):
            tally = Counter(b for rel in roles[role] for b in bases_by_file.get(rel, ()))
            base = min(tally, key=lambda b: (-tally[b], b)) if tally else None
            # the file that defines the base is its source, not one more use of it
            members = sorted(rel for rel in roles[role] if rel not in defined_in.get(base, ()))
            if len(members) < 3:
                continue
            k = sum(base in bases_by_file.get(rel, ()) for rel in members)
            if k == 0:
                base, status = None, "candidate (no shared base) · signal only — same-behaviour test decides"
            elif 2 * k >= len(members):
                status = "applied"
            else:
                status = f"partial {k}/{len(members)}"
            rows.append(_pattern(members, name=f"shape:{role}", kind="shape", status=status,
                                 evidence_paths=members[:MAP_MAX_EVIDENCE], count=len(members),
                                 base=base, exemplar=next(
                                     (rel for rel in members if base in bases_by_file.get(rel, ())),
                                     members[0])))
        if type_counts:
            by_type = sorted(type_counts.items(), key=lambda kv: (-kv[1], kv[0]))
            by_file = sorted(type_files.items(), key=lambda kv: (-kv[1], kv[0]))
            rows.append(_pattern(sorted(type_files), name="types:utility", kind="types", status="applied",
                                 evidence_paths=sorted(p for p, _ in by_file[:MAP_MAX_EVIDENCE]),
                                 count=sum(type_counts.values()),
                                 base=" · ".join(f"{name} {n}" for name, n in by_type),
                                 exemplar=by_file[0][0]))
        return _cap_patterns(rows)

    def _map_where(self):
        """Repo-level pointers: README, agent instructions, docs/ pages (minus the `skip` dirs) and API specs."""
        def rel_of(path) -> str:
            return os.path.relpath(path, self.root).replace(os.sep, "/")

        def title(rel: str) -> str:
            try:
                head = (self.root / rel).read_text(encoding="utf-8", errors="ignore")[:2000]
            except OSError:
                head = ""
            heading = re.search(r"^#[ \t]+(.+?)[ \t#]*$", head, re.M)
            return heading.group(1) if heading else re.sub(r"[-_]+", " ", Path(rel).stem).strip()

        topics: dict[str, str] = {}
        try:
            names = sorted(os.listdir(self.root))
        except OSError:
            names = []
        for name in names:
            low = name.lower()
            topic = ("Project README" if low.startswith("readme") else
                     "Claude instructions" if low == "claude.md" else
                     "Agent instructions" if low == "agents.md" else None)
            if topic and (self.root / name).is_file():
                topics[name] = topic
        docs = []
        for dirpath, dirnames, filenames in os.walk(self.root / "docs"):
            dirnames[:] = [d for d in _walkable(dirnames) if Path(dirpath, d).resolve() not in self.skip]
            docs.extend(rel_of(os.path.join(dirpath, f)) for f in filenames if f.lower().endswith(".md"))
        for rel in sorted(docs)[:MAP_MAX_DOCS]:
            topics.setdefault(rel, title(rel))
        for spec in self._openapi_files:
            topics.setdefault(rel_of(spec), "OpenAPI spec")
        return [{"topic": topic, "path": path} for path, topic in sorted(topics.items())][:MAP_MAX_WHERE]


def delta(result: dict, changed: list[str]) -> dict:
    """The `update` block for the project-relative paths in `changed`: what a delta refresh revisits."""
    def touched(path: str) -> bool:
        return _within(path, changed)

    def touches(folder_path: str) -> bool:
        return touched(folder_path) or any(_within(p, (folder_path,)) for p in changed)

    affected_folders = sorted({f["path"] for f in result["folders"]
                               if f["path"] != "." and touches(f["path"])})
    affected_surfaces = sorted({
        s["symbol"] for s in result["usage_map"]["surfaces"]
        if touched(s["defined_in"]) or any(touched(c) for c in s["consumers"])
    })
    rows = result["map"]
    affected_map_rows = {
        "utilities": sorted(f"{u['symbol']}@{u['path']}" for u in rows["utilities"]
                            if touched(u["path"]) or (u["exemplar"] and touched(u["exemplar"]))),
        "patterns": sorted(pat["name"] for pat in rows["patterns"]
                           if any(touched(e) for e in getattr(pat, "members", pat["evidence_paths"]))
                           or (pat["exemplar"] and touched(pat["exemplar"]))),
    }
    return {
        "paths": changed,
        "affected_folders": affected_folders,
        "affected_surfaces": affected_surfaces,
        "affected_map_rows": affected_map_rows,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    # Requires Python 3 (stdlib only). The f-strings and type hints in this file
    # would already fail in Python 2, but we give a clear message just in case.
    if sys.version_info[0] < 3:
        sys.stderr.write("Error: this scanner requires Python 3.\n")
        return 2

    parser = argparse.ArgumentParser(description="Scans a project and produces a structured JSON.")
    parser.add_argument("path", help="Absolute path to the project")
    parser.add_argument("--output", "-o", default="-",
                        help="Output file (default: stdout)")
    parser.add_argument("--max-depth", type=int, default=4,
                        help="Maximum tree depth (default: 4)")
    parser.add_argument("--pretty", action="store_true", help="Output with indentation")
    parser.add_argument("--update", default=None, metavar="PATHS",
                        help="Comma-separated project-relative paths that changed "
                             "(e.g. after a closed wave). Adds an 'update' block to the "
                             "JSON naming the affected folders and usage-map surfaces, "
                             "so the context skill refreshes ONLY those files "
                             "(delta refresh) instead of regenerating everything.")
    args = parser.parse_args()

    root = Path(args.path).expanduser().resolve()
    if not root.exists():
        sys.stderr.write(f"Error: path '{root}' does not exist.\n")
        return 1
    if not root.is_dir():
        sys.stderr.write(f"Error: path '{root}' is not a directory.\n")
        return 1
    if not os.access(root, os.R_OK):
        sys.stderr.write(f"Error: path '{root}' is not readable (permissions).\n")
        return 1

    scanner = ProjectScanner(root, max_depth=args.max_depth)
    try:
        result = scanner.scan()
    except FileNotFoundError as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1
    except OSError as exc:
        sys.stderr.write(f"Error scanning the project: {exc}\n")
        return 1

    if args.update:
        changed = [p.strip().strip("/") for p in args.update.split(",") if p.strip()]
        result["update"] = delta(result, changed)
        if dependency_update_targets:
            result["update"]["affected_context_files"] = dependency_update_targets(changed)

    out = json.dumps(result, indent=2 if args.pretty else None, ensure_ascii=False, default=str)

    if args.output == "-":
        print(out)
    else:
        try:
            Path(args.output).write_text(out, encoding="utf-8")
        except OSError as exc:
            sys.stderr.write(f"Error: could not write the output to '{args.output}': {exc}\n")
            return 1
        print(f"✓ Scan saved to {args.output}", file=sys.stderr)
        print(f"  - Files scanned: {result['meta']['files_scanned']}", file=sys.stderr)
        print(f"  - Detected languages: {list(result['stack']['languages'].keys())}", file=sys.stderr)
        print(f"  - Frameworks: {result['stack']['frameworks']}", file=sys.stderr)
        print(f"  - Top-level folders: {len([f for f in result['folders'] if f['depth'] == 1])}", file=sys.stderr)
        print(f"  - API endpoints: {result['api_surface']['count']} (style: {result['api_surface']['style']})", file=sys.stderr)
        print(f"  - Data models: {len(result['data_models']['entities'])} "
              f"(orm: {result['data_models']['orm']}, migrations: {result['data_models']['migrations_count']})", file=sys.stderr)
        print(f"  - Env vars: {len(result['config_env']['vars'])}", file=sys.stderr)
        print(f"  - Test files: {result['testing']['test_file_count']} "
              f"(frameworks: {result['testing']['frameworks']})", file=sys.stderr)
        print(f"  - Shared surfaces (usage map): {result['usage_map']['count']} "
              f"(roots: {result['usage_map']['shared_roots']})", file=sys.stderr)
        print(f"  - Map candidates: utilities {len(result['map']['utilities'])} · "
              f"patterns {len(result['map']['patterns'])} · "
              f"where {len(result['map']['where_to_look'])}", file=sys.stderr)
        if "update" in result:
            print(f"  - Delta update: {len(result['update']['affected_folders'])} folders, "
                  f"{len(result['update']['affected_surfaces'])} surfaces affected", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
