#!/usr/bin/env python3
"""
Code Project Scanner — Analiza un proyecto de código y produce un JSON estructurado
con stack, árbol de carpetas, entry points, convenciones y términos de dominio.

El output está diseñado para alimentar la generación de un skill
`code-project-context:[project-name]` con lazy-loading.

Uso:
    python3 scan_project.py <project_path> [--output report.json] [--max-depth 4]

El scanner es agnóstico de stack — detecta Node/TS, PHP, Python, Go, Rust, Java, Ruby.
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
# Configuración
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

# Mapeo de extensión → lenguaje
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

# Heurísticas de propósito por nombre de carpeta
FOLDER_PURPOSE_HINTS = {
    # Web/App
    "src": "código fuente principal",
    "app": "aplicación (entrypoint o módulos de app)",
    "lib": "librerías internas reutilizables",
    "pkg": "paquetes internos (convención Go)",
    "packages": "monorepo: paquetes",
    "apps": "monorepo: apps",
    "public": "assets estáticos servidos tal cual",
    "static": "assets estáticos",
    "assets": "recursos (imágenes, fuentes, etc.)",
    # Frontend
    "components": "componentes UI reutilizables",
    "pages": "páginas/rutas (Next, Nuxt, etc.)",
    "routes": "definición de rutas",
    "views": "vistas/pantallas",
    "layouts": "layouts de página",
    "hooks": "React hooks personalizados",
    "composables": "composables de Vue",
    "stores": "estado global (Redux, Pinia, Zustand)",
    "styles": "estilos globales",
    "templates": "plantillas",
    # Backend
    "controllers": "controladores HTTP",
    "services": "lógica de negocio",
    "models": "modelos de datos / ORM",
    "entities": "entidades de dominio",
    "repositories": "acceso a persistencia",
    "handlers": "handlers de eventos/requests",
    "middleware": "middleware HTTP",
    "middlewares": "middleware HTTP",
    "api": "capa de API",
    "graphql": "schema y resolvers GraphQL",
    "resolvers": "resolvers GraphQL",
    "dto": "data transfer objects",
    "schemas": "esquemas de validación",
    "validators": "validaciones de input",
    "policies": "policies/authorization",
    "guards": "guards de rutas/auth",
    "jobs": "jobs en background/queues",
    "workers": "workers de procesos async",
    "tasks": "tareas programadas",
    "commands": "comandos CLI",
    "events": "eventos y listeners",
    "listeners": "event listeners",
    "notifications": "notificaciones",
    # Database
    "migrations": "migraciones de base de datos",
    "seeders": "seeders de datos iniciales",
    "seeds": "seeds de base de datos",
    "fixtures": "datos de prueba",
    "factories": "factories para tests/seeds",
    # Config
    "config": "configuración por entorno",
    "configs": "configuración",
    "env": "variables de entorno",
    # Tests
    "test": "tests",
    "tests": "tests",
    "__tests__": "tests (convención Jest)",
    "spec": "specs de tests",
    "e2e": "tests end-to-end",
    "integration": "tests de integración",
    "unit": "tests unitarios",
    # Infra / DevOps
    "docker": "configuración de Docker",
    "infra": "infraestructura como código",
    "infrastructure": "infraestructura como código",
    "terraform": "módulos de Terraform",
    "k8s": "manifiestos de Kubernetes",
    "kubernetes": "manifiestos de Kubernetes",
    "helm": "charts de Helm",
    ".github": "workflows y configs de GitHub",
    ".gitlab": "configs de GitLab",
    "ci": "configuración de CI",
    "scripts": "scripts administrativos/helpers",
    "tools": "herramientas internas",
    # Docs
    "docs": "documentación",
    "doc": "documentación",
    "documentation": "documentación",
    # Assets/Media
    "images": "imágenes",
    "img": "imágenes",
    "fonts": "fuentes tipográficas",
    "locales": "archivos de i18n",
    "i18n": "internacionalización",
    "translations": "traducciones",
    # Utilities
    "utils": "utilidades genéricas",
    "helpers": "helpers",
    "common": "código compartido",
    "shared": "código compartido entre módulos",
    "core": "funcionalidad core/base",
    "types": "tipos TypeScript",
    "interfaces": "interfaces TypeScript",
    "constants": "constantes",
    "enums": "enumeraciones",
}

# Extensiones que cuentan como "código" (para detectar convenciones)
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
                "languages": {},         # ext count por lenguaje
                "frameworks": [],        # detectados
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
                "docker": [],            # Dockerfiles encontrados
                "ci": [],                # CI configs
                "main_files": [],        # main.py, index.ts, artisan, manage.py
            },
            "configs": [],               # lista de archivos config encontrados
            "tree": {},                  # árbol anidado
            "folders": [],               # lista plana con metadata
            "conventions": [],           # detectadas
            "domain_terms": [],          # candidatos a glosario
            "docs": [],                  # READMEs y docs encontrados
        }
        self._symbol_counter: Counter[str] = Counter()

    # ---- main entry ----
    def scan(self) -> dict:
        if not self.root.exists():
            raise FileNotFoundError(f"Root no existe: {self.root}")

        self._walk()
        self._detect_frameworks()
        self._build_tree()
        self._extract_domain_terms()
        self._detect_conventions()
        return self.result

    # ---- walker ----
    def _walk(self):
        for dirpath, dirnames, filenames in os.walk(self.root):
            # depth relativo
            rel = Path(dirpath).relative_to(self.root)
            depth = 0 if str(rel) == "." else len(rel.parts)

            # filtrar subdirs
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            # pero dejar pasar carpetas dot relevantes (.github, .gitlab)
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

                # main files heurísticos
                if fname in ("main.py", "manage.py", "artisan", "server.js", "server.ts",
                             "index.ts", "index.js", "app.py", "main.go", "main.rs", "main.ts"):
                    self.result["entry_points"]["main_files"].append(str(fpath.relative_to(self.root)))

                # docs
                if fname.lower() in ("readme.md", "readme.rst", "readme.txt", "readme"):
                    self.result["docs"].append(str(fpath.relative_to(self.root)))

                # recolectar símbolos para glosario (solo a profundidad razonable)
                if depth <= 3 and ext in CODE_EXTS:
                    self._collect_symbols(fpath)

            # CI en .github/workflows
            if rel.name == "workflows" and rel.parent.name == ".github":
                for fname in filenames:
                    if fname.endswith((".yml", ".yaml")):
                        self.result["entry_points"]["ci"].append(
                            str((Path(dirpath) / fname).relative_to(self.root)))

            folder_info["extensions"] = dict(folder_info["extensions"])
            if folder_info["file_count"] > 0 or str(rel) != ".":
                self.result["folders"].append(folder_info)

    # ---- heurísticas ----
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
            # parseo ligero sin tomllib
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

        # Go frameworks (por imports detectables)
        go_deps = " ".join(self.result["dependencies"]["go"]).lower()
        if "gin-gonic/gin" in go_deps: detected.append("Gin")
        if "labstack/echo" in go_deps: detected.append("Echo")
        if "gofiber" in go_deps: detected.append("Fiber")

        self.result["stack"]["frameworks"] = sorted(set(detected))

    # ---- árbol ----
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

    # ---- símbolos / glosario ----
    def _collect_symbols(self, path: Path):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return
        # patrones: class, function, interface, type, model definitions
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
        # Top 30 símbolos más frecuentes, excluyendo nombres genéricos
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

    # ---- convenciones ----
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
            conventions.append("Controllers → Services (lógica en services/)")
        # Feature-based
        feature_dirs = [f for f in self.result["folders"]
                        if f["depth"] == 2 and f["path"].startswith(("src", "app"))
                        and f["purpose_hint"] is None]
        if len(feature_dirs) >= 3:
            conventions.append("Feature-based folders (src/feature-x, src/feature-y)")
        # Tests co-ubicados
        if any(".test." in c["path"] or ".spec." in c["path"] for c in self.result["configs"]):
            conventions.append("Tests co-ubicados junto al código (*.test.*, *.spec.*)")
        # TypeScript strict
        ts_configs = [c for c in self.result["configs"] if c["path"].endswith("tsconfig.json")]
        if ts_configs:
            conventions.append("TypeScript configurado")
        # Docker
        if self.result["entry_points"]["docker"]:
            conventions.append(f"Dockerizado ({len(self.result['entry_points']['docker'])} Dockerfile(s))")
        # CI
        if self.result["entry_points"]["ci"]:
            conventions.append(f"CI configurado ({len(self.result['entry_points']['ci'])} workflow(s))")

        self.result["conventions"] = conventions


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    # Requiere Python 3 (solo stdlib). El f-string y los type hints de este archivo
    # ya fallarían en Python 2, pero damos un mensaje claro por si acaso.
    if sys.version_info[0] < 3:
        sys.stderr.write("Error: este scanner requiere Python 3.\n")
        return 2

    parser = argparse.ArgumentParser(description="Escanea un proyecto y produce un JSON estructurado.")
    parser.add_argument("path", help="Path absoluto al proyecto")
    parser.add_argument("--output", "-o", default="-",
                        help="Archivo de output (default: stdout)")
    parser.add_argument("--max-depth", type=int, default=4,
                        help="Profundidad máxima del árbol (default: 4)")
    parser.add_argument("--pretty", action="store_true", help="Output con indentación")
    args = parser.parse_args()

    root = Path(args.path).expanduser().resolve()
    if not root.exists():
        sys.stderr.write(f"Error: el path '{root}' no existe.\n")
        return 1
    if not root.is_dir():
        sys.stderr.write(f"Error: el path '{root}' no es un directorio.\n")
        return 1
    if not os.access(root, os.R_OK):
        sys.stderr.write(f"Error: el path '{root}' no es legible (permisos).\n")
        return 1

    scanner = ProjectScanner(root, max_depth=args.max_depth)
    try:
        result = scanner.scan()
    except FileNotFoundError as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1
    except OSError as exc:
        sys.stderr.write(f"Error escaneando el proyecto: {exc}\n")
        return 1

    out = json.dumps(result, indent=2 if args.pretty else None, ensure_ascii=False, default=str)

    if args.output == "-":
        print(out)
    else:
        try:
            Path(args.output).write_text(out, encoding="utf-8")
        except OSError as exc:
            sys.stderr.write(f"Error: no se pudo escribir el output en '{args.output}': {exc}\n")
            return 1
        print(f"✓ Escaneo guardado en {args.output}", file=sys.stderr)
        print(f"  - Archivos escaneados: {result['meta']['files_scanned']}", file=sys.stderr)
        print(f"  - Lenguajes detectados: {list(result['stack']['languages'].keys())}", file=sys.stderr)
        print(f"  - Frameworks: {result['stack']['frameworks']}", file=sys.stderr)
        print(f"  - Carpetas top-level: {len([f for f in result['folders'] if f['depth'] == 1])}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
