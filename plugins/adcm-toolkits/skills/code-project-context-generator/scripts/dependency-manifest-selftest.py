#!/usr/bin/env python3
"""dependency-manifest-selftest - behavioural tests for dependency_manifest.py (stdlib only).

Usage:
  python3 dependency-manifest-selftest.py [--scanner PATH] [--only NAME] [--keep]

Every case builds one throwaway `tempfile` project (generic "Acme" files, example.com hosts), calls the
module in this process and asserts the JSON it returns. The cases that cover the cpcg scanner run it as
a subprocess (`<project> [--update PATHS]`, PYTHONDONTWRITEBYTECODE=1). Output is `PASS|FAIL|SKIP <case>
[- why]` per case, then the tally `N PASS · N FAIL · N SKIP (of N)`. Exit code 1 when any case FAILs. No
real project tree is ever scanned.

The module under test is the dependency_manifest.py next to this file; the scanner defaults to the
scan_project.py next to this file (pass --scanner to test another copy). --keep leaves the temp trees on
disk.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True
sys.path.insert(0, HERE)
import dependency_manifest as dm  # noqa: E402

PARENT = os.pardir + "/"


class Skip(Exception):
    pass


# ------------------------------------------------------------------ harness
class R:
    """One scanner run."""

    def __init__(self, p):
        self.rc, self.out, self.err = p.returncode, p.stdout, p.stderr


class Ctx:
    def __init__(self, scanner, root):
        self.scanner, self.root = scanner, root
        self.env = dict(os.environ)
        self.env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
                         "HOME": root})

    def path(self, rel):
        return os.path.join(self.root, *rel.split("/"))

    def write(self, rel, content):
        p = self.path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(content)
        return p

    def tree(self, project, files):
        """Write {relative path: content} under <root>/<project>/ and return the project directory."""
        for rel, content in files.items():
            self.write(f"{project}/{rel}", content)
        return self.path(project)

    def manifest(self, project):
        """The module's manifest for a project, normalised through JSON."""
        return json.loads(json.dumps(dm.dependency_manifest(Path(self.path(project)))))

    def run(self, scanner, project, *flags):
        cmd = [sys.executable, scanner, self.path(project)] + list(flags)
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=self.env, cwd=self.root, timeout=120)
        return R(p)

    def scan(self, project, *flags, scanner=None):
        """Run the scanner and return its parsed JSON; a failing run raises (the case reports FAIL)."""
        r = self.run(scanner or self.scanner, project, *flags)
        if r.rc != 0:
            raise RuntimeError(f"scanner exit {r.rc}: {r.err.strip()[:300]}")
        return json.loads(r.out)


class Check:
    def __init__(self):
        self.problems = []

    def ok(self, cond, what):
        if not cond:
            self.problems.append(what)

    def eq(self, got, want, what):
        if got != want:
            self.problems.append(f"{what}: got {got!r}, want {want!r}")

    def lacks(self, hay, needle, what):
        if needle in (hay or ""):
            self.problems.append(f"{what}: {needle!r} must not be present")

    def clean(self, manifest, what="manifest"):
        """No section of the manifest may have failed."""
        bad = [n for n in manifest["notes"] if "failed" in n]
        if bad:
            self.problems.append(f"{what}: {bad[0]}")


def J(obj):
    return json.dumps(obj, indent=2) + "\n"


def pkg(by, name, kind="prod", workspace="."):
    """The package entry for (name, kind, workspace) of a manifest, or {}."""
    return next((p for p in by["packages"] if (p["name"], p["kind"], p["workspace"]) == (name, kind, workspace)), {})


PNPM_V9 = """lockfileVersion: '9.0'

settings:
  autoInstallPeers: true
  excludeLinksFromLockfile: false

importers:

  .:
    dependencies:
      react:
        specifier: ^18.3.1
        version: 18.3.1
      react-dom:
        specifier: ^18.3.1
        version: 18.3.1(react@18.3.1)
    devDependencies:
      vite:
        specifier: ^5.2.0
        version: 5.2.11(@types/node@20.12.7)(terser@5.31.0)

  packages/ui:
    dependencies:
      clsx:
        specifier: catalog:
        version: 2.1.1
      '@acme/core':
        specifier: workspace:*
        version: link:@UP@core

packages:

  react@18.3.1:
    resolution: {integrity: sha512-abc}
    engines: {node: '>=0.10.0'}

snapshots:

  react@18.3.1: {}
""".replace("@UP@", PARENT)


# ------------------------------------------------------------------ cases: package manager and lockfiles
def case_npm_lockfile_v3(ctx, t):
    ctx.tree("acme", {
        "package.json": J({"name": "acme", "version": "1.0.0",
                           "dependencies": {"express": "^4.18.2", "lodash": "4.17.21", "left-pad": "latest",
                                            "legacy": "npm:old-name@^1.0.0", "tool": "github:acme/tool#v2"},
                           "devDependencies": {"typescript": "~5.4.5"},
                           "peerDependencies": {"react": ">=18"}}),
        "package-lock.json": J({"name": "acme", "version": "1.0.0", "lockfileVersion": 3, "requires": True,
                                "packages": {"": {"name": "acme", "version": "1.0.0"},
                                             "node_modules/express": {"version": "4.19.2"},
                                             "node_modules/lodash": {"version": "4.17.21"},
                                             "node_modules/left-pad": {"version": "1.3.0"},
                                             "node_modules/typescript": {"version": "5.4.5", "dev": True}}}),
    })
    m = ctx.manifest("acme")
    t.clean(m)
    t.eq(sorted(m), sorted(["format", "package_manager", "lockfiles", "workspaces", "catalogs", "packages",
                            "overrides", "patched", "install_scripts", "npmrc", "runtimes", "bots", "ci",
                            "docker", "verification", "other", "notes"]), "the 17 fixed keys")
    t.eq(m["format"], 1, "format")
    t.eq(m["package_manager"], {"name": "npm", "version": None, "source": "lockfile"}, "package manager")
    t.eq(m["lockfiles"], [{"path": "package-lock.json", "type": "package-lock", "version": "3"}], "lockfiles")
    t.eq(m["workspaces"], ["."], "workspaces")
    t.eq(pkg(m, "express"), {"name": "express", "workspace": ".", "kind": "prod", "declared": "^4.18.2",
                             "locked": "4.19.2", "style": "range", "catalog": None}, "express entry")
    t.eq(pkg(m, "lodash")["style"], "exact", "exact pin style")
    t.eq(pkg(m, "left-pad")["style"], "tag", "dist-tag style")
    t.eq(pkg(m, "legacy")["style"], "alias", "alias style")
    t.eq(pkg(m, "tool")["style"], "url", "git shorthand style")
    t.eq((pkg(m, "typescript", "dev")["locked"], pkg(m, "typescript", "dev")["style"]), ("5.4.5", "range"), "dev dep")
    t.eq(pkg(m, "react", "peer")["locked"], None, "a peer dependency that is not in the lock")

    ctx.tree("legacy", {
        "package.json": J({"name": "old", "dependencies": {"chalk": "^2.4.2"}}),
        "package-lock.json": J({"lockfileVersion": 1, "dependencies": {"chalk": {"version": "2.4.2"}}}),
    })
    old = ctx.manifest("legacy")
    t.eq(old["lockfiles"][0]["version"], "1", "lockfileVersion 1")
    t.eq(pkg(old, "chalk")["locked"], "2.4.2", "v1 locked version comes from dependencies[n].version")

    ctx.tree("bom", {"package.json": chr(0xFEFF) + J({"name": "acme", "dependencies": {"chalk": "^5.0.0"}})})
    t.eq(pkg(ctx.manifest("bom"), "chalk")["declared"], "^5.0.0", "a BOM before the JSON is ignored")


def case_pnpm_packagemanager_v9_importers(ctx, t):
    ctx.tree("acme", {
        "package.json": J({"name": "acme", "packageManager": "pnpm@9.1.0+sha512.deadbeef",
                           "dependencies": {"react": "^18.3.1", "react-dom": "^18.3.1"},
                           "devDependencies": {"vite": "^5.2.0"}}),
        "pnpm-lock.yaml": PNPM_V9,
        "pnpm-workspace.yaml": "packages:\n  - 'packages/*'\n",
        "packages/ui/package.json": J({"name": "@acme/ui", "dependencies": {"clsx": "catalog:", "@acme/core": "workspace:*"}}),
        "packages/core/package.json": J({"name": "@acme/core"}),
    })
    m = ctx.manifest("acme")
    t.clean(m)
    t.eq(m["package_manager"], {"name": "pnpm", "version": "9.1.0", "source": "packageManager"},
         "packageManager wins and the +hash is cut")
    t.eq(m["lockfiles"], [{"path": "pnpm-lock.yaml", "type": "pnpm", "version": "9.0"}], "pnpm lockfile version")
    t.eq(m["workspaces"], [".", "packages/core", "packages/ui"], "pnpm-workspace.yaml globs")
    t.eq(pkg(m, "react")["locked"], "18.3.1", "locked from importers")
    t.eq(pkg(m, "react-dom")["locked"], "18.3.1", "the (peer) suffix is stripped")
    t.eq(pkg(m, "vite", "dev")["locked"], "5.2.11", "a long peer suffix is stripped")
    t.eq(pkg(m, "clsx", workspace="packages/ui")["locked"], "2.1.1", "workspace importer")
    t.eq((pkg(m, "clsx", workspace="packages/ui")["style"], pkg(m, "clsx", workspace="packages/ui")["catalog"]),
         ("catalog", "default"), "catalog: spec")
    t.eq(pkg(m, "@acme/core", workspace="packages/ui")["style"], "workspace", "workspace: spec")

    ctx.tree("v6", {
        "package.json": J({"name": "acme", "dependencies": {"left-pad": "1.3.0"}}),
        "pnpm-lock.yaml": ("lockfileVersion: '6.0'\n\ndependencies:\n  left-pad:\n    specifier: 1.3.0\n"
                           "    version: 1.3.0\n\npackages:\n\n  /left-pad@1.3.0:\n    resolution: {integrity: sha512-x}\n"),
    })
    old = ctx.manifest("v6")
    t.eq(old["package_manager"], {"name": "pnpm", "version": None, "source": "lockfile"}, "lockfile-only detection")
    t.eq(pkg(old, "left-pad")["locked"], "1.3.0", "v6 single-project layout")


def case_npm_mislabel_fixed(ctx, t):
    ctx.tree("pnpm-only", {
        "package.json": J({"name": "acme", "dependencies": {"react": "^18.3.1"}}),
        "pnpm-lock.yaml": PNPM_V9,
        "src/index.ts": "export const answer = 42\n",
    })
    out = ctx.scan("pnpm-only")
    t.eq(out["stack"]["package_managers"], ["pnpm"], "a pnpm-only tree is not labelled npm")
    t.eq(out["dependency_manifest"]["package_manager"]["name"], "pnpm", "manifest agrees")

    ctx.tree("yarn-field", {"package.json": J({"name": "acme", "packageManager": "yarn@4.1.0"}),
                            "src/index.ts": "export const answer = 42\n"})
    t.eq(ctx.scan("yarn-field")["stack"]["package_managers"], ["yarn"], "packageManager yarn without a lockfile")

    ctx.tree("npm-only", {"package.json": J({"name": "acme"}), "package-lock.json": J({"lockfileVersion": 3}),
                          "src/index.ts": "export const answer = 42\n"})
    t.eq(ctx.scan("npm-only")["stack"]["package_managers"], ["npm"], "a real npm project stays npm")

    ctx.tree("php-front", {"composer.json": J({"name": "acme/app", "require": {"php": "^8.2"}}),
                           "composer.lock": J({"packages": []}), "web/package.json": J({"name": "web"}),
                           "web/index.js": "module.exports = 1\n"})
    t.eq(sorted(ctx.scan("php-front")["stack"]["package_managers"]), ["composer", "npm"],
         "a nested package.json beside a PHP root keeps npm")


def case_both_lockfiles_note(ctx, t):
    ctx.tree("acme", {
        "package.json": J({"name": "acme", "dependencies": {"left-pad": "1.3.0"}}),
        "package-lock.json": J({"lockfileVersion": 3, "packages": {"node_modules/left-pad": {"version": "1.3.0"}}}),
        "pnpm-lock.yaml": "lockfileVersion: '9.0'\n\nimporters:\n\n  .:\n    dependencies:\n      left-pad:\n"
                          "        specifier: 1.3.0\n        version: 1.3.0\n",
    })
    m = ctx.manifest("acme")
    t.eq([l["path"] for l in m["lockfiles"]], ["package-lock.json", "pnpm-lock.yaml"], "both lockfiles are listed")
    t.ok("conflicting lockfiles: package-lock.json, pnpm-lock.yaml" in m["notes"], "conflict note: %r" % m["notes"])
    t.eq(m["package_manager"], {"name": "pnpm", "version": None, "source": "lockfile"}, "pnpm wins the tie")

    ctx.tree("mismatch", {"package.json": J({"name": "acme", "packageManager": "npm@10.5.0"}),
                          "pnpm-lock.yaml": "lockfileVersion: '9.0'\n"})
    other = ctx.manifest("mismatch")
    t.eq(other["package_manager"]["name"], "npm", "packageManager outranks the lockfile")
    t.ok(any("packageManager says npm but the root lockfile is pnpm-lock.yaml" in n for n in other["notes"]),
         "mismatch note: %r" % other["notes"])


def case_npm_workspaces_globs(ctx, t):
    files = {"package.json": J({"name": "acme", "private": True,
                                "workspaces": ["packages/*", "!packages/legacy", "apps/web", "tools/**"]}),
             "package-lock.json": J({"lockfileVersion": 3, "packages": {
                 "": {}, "node_modules/lodash": {"version": "4.17.21"},
                 "packages/b/node_modules/lodash": {"version": "3.10.1"},
                 "node_modules/@acme/a": {"resolved": "packages/a", "link": True},
                 "packages/a": {"name": "@acme/a", "version": "0.4.0"}}})}
    for name in ("packages/a", "packages/b", "packages/legacy", "apps/web", "apps/other", "tools/x/y"):
        files[f"{name}/package.json"] = J({"name": name.replace("/", "-"), "dependencies": {"lodash": "^4.0.0"}})
    ctx.tree("acme", files)
    m = ctx.manifest("acme")
    t.clean(m)
    t.eq(m["workspaces"], [".", "apps/web", "packages/a", "packages/b", "tools/x/y"],
         "globs expanded, ! honoured, sorted with . first")
    t.eq(pkg(m, "lodash", workspace="packages/b")["locked"], "3.10.1", "the workspace's own node_modules wins")
    t.eq(pkg(m, "lodash", workspace="packages/a")["locked"], "4.17.21", "otherwise the root node_modules")
    t.eq([p["workspace"] for p in m["packages"]], [".", "apps/web", "packages/a", "packages/b", "tools/x/y"][1:],
         "packages are ordered by workspace")

    ctx.tree("object-form", {"package.json": J({"name": "acme", "workspaces": {"packages": ["libs/*"]}}),
                             "libs/one/package.json": J({"name": "one"})})
    t.eq(ctx.manifest("object-form")["workspaces"], [".", "libs/one"], "workspaces as {packages: [...]}")
    ctx.tree("none", {"package.json": J({"name": "acme"})})
    t.eq(ctx.manifest("none")["workspaces"], ["."], "no workspaces declared")
    ctx.tree("empty", {"README.md": "# Acme\n"})
    t.eq(ctx.manifest("empty")["workspaces"], [], "a tree without manifests has no workspaces")


def case_pnpm_workspace_catalog_overrides_allowbuilds_comments(ctx, t):
    ctx.tree("acme", {
        "package.json": J({"name": "acme", "packageManager": "pnpm@10.4.0",
                           "dependencies": {"react": "catalog:", "react-next": "catalog:next", "left-pad": "1.3.0"}}),
        "pnpm-workspace.yaml": (
            "packages:\n  - 'packages/*'\n  - '!packages/legacy'\n\n"
            "catalog:\n"
            "  # Stay on React 18 until the design system supports 19\n"
            "  react: ^18.3.1\n"
            "  typescript: 5.4.5 # exact on purpose\n\n"
            "catalogs:\n"
            "  next:\n"
            "    # canary tracks the staging branch\n"
            "    react: ^19.0.0-rc\n\n"
            "overrides:\n"
            "  # CVE fix, remove once upstream bumps\n"
            "  semver: ^7.6.0\n"
            "  '@acme/tool>glob': 10.3.10\n\n"
            "onlyBuiltDependencies:\n"
            "  # native binary download\n"
            "  - esbuild\n"
            "  - sharp # image processing\n\n"
            "ignoredBuiltDependencies:\n"
            "  - core-js\n\n"
            "allowBuilds:\n"
            "  fsevents: true\n"
            "  unrs-resolver: false\n"),
        "packages/legacy/package.json": J({"name": "legacy"}),
        "packages/app/package.json": J({"name": "app"}),
    })
    m = ctx.manifest("acme")
    t.clean(m)
    t.eq(m["catalogs"], {
        "default": {"react": {"spec": "^18.3.1", "comment": "Stay on React 18 until the design system supports 19"},
                    "typescript": {"spec": "5.4.5", "comment": "exact on purpose"}},
        "next": {"react": {"spec": "^19.0.0-rc", "comment": "canary tracks the staging branch"}}},
         "catalogs keep the comment above (and after) each pin")
    t.eq(list(m["catalogs"]), ["default", "next"], "default catalog first")
    t.eq(m["overrides"], [{"name": "@acme/tool>glob", "spec": "10.3.10", "source": "pnpm-workspace.yaml#overrides"},
                          {"name": "semver", "spec": "^7.6.0", "source": "pnpm-workspace.yaml#overrides"}],
         "pnpm-workspace overrides")
    t.eq(m["install_scripts"], {"allow": ["esbuild", "fsevents", "sharp"], "deny": ["core-js", "unrs-resolver"],
                                "source": "pnpm-workspace.yaml",
                                "comments": {"esbuild": "native binary download", "sharp": "image processing"}},
         "install-script policy")
    t.eq(m["workspaces"], [".", "packages/app"], "pnpm-workspace.yaml honours ! patterns")
    t.eq((pkg(m, "react")["style"], pkg(m, "react")["catalog"]), ("catalog", "default"), "catalog: -> default")
    t.eq(pkg(m, "react-next")["catalog"], "next", "catalog:next")

    ctx.tree("in-package-json", {"package.json": J({"name": "acme", "pnpm": {
        "onlyBuiltDependencies": ["esbuild"], "overrides": {"semver": "^7.6.0"}}}),
        "pnpm-lock.yaml": "lockfileVersion: '9.0'\n"})
    other = ctx.manifest("in-package-json")
    t.eq(other["install_scripts"], {"allow": ["esbuild"], "deny": [], "source": "package.json#pnpm", "comments": {}},
         "policy from package.json#pnpm")
    t.eq(other["overrides"], [{"name": "semver", "spec": "^7.6.0", "source": "package.json#pnpm.overrides"}],
         "package.json#pnpm.overrides")
    ctx.tree("npm-overrides", {"package.json": J({"name": "acme", "overrides": {"foo": {".": "1.2.3", "bar": "2.0.0"}},
                                                    "resolutions": {"**/baz": "3.0.0"}})})
    third = ctx.manifest("npm-overrides")
    t.eq([(o["name"], o["spec"], o["source"]) for o in third["overrides"]],
         [("foo", "1.2.3", "package.json#overrides"), ("foo>bar", "2.0.0", "package.json#overrides"),
          ("**/baz", "3.0.0", "package.json#resolutions")], "npm nested overrides and yarn resolutions")
    t.eq(third["install_scripts"], None, "no policy declared")


def case_pnpm_patched_dependencies(ctx, t):
    ctx.tree("acme", {
        "package.json": J({"name": "acme", "pnpm": {"patchedDependencies": {
            "express@4.18.2": "patches/express@4.18.2.patch"}}}),
        "pnpm-workspace.yaml": "patchedDependencies:\n  '@acme/ui@1.0.0': patches/acme-ui.patch\n",
        "patches/lodash+4.17.21.patch": "diff\n",
        "patches/@acme+tool+2.0.0.patch": "diff\n",
        "patches/README.md": "notes\n",
    })
    m = ctx.manifest("acme")
    t.clean(m)
    t.eq(m["patched"], [
        {"name": "express@4.18.2", "path": "patches/express@4.18.2.patch", "source": "package.json#pnpm.patchedDependencies"},
        {"name": "@acme/tool@2.0.0", "path": "patches/@acme+tool+2.0.0.patch", "source": "patches/"},
        {"name": "lodash@4.17.21", "path": "patches/lodash+4.17.21.patch", "source": "patches/"},
        {"name": "@acme/ui@1.0.0", "path": "patches/acme-ui.patch", "source": "pnpm-workspace.yaml#patchedDependencies"}],
         "pnpm patchedDependencies and patch-package files")


# ------------------------------------------------------------------ cases: runtimes
def case_runtime_pins_all_sources(ctx, t):
    ctx.tree("acme", {
        "package.json": J({"name": "acme", "engines": {"node": ">=20.11 <23"},
                           "volta": {"node": "20.11.1", "npm": "10.2.4"},
                           "devEngines": {"runtime": {"name": "node", "version": "^20.11.0", "onFail": "error"}},
                           "devDependencies": {"@types/node": "^20.12.0"}}),
        ".nvmrc": "v20.11.1\n",
        ".node-version": "20.11.1\n",
        ".tool-versions": "nodejs 20.11.1\npython 3.12.1  # build scripts\nphp 8.3.4\n",
        "Dockerfile": ("# syntax=docker/dockerfile:1\n"
                       "ARG NODE_VERSION=20.11.1 FLAVOR=alpine\n"
                       "FROM --platform=$BUILDPLATFORM node:${NODE_VERSION}-alpine AS build\n"
                       "WORKDIR /app\n"
                       "FROM nginx:1.25-${FLAVOR}\n"
                       "COPY --from=build /app/dist /usr/share/nginx/html\n"
                       "FROM build AS final\n"),
        ".gitlab-ci.yml": ("variables:\n  NODE_TAG: \"20.11-bookworm\"\n\nimage: node:$NODE_TAG\n\n"
                           "test:\n  script:\n    - npm test\n"),
        ".github/workflows/ci.yml": (
            "name: ci\non: [push]\njobs:\n  build:\n    runs-on: ubuntu-latest\n    strategy:\n      matrix:\n"
            "        node: [18, 20]\n    steps:\n      - uses: actions/checkout@v4\n"
            "      - uses: actions/setup-node@v4\n        with:\n          node-version: ${{ matrix.node }}\n"
            "      - run: npm ci\n"),
    })
    m = ctx.manifest("acme")
    t.clean(m)
    gh = ".github/workflows/ci.yml"
    t.eq(m["runtimes"]["node"]["pins"], [
        {"source": ".nvmrc", "value": "v20.11.1"},
        {"source": ".node-version", "value": "20.11.1"},
        {"source": ".tool-versions", "value": "20.11.1"},
        {"source": "engines.node", "value": ">=20.11 <23"},
        {"source": "volta.node", "value": "20.11.1"},
        {"source": "devEngines.runtime", "value": "^20.11.0"},
        {"source": "@types/node", "value": "^20.12.0"},
        {"source": "ci-image:.gitlab-ci.yml", "value": "20.11-bookworm"},
        {"source": "docker:Dockerfile", "value": "20.11.1-alpine"},
        {"source": "setup-node:" + gh, "value": "18"},
        {"source": "setup-node:" + gh, "value": "20"}], "every node pin source, with its file, in a fixed order")
    t.eq(m["runtimes"]["node"]["shadowed_by"], None, "no shadowing package")
    t.eq(m["runtimes"]["python"]["pins"], [{"source": ".tool-versions", "value": "3.12.1"}], "python pin")
    t.eq(m["runtimes"]["php"]["pins"], [{"source": ".tool-versions", "value": "8.3.4"}], "php pin")
    t.eq(m["runtimes"]["deno"], {"pins": []}, "no deno pin")
    t.eq(m["docker"], [
        {"file": "Dockerfile", "line": 3, "image": "node", "tag": "20.11.1-alpine", "stage": "build"},
        {"file": "Dockerfile", "line": 5, "image": "nginx", "tag": "1.25-alpine", "stage": None}],
         "FROM lines with ARG defaults resolved; a stage reference is not an image")
    t.eq(m["ci"]["node_versions"], [{"file": ".github/workflows/ci.yml", "value": "18"},
                                    {"file": ".github/workflows/ci.yml", "value": "20"},
                                    {"file": ".gitlab-ci.yml", "value": "20.11-bookworm"}], "ci.node_versions")

    ctx.tree("others", {
        "pyproject.toml": "[project]\nname = 'acme'\nrequires-python = \">=3.11\"\n",
        "composer.json": J({"name": "acme/app", "require": {"php": "^8.2", "ext-json": "*"},
                            "config": {"platform": {"php": "8.2.20"}}}),
        ".python-version": "3.12\n", "runtime.txt": "python-3.12.4\n",
        "docker-compose.yml": "services:\n  web:\n    image: php:8.3-fpm\n  db:\n    image: \"postgres:16\"\n",
    })
    o = ctx.manifest("others")
    t.eq(o["runtimes"]["python"]["pins"], [{"source": ".python-version", "value": "3.12"},
                                           {"source": "runtime.txt", "value": "3.12.4"},
                                           {"source": "requires-python", "value": ">=3.11"}], "python pin sources")
    t.eq(o["runtimes"]["php"]["pins"], [{"source": "require.php", "value": "^8.2"},
                                        {"source": "config.platform.php", "value": "8.2.20"},
                                        {"source": "docker:docker-compose.yml", "value": "8.3-fpm"}], "php pin sources")
    t.eq([(d["image"], d["tag"], d["stage"], d["line"]) for d in o["docker"]],
         [("php", "8.3-fpm", "web", 3), ("postgres", "16", "db", 5)], "compose service images")


def case_shadowed_by_node_package(ctx, t):
    ctx.tree("declared", {
        "package.json": J({"name": "acme", "devDependencies": {"node": "^20.11.0", "typescript": "^5.4.0"}}),
        "package-lock.json": J({"lockfileVersion": 3, "packages": {
            "": {}, "node_modules/node": {"version": "20.11.0", "bin": {"node": "bin/node"}},
            "node_modules/typescript": {"version": "5.4.5", "bin": {"tsc": "bin/tsc"}}}}),
    })
    m = ctx.manifest("declared")
    t.eq(m["runtimes"]["node"]["shadowed_by"], {"package": "node", "declared": "^20.11.0", "locked": "20.11.0"},
         "a declared `node` dependency shadows the runtime")
    t.eq(pkg(m, "node", "dev")["locked"], "20.11.0", "and stays in the package list")

    ctx.tree("transitive", {
        "package.json": J({"name": "acme", "dependencies": {"wrapper": "^1.0.0"}}),
        "package-lock.json": J({"lockfileVersion": 3, "packages": {
            "": {}, "node_modules/wrapper": {"version": "1.0.0"},
            "node_modules/node": {"version": "18.19.0", "bin": {"node": "bin/node"}}}}),
    })
    t.eq(ctx.manifest("transitive")["runtimes"]["node"]["shadowed_by"],
         {"package": "node", "declared": None, "locked": "18.19.0"}, "found through the lock's bin entry")

    ctx.tree("none", {"package.json": J({"name": "acme", "dependencies": {"nodemon": "^3.0.0"}}),
                      "package-lock.json": J({"lockfileVersion": 3, "packages": {
                          "": {}, "node_modules/nodemon": {"version": "3.1.0", "bin": {"nodemon": "bin/nodemon.js"}}}})})
    t.eq(ctx.manifest("none")["runtimes"]["node"]["shadowed_by"], None, "other binaries do not shadow")


# ------------------------------------------------------------------ cases: update bots
def case_renovate_caps_disabled_minage_groups(ctx, t):
    ctx.tree("acme", {"renovate.json": J({
        "extends": ["config:recommended", "group:monorepos"],
        "minimumReleaseAge": "3 days",
        "vulnerabilityAlerts": {"enabled": True, "labels": ["security"]},
        "ignoreDeps": ["left-pad"],
        "packageRules": [
            {"matchPackageNames": ["react", "react-dom"], "allowedVersions": "<19"},
            {"matchPackagePatterns": ["^@types/"], "groupName": "types"},
            {"matchPackageNames": ["typescript"], "matchUpdateTypes": ["major"], "enabled": False},
            {"matchPackageNames": ["vitest", "/^@vitest\\//"], "groupName": "vitest"},
            {"matchUpdateTypes": ["major"], "enabled": False}]})})
    m = ctx.manifest("acme")
    t.clean(m)
    t.eq(m["bots"], [{
        "kind": "renovate", "path": "renovate.json", "parsed": True,
        "caps": [{"names": ["react", "react-dom"], "patterns": [], "allowed": "<19"}],
        "disabled": [{"names": ["typescript"], "patterns": [], "update_types": ["major"]},
                     {"names": [], "patterns": [], "update_types": ["major"]},
                     {"names": ["left-pad"], "patterns": [], "update_types": []}],
        "min_release_age_days": 3,
        "groups": [{"name": "types", "names": [], "patterns": ["^@types/"]},
                   {"name": "vitest", "names": ["vitest"], "patterns": ["^@vitest\\/"]}],
        "vulnerability_alerts": {"enabled": True, "labels": ["security"]},
        "extends": ["config:recommended", "group:monorepos"]}], "renovate.json parsed")

    ctx.tree("weeks", {".renovaterc": J({"minimumReleaseAge": "2 weeks"}), "renovate.json": "{ not json"})
    w = ctx.manifest("weeks")
    t.eq([(b["path"], b["parsed"], b["min_release_age_days"]) for b in w["bots"]],
         [(".renovaterc", True, 14), ("renovate.json", False, None)], ".renovaterc parsed, broken JSON is not")
    t.ok("unparsed renovate.json (invalid JSON)" in w["notes"], "note for the broken file: %r" % w["notes"])
    ctx.tree("legacy", {".renovaterc.json": J({"stabilityDays": 5})})
    t.eq(ctx.manifest("legacy")["bots"][0]["min_release_age_days"], 5, "stabilityDays")


def case_renovate_json5_unparsed(ctx, t):
    ctx.tree("acme", {"renovate.json5": ("// Acme update policy\n{\n  extends: ['config:recommended'],\n"
                                         "  packageRules: [{matchPackageNames: ['react'], allowedVersions: '<19'}],\n}\n")})
    m = ctx.manifest("acme")
    t.eq(m["bots"], [{"kind": "renovate", "path": "renovate.json5", "parsed": False, "caps": [], "disabled": [],
                      "min_release_age_days": None, "groups": [], "vulnerability_alerts": None, "extends": []}],
         "renovate.json5 is presence only")
    t.ok("unparsed renovate.json5 (presence only)" in m["notes"], "note: %r" % m["notes"])


def case_dependabot_presence(ctx, t):
    ctx.tree("acme", {".github/dependabot.yml": ("version: 2\nupdates:\n  - package-ecosystem: npm\n"
                                                  "    directory: /\n    schedule:\n      interval: weekly\n")})
    m = ctx.manifest("acme")
    t.eq([(b["kind"], b["path"], b["parsed"]) for b in m["bots"]], [("dependabot", ".github/dependabot.yml", False)],
         "dependabot is presence only")
    t.eq(m["bots"][0]["caps"], [], "nothing is read from it")
    t.eq(m["ci"]["provider"], "none", "dependabot.yml is not a pipeline")
    ctx.tree("yaml-ext", {".github/dependabot.yaml": "version: 2\n"})
    t.eq(ctx.manifest("yaml-ext")["bots"][0]["path"], ".github/dependabot.yaml", ".yaml extension")


# ------------------------------------------------------------------ cases: CI
GITLAB_CI = """image: node:20.11-alpine

variables:
  PG_VERSION: "15"

workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

stages: [verify, audit]

.install: &install
  before_script:
    - npm ci

lint:
  stage: verify
  <<: *install
  script:
    - npm run lint
    - npx tsc --noEmit

unit:
  stage: verify
  image:
    name: node:22-bookworm
  services:
    - postgres:$PG_VERSION
    - name: redis:7.2
      alias: cache
  script:
    - npm test

e2e:
  stage: verify
  extends: .e2e-base

.e2e-base:
  image: registry.example.com/playwright:v1.44.0-jammy
  script:
    - npx playwright test

deps-audit:
  stage: audit
  allow_failure: true
  script:
    - npm audit --audit-level=high
    - gitleaks detect --no-banner

secrets:
  stage: audit
  script: |
    trivy fs --exit-code 1 .
"""


def case_gitlab_ci_images_services_verify_audit_mrpipelines(ctx, t):
    ctx.tree("acme", {".gitlab-ci.yml": GITLAB_CI, "package.json": J({"name": "acme"})})
    m = ctx.manifest("acme")
    t.clean(m)
    ci, f = m["ci"], ".gitlab-ci.yml"
    t.eq((ci["provider"], ci["files"], ci["mr_pipelines"]), ("gitlab", [f], True), "provider, files, mr_pipelines")
    t.eq(ci["images"], [
        {"file": f, "job": None, "image": "node", "tag": "20.11-alpine", "role": "default"},
        {"file": f, "job": ".e2e-base", "image": "registry.example.com/playwright", "tag": "v1.44.0-jammy", "role": "job"},
        {"file": f, "job": "unit", "image": "node", "tag": "22-bookworm", "role": "job"},
        {"file": f, "job": "unit", "image": "postgres", "tag": "15", "role": "service"},
        {"file": f, "job": "unit", "image": "redis", "tag": "7.2", "role": "service"}],
         "default, job and service images (variables resolved)")
    t.eq(ci["verify_jobs"], [
        {"file": f, "job": "e2e", "commands": ["npx playwright test"]},
        {"file": f, "job": "lint", "commands": ["npm run lint", "npx tsc --noEmit"]},
        {"file": f, "job": "unit", "commands": ["npm test"]}], "verify jobs (extends resolved, templates skipped)")
    t.eq(ci["audit_jobs"], [
        {"file": f, "job": "deps-audit", "tool": "gitleaks", "allow_failure": True},
        {"file": f, "job": "deps-audit", "tool": "npm audit", "allow_failure": True},
        {"file": f, "job": "secrets", "tool": "trivy", "allow_failure": False}], "audit jobs")
    t.eq([(v["job"], v["command"]) for v in m["verification"]["ci"]],
         [("e2e", "npx playwright test"), ("lint", "npm run lint"), ("lint", "npx tsc --noEmit"), ("unit", "npm test")],
         "verification.ci mirrors the verify jobs")
    t.eq(m["runtimes"]["node"]["pins"], [{"source": "ci-image:" + f, "value": "20.11-alpine"},
                                         {"source": "ci-image:" + f, "value": "22-bookworm"}], "node images are pins")

    ctx.tree("branch-pipelines", {".gitlab-ci.yml": "workflow:\n  rules:\n    - if: $CI_COMMIT_BRANCH\n\nbuild:\n"
                                                    "  rules:\n    - if: $CI_PIPELINE_SOURCE == \"merge_request_event\"\n"
                                                    "  script:\n    - npm run build\n"})
    t.eq(ctx.manifest("branch-pipelines")["ci"]["mr_pipelines"], False, "only workflow rules decide mr_pipelines")
    ctx.tree("with-include", {".gitlab-ci.yml": "include:\n  - local: ci/build.yml\n\ntest:\n  script:\n    - npm test\n"})
    t.ok(any("include" in n for n in ctx.manifest("with-include")["notes"]), "an include is reported, not followed")


def at(text, needle):
    """The 1-based number of the first line of `text` that contains `needle`."""
    return next(i for i, line in enumerate(text.splitlines(), 1) if needle in line)


def case_ci_pins_pip_supabase(ctx, t):
    gitlab = ("image: python:3.12-slim\n\nsetup:\n  script:\n"
              "    - pip install --upgrade pip\n"
              "    - pip install supabase==2.5.0 \"ruff==0.4.4\" requests>=2.0\n"
              "    - python -m pip install -r requirements.txt -c constraints.txt black==24.4.2\n"
              "    - npx -y supabase@1.200.3 db lint\n"
              "    - npm install -g vercel@34.0.0 prettier\n"
              "    - go install example.com/acme/tool/cmd/tool@v1.4.2 && echo done\n"
              "    # pip install commented==1.0.0\n")
    github = ("name: db\non: [push]\njobs:\n  db:\n    runs-on: ubuntu-latest\n    steps:\n"
              "      - uses: supabase/setup-cli@v1\n        with:\n          version: 1.200.3\n"
              "      - uses: actions/checkout@v4\n        with:\n          version: not-a-pin\n"
              "      - run: pnpm dlx supabase@1.190.0 --version\n")
    ctx.tree("acme", {".gitlab-ci.yml": gitlab, ".github/workflows/db.yml": github})
    m = ctx.manifest("acme")
    t.clean(m)
    g, h = ".gitlab-ci.yml", ".github/workflows/db.yml"

    def pin(file, text, kind, name, version, needle=None):
        return {"file": file, "line": at(text, needle or name), "kind": kind, "name": name, "version": version}
    t.eq(m["ci"]["pins"], [
        pin(h, github, "supabase-cli", "supabase", "1.200.3", "version: 1.200.3"),
        pin(h, github, "supabase-cli", "supabase", "1.190.0", "dlx supabase"),
        pin(g, gitlab, "pip", "ruff", "0.4.4"),
        pin(g, gitlab, "pip", "supabase", "2.5.0"),
        pin(g, gitlab, "pip", "black", "24.4.2"),
        pin(g, gitlab, "supabase-cli", "supabase", "1.200.3", "npx -y supabase"),
        pin(g, gitlab, "npx", "vercel", "34.0.0"),
        pin(g, gitlab, "other", "example.com/acme/tool/cmd/tool", "v1.4.2")], "pins with their line numbers")
    t.eq(m["runtimes"]["python"]["pins"], [{"source": "ci-image:" + g, "value": "3.12-slim"}], "python image pin")


def case_github_actions_setup_node(ctx, t):
    workflow = """name: ci
on:
  pull_request:
  push:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    container:
      image: node:20-bookworm
    services:
      postgres:
        image: postgres:16
    strategy:
      matrix:
        node-version: [18.x, 20.x, 22.x]
        include:
          - node-version: 24.x
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: ${{ matrix.node-version }}
          cache: pnpm
      - uses: pnpm/action-setup@v4
        with:
          version: 9
      - run: pnpm install --frozen-lockfile
      - run: |
          pnpm run lint
          pnpm test
  audit:
    runs-on: ubuntu-latest
    continue-on-error: true
    steps:
      - uses: actions/checkout@v4
      - run: pnpm audit --prod
      - uses: gitleaks/gitleaks-action@v2
  scan:
    runs-on: ubuntu-latest
    steps:
      - run: pip install semgrep==1.90.0 && semgrep --config auto .
        continue-on-error: true
      - run: trivy fs .
  release:
    uses: acme/shared/.github/workflows/release.yml@v3
  local:
    runs-on: ubuntu-latest
    steps:
      - uses: ./.github/actions/setup
"""
    ctx.tree("acme", {".github/workflows/ci.yml": workflow, ".github/workflows/notes.md": "not a workflow\n"})
    m = ctx.manifest("acme")
    t.clean(m)
    ci, f = m["ci"], ".github/workflows/ci.yml"
    t.eq((ci["provider"], ci["files"], ci["mr_pipelines"]), ("github", [f], False), "provider and files")
    t.eq([(a["uses"], a["ref"]) for a in ci["actions"]],
         [("acme/shared/.github/workflows/release.yml", "v3"), ("actions/checkout", "v4"),
          ("actions/setup-node", "v4"), ("gitleaks/gitleaks-action", "v2"), ("pnpm/action-setup", "v4")],
         "actions with their refs (deduplicated, local actions skipped)")
    t.eq(ci["images"], [{"file": f, "job": "test", "image": "node", "tag": "20-bookworm", "role": "job"},
                        {"file": f, "job": "test", "image": "postgres", "tag": "16", "role": "service"}],
         "container and service images")
    t.eq([n["value"] for n in ci["node_versions"]], ["18.x", "20-bookworm", "20.x", "22.x", "24.x"],
         "setup-node matrix values are expanded, include entries too")
    t.eq(ci["verify_jobs"], [{"file": f, "job": "test", "commands": ["pnpm run lint", "pnpm test"]}], "run block commands")
    t.eq(ci["audit_jobs"], [{"file": f, "job": "audit", "tool": "gitleaks", "allow_failure": True},
                            {"file": f, "job": "audit", "tool": "pnpm audit", "allow_failure": True},
                            {"file": f, "job": "scan", "tool": "semgrep", "allow_failure": True},
                            {"file": f, "job": "scan", "tool": "trivy", "allow_failure": False}],
         "audit jobs: continue-on-error on the job or on the step")
    t.eq([p["source"] for p in m["runtimes"]["node"]["pins"]],
         ["ci-image:" + f] + ["setup-node:" + f] * 4, "setup-node pins")

    ctx.tree("both", {".gitlab-ci.yml": "test:\n  script:\n    - npm test\n", ".github/workflows/ci.yml": workflow})
    both = ctx.manifest("both")
    t.eq(both["ci"]["provider"], "both", "both providers")
    t.ok(any("probably dead" in n for n in both["notes"]), "GitHub workflows beside GitLab CI are flagged: %r" % both["notes"])


# ------------------------------------------------------------------ cases: verification, npmrc
def case_verification_placeholder_and_external(ctx, t):
    outside, missing = PARENT + "shared", PARENT + "missing-tool"
    ctx.write("shared/lib.txt", "x\n")
    ctx.tree("acme", {
        "package.json": J({"name": "acme", "packageManager": "pnpm@9.1.0", "scripts": {
            "build": "vite build", "lint": "eslint .", "test": "echo \"Error: no test specified\" && exit 1",
            "check-types": "tsc --noEmit", "e2e": "playwright test"}}),
        ".gitlab-ci.yml": ("test:\n  script:\n    - cd %s && pnpm test\n    - pnpm test --prefix=%s\n"
                           "    - pytest tests/\n    - SNYK_TOKEN=abc123 pnpm run lint\n"
                           "    - curl https://deploy:s3cret@registry.example.com/ping && pnpm test\n" % (outside, missing)),
    })
    m = ctx.manifest("acme")
    t.clean(m)
    v = m["verification"]
    t.eq(v["build"], {"command": "pnpm run build", "source": "package.json#scripts.build", "note": None}, "build")
    t.eq(v["typecheck"]["command"], "pnpm run check-types", "typecheck falls through to check-types")
    t.eq(v["lint"]["command"], "pnpm run lint", "lint")
    t.eq(v["test"], {"command": None, "source": "package.json#scripts.test", "note": "placeholder"},
         "the npm placeholder test is not a command")
    t.eq(v["e2e"]["command"], "pnpm run e2e", "e2e")
    t.eq(v["ci"], [
        {"command": "cd %s && pnpm test" % outside, "job": "test", "external": [{"path": outside, "exists": True}]},
        {"command": "pnpm test --prefix=%s" % missing, "job": "test", "external": [{"path": missing, "exists": False}]},
        {"command": "pytest tests/", "job": "test", "external": []},
        {"command": "SNYK_TOKEN=*** pnpm run lint", "job": "test", "external": []},
        {"command": "curl https://***@registry.example.com/ping && pnpm test", "job": "test", "external": []}],
         "paths that leave the repo, with existence; inline credentials are masked")
    for secret in ("abc123", "s3cret"):
        t.lacks(json.dumps(m), secret, "the manifest JSON")

    ctx.tree("bare", {"package.json": J({"name": "acme", "scripts": {"test": "vitest run", "tsc": "tsc -b"}})})
    b = ctx.manifest("bare")["verification"]
    t.eq((b["build"]["command"], b["typecheck"]["command"], b["test"]["command"], b["lint"]["command"]),
         (None, "npm run tsc", "npm run test", None), "npm default runner; missing scripts give null")


def case_npmrc_whitelist_no_secret(ctx, t):
    secrets = ("SECRET_TOKEN_VALUE", "hunter2", "c2VjcmV0dG9rZW4", "SECRET_PASSWORD", "acme-bot", "OTHER_REGISTRY",
               "NESTED_SECRET")
    ctx.tree("acme", {
        "package.json": J({"name": "acme"}),
        ".npmrc": ("# project npm config\nsave-exact=true\nsave-prefix=\nengine-strict = true\nlegacy-peer-deps=false\n"
                   "node-linker=hoisted\nregistry=https://user:hunter2@registry.example.com/npm/\n"
                   "@acme:registry=https://npm.example.com:4873/\n@other:registry=${OTHER_REGISTRY}\n"
                   "//registry.example.com/npm/:_authToken=SECRET_TOKEN_VALUE\n"
                   "//npm.example.com/:_auth=c2VjcmV0dG9rZW4=\n_password=SECRET_PASSWORD\nusername=acme-bot\n"
                   "always-auth=true\n"),
        "packages/app/.npmrc": "save-exact=false\n//registry.example.com/:_authToken=NESTED_SECRET\n",
    })
    m = ctx.manifest("acme")
    t.clean(m)
    t.eq(m["npmrc"], [
        {"path": ".npmrc", "keys": {"@acme:registry": "npm.example.com:4873", "engine-strict": True,
                                    "legacy-peer-deps": False, "node-linker": "hoisted",
                                    "registry": "registry.example.com", "save-exact": True, "save-prefix": ""}},
        {"path": "packages/app/.npmrc", "keys": {"save-exact": False}}], "whitelisted keys only, hosts without credentials")
    blob = json.dumps(m)
    for secret in secrets:
        t.lacks(blob, secret, "the manifest JSON")


# ------------------------------------------------------------------ cases: update targets
MANIFEST_BASENAMES = ("package.json", "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml",
                      "pnpm-workspace.yaml", "yarn.lock", "bun.lock", "bun.lockb", ".npmrc", ".nvmrc",
                      ".node-version", ".tool-versions", ".python-version", "composer.json", "composer.lock",
                      "requirements.txt", "requirements-dev.txt", "pyproject.toml", "poetry.lock", "Pipfile",
                      "Pipfile.lock", "renovate.json", "renovate.json5", ".renovaterc", ".renovaterc.json",
                      "deno.json", "import_map.json")
STACK_MANIFEST = ["Runtimes", "Frameworks and Critical Libraries", "Package Managers"]


def targets(paths, sections):
    return [{"file": "dependencies.md", "paths": paths}, {"file": "stack.md", "sections": sections, "paths": paths}]


def case_update_root_lockfile(ctx, t):
    t.eq(dm.dependency_update_targets(["pnpm-lock.yaml", "src/app.ts"]),
         targets(["pnpm-lock.yaml"], STACK_MANIFEST), "a root lockfile touches both context files")
    for name in MANIFEST_BASENAMES:
        t.eq(dm.dependency_update_targets([name]), targets([name], STACK_MANIFEST), "basename " + name)
    t.eq(dm.dependency_update_targets(["./packages/web/package.json", "packages/web/package.json"]),
         targets(["packages/web/package.json"], STACK_MANIFEST), "nested manifests, normalised and deduplicated")
    t.eq(dm.dependency_update_targets(["src/z.ts", "yarn.lock", "package.json"]),
         targets(["package.json", "yarn.lock"], STACK_MANIFEST), "paths are sorted")


def case_update_ci_file(ctx, t):
    for path in (".gitlab-ci.yml", "ci/build.gitlab-ci.yml", ".github/workflows/ci.yml", ".github/workflows/release.yaml",
                 ".github/dependabot.yml", ".github/dependabot.yaml", "Dockerfile", "docker/Dockerfile.prod",
                 "docker-compose.yml", "docker-compose.override.yaml", "compose.yaml", "compose.dev.yml"):
        t.eq(dm.dependency_update_targets([path]), targets([path], ["CI/CD"]), "pipeline file " + path)
    t.eq(dm.dependency_update_targets([".gitlab-ci.yml", "package.json"]),
         targets([".gitlab-ci.yml", "package.json"], STACK_MANIFEST + ["CI/CD"]), "a manifest and a pipeline file together")
    for path in (".github/workflows/notes.md", ".github/workflows/sub/ci.yml", "docs/gitlab-ci.md", "docs/dependabot.yml"):
        t.eq(dm.dependency_update_targets([path]), [], "not a pipeline file " + path)


def case_update_unrelated_empty(ctx, t):
    t.eq(dm.dependency_update_targets(["README.md", "src/index.ts", "docs/package.json.md", "composer.jsonl",
                                       "src/requirements.md"]), [], "unrelated paths touch nothing")
    t.eq(dm.dependency_update_targets([]), [], "no paths")
    t.eq(dm.dependency_update_targets(None), [], "no list")


# ------------------------------------------------------------------ cases: the cpcg scanner
OLD_TOP = ["meta", "stack", "dependencies", "entry_points", "configs", "tree", "folders", "conventions",
           "domain_terms", "docs", "api_surface", "data_models", "config_env", "testing", "usage_map", "map"]
OLD_UPDATE = ["affected_folders", "affected_map_rows", "affected_surfaces", "paths"]
ACME_APP = {
    "package.json": J({"name": "acme", "version": "1.0.0", "dependencies": {"react": "^18.0.0"},
                       "scripts": {"build": "vite build"}}),
    "package-lock.json": J({"lockfileVersion": 3, "packages": {"": {}, "node_modules/react": {"version": "18.3.1"}}}),
    "src/app.ts": "export const app = 1\n",
    "src/shared/format.ts": "export function formatMoney(v: number) { return v.toFixed(2) }\n",
}


def lone_scanner(ctx):
    """A copy of the scanner alone in an otherwise empty directory (the module cannot be imported there)."""
    folder = ctx.path("lone")
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, "scan_project.py")
    shutil.copyfile(ctx.scanner, target)
    return target


def case_scan_keys_additive(ctx, t):
    ctx.tree("acme", ACME_APP)
    plain = ctx.scan("acme")
    t.eq(sorted(plain), sorted(OLD_TOP + ["dependency_manifest"]), "top-level keys: the old ones + dependency_manifest")
    out = ctx.scan("acme", "--update", "package.json,src/app.ts")
    t.eq(sorted(out), sorted(OLD_TOP + ["dependency_manifest", "update"]), "top-level keys with --update")
    t.eq(sorted(out["update"]), sorted(OLD_UPDATE + ["affected_context_files"]), "update keys: the old 4 + affected_context_files")
    t.eq(out["update"]["affected_context_files"], dm.dependency_update_targets(["package.json", "src/app.ts"]),
         "affected_context_files is dependency_update_targets(changed)")
    t.eq(ctx.scan("acme", "--update", "src/app.ts")["update"]["affected_context_files"], [],
         "a source file touches no context file")
    base = ctx.scan("acme", "--update", "package.json,src/app.ts", scanner=lone_scanner(ctx))
    for key in OLD_TOP:
        t.eq(out[key], base[key], "legacy key " + key + " is untouched")
    t.eq({k: v for k, v in out["update"].items() if k != "affected_context_files"}, base["update"],
         "legacy update keys are untouched")
    t.eq(out["dependency_manifest"]["format"], 1, "the block carries its format")


def case_module_missing_still_scans(ctx, t):
    ctx.tree("acme", ACME_APP)
    r = ctx.run(lone_scanner(ctx), "acme", "--update", "package.json")
    t.eq(r.rc, 0, "the scan succeeds without the module")
    t.lacks(r.err, "Traceback", "stderr")
    out = json.loads(r.out)
    t.ok("dependency_manifest" not in out, "no dependency_manifest key")
    t.eq(sorted(out["update"]), OLD_UPDATE, "update keeps its 4 keys")
    t.eq(out["stack"]["package_managers"], ["npm"], "the scanner's own package manager list is untouched")


# ------------------------------------------------------------------ cases: other ecosystems
def case_composer_and_requirements(ctx, t):
    ctx.tree("acme", {
        "composer.json": J({"name": "acme/app",
                            "require": {"php": "^8.2", "ext-json": "*", "laravel/framework": "^11.0", "acme/lib": "dev-main"},
                            "require-dev": {"phpunit/phpunit": "^11.1"},
                            "scripts": {"test": "phpunit", "lint": "pint --test"}}),
        "composer.lock": J({"packages": [{"name": "laravel/framework", "version": "v11.9.2"}],
                            "packages-dev": [{"name": "phpunit/phpunit", "version": "11.1.3"}]}),
        "requirements.txt": ("# runtime\nrequests==2.31.0\nflask>=2.0,<3  # web\n-r base.txt\n"
                             "numpy[extra]==1.26.4 ; python_version >= \"3.9\"\n"
                             "git+https://example.com/acme/tool.git#egg=acme-tool\n"),
        "requirements-dev.txt": "pytest==8.2.0\n",
    })
    m = ctx.manifest("acme")
    t.clean(m)
    t.eq(m["package_manager"], {"name": "composer", "version": None, "source": "lockfile"}, "composer.lock decides")
    t.eq(m["lockfiles"], [{"path": "composer.lock", "type": "composer", "version": None}], "composer lockfile")
    rows = {(p["name"], p["kind"]): (p["declared"], p["locked"], p["style"]) for p in m["packages"]}
    t.eq(rows, {
        ("laravel/framework", "prod"): ("^11.0", "v11.9.2", "range"),
        ("acme/lib", "prod"): ("dev-main", None, "tag"),
        ("phpunit/phpunit", "dev"): ("^11.1", "11.1.3", "range"),
        ("requests", "prod"): ("==2.31.0", "2.31.0", "exact"),
        ("flask", "prod"): (">=2.0,<3", None, "range"),
        ("numpy", "prod"): ("==1.26.4", "1.26.4", "exact"),
        ("acme-tool", "prod"): ("git+https://example.com/acme/tool.git", None, "url"),
        ("pytest", "dev"): ("==8.2.0", "8.2.0", "exact")}, "composer packages, platform requirements skipped, pip pins")
    t.eq(m["verification"]["test"], {"command": "composer run test", "source": "composer.json#scripts.test", "note": None},
         "composer scripts back the verification commands")
    t.eq(m["runtimes"]["php"]["pins"], [{"source": "require.php", "value": "^8.2"}], "php pin")

    ctx.tree("pip-only", {"requirements.txt": "requests==2.31.0\n"})
    t.eq(ctx.manifest("pip-only")["package_manager"], {"name": "pip", "version": None, "source": "manifest"},
         "requirements.txt alone means pip")


def case_poetry_tomllib(ctx, t):
    if sys.version_info < (3, 11):
        raise Skip("tomllib needs Python 3.11")
    ctx.tree("acme", {
        "pyproject.toml": ('[tool.poetry]\nname = "acme"\nversion = "0.1.0"\n\n[tool.poetry.dependencies]\n'
                           'python = "^3.11"\nrequests = "^2.31"\ndjango = {version = "^5.0", extras = ["argon2"]}\n'
                           'acme-tool = {git = "https://example.com/acme/tool.git"}\n\n'
                           '[tool.poetry.group.dev.dependencies]\npytest = "^8.2"\n\n'
                           '[build-system]\nrequires = ["poetry-core"]\n'),
        "poetry.lock": ('# This file is automatically @generated by Poetry 1.8.3 and should not be changed by hand.\n\n'
                        '[[package]]\nname = "requests"\nversion = "2.32.3"\n\n[[package]]\nname = "Django"\n'
                        'version = "5.0.6"\n\n[[package]]\nname = "pytest"\nversion = "8.2.2"\n\n[metadata]\n'
                        'lock-version = "2.0"\npython-versions = "^3.11"\ncontent-hash = "abc"\n'),
    })
    m = ctx.manifest("acme")
    t.clean(m)
    t.eq(m["package_manager"], {"name": "poetry", "version": None, "source": "lockfile"}, "poetry.lock decides")
    t.eq(m["lockfiles"], [{"path": "poetry.lock", "type": "poetry", "version": "2.0"}], "lock-version")
    rows = {(p["name"], p["kind"]): (p["declared"], p["locked"], p["style"]) for p in m["packages"]}
    t.eq(rows, {("requests", "prod"): ("^2.31", "2.32.3", "range"),
                ("django", "prod"): ("^5.0", "5.0.6", "range"),
                ("acme-tool", "prod"): ("https://example.com/acme/tool.git", None, "url"),
                ("pytest", "dev"): ("^8.2", "8.2.2", "range")}, "poetry tables joined with poetry.lock")
    t.eq(m["runtimes"]["python"]["pins"], [{"source": "tool.poetry.python", "value": "^3.11"}], "python pin")

    ctx.tree("pep621", {"pyproject.toml": ('[project]\nname = "acme"\nrequires-python = ">=3.10"\n'
                                           'dependencies = ["requests>=2.31", "rich==13.7.1"]\n\n'
                                           '[project.optional-dependencies]\ndocs = ["mkdocs>=1.5"]\n\n'
                                           '[dependency-groups]\ndev = ["pytest>=8"]\n')})
    p = ctx.manifest("pep621")
    t.eq({(e["name"], e["kind"]): (e["declared"], e["locked"]) for e in p["packages"]},
         {("requests", "prod"): (">=2.31", None), ("rich", "prod"): ("==13.7.1", "13.7.1"),
          ("mkdocs", "optional"): (">=1.5", None), ("pytest", "dev"): (">=8", None)}, "PEP 621 and dependency groups")
    t.eq(p["package_manager"], {"name": "pip", "version": None, "source": "manifest"}, "no poetry table means pip")


# ------------------------------------------------------------------ cases: determinism
RICH = {
    "package.json": J({"name": "acme", "packageManager": "pnpm@9.1.0", "workspaces": ["packages/*"],
                       "engines": {"node": ">=20"}, "pnpm": {"patchedDependencies": {"express@4.18.2": "patches/e.patch"}},
                       "dependencies": {"zod": "^3.23.0", "express": "^4.18.2"}, "devDependencies": {"@types/node": "^20"},
                       "scripts": {"build": "vite build", "test": "vitest run"}}),
    "pnpm-workspace.yaml": "packages:\n  - 'packages/*'\ncatalog:\n  # pin\n  zod: ^3.23.0\nonlyBuiltDependencies:\n  - esbuild\n",
    "pnpm-lock.yaml": PNPM_V9,
    "packages/a/package.json": J({"name": "a", "dependencies": {"zod": "catalog:"}}),
    "packages/b/package.json": J({"name": "b"}),
    ".npmrc": "save-exact=true\nregistry=https://registry.example.com/\n",
    ".nvmrc": "20.11.1\n",
    "renovate.json": J({"packageRules": [{"matchPackageNames": ["zod", "express"], "allowedVersions": "<4"}]}),
    ".gitlab-ci.yml": GITLAB_CI,
    ".github/workflows/ci.yml": "name: ci\non: [push]\njobs:\n  t:\n    runs-on: ubuntu-latest\n    steps:\n"
                                "      - uses: actions/checkout@v4\n      - run: pnpm test\n",
    "Dockerfile": "FROM node:20.11.1-alpine AS build\nFROM nginx:1.25\n",
    "docker-compose.yml": "services:\n  web:\n    image: nginx:1.25\n  db:\n    image: postgres:16\n",
    "requirements.txt": "requests==2.31.0\nflask>=2.0\n",
    "go.mod": "module example.com/acme\n",
    "patches/lodash+4.17.21.patch": "diff\n",
}
DUMP = ("import sys, json\nsys.dont_write_bytecode = True\nsys.path.insert(0, sys.argv[1])\n"
        "import dependency_manifest as m\nsys.stdout.write(json.dumps(m.dependency_manifest(sys.argv[2])))\n")


def case_deterministic_bytes(ctx, t):
    ctx.tree("acme", RICH)
    ctx.tree("copy", RICH)
    first = json.dumps(dm.dependency_manifest(Path(ctx.path("acme"))))
    t.eq(json.dumps(dm.dependency_manifest(Path(ctx.path("acme")))), first, "two runs in one process")
    t.eq(json.dumps(dm.dependency_manifest(Path(ctx.path("copy")))), first, "the same tree under another root")
    t.lacks(first, ctx.root, "the manifest must not carry absolute paths")
    for seed in ("1", "2", "3"):
        env = dict(ctx.env)
        env["PYTHONHASHSEED"] = seed
        p = subprocess.run([sys.executable, "-c", DUMP, HERE, ctx.path("acme")], capture_output=True, text=True, env=env)
        t.eq(p.returncode, 0, "fresh interpreter, hash seed " + seed)
        t.ok(p.stdout == first, "fresh interpreter output differs for hash seed " + seed)
    t.ok(json.loads(first)["notes"] == sorted(json.loads(first)["notes"]), "notes are sorted")


# ------------------------------------------------------------------ runner
CASES = [
    ("npm_lockfile_v3", case_npm_lockfile_v3),
    ("pnpm_packagemanager_v9_importers", case_pnpm_packagemanager_v9_importers),
    ("npm_mislabel_fixed", case_npm_mislabel_fixed),
    ("both_lockfiles_note", case_both_lockfiles_note),
    ("npm_workspaces_globs", case_npm_workspaces_globs),
    ("pnpm_workspace_catalog_overrides_allowbuilds_comments", case_pnpm_workspace_catalog_overrides_allowbuilds_comments),
    ("pnpm_patched_dependencies", case_pnpm_patched_dependencies),
    ("runtime_pins_all_sources", case_runtime_pins_all_sources),
    ("shadowed_by_node_package", case_shadowed_by_node_package),
    ("renovate_caps_disabled_minage_groups", case_renovate_caps_disabled_minage_groups),
    ("renovate_json5_unparsed", case_renovate_json5_unparsed),
    ("dependabot_presence", case_dependabot_presence),
    ("gitlab_ci_images_services_verify_audit_mrpipelines", case_gitlab_ci_images_services_verify_audit_mrpipelines),
    ("ci_pins_pip_supabase", case_ci_pins_pip_supabase),
    ("github_actions_setup_node", case_github_actions_setup_node),
    ("verification_placeholder_and_external", case_verification_placeholder_and_external),
    ("npmrc_whitelist_no_secret", case_npmrc_whitelist_no_secret),
    ("update_root_lockfile", case_update_root_lockfile),
    ("update_ci_file", case_update_ci_file),
    ("update_unrelated_empty", case_update_unrelated_empty),
    ("scan_keys_additive", case_scan_keys_additive),
    ("module_missing_still_scans", case_module_missing_still_scans),
    ("composer_and_requirements", case_composer_and_requirements),
    ("poetry_tomllib", case_poetry_tomllib),
    ("deterministic_bytes", case_deterministic_bytes),
]


def run_case(fn, scanner, keep):
    root = os.path.realpath(tempfile.mkdtemp(prefix="dependency-manifest-selftest-"))
    t = Check()
    try:
        fn(Ctx(scanner, root), t)
        verdict, why = ("FAIL", "; ".join(p[:150] for p in t.problems[:8])) if t.problems else ("PASS", "")
    except Skip as s:
        verdict, why = "SKIP", str(s)
    except Exception as exc:  # a broken harness or a crashing module is a failure, not a crash
        verdict, why = "FAIL", f"harness error: {exc!r}"
    finally:
        if keep:
            print(f"  kept {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)
    return verdict, why


def main():
    ap = argparse.ArgumentParser(description="Behavioural tests for dependency_manifest.py")
    ap.add_argument("--scanner", default=os.path.join(HERE, "scan_project.py"),
                    help="scan_project.py under test")
    ap.add_argument("--only", help="run a single case by name")
    ap.add_argument("--keep", action="store_true", help="leave the temp trees on disk")
    args = ap.parse_args()
    scanner = os.path.abspath(os.path.expanduser(args.scanner))
    if not os.path.isfile(scanner):
        print(f"scanner not found: {scanner}")
        return 2
    cases = [c for c in CASES if not args.only or c[0] == args.only]
    if not cases:
        print(f"unknown case {args.only!r}; known: {', '.join(n for n, _ in CASES)}")
        return 2
    tally = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    for name, fn in cases:
        verdict, why = run_case(fn, scanner, args.keep)
        tally[verdict] += 1
        print(f"{verdict} {name}" + (f" — {why}" if why else ""))
    print(f"{tally['PASS']} PASS · {tally['FAIL']} FAIL · {tally['SKIP']} SKIP (of {len(cases)})")
    return 1 if tally["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
