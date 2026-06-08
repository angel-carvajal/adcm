#!/usr/bin/env python3
"""
Code Project Scanner — Analyzes a code project and produces a structured JSON
with stack, folder tree, entry points, conventions, and domain terms.

The output is designed to feed the generation of a
`code-project-context:[project-name]` skill with lazy-loading.

Usage:
    python3 scan_project.py <project_path> [--output report.json] [--max-depth 4]

The scanner is stack-agnostic — it detects Node/TS, PHP, Python, Go, Rust, Java, Ruby.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

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


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

class ProjectScanner:
    def __init__(self, root: Path, max_depth: int = 4):
        self.root = root
        self.max_depth = max_depth
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
        }
        self._symbol_counter: Counter[str] = Counter()
        # candidate files collected during the walk, processed by the detectors
        self._route_files: list[Path] = []
        self._model_files: list[Path] = []
        self._schema_files: list[Path] = []
        self._openapi_files: list[Path] = []
        self._test_dirs: set[str] = set()

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
        return self.result

    # ---- walker ----
    def _walk(self):
        for dirpath, dirnames, filenames in os.walk(self.root):
            # relative depth
            rel = Path(dirpath).relative_to(self.root)
            depth = 0 if str(rel) == "." else len(rel.parts)

            # filter subdirs
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
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

        # test files (PHPUnit uses PascalCase `*Test.php`; avoid matching latest.php etc.)
        if (".test." in flow or ".spec." in flow
                or flow.endswith(("_test.go", "_test.py", "_test.rb", "_spec.rb"))
                or (flow.startswith("test_") and ext == ".py")
                or (ext == ".php" and (fname.endswith("Test.php") or flow.endswith("_test.php")))):
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

    return 0


if __name__ == "__main__":
    sys.exit(main())
