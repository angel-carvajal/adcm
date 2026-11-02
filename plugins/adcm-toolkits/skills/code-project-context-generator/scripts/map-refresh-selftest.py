#!/usr/bin/env python3
"""map-refresh-selftest - behavioural tests for the map detectors of scan_project.py (stdlib only).

Usage:
  python3 map-refresh-selftest.py [--scanner PATH] [--script PATH] [--only NAME] [--keep]

Every case builds one throwaway `tempfile` project (generic "Acme" code), runs scan_project.py on it as a
subprocess (`<project> [--update PATHS]`, PYTHONDONTWRITEBYTECODE=1) and prints
`PASS|FAIL|SKIP <case> [- why]`, then the tally `N PASS · N FAIL · N SKIP (of N)`. Exit code 1 when any
case FAILs. No real project tree is ever scanned. One case imports the scanner under test as a module,
to run two of its detectors in both orders.

What is asserted (JSON structure of the scanner output, never prose):
  - the `usage_map` block (shared roots, surfaces and their consumer census) and the legacy `update` keys
    keep their exact content, so extending the scanner cannot move them;
  - the additive `map` block and `update.affected_map_rows`: keys, row shapes, caps and determinism.

The scanner under test defaults to the scan_project.py next to this file; pass --scanner to test another
copy. --script names the map writer (map_refresh.py), which the writer cases drive and skip when it is
absent. The writer cases lay out a container in the temp tree (the brain at ai/ai-brain, each project under
projects/) and run the writer from its root; they assert the rendered map files, exit codes and last lines.
--keep leaves the temp trees on disk.
"""
import argparse
import datetime
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))


class Skip(Exception):
    pass


# ------------------------------------------------------------------ harness
class R:
    """One scanner run."""

    def __init__(self, p):
        self.rc, self.out, self.err = p.returncode, p.stdout, p.stderr
        self.text = p.stdout + p.stderr


class Ctx:
    def __init__(self, scanner, script, root):
        self.scanner, self.script, self.root = scanner, script, root
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

    def run(self, project, *flags):
        cmd = [sys.executable, self.scanner, self.path(project)] + list(flags)
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=self.env, cwd=self.root, timeout=120)
        return R(p)

    def scan(self, project, *flags):
        """Run the scanner and return its parsed JSON; a failing run raises (the case reports FAIL)."""
        r = self.run(project, *flags)
        if r.rc != 0:
            raise RuntimeError(f"scanner exit {r.rc}: {r.err.strip()[:300]}")
        return json.loads(r.out)


def load_scanner(path):
    """Import the scanner under test as a module, writing no bytecode next to it."""
    keep, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec = importlib.util.spec_from_file_location("scan_project_under_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = keep
    return module


class Check:
    def __init__(self):
        self.problems = []

    def ok(self, cond, what):
        if not cond:
            self.problems.append(what)

    def eq(self, got, want, what):
        if got != want:
            self.problems.append(f"{what}: got {got!r}, want {want!r}")

    def has(self, hay, needle, what):
        if needle not in (hay or ""):
            self.problems.append(f"{what}: {needle!r} not in {(hay or '')[:80]!r}")

    def lacks(self, hay, needle, what):
        if needle in (hay or ""):
            self.problems.append(f"{what}: {needle!r} must not be present")


# ------------------------------------------------------------------ fixtures
# A project with several shared folders and billing consumers. It deliberately has no folder named
# services, api, hooks, models, clients, stores or composables: those are shared roots only for the map.
ACME_USAGE = {
    "package.json": '{"name": "acme", "version": "1.0.0", "dependencies": {"react": "^18.0.0"}}\n',
    "shared/invoice.ts": (
        "export interface Invoice { id: string; total: number }\n"
        "export class InvoiceTotals {\n"
        "  sum(): number { return 0 }\n"
        "}\n"
        "export const TAX_RATE = 0.16\n"
        "class InternalRow {}\n"
    ),
    "shared/payment.ts": (
        "export class PaymentProvider {}\n"
        "export type PaymentId = string\n"
    ),
    "shared/provider.ts": (
        "export class Provider {}\n"
        "export function Client() { return null }\n"
    ),
    "shared/ui/badge.tsx": "export default function Badge() { return null }\n",
    "shared/ui/index.ts": "export { Badge as StatusBadge } from './badge'\n",
    "components/receipt-card.component.ts": (
        "@Component({ selector: 'acme-receipt-card' })\n"
        "export class ReceiptCard {}\n"
    ),
    "lib/money.ts": (
        "export const formatMoney = (n: number) => String(n)\n"
        "export const fmt = 1\n"
    ),
    "modules/billing/invoice-page.tsx": (
        "import { Invoice, InvoiceTotals, TAX_RATE } from '@/shared/invoice'\n"
        "import { PaymentProvider } from '@/shared/payment'\n"
        "import { formatMoney } from '@/lib/money'\n"
        "import { StatusBadge } from '@/shared/ui'\n"
        "export function InvoicePage(props: { invoice: Invoice }) {\n"
        "  const money = fmt(1)\n"
        "  return Client()\n"
        "}\n"
    ),
    "modules/billing/invoice-list.tsx": (
        "import { Invoice } from '@/shared/invoice'\n"
        "import { formatMoney } from '@/lib/money'\n"
        "import { StatusBadge } from '@/shared/ui'\n"
        "export const InvoiceList = (rows: Invoice[]) => rows\n"
    ),
    "modules/billing/invoice-form.tsx": (
        "import Badge from '@/shared/ui/badge'\n"
        "import { Invoice } from '@/shared/invoice'\n"
        "import { PaymentId } from '@/shared/payment'\n"
        "import { formatMoney } from '@/lib/money'\n"
        "export const tag = '<acme-receipt-card />'\n"
    ),
    "modules/billing/index.ts": (
        "export type { Invoice } from '@/shared/invoice'\n"
        "export const rowKind = 'InternalRow'\n"
    ),
    "src/app.tsx": "import { ReceiptCard } from '@/components/receipt-card.component'\n",
}

# The census one-liner exactly as emitted for every surface.
CENSUS_FMT = ("grep -rl '{sym}' . --exclude-dir=node_modules --exclude-dir=.git --exclude-dir=coverage "
              "--exclude-dir=reports --exclude-dir=dist --exclude-dir=.next | wc -l")

BILLING = "modules/billing/"
# symbol, defined_in, consumers_count, consumers
USAGE_SURFACES = [
    ("Invoice", "shared/invoice.ts", 4,
     [BILLING + "index.ts", BILLING + "invoice-form.tsx", BILLING + "invoice-list.tsx",
      BILLING + "invoice-page.tsx"]),
    ("Badge", "shared/ui/badge.tsx", 3,
     [BILLING + "invoice-form.tsx", BILLING + "invoice-list.tsx", BILLING + "invoice-page.tsx"]),
    ("formatMoney", "lib/money.ts", 3,
     [BILLING + "invoice-form.tsx", BILLING + "invoice-list.tsx", BILLING + "invoice-page.tsx"]),
    ("StatusBadge", "shared/ui/index.ts", 2,
     [BILLING + "invoice-list.tsx", BILLING + "invoice-page.tsx"]),
    ("InternalRow", "shared/invoice.ts", 1, [BILLING + "index.ts"]),
    ("InvoiceTotals", "shared/invoice.ts", 1, [BILLING + "invoice-page.tsx"]),
    ("PaymentId", "shared/payment.ts", 1, [BILLING + "invoice-form.tsx"]),
    ("PaymentProvider", "shared/payment.ts", 1, [BILLING + "invoice-page.tsx"]),
    ("ReceiptCard", "components/receipt-card.component.ts", 1, ["src/app.tsx"]),
    ("TAX_RATE", "shared/invoice.ts", 1, [BILLING + "invoice-page.tsx"]),
    ("acme-receipt-card", "components/receipt-card.component.ts", 1, [BILLING + "invoice-form.tsx"]),
]


# ------------------------------------------------------------------ cases
def case_usage_map_golden(ctx, t):
    ctx.tree("acme", ACME_USAGE)
    out = ctx.scan("acme", "--update", "shared/invoice.ts," + BILLING + "invoice-form.tsx")

    um = out["usage_map"]
    t.eq(sorted(um), ["count", "shared_roots", "surfaces"], "usage_map keys")
    t.eq(um["shared_roots"], ["components", "lib", "shared"], "shared_roots (shared/ui is nested, not a root)")
    t.eq(um["count"], len(USAGE_SURFACES), "usage_map count")
    got = {s["symbol"]: s for s in um["surfaces"]}
    t.eq(sorted(got), sorted(w[0] for w in USAGE_SURFACES),
         "surface symbols (Provider, Client and fmt are consumed but filtered out)")
    for sym, defined_in, n, consumers in USAGE_SURFACES:
        g = got.get(sym)
        if g is None:
            continue
        # the consumer sample is in directory-listing order, which the filesystem decides
        t.eq(dict(g, consumers=sorted(g["consumers"])),
             {"symbol": sym, "defined_in": defined_in, "consumers_count": n, "consumers": consumers,
              "census_cmd": CENSUS_FMT.format(sym=sym)}, f"surface {sym}")
    counts = [s["consumers_count"] for s in um["surfaces"]]
    t.eq(counts, sorted(counts, reverse=True), "surfaces are ordered by consumers_count, highest first")

    up = out["update"]
    t.eq(up["paths"], ["shared/invoice.ts", BILLING + "invoice-form.tsx"], "update.paths")
    t.eq(up["affected_folders"], ["modules", "modules/billing", "shared"], "update.affected_folders")
    t.eq(up["affected_surfaces"],
         ["Badge", "InternalRow", "Invoice", "InvoiceTotals", "PaymentId", "TAX_RATE", "acme-receipt-card",
          "formatMoney"],
         "update.affected_surfaces")


UTILITY_KEYS = ["consumers_count", "exemplar", "generics", "kind", "path", "signature", "symbol"]
PATTERN_KEYS = ["base", "count", "evidence_paths", "exemplar", "kind", "name", "status"]
CANDIDATE_LABEL = "signal only — same-behaviour test decides"
PKG = '{"name": "acme", "dependencies": {"%s": "^18.0.0"}}\n'


def rows(out, key):
    return out["map"][key]


def find(found, field, value):
    return next((r for r in found if r[field] == value), None)


def check_row(t, got, want, what):
    """Compare a row key by key so a failure names the field that moved."""
    if got is None:
        t.ok(False, f"{what}: row missing")
        return
    for k, v in want.items():
        t.eq(got.get(k), v, f"{what}.{k}")


def abstract_class(name):
    return f"export abstract class {name}<T> {{}}\n"


def generic_fn(name):
    return f"export function {name}<T>(x: T): T {{ return x }}\n"


def add_family(files, n, base_path):
    """BaseFam<n> at `base_path` and the two classes under src/ext/ that extend it."""
    files[base_path] = "export class BaseFam%02d {}\n" % n
    for side in "ab":
        files[f"src/ext/fam{n:02d}{side}.ts"] = "export class Fam%02d%s extends BaseFam%02d {}\n" % (n, side, n)


# ------------------------------------------------------------------ map cases
BASE_API = ("export abstract class BaseApiService<T extends Record<string, unknown>> {\n"
            "  constructor(protected readonly path: string) {}\n"
            "}\n")
SERVICES = "src/features/%s/%s.service.ts"


def service_tree():
    """A generic abstract base in shared/ and three services that extend it."""
    return {
        "package.json": PKG % "react",
        "README.md": "# Acme\n",
        "src/shared/base-api.service.ts": BASE_API,
        SERVICES % ("providers", "providers"): (
            "import { BaseApiService } from '@/shared/base-api.service'\n"
            "export class ProvidersService extends BaseApiService<Provider> {}\n"),
        SERVICES % ("invoices", "invoices"): "export class InvoicesService extends BaseApiService<Invoice> {}\n",
        SERVICES % ("payments", "payments"): "export class PaymentsService extends BaseApiService<Payment> {}\n",
    }


def case_map_block_keys(ctx, t):
    ctx.tree("acme", service_tree())
    out = ctx.scan("acme")
    t.eq(sorted(out["map"]), ["count", "patterns", "utilities", "where_to_look"], "map keys")
    t.ok(rows(out, "utilities") and rows(out, "patterns") and rows(out, "where_to_look"),
         "the fixture fills all three lists, so the row shapes below are really checked")
    for u in rows(out, "utilities"):
        t.eq(sorted(u), UTILITY_KEYS, f"utility row {u['symbol']} keys")
    t.lacks(json.dumps(rows(out, "utilities")), "census_cmd", "utility rows leave the census one-liner to usage_map")
    for p in rows(out, "patterns"):
        t.eq(sorted(p), PATTERN_KEYS, f"pattern row {p['name']} keys")
    for w in rows(out, "where_to_look"):
        t.eq(sorted(w), ["path", "topic"], f"where_to_look row {w.get('path')} keys")
    t.eq(out["map"]["count"], len(rows(out, "utilities")) + len(rows(out, "patterns"))
         + len(rows(out, "where_to_look")), "map.count is the number of rows across the three lists")
    t.eq(sorted(out["usage_map"]), ["count", "shared_roots", "surfaces"], "usage_map keeps its own three keys")
    t.eq(json.dumps(ctx.scan("acme")["map"], sort_keys=True), json.dumps(out["map"], sort_keys=True),
         "a second scan of the same tree yields the same map")

    dest = ctx.path("report.json")
    r = ctx.run("acme", "--output", dest)
    t.eq(r.rc, 0, "scan to a file: exit code")
    n = (len(rows(out, "utilities")), len(rows(out, "patterns")), len(rows(out, "where_to_look")))
    t.has(r.text, "Map candidates: utilities %d · patterns %d · where %d" % n, "stderr summary names the map")
    with open(dest, encoding="utf-8") as fh:
        t.eq(json.load(fh)["map"], out["map"], "the file carries the same map block")


def case_ts_generic_base_family(ctx, t):
    files = service_tree()
    files.update({
        "src/features/invoices/a-first.spec.ts": "export class FakeService extends BaseApiService<Fake> {}\n",
        "src/features/solo/base-solo.ts": "export class BaseSolo {}\n",
        "src/features/solo/solo.ts": "export class Solo extends BaseSolo {}\n",
        "src/views/left.ts": "export class Left extends Model {}\n",
        "src/views/right.ts": "export class Right extends Model {}\n",
        "src/views/third.ts": "export class Third extends React.Component<Props> {}\n",
        "src/views/fourth.ts": "export class Fourth extends React.Component<Props> {}\n",
        "src/messaging/mailer.ts": "export class Mailer {}\n",
        "src/messaging/smtp-mailer.ts": "export class SmtpMailer extends Mailer {}\n",
        "src/messaging/ses-mailer.ts": "export class SesMailer extends Mailer {}\n",
    })
    ctx.tree("acme", files)
    out = ctx.scan("acme")

    t.eq([u["symbol"] for u in rows(out, "utilities")], ["BaseApiService", "Mailer"],
         "utilities: the abstract base, then the plain class that heads a family (BaseSolo has one subclass)")
    check_row(t, find(rows(out, "utilities"), "symbol", "BaseApiService"), {
        "path": "src/shared/base-api.service.ts", "kind": "abstract-class",
        "signature": "export abstract class BaseApiService<T extends Record<string, unknown>>",
        "generics": "T extends Record<string, unknown>",
        "consumers_count": 4,
        "exemplar": "src/features/invoices/invoices.service.ts"}, "BaseApiService")
    check_row(t, find(rows(out, "utilities"), "symbol", "Mailer"), {
        "path": "src/messaging/mailer.ts", "kind": "base-class", "signature": "export class Mailer {}",
        "generics": "", "consumers_count": 2, "exemplar": "src/messaging/ses-mailer.ts"}, "Mailer")

    families = [p["name"] for p in rows(out, "patterns") if p["kind"] == "family"]
    t.eq(families, ["family:BaseApiService", "family:Mailer"],
         "families: framework bases (Model, React.Component), a one-subclass base and test doubles are left out")
    check_row(t, find(rows(out, "patterns"), "name", "family:BaseApiService"), {
        "kind": "family", "status": "applied", "count": 3, "base": "BaseApiService",
        "evidence_paths": [SERVICES % ("invoices", "invoices"), SERVICES % ("payments", "payments"),
                           SERVICES % ("providers", "providers")],
        "exemplar": SERVICES % ("invoices", "invoices")}, "family:BaseApiService")


def case_hooks_and_composables(ctx, t):
    hooks = {
        "src/hooks/useToggle.ts": "export const useToggle = (initial = false) => initial\n",
        "src/hooks/useDebounce.ts": ("export function useDebounce<T>(value: T, delay = 300): T {\n"
                                     "  return value\n}\n"),
        "src/hooks/useStable.ts": ("export function useStable<T extends (a: number) => void>(fn: T): T {\n"
                                   "  return fn\n}\n"),
        "src/pages/home.tsx": ("import { useToggle } from '@/hooks/useToggle'\n"
                               "import { useDebounce } from '@/hooks/useDebounce'\n"),
    }
    ctx.tree("react-app", {**hooks, "package.json": PKG % "react"})
    out = ctx.scan("react-app")
    check_row(t, find(rows(out, "utilities"), "symbol", "useToggle"),
              {"kind": "hook", "path": "src/hooks/useToggle.ts", "generics": "", "consumers_count": 1,
               "signature": "export const useToggle = (initial = false) => initial"}, "react useToggle")
    check_row(t, find(rows(out, "utilities"), "symbol", "useDebounce"),
              {"kind": "generic-fn", "generics": "T", "consumers_count": 1,
               "signature": "export function useDebounce<T>(value: T, delay = 300): T"},
              "react useDebounce (a generic function outranks a plain hook)")
    check_row(t, find(rows(out, "utilities"), "symbol", "useStable"),
              {"kind": "generic-fn", "generics": "T extends (a: number) => void"},
              "react useStable (the arrow inside the type parameters is not a closing bracket)")

    ctx.tree("vue-app", {**hooks, "package.json": PKG % "vue",
                         "src/composables/useCart.ts": "export function useCart() { return 1 }\n"})
    out = ctx.scan("vue-app")
    for name in ("useToggle", "useCart"):
        got = find(rows(out, "utilities"), "symbol", name)
        t.eq(got and got["kind"], "composable", f"vue {name} is a composable")

    ctx.tree("plain-app", {"package.json": '{"name": "acme"}\n',
                           "src/hooks/useToggle.ts": hooks["src/hooks/useToggle.ts"],
                           "src/composables/useCart.ts": "export function useCart() { return 1 }\n"})
    out = ctx.scan("plain-app")
    kinds = {u["symbol"]: u["kind"] for u in rows(out, "utilities")}
    t.eq(kinds, {"useCart": "composable", "useToggle": "hook"},
         "without Vue, only a file under composables/ makes a composable")


def case_shape_without_base(ctx, t):
    ctx.tree("acme", {
        "package.json": '{"name": "acme"}\n',
        "src/features/providers/providers.repository.ts": "export const listProviders = () => []\n",
        "src/features/invoices/InvoiceRepository.ts": "export const listInvoices = () => []\n",
        "src/features/payments/payment_repository.py": "def list_payments():\n    return []\n",
        "src/features/orders/test_orders_repository.py": "def test_orders():\n    pass\n",
        "src/features/providers/providers.form.tsx": "export const ProvidersForm = 1\n",
        "src/features/invoices/invoices.form.tsx": "export const InvoicesForm = 1\n",
        "src/dto/UserDTO.ts": "export interface UserDTO { id: string }\n",
        "src/dto/OrderDto.ts": "export interface OrderDto { id: string }\n",
        "src/dto/item.dto.ts": "export interface ItemDto { id: string }\n",
        "src/dto/a.dto.ts": "export interface ADto { id: string }\n",
        "src/dto/b.dto.ts": "export interface BDto { id: string }\n",
        "src/dto/c.dto.ts": "export interface CDto { id: string }\n",
    })
    out = ctx.scan("acme")
    shapes = [p for p in rows(out, "patterns") if p["kind"] == "shape"]
    t.eq([p["name"] for p in shapes], ["shape:dto", "shape:repository"],
         "a role needs three non-test members (two forms are not enough); the role is the last word of the "
         "name, whether dotted, PascalCase, snake_case or an acronym")
    check_row(t, find(shapes, "name", "shape:repository"), {
        "count": 3, "base": None,
        "evidence_paths": ["src/features/invoices/InvoiceRepository.ts",
                           "src/features/payments/payment_repository.py",
                           "src/features/providers/providers.repository.ts"],
        "exemplar": "src/features/invoices/InvoiceRepository.ts"},
        "shape:repository (test_orders_repository.py is a test and is left out)")
    check_row(t, find(shapes, "name", "shape:dto"), {
        "count": 6, "base": None, "exemplar": "src/dto/OrderDto.ts",
        "evidence_paths": ["src/dto/OrderDto.ts", "src/dto/UserDTO.ts", "src/dto/a.dto.ts", "src/dto/b.dto.ts",
                           "src/dto/c.dto.ts"]}, "shape:dto (six members, five evidence paths)")
    for row in shapes:
        t.ok(row["status"].startswith("candidate (no shared base)"), f"{row['name']}: status says no shared base")
        t.has(row["status"], CANDIDATE_LABEL, f"{row['name']}: the candidate is labelled as a signal only")


def case_shape_base_status(ctx, t):
    ctx.tree("acme", {
        "package.json": '{"name": "acme"}\n',
        "src/web/base-http.ts": "export class BaseController {}\nexport class BaseStore {}\n",
        "src/web/users.controller.ts": "export class UsersController extends BaseController {}\n",
        "src/web/orders.controller.ts": "export class OrdersController {}\n",
        "src/web/items.controller.ts": "export class ItemsController {}\n",
        "src/web/misc.controller.ts": "export class MiscController {}\n",
        "src/state/cart.store.ts": "export class CartStore extends BaseStore {}\n",
        "src/state/user.store.ts": "export class UserStore extends BaseStore {}\n",
        "src/state/ui.store.ts": "export class UiStore extends BaseStore {}\n",
        "src/state/log.store.ts": "export class LogStore {}\n",
        "src/views/bases.ts": "export class BaseListA {}\nexport class BaseListB {}\n",
        "src/views/a1.list.ts": "export class A1List extends BaseListA {}\n",
        "src/views/a2.list.ts": "export class A2List extends BaseListA {}\n",
        "src/views/b1.list.ts": "export class B1List extends BaseListB {}\n",
        "src/views/b2.list.ts": "export class B2List extends BaseListB {}\n",
    })
    out = ctx.scan("acme")
    check_row(t, find(rows(out, "patterns"), "name", "shape:store"), {
        "status": "applied", "base": "BaseStore", "count": 4,
        "exemplar": "src/state/cart.store.ts"}, "shape:store (3 of 4 extend one local base)")
    check_row(t, find(rows(out, "patterns"), "name", "shape:controller"), {
        "status": "partial 1/4", "base": "BaseController", "count": 4,
        "exemplar": "src/web/users.controller.ts"}, "shape:controller (1 of 4 extends a local base)")
    check_row(t, find(rows(out, "patterns"), "name", "shape:list"), {
        "status": "applied", "base": "BaseListA", "count": 4,
        "exemplar": "src/views/a1.list.ts"}, "shape:list (two bases tie: the first by name is reported)")


def case_utility_type_counts(ctx, t):
    ctx.tree("acme", {
        "package.json": '{"name": "acme"}\n',
        "src/a.ts": ("type A = Partial<Invoice>\ntype B = Pick<Invoice, 'id'>\ntype C = Record<string, number>\n"
                     "type D = ReadonlyArray<string> & MyPartial<Invoice>\n"),
        "src/b.ts": "type E = Partial<Provider> & Record<string, string> & Record<number, number>\n",
        "src/c.tsx": "type F = Omit<Props, 'x'>\n",
        "src/f1.ts": "type H = Awaited<Promise<number>>\n",
        "src/f2.ts": "type I = Awaited<Promise<string>>\n",
        "src/f3.ts": "type J = Awaited<Promise<boolean>>\n",
        "src/z.ts": "type Z = Required<A> & Required<B> & Required<C> & Required<D> & Required<E>\n",
        "src/a.spec.ts": "type G = Partial<A> & Partial<B> & Partial<C> & Partial<D>\n",
    })
    out = ctx.scan("acme")
    found = [p for p in rows(out, "patterns") if p["name"].startswith("types:")]
    t.eq(len(found), 1, "types:utility is a single row")
    check_row(t, found[0] if found else None, {
        "name": "types:utility", "kind": "types", "status": "applied", "count": 15,
        "base": "Required 5 · Awaited 3 · Record 3 · Partial 2 · Omit 1 · Pick 1",
        "evidence_paths": ["src/a.ts", "src/b.ts", "src/c.tsx", "src/f1.ts", "src/z.ts"], "exemplar": "src/z.ts"},
        "types:utility (tests, ReadonlyArray and MyPartial are not counted; the files using it most are the evidence)")

    ctx.tree("bare", {"package.json": '{"name": "acme"}\n', "src/a.ts": "export const a = 1\n"})
    t.eq([p for p in rows(ctx.scan("bare"), "patterns") if p["name"].startswith("types:")], [],
         "no row when no utility type is used")


def case_shared_hints_extended(ctx, t):
    ctx.tree("acme", {
        "package.json": PKG % "react",
        "src/services/BaseMailer.ts": abstract_class("BaseMailer"),
        "src/services/audit.service.ts": "@Injectable({ providedIn: 'root' })\nexport class AuditService {}\n",
        "src/api/BaseFetcher.ts": abstract_class("BaseFetcher"),
        "src/models/BaseModel.ts": abstract_class("BaseModel"),
        "src/stores/BaseStore.ts": abstract_class("BaseStore"),
        "src/clients/BaseHttpClient.ts": abstract_class("BaseHttpClient"),
        "src/shared/BaseShared.ts": abstract_class("BaseShared"),
        "src/shared/Wrapper.ts": "export class Wrapper<T> {}\n",
        "src/shared/identity.tsx": "export const identity = <T,>(value: T) => value\n",
        "src/hooks/useThing.ts": "export const useThing = () => 1\n",
        "src/composables/useCart.ts": "export function useCart() { return 1 }\n",
        "app/api/BaseRoute.ts": abstract_class("BaseRoute"),
        "pages/api/BasePageApi.ts": abstract_class("BasePageApi"),
        "routes/api/BaseRouteApi.ts": abstract_class("BaseRouteApi"),
    })
    out = ctx.scan("acme")
    t.eq({u["symbol"]: u["kind"] for u in rows(out, "utilities")}, {
        "BaseMailer": "abstract-class", "BaseFetcher": "abstract-class", "BaseModel": "abstract-class",
        "BaseStore": "abstract-class", "BaseHttpClient": "abstract-class", "BaseShared": "abstract-class",
        "AuditService": "service", "Wrapper": "generic-class", "identity": "generic-fn",
        "useThing": "hook", "useCart": "composable"},
        "services, api, hooks, models, clients, stores and composables are shared roots for the map; "
        "app/api, pages/api and routes/api hold route handlers and are not")
    check_row(t, find(rows(out, "utilities"), "symbol", "identity"), {
        "generics": "T,", "signature": "export const identity = <T,>(value: T) => value"},
        "identity (type parameters of a generic arrow function)")
    t.eq(out["usage_map"]["shared_roots"], ["src/shared"],
         "the usage map still reads only its original hints")


def case_app_root_guard(ctx, t):
    files = {"package.json": '{"name": "acme"}\n',
             "apps/api/BaseHandler.ts": abstract_class("BaseHandler"),
             "apps/api/src/services/BaseUsers.ts": abstract_class("BaseUsers"),
             "apps/web/hooks/BaseWebHooks.ts": abstract_class("BaseWebHooks"),
             "apps/web/src/lib/BaseWebLib.ts": abstract_class("BaseWebLib"),
             "services/api/package.json": '{"name": "svc"}\n',
             "services/api/BaseWorker.ts": abstract_class("BaseWorker"),
             "packages/hooks/package.json": '{"name": "hk"}\n',
             "packages/hooks/BaseHooks.ts": abstract_class("BaseHooks"),
             "src/services/BaseMailer.ts": abstract_class("BaseMailer"),
             "apps/web/src/services/BaseWebStore.ts": abstract_class("BaseWebStore")}
    # each manifest kind turns a folder into an application of its own
    for folder, manifest in (("models", "pyproject.toml"), ("clients", "go.mod"),
                             ("stores", "composer.json"), ("hooks", "Cargo.toml")):
        files[f"{folder}/{manifest}"] = "x\n"
        files[f"{folder}/Base{folder.title()}.ts"] = abstract_class("Base" + folder.title())
    ctx.tree("acme", files)
    out = ctx.scan("acme")
    t.eq(sorted(u["symbol"] for u in rows(out, "utilities")), ["BaseMailer", "BaseWebLib"],
         "apps/api, a folder with its own manifest and anything inside apps/<app>/, at any depth, are not "
         "mistaken for shared code; a plain src/services is, and so is a lib/ inside an app, which the usage "
         "map reads too")
    t.eq(out["usage_map"]["shared_roots"], ["apps/web/src/lib"], "the usage map keeps reading that lib/")


def case_utility_exemplar(ctx, t):
    ctx.tree("acme", {
        "package.json": '{"name": "acme"}\n',
        "lib/base-thing.ts": abstract_class("BaseThing"),
        "lib/barrel.ts": "export { BaseThing } from './base-thing'\nexport { formatMoney } from './money'\n",
        "lib/money.ts": ("export function formatMoney(n: number): string {\n  return String(n)\n}\n"
                         "export const roundTo = (n: number) => n\n"
                         "export const doubled = n => n * 2\n"
                         "export const memo = function (n: number) { return n }\n"
                         "export const fetchRate = async (id: string) => id\n"
                         "export const clampTo = (n: number) => n\n"),
        "lib/solo.ts": abstract_class("BaseSolo"),
        "lib/index.ts": "export { BaseSolo } from './solo'\n",
        "lib/a-solo.spec.ts": "BaseSolo\n",
        "lib/lonely.ts": abstract_class("BaseLonely"),
        "lib/nobody.ts": abstract_class("BaseNobody"),
        "src/page.ts": "import { BaseThing } from 'lib'\nformatMoney(1)\n",
        "src/page.spec.ts": "BaseThing\nformatMoney(2)\nBaseLonely\n",
        "src/other.ts": "roundTo(2); doubled(2); memo(2); fetchRate('a'); clampTo(2)\n",
        "src/another.ts": "roundTo(3); doubled(3); memo(3); fetchRate('b')\n",
    })
    out = ctx.scan("acme")
    t.eq([(u["symbol"], u["kind"], u["consumers_count"]) for u in rows(out, "utilities")],
         [("BaseThing", "abstract-class", 3), ("BaseSolo", "abstract-class", 2),
          ("BaseLonely", "abstract-class", 1), ("BaseNobody", "abstract-class", 0),
          ("formatMoney", "helper", 3), ("doubled", "helper", 2), ("fetchRate", "helper", 2),
          ("memo", "helper", 2), ("roundTo", "helper", 2)],
         "utilities rank by kind, then consumers; a function declaration, arrow, async arrow and function "
         "expression are helpers once two files use them (clampTo has one consumer)")
    for symbol, want in (("BaseThing", "src/page.ts"), ("formatMoney", "src/page.ts"),
                         ("BaseSolo", "lib/index.ts"), ("BaseLonely", "src/page.spec.ts"),
                         ("BaseNobody", None), ("roundTo", "src/another.ts")):
        t.eq(find(rows(out, "utilities"), "symbol", symbol)["exemplar"], want, f"exemplar of {symbol}")
    check_row(t, find(rows(out, "utilities"), "symbol", "formatMoney"), {
        "path": "lib/money.ts", "generics": "",
        "signature": "export function formatMoney(n: number): string"}, "formatMoney")


def case_where_to_look(ctx, t):
    ctx.tree("acme", {
        "README.md": "# Acme Billing\n",
        "CLAUDE.md": "# Rules\n",
        "AGENTS.md": "# Agents\n",
        "docs/architecture.md": "# System architecture\n\nText.\n",
        "docs/guides/onboarding-steps.md": "No heading here.\n",
        "docs/notes.txt": "x\n",
        "docs/.drafts/wip.md": "# Draft\n",
        "docs/node_modules/dep.md": "# Dependency\n",
        "openapi.yaml": "openapi: 3.0.0\n",
        "api/swagger.json": "{}\n",
        "src/app.ts": "export const app = 1\n",
    })
    out = ctx.scan("acme")
    t.eq(rows(out, "where_to_look"), [
        {"topic": "Agent instructions", "path": "AGENTS.md"},
        {"topic": "Claude instructions", "path": "CLAUDE.md"},
        {"topic": "Project README", "path": "README.md"},
        {"topic": "OpenAPI spec", "path": "api/swagger.json"},
        {"topic": "System architecture", "path": "docs/architecture.md"},
        {"topic": "onboarding steps", "path": "docs/guides/onboarding-steps.md"},
        {"topic": "OpenAPI spec", "path": "openapi.yaml"}],
        "README, CLAUDE.md, AGENTS.md, docs/**/*.md (titled by their first heading, else by file name) and "
        "API specs, sorted by path; hidden and vendored folders are skipped")


def case_docs_symlink(ctx, t):
    project = ctx.tree("linked", {"handbook/guide.md": "# Team guide\n", "src/app.ts": "export const app = 1\n"})
    link = os.path.join(project, "docs")
    try:
        os.symlink(os.path.relpath(os.path.join(project, "handbook"), os.path.dirname(link)), link)
    except (OSError, NotImplementedError):
        raise Skip("this filesystem cannot create symlinks")
    out = ctx.scan("linked")
    t.eq(rows(out, "where_to_look"), [{"topic": "Team guide", "path": "docs/guide.md"}],
         "a docs/ that is a relative symlink is listed under the link's own name")


def case_update_affected_map_rows(ctx, t):
    files = service_tree()
    files["src/pages/home.tsx"] = "import { BaseApiService } from '@/shared/base-api.service'\n"
    ctx.tree("acme", files)
    base = "src/shared/base-api.service.ts"
    key = ["affected_context_files", "affected_folders", "affected_map_rows", "affected_surfaces", "paths"]

    out = ctx.scan("acme", "--update", base)
    t.eq(sorted(out["update"]), key, "update keys")
    t.eq(out["update"]["affected_map_rows"],
         {"utilities": ["BaseApiService@" + base], "patterns": ["types:utility"]},
         "touching the defining file affects its utility row and the patterns that list it as evidence "
         "(it is no member of the service shape it gives its name to)")

    out = ctx.scan("acme", "--update", "src/features/invoices")
    t.eq(sorted(out["update"]), key, "update keys for a folder")
    t.eq(out["update"]["affected_map_rows"],
         {"utilities": ["BaseApiService@" + base], "patterns": ["family:BaseApiService", "shape:service"]},
         "touching a folder reaches the rows whose exemplar or evidence lives inside it")

    out = ctx.scan("acme", "--update", "README.md")
    t.eq(out["update"]["affected_map_rows"], {"utilities": [], "patterns": []}, "an unrelated path affects no row")
    t.eq(out["update"]["paths"], ["README.md"], "update.paths echoes the changed paths")


def case_python_only_degrades(ctx, t):
    ctx.tree("py-app", {
        "pyproject.toml": "[project]\nname = 'acme'\n",
        "core/base.py": ("class BaseRepo(ABC, Generic[T]):\n    pass\n\n\ndef format_money(value):\n"
                         "    return value\n\n\ndef lonely_helper():\n    return 1\n"),
        "core/registry.py": "class Registry(Generic[T]):\n    pass\n",
        "core/contracts.py": "class Notifier(Protocol):\n    pass\n",
        "billing/providers.py": "class ProviderRepo(BaseRepo[Provider]):\n    pass\n\nformat_money(1)\n",
        "billing/invoices.py": "class InvoiceRepo(BaseRepo[Invoice]):\n    pass\n\nformat_money(2)\n",
        "billing/users.py": "class UserRepo(Auditable, BaseRepo[User], metaclass=Meta):\n    pass\n",
        "billing/rates.py": "lonely_helper()\n",
        "billing/mixins.py": "class Timestamped:\n    pass\n",
        "billing/invoice_row.py": "class InvoiceRow(Timestamped):\n    pass\n",
        "billing/receipt_row.py": "class ReceiptRow(Timestamped):\n    pass\n",
    })
    out = ctx.scan("py-app")
    t.eq([(u["symbol"], u["kind"]) for u in rows(out, "utilities")],
         [("BaseRepo", "abstract-class"), ("Notifier", "abstract-class"), ("Timestamped", "base-class"),
          ("Registry", "generic-class"), ("format_money", "helper")],
         "Python: ABC/Protocol/Generic bases, a plain class without a base list that heads a family, and a "
         "helper used twice; a helper used once is left out")
    check_row(t, find(rows(out, "utilities"), "symbol", "BaseRepo"), {
        "path": "core/base.py", "signature": "class BaseRepo(ABC, Generic[T])", "generics": "T",
        "consumers_count": 3, "exemplar": "billing/invoices.py"}, "BaseRepo")
    check_row(t, find(rows(out, "utilities"), "symbol", "Registry"),
              {"signature": "class Registry(Generic[T])", "generics": "T"}, "Registry")
    check_row(t, find(rows(out, "utilities"), "symbol", "format_money"),
              {"path": "core/base.py", "consumers_count": 2, "signature": "def format_money(value)"},
              "format_money")
    t.eq([(p["name"], p["count"]) for p in rows(out, "patterns")],
         [("family:BaseRepo", 3), ("family:Timestamped", 2)],
         "the keyword argument and the non-local Auditable base are not bases; no TypeScript-only rows appear")

    ctx.tree("bare-py", {"main.py": "print('hello')\n"})
    t.eq(ctx.scan("bare-py")["map"], {"utilities": [], "patterns": [], "where_to_look": [], "count": 0},
         "a project with nothing to map still carries the empty block")


def case_other_languages(ctx, t):
    ctx.tree("poly", {
        "app/Services/AbstractGateway.php": "<?php\nabstract class AbstractGateway\n{\n}\n",
        "app/Services/StripeGateway.php": ("<?php\nclass StripeGateway extends \\App\\Services\\AbstractGateway "
                                           "implements Gateway\n{\n}\n"),
        "app/Services/PaypalGateway.php": "<?php\nclass PaypalGateway extends AbstractGateway\n{\n}\n",
        "domain/BaseEntity.java": "public abstract class BaseEntity<T> {\n}\n",
        "domain/UserEntity.java": "public class UserEntity extends BaseEntity<User> {\n}\n",
        "domain/OrderEntity.java": "public class OrderEntity extends BaseEntity<Order> implements Serializable {\n}\n",
        "utils/collections.go": ("package utils\n\nfunc MapSlice[T any, U any](xs []T, f func(T) U) []U {\n"
                                 "\treturn nil\n}\n"),
    })
    out = ctx.scan("poly")
    t.eq([(u["symbol"], u["kind"]) for u in rows(out, "utilities")],
         [("AbstractGateway", "abstract-class"), ("BaseEntity", "abstract-class"), ("MapSlice", "generic-fn")],
         "PHP and Java abstract classes, and a Go generic function")
    check_row(t, find(rows(out, "utilities"), "symbol", "AbstractGateway"), {
        "path": "app/Services/AbstractGateway.php", "signature": "abstract class AbstractGateway",
        "generics": "", "consumers_count": 2, "exemplar": "app/Services/PaypalGateway.php"}, "AbstractGateway")
    check_row(t, find(rows(out, "utilities"), "symbol", "BaseEntity"), {
        "path": "domain/BaseEntity.java", "signature": "public abstract class BaseEntity<T>", "generics": "T",
        "consumers_count": 2, "exemplar": "domain/OrderEntity.java"}, "BaseEntity")
    check_row(t, find(rows(out, "utilities"), "symbol", "MapSlice"), {
        "path": "utils/collections.go", "generics": "T any, U any",
        "signature": "func MapSlice[T any, U any](xs []T, f func(T) U) []U"}, "MapSlice")
    t.eq([(p["name"], p["count"], p["base"]) for p in rows(out, "patterns")],
         [("family:AbstractGateway", 2, "AbstractGateway"), ("family:BaseEntity", 2, "BaseEntity")],
         "a qualified PHP base (\\App\\Services\\AbstractGateway) resolves to the local class")


def case_map_caps(ctx, t):
    files = {"package.json": '{"name": "acme"}\n', "README.md": "# Acme\n"}
    for n in range(45):
        files[f"shared/widgets/base-widget{n:02d}.ts"] = abstract_class("BaseWidget%02d" % n)
    files["shared/widgets/base-long.ts"] = (
        "export abstract class BaseVeryLong<TFirst extends Record<string, unknown>, "
        "TSecond extends Record<string, unknown>> {}\n")
    for n in range(22):
        add_family(files, n, f"shared/fam/base-fam{n:02d}.ts")
    files["shared/fam/base-big.ts"] = "export class BaseBig {}\n"
    for n in range(7):
        files[f"src/big/big{n}.ts"] = "export class Big%d extends BaseBig {}\n" % n
    for n in range(25):
        files[f"docs/page-{n:02d}.md"] = "# Page %d\n" % n
    for n in range(12):
        files[f"svc{n:02d}/openapi.yaml"] = "openapi: 3.0.0\n"
    ctx.tree("acme", files)
    out = ctx.scan("acme")

    symbols = [u["symbol"] for u in rows(out, "utilities")]
    t.eq(len(symbols), 40, "utilities are capped at 40")
    t.eq(symbols, sorted(symbols), "equally ranked utilities come out in name order")
    t.eq(symbols[0], "BaseVeryLong", "BaseVeryLong sorts first among the abstract classes")
    long_row = rows(out, "utilities")[0]
    t.eq(len(long_row["signature"]), 80, "a long declaration is cut to 80 characters")
    t.ok(long_row["signature"].endswith("…"), "the cut is marked with an ellipsis")
    t.eq(long_row["generics"],
         "TFirst extends Record<string, unknown>, TSecond extends Record<string, unknown>",
         "generics keep the nested angle brackets whole")

    names = [p["name"] for p in rows(out, "patterns")]
    t.eq(len(names), 20, "patterns are capped at 20")
    t.eq(names[0], "family:BaseBig", "the family with the most members ranks first")
    check_row(t, find(rows(out, "patterns"), "name", "family:BaseBig"),
              {"count": 7, "evidence_paths": ["src/big/big%d.ts" % n for n in range(5)]},
              "family:BaseBig (7 members, 5 evidence paths)")

    where = [w["path"] for w in rows(out, "where_to_look")]
    t.eq(len(where), 30, "where_to_look is capped at 30")
    t.eq(where, sorted(where), "where_to_look is sorted by path")
    t.eq([p for p in where if p.startswith("docs/")], ["docs/page-%02d.md" % n for n in range(20)],
         "the first 20 pages of docs/ by path are listed")
    t.eq(out["map"]["count"], 40 + 20 + 30, "map.count adds up the capped lists")


TURBO = {
    "package.json": '{"name": "acme", "workspaces": ["apps/*", "packages/*"]}\n',
    "apps/web/package.json": '{"name": "web"}\n',
    "apps/web/src/page.tsx": "import { useInvoice, formatMoney, BaseRepo } from '@acme/utils'\n",
    "apps/admin/package.json": '{"name": "admin"}\n',
    "apps/admin/src/page.tsx": "import { useInvoice, formatMoney, BaseRepo } from '@acme/utils'\n",
    "packages/utils/package.json": '{"name": "@acme/utils"}\n',
    "packages/utils/src/index.ts": ("export function formatMoney(n: number) { return n }\n"
                                    "export const useInvoice = () => 1\n"
                                    "export abstract class BaseRepo<T> {}\n"),
}


def case_workspace_packages(ctx, t):
    ctx.tree("turbo", TURBO)
    out = ctx.scan("turbo")
    t.eq(out["usage_map"]["shared_roots"], ["packages/utils"], "the usage map reads packages/utils")
    index = "packages/utils/src/index.ts"
    both = ["apps/admin/src/page.tsx", "apps/web/src/page.tsx"]
    t.eq({s["symbol"]: (s["defined_in"], s["consumers_count"], sorted(s["consumers"]))
          for s in out["usage_map"]["surfaces"]},
         {"BaseRepo": (index, 2, both), "formatMoney": (index, 2, both), "useInvoice": (index, 2, both)},
         "the usage map's surfaces")
    t.eq([(u["symbol"], u["kind"], u["path"], u["consumers_count"], u["exemplar"]) for u in rows(out, "utilities")],
         [("BaseRepo", "abstract-class", index, 2, "apps/admin/src/page.tsx"),
          ("useInvoice", "hook", index, 2, "apps/admin/src/page.tsx"),
          ("formatMoney", "helper", index, 2, "apps/admin/src/page.tsx")],
         "a workspace package with a manifest of its own inside a shared-code folder is a root for the map as "
         "it is for the usage map: its generic base, hook and helper are utilities")


def case_nested_app_in_root(ctx, t):
    app = {
        "services/billing/package.json": '{"name": "billing"}\n',
        "services/billing/src/util.ts": ("export function chargeCard(x: number) { return x }\n"
                                         "export abstract class BaseBillingJob {}\n"),
        "services/billing/src/a.ts": "chargeCard(1)\n",
        "services/billing/src/b.ts": "chargeCard(2)\n",
    }
    ctx.tree("with-readme", {"package.json": '{"name": "acme"}\n', "services/README.md": "# Services\n",
                             "services/mailer.ts": abstract_class("BaseMailer"), **app})
    got = [(u["symbol"], u["path"]) for u in rows(ctx.scan("with-readme"), "utilities")]
    t.eq(got, [("BaseMailer", "services/mailer.ts")],
         "services/ holds files of its own and is a root, but the application inside it (services/billing, with "
         "a manifest of its own) is not shared code")
    ctx.tree("without-readme", {"package.json": '{"name": "acme"}\n', **app})
    t.eq(rows(ctx.scan("without-readme"), "utilities"), [],
         "without a file of its own services/ is no root, and the application is still no shared code")

    ctx.tree("shared-inside", {
        "package.json": '{"name": "acme"}\n', "services/README.md": "# Services\n", **app,
        "services/billing/lib/format.ts": "export function formatCharge<T>(x: T): T { return x }\n"})
    t.eq([(u["symbol"], u["path"]) for u in rows(ctx.scan("shared-inside"), "utilities")],
         [("formatCharge", "services/billing/lib/format.ts")],
         "a lib/ inside that application stays shared: the usage map reads it, so the map does too")


def case_signature_start(ctx, t):
    ctx.tree("acme", {
        "package.json": '{"name": "acme"}\n',
        "shared/dense.ts": ("export function firstHelper<T>(x: T) { return x } "
                            "export function secondHelper<T>(x: T) { return x }\n"),
        "shared/commented.ts": ("/* " + "a long licence comment " * 15 + "*/ "
                                "export function hiddenDecl<T>(x: T) { return x }\n"),
        "shared/classes.ts": ("const one = 1; export abstract class BaseOne<T> {} "
                              "export default abstract class BaseTwo<T> {}\n"),
    })
    out = ctx.scan("acme")
    got = {u["symbol"]: u["signature"] for u in rows(out, "utilities")}
    t.ok(got.get("firstHelper", "").startswith("export function firstHelper<T>(x: T) { return x }"),
         "firstHelper's signature starts at its own declaration: %r" % got.get("firstHelper"))
    t.eq(got.get("secondHelper"), "export function secondHelper<T>(x: T) { return x }",
         "secondHelper shares its line with another declaration")
    t.eq(got.get("hiddenDecl"), "export function hiddenDecl<T>(x: T) { return x }",
         "a declaration behind a comment longer than the 320 characters a signature reads")
    t.ok(got.get("BaseOne", "").startswith("export abstract class BaseOne<T> {}"),
         "BaseOne's signature starts at its own declaration: %r" % got.get("BaseOne"))
    t.eq(got.get("BaseTwo"), "export default abstract class BaseTwo<T> {}",
         "all the modifiers in front of the name belong to the signature")


def case_exemplar_past_sample(ctx, t):
    files = {"package.json": '{"name": "acme"}\n', "lib/base-thing.ts": abstract_class("BaseThing"),
             "src/page.ts": "import { BaseThing } from 'lib'\n"}
    for n in range(15):
        files[f"app/__tests__/t{n:02d}.spec.ts"] = "BaseThing\n"
    ctx.tree("acme", files)
    out = ctx.scan("acme")
    check_row(t, find(rows(out, "utilities"), "symbol", "BaseThing"),
              {"consumers_count": 16, "exemplar": "src/page.ts"},
              "BaseThing (the exemplar is the only consumer that is not a test, although 15 tests come first)")


def case_update_beyond_evidence(ctx, t):
    files = {"package.json": '{"name": "acme"}\n', "src/base.ts": "export class BaseBig {}\n"}
    for n in range(7):
        files[f"src/m/big{n}.ts"] = "export class Big%d extends BaseBig {}\n" % n
    ctx.tree("acme", files)
    out = ctx.scan("acme", "--update", "src/m/big6.ts")
    check_row(t, find(rows(out, "patterns"), "name", "family:BaseBig"),
              {"count": 7, "evidence_paths": ["src/m/big%d.ts" % n for n in range(5)]},
              "family:BaseBig lists five of its seven members")
    t.eq(out["update"]["affected_map_rows"], {"utilities": [], "patterns": ["family:BaseBig"]},
         "touching the seventh member, which the row does not list, still affects the family")
    t.lacks(json.dumps(out["map"]), "members", "the member list stays internal: the JSON never shows it")
    t.eq(ctx.scan("acme", "--update", "README.md")["update"]["affected_map_rows"],
         {"utilities": [], "patterns": []}, "an unrelated path still affects nothing")


def case_shape_excludes_base_file(ctx, t):
    base = {"package.json": '{"name": "acme"}\n',
            "src/x/base-api.service.ts": "export class BaseApiService {}\n",
            "src/x/a.service.ts": "export class AService extends BaseApiService {}\n",
            "src/x/b.service.ts": "export class BService {}\n"}
    ctx.tree("two", base)
    t.eq([p["name"] for p in rows(ctx.scan("two"), "patterns") if p["kind"] == "shape"], [],
         "the file that defines the base is no member of its shape: two services are not a shape")
    ctx.tree("three", {**base, "src/x/c.service.ts": "export class CService extends BaseApiService {}\n"})
    check_row(t, find(rows(ctx.scan("three"), "patterns"), "name", "shape:service"), {
        "status": "applied", "count": 3, "base": "BaseApiService", "exemplar": "src/x/a.service.ts",
        "evidence_paths": ["src/x/a.service.ts", "src/x/b.service.ts", "src/x/c.service.ts"]},
        "shape:service (2 of the 3 real members extend the base)")
    ctx.tree("four", {
        "package.json": '{"name": "acme"}\n',
        "src/x/base-api.service.ts": ("export class BaseApiService {}\n"
                                      "export class ApiService extends BaseApiService {}\n"),
        "src/x/a.service.ts": "export class AService {}\n", "src/x/b.service.ts": "export class BService {}\n",
        "src/x/c.service.ts": "export class CService {}\n"})
    check_row(t, find(rows(ctx.scan("four"), "patterns"), "name", "shape:service"),
              {"count": 3, "base": None, "evidence_paths": ["src/x/a.service.ts", "src/x/b.service.ts",
                                                           "src/x/c.service.ts"]},
              "shape:service (the only class extending the base lives in the base's own file: no shared base)")


def case_pattern_slots(ctx, t):
    files = {"package.json": '{"name": "acme"}\n', "src/types.ts": "type Row = Partial<Invoice>\n"}
    for n in range(41):
        add_family(files, n, f"src/fam/base{n:02d}.ts")
    roles = ("api", "columns", "controller", "detail", "dto", "form", "list", "repository", "schema", "service",
             "store")
    for role in roles:
        for k in range(3):
            files[f"src/{role}/item{k}.{role}.ts"] = "export class Item%d {}\n" % k
    ctx.tree("acme", files)
    first, second = rows(ctx.scan("acme"), "patterns"), rows(ctx.scan("acme"), "patterns")
    t.eq([p["name"] for p in first],
         ["family:BaseFam%02d" % n for n in range(10)] + ["shape:" + r for r in roles[:9]] + ["types:utility"],
         "41 families, 11 shapes and the types row share 20 slots: the types row, then families and shapes by "
         "turns, each in name order")
    t.eq(first, second, "two scans of the same tree give the same rows")


def case_detector_order(ctx, t):
    files = {"package.json": '{"name": "acme"}\n', "lib/money.ts": "export const formatMoney = (n: number) => n\n"}
    for n in range(20):
        files[f"src/c{n:02d}.ts"] = "formatMoney(%d)\n" % n
    ctx.tree("acme", files)
    mod = load_scanner(ctx.scanner)

    class Reversed(mod.ProjectScanner):
        """Lists the source files last-first, as a filesystem may, and can run the map detector first."""
        map_first = False

        def _walk(self):
            super()._walk()
            self._source_files.sort(key=lambda item: item[1], reverse=True)

        def _detect_usage_map(self):
            if self.map_first:
                mod.ProjectScanner._detect_map(self)
            super()._detect_usage_map()

        def _detect_map(self):
            if not self.map_first:
                super()._detect_map()

    def scan(map_first):
        scanner = Reversed(Path(ctx.path("acme")))
        scanner.map_first = map_first
        result = scanner.scan()
        return result["usage_map"], result["map"]

    usage, mapped = scan(False)
    t.eq(next(s["consumers"] for s in usage["surfaces"] if s["symbol"] == "formatMoney"),
         ["src/c%02d.ts" % n for n in range(19, 4, -1)],
         "the usage map samples consumers in scan order")
    usage_swapped, mapped_swapped = scan(True)
    t.eq(json.dumps(usage_swapped), json.dumps(usage),
         "the usage map does not depend on the map detector running first")
    t.eq(json.dumps(mapped_swapped), json.dumps(mapped), "the map does not depend on the order of the scan either")


TEST_FOLDERS = ("test", "tests", "__tests__", "spec", "specs", "e2e", "__mocks__")


def case_test_file_rule(ctx, t):
    files = {
        "package.json": '{"name": "acme"}\n',
        # named like a test: the testing block counts them and the map leaves them out
        "src/shared/billing.spec.ts": generic_fn("makeSpec"),
        "src/shared/api_test.go": "package shared\n\nfunc MapAll[T any](xs []T) []T {\n\treturn xs\n}\n",
        "src/shared/Test.php": "<?php\nabstract class AbstractGuard\n{\n}\n",
        "src/shared/test_utils.py": "class BaseBuilder:\n    pass\n",
        "e2e/checkout.spec.ts": "describe('checkout', () => {})\n",
        # test_ is a Python prefix only, and a folder that merely contains the word is no test folder
        "src/shared/test_fixtures.ts": generic_fn("makeFixture"),
        "src/shared/contest/ranking.ts": generic_fn("rankAll"),
        "src/shared/latest/feed.ts": generic_fn("feedAll"),
        # the consumer to copy from sorts after the two in test folders, so only the folder rule moves
        # the exemplar to it
        "src/shared/format.ts": generic_fn("formatAll"),
        "__mocks__/format.ts": "formatAll([])\n",
        "e2e/checkout.ts": "formatAll([])\n",
        "src/latest/page.ts": "formatAll([])\n",
        # test support code keeps ordinary names inside a test folder
        "e2e/pages/base-page.ts": "export abstract class BasePage {}\n",
        "e2e/pages/login-page.ts": "export class LoginPage extends BasePage {}\n",
        "e2e/pages/home-page.ts": "export class HomePage extends BasePage {}\n",
    }
    for n, folder in enumerate(TEST_FOLDERS):
        files[f"src/shared/{folder}/helpers.ts"] = generic_fn(f"makeProbe{n}")
    for name in ("Users", "Orders", "Items"):
        for folder in ("__tests__/fixtures", "src/latest"):
            files[f"{folder}/{name.lower()}.service.ts"] = f"export class {name}Service {{}}\n"
    ctx.tree("acme", files)
    out = ctx.scan("acme")

    t.eq(out["testing"]["test_file_count"], 5,
         "the testing block counts by name alone: billing.spec.ts, api_test.go, Test.php, test_utils.py and "
         "e2e/checkout.spec.ts, and no file that merely sits in a test folder")
    t.eq(out["testing"]["test_dirs"], ["e2e", "src/shared"],
         "test_dirs lists the folders that hold a test-named file, not the folders named after tests")

    utilities = rows(out, "utilities")
    t.eq(sorted(u["symbol"] for u in utilities), ["feedAll", "formatAll", "makeFixture", "rankAll"],
         "the map leaves out the files named like a test and everything in the seven test folders "
         "(makeProbe0..6, BasePage), and keeps contest/ and latest/")
    check_row(t, find(utilities, "symbol", "formatAll"), {"consumers_count": 3, "exemplar": "src/latest/page.ts"},
              "formatAll (a consumer in a test folder counts, but never leads)")
    t.eq([(p["name"], p["count"], p["evidence_paths"]) for p in rows(out, "patterns")],
         [("shape:service", 3, [f"src/latest/{name}.service.ts" for name in ("items", "orders", "users")])],
         "no family or shape forms from a test folder (e2e/pages, __tests__/fixtures); latest/ still does")
    check_row(t, find(out["usage_map"]["surfaces"], "symbol", "formatAll"), {
        "consumers_count": 3, "consumers": ["__mocks__/format.ts", "e2e/checkout.ts", "src/latest/page.ts"]},
        "usage_map surface formatAll (the folder rule is the map's alone)")


# ------------------------------------------------------------------ writer cases
# The container is the case root: the brain lives at ai/ai-brain and each project at projects/<name>, so
# block headers name the project as `projects/<name>`.
BRAIN = "ai/ai-brain"
MAP_FILES = ("utilities.md", "patterns.md", "where-to-look.md")
MARKER_RX = (r"^<!-- map-refresh: scan (\d{4}-\d{2}-\d{2}) · project (\S+) · format 1 — rows regenerate; "
             r"✍ columns are human and preserved -->$")
TODAY = datetime.date.today().isoformat()
MONEY = "src/shared/format-money.ts"
ROUND = "src/shared/round-cents.ts"


def writer_tree(ctx, project="acme", extra=None):
    """A service family, two shared generic functions and a README under projects/<project>; the brain dir."""
    files = service_tree()
    files.update({MONEY: generic_fn("formatMoney"), ROUND: generic_fn("roundCents")})
    files.update(extra or {})
    ctx.tree(f"projects/{project}", files)
    os.makedirs(ctx.path(BRAIN), exist_ok=True)
    return ctx.path(f"projects/{project}"), ctx.path(BRAIN)


def refresh(ctx, *flags):
    """Run the map writer from the case root; a missing writer skips the case."""
    if not os.path.isfile(ctx.script):
        raise Skip("map writer not found: " + os.path.basename(ctx.script))
    p = subprocess.run([sys.executable, ctx.script] + list(flags), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=ctx.env, cwd=ctx.root, timeout=120)
    return R(p)


def last(r):
    lines = r.out.strip().splitlines()
    return lines[-1] if lines else ""


def map_text(ctx, name, brain=BRAIN):
    with open(ctx.path(f"{brain}/map/{name}"), encoding="utf-8") as fh:
        return fh.read()


def snapshot(top):
    """{relative path: (kind, bytes or link target, mtime)} for every entry under `top`."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(top):
        for n in dirnames + filenames:
            p = os.path.join(dirpath, n)
            rel = os.path.relpath(p, top)
            if os.path.islink(p):
                out[rel] = ("link", os.readlink(p), None)
            elif os.path.isfile(p):
                with open(p, "rb") as fh:
                    out[rel] = ("file", fh.read(), os.stat(p).st_mtime_ns)
            else:
                out[rel] = ("dir", None, None)
    return out


def row_line(text, first):
    """The table line whose first cell is `first` (backticks included), else None."""
    return next((x for x in text.splitlines() if x.startswith(f"| {first} |")), None)


def row_cells(text, first):
    found = row_line(text, first)
    return [c.strip() for c in re.split(r"(?<!\\)\|", found)[1:-1]] if found else None


def fill(path, first, texts):
    """Write `texts` into the last len(texts) cells of the row whose first cell is `first`, as a human would."""
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    i = next(k for k, x in enumerate(lines) if x.startswith(f"| {first} |"))
    parts = lines[i][2:-2].split(" | ")
    parts[-len(texts):] = texts
    lines[i] = "| " + " | ".join(parts) + " |"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def section(text, head):
    """The text of the `## head` section, up to the next `## ` heading."""
    start = text.index(head)
    nxt = text.find("\n## ", start + len(head))
    return text[start:] if nxt < 0 else text[start:nxt]


def module_link(ctx, project, target):
    link = os.path.join(project, "ai-brain")
    try:
        os.symlink(os.path.relpath(target, os.path.dirname(link)), link)
    except (OSError, NotImplementedError):
        raise Skip("this filesystem cannot create symlinks")


def case_render_creates_three_files(ctx, t):
    writer_tree(ctx)
    r = refresh(ctx, "--project", "projects/acme", "--brain", BRAIN)
    t.eq(r.rc, 0, "first render: exit code")
    t.eq(last(r), "MAP: written", "first render: last line")
    t.eq(sorted(os.listdir(ctx.path(BRAIN + "/map"))), sorted(MAP_FILES), "map/ holds exactly the three files")
    heads = {"utilities.md": "| Symbol | Kind | Path | Signature | Consumers | Exemplar | ✍ What it does | ✍ When to use |",
             "patterns.md": "| Pattern | Kind | Status | Evidence | Exemplar | ✍ When to apply | ✍ Anti-pattern |",
             "where-to-look.md": "| Path | Kind | Label | ✍ Answers |"}
    for name in MAP_FILES:
        text = map_text(ctx, name)
        t.eq(len(re.findall(MARKER_RX, text, re.M)), 1, f"{name}: one project block")
        t.has(text, heads[name], f"{name}: column headers")
        t.ok(text.index("<!-- end map-refresh -->") < text.index("## Curated (human)") < text.index("## Retired (review)"),
             f"{name}: block, then Curated, then Retired")
        t.lacks(text, "{{", f"{name}: no placeholder left")
    u = map_text(ctx, "utilities.md")
    t.eq(row_cells(u, "`BaseApiService`")[:3], ["`BaseApiService`", "abstract-class", "`src/shared/base-api.service.ts`"],
         "the generic base heads the utilities")
    t.eq(row_cells(u, "`formatMoney`")[-2:], ["—", "—"], "a new row starts with empty ✍ cells")
    p = map_text(ctx, "patterns.md")
    t.eq(row_cells(p, "`family:BaseApiService`")[1:4],
         ["family", "applied", "3 · `src/features/invoices/invoices.service.ts`, "
          "`src/features/payments/payments.service.ts`, `src/features/providers/providers.service.ts`"],
         "family row: kind, status, evidence led by the count")


def case_check_init_shells_fresh(ctx, t):
    os.makedirs(ctx.path(BRAIN))
    r = refresh(ctx, "--brain", BRAIN, "--init")
    t.eq((r.rc, last(r)), (0, "MAP: written"), "--init on an empty brain")
    c = refresh(ctx, "--brain", BRAIN, "--check")
    t.eq((c.rc, last(c)), (0, "MAP: fresh"), "--check over the bare shells")
    t.has(c.out, "  note: no project block", "--check names the empty shells")


def case_render_preserves_human_columns(ctx, t):
    writer_tree(ctx)
    refresh(ctx, "--project", "projects/acme", "--brain", BRAIN)
    fill(ctx.path(BRAIN + "/map/utilities.md"), "`BaseApiService`",
         ["Shared CRUD calls for one entity \\| path-based", "A new entity needs list/get/save"])
    fill(ctx.path(BRAIN + "/map/patterns.md"), "`family:BaseApiService`",
         ["Every entity service", "A base forced on a service with its own protocol"])
    fill(ctx.path(BRAIN + "/map/where-to-look.md"), "`README.md`", ["Setup and scripts"])
    ctx.write("projects/acme/" + SERVICES % ("clients", "clients"),
              "export class ClientsService extends BaseApiService<Client> {}\n")
    ctx.write("projects/acme/src/shared/to-cents.ts", generic_fn("toCents"))
    r = refresh(ctx, "--project", "projects/acme", "--brain", BRAIN)
    t.eq((r.rc, last(r)), (0, "MAP: written"), "refresh after the code changed")
    u = map_text(ctx, "utilities.md")
    t.eq(row_cells(u, "`BaseApiService`")[-2:],
         ["Shared CRUD calls for one entity \\| path-based", "A new entity needs list/get/save"],
         "utilities ✍ cells survive the refresh (the pipe stays escaped)")
    t.ok(row_line(u, "`toCents`") is not None, "the new utility row appears")
    p = map_text(ctx, "patterns.md")
    cells_ = row_cells(p, "`family:BaseApiService`")
    t.eq(cells_[-2:], ["Every entity service", "A base forced on a service with its own protocol"],
         "patterns ✍ cells survive")
    t.ok(cells_[3].startswith("4 · "), "the family row regenerated with the fourth member")
    t.eq(row_cells(map_text(ctx, "where-to-look.md"), "`README.md`")[-1], "Setup and scripts", "where ✍ cell survives")
    c = refresh(ctx, "--brain", BRAIN, "--check")
    t.eq((c.rc, last(c)), (0, "MAP: fresh"), "the refreshed map checks fresh")


def case_retired_rows_keep_human_text(ctx, t):
    writer_tree(ctx)
    refresh(ctx, "--project", "projects/acme", "--brain", BRAIN)
    path = ctx.path(BRAIN + "/map/utilities.md")
    fill(path, "`formatMoney`", ["Formats cents as money", "Any amount shown to a user"])
    os.remove(ctx.path("projects/acme/" + MONEY))
    os.remove(ctx.path("projects/acme/" + ROUND))
    r = refresh(ctx, "--project", "projects/acme", "--brain", BRAIN)
    t.eq((r.rc, last(r)), (0, "MAP: written"), "refresh after two utilities vanished")
    t.has(r.out, "1 retired · 1 dropped", "the summary counts one retired and one dropped row")
    u = map_text(ctx, "utilities.md")
    block = u[:u.index("<!-- end map-refresh -->")]
    t.lacks(block, "formatMoney", "the vanished row leaves the block")
    retired = section(u, "## Retired (review)")
    found = row_cells(retired, "`formatMoney`")
    t.ok(found is not None, "the vanished row with ✍ text moves to Retired")
    if found:
        t.eq(found[-3:], ["Formats cents as money", "Any amount shown to a user", f"{TODAY} · projects/acme"],
             "Retired keeps the ✍ text and dates the row")
    t.lacks(u, "roundCents", "the vanished row without ✍ text is dropped everywhere")
    again = refresh(ctx, "--project", "projects/acme", "--brain", BRAIN)
    t.eq(last(again), "MAP: unchanged", "a retired row is not retired twice")
    ctx.write("projects/acme/" + MONEY, generic_fn("formatMoney"))
    back = refresh(ctx, "--project", "projects/acme", "--brain", BRAIN)
    t.eq(row_cells(map_text(ctx, "utilities.md"), "`formatMoney`")[-2:],
         ["Formats cents as money", "Any amount shown to a user"], "a row that comes back takes its text from Retired")
    t.lacks(section(map_text(ctx, "utilities.md"), "## Retired (review)"), "formatMoney",
            "and leaves Retired")
    t.eq(back.rc, 0, "return refresh: exit code")


def case_moved_symbol_carries_human_text(ctx, t):
    writer_tree(ctx)
    refresh(ctx, "--project", "projects/acme", "--brain", BRAIN)
    fill(ctx.path(BRAIN + "/map/utilities.md"), "`formatMoney`", ["Formats cents", "Money display"])
    os.remove(ctx.path("projects/acme/" + MONEY))
    ctx.write("projects/acme/src/shared/money/format-money.ts", generic_fn("formatMoney"))
    r = refresh(ctx, "--project", "projects/acme", "--brain", BRAIN)
    t.eq((r.rc, last(r)), (0, "MAP: written"), "refresh after the move")
    u = map_text(ctx, "utilities.md")
    found = row_cells(u, "`formatMoney`")
    t.ok(found is not None, "the moved symbol keeps a row")
    if found:
        t.eq(found[2], "`src/shared/money/format-money.ts`", "the row carries the new path")
        t.eq(found[-2:], ["Formats cents", "Money display"], "the moved symbol keeps its ✍ text")
    t.lacks(section(u, "## Retired (review)"), "formatMoney", "a moved symbol is not retired")


def case_pipe_escaping_in_signature(ctx, t):
    writer_tree(ctx, extra={"src/shared/pick-one.ts":
                            "export function pickOne<T>(x: T | null, y: T | undefined): T | null { return x }\n"})
    refresh(ctx, "--project", "projects/acme", "--brain", BRAIN)
    u = map_text(ctx, "utilities.md")
    found = row_line(u, "`pickOne`")
    t.ok(found is not None and "T \\| null" in found, "the pipes of the signature are escaped")
    t.eq(len(row_cells(u, "`pickOne`") or []), 8, "the escaped row still has eight cells")
    c = refresh(ctx, "--brain", BRAIN, "--check")
    t.eq((c.rc, last(c)), (0, "MAP: fresh"), "an escaped signature reads back equal")


def case_check_exit_codes(ctx, t):
    writer_tree(ctx)
    refresh(ctx, "--project", "projects/acme", "--brain", BRAIN)
    c = refresh(ctx, "--brain", BRAIN, "--check")
    t.eq((c.rc, last(c)), (0, "MAP: fresh"), "--check right after a render")
    ctx.write("projects/acme/src/shared/to-cents.ts", generic_fn("toCents"))
    before = snapshot(ctx.root)
    c = refresh(ctx, "--brain", BRAIN, "--check")
    t.eq((c.rc, last(c)), (1, "MAP: stale(utilities.md)"), "--check after a new utility")
    t.ok(snapshot(ctx.root) == before, "--check writes nothing (whole tree unchanged)")
    os.remove(ctx.path(BRAIN + "/map/patterns.md"))
    c = refresh(ctx, "--brain", BRAIN, "--check")
    t.eq((c.rc, last(c)), (2, "MAP: missing(patterns.md)"), "--check with a map file gone")
    c = refresh(ctx, "--brain", "no-such-brain", "--check")
    t.eq(c.rc, 2, "--check on a missing brain: exit code")
    t.ok(last(c).startswith("MAP: unresolved (") or last(c).startswith("MAP: missing("), "missing brain: last line")
    t.ok(not os.path.exists(ctx.path("no-such-brain")), "--check never creates the brain")


def case_idempotent_second_run(ctx, t):
    writer_tree(ctx)
    refresh(ctx, "--project", "projects/acme", "--brain", BRAIN)
    before = snapshot(ctx.path(BRAIN))
    r = refresh(ctx, "--project", "projects/acme", "--brain", BRAIN)
    t.eq((r.rc, last(r)), (0, "MAP: unchanged"), "second run: exit code and last line")
    t.ok(snapshot(ctx.path(BRAIN)) == before, "second run: bytes and mtimes unchanged, no temp file left")
    path = ctx.path(BRAIN + "/map/utilities.md")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(re.sub(r"scan \d{4}-\d{2}-\d{2}", "scan 2001-01-01", text))
    r = refresh(ctx, "--project", "projects/acme", "--brain", BRAIN)
    t.eq(last(r), "MAP: unchanged", "equal rows under an older scan date leave the file untouched")
    t.has(map_text(ctx, "utilities.md"), "scan 2001-01-01", "the older date stays")


def case_module_brain_via_symlink(ctx, t):
    project, _ = writer_tree(ctx)
    module = ctx.path(BRAIN + "/modules/billing")
    os.makedirs(module)
    module_link(ctx, project, module)
    r = refresh(ctx, "--project", "projects/acme")
    t.eq((r.rc, last(r)), (0, "MAP: written"), "refresh through the module symlink")
    t.eq(sorted(os.listdir(os.path.join(module, "map"))), sorted(MAP_FILES), "the map lands in modules/billing/map")
    t.ok(not os.path.exists(ctx.path(BRAIN + "/map")), "the root brain gets no map")
    t.eq(re.findall(MARKER_RX, map_text(ctx, "utilities.md", BRAIN + "/modules/billing"), re.M)[0][1],
         "projects/acme", "the module block names the project from the container")
    for brain in (BRAIN + "/modules/billing", "projects/acme/ai-brain"):
        c = refresh(ctx, "--brain", brain, "--check")
        t.eq((c.rc, last(c)), (0, "MAP: fresh"), f"--check --brain {brain}")


def case_modules_brain_without_symlink(ctx, t):
    writer_tree(ctx)
    os.makedirs(ctx.path(BRAIN + "/modules/billing"))
    before = snapshot(ctx.root)
    r = refresh(ctx, "--project", "projects/acme")
    t.eq(r.rc, 2, "a brain with modules/ and no symlink: exit code")
    t.has(r.out, "pass --brain ai/ai-brain/modules/<mod>", "the suggestion names the module path")
    t.ok(last(r).startswith("MAP: unresolved ("), "last line")
    t.ok(snapshot(ctx.root) == before, "nothing written anywhere")


def case_no_write_without_brain_or_symlink(ctx, t):
    writer_tree(ctx)
    before = snapshot(ctx.root)
    r = refresh(ctx, "--project", "projects/acme")
    t.eq(r.rc, 2, "brain two levels up, no --brain, no symlink: exit code")
    t.has(r.out, "pass --brain ai/ai-brain", "the upward search only suggests the brain")
    t.ok(last(r).startswith("MAP: unresolved ("), "last line")
    t.ok(snapshot(ctx.root) == before, "the whole container tree is unchanged")


def case_symlinked_map_dir_refused(ctx, t):
    writer_tree(ctx)
    elsewhere = ctx.path("elsewhere")
    os.makedirs(elsewhere)
    try:
        os.symlink(elsewhere, ctx.path(BRAIN + "/map"))
    except (OSError, NotImplementedError):
        raise Skip("this filesystem cannot create symlinks")
    for flags in (("--project", "projects/acme", "--brain", BRAIN), ("--brain", BRAIN, "--init"),
                  ("--brain", BRAIN, "--check")):
        r = refresh(ctx, *flags)
        t.eq(r.rc, 2, f"symlinked map/ {flags[-1]}: exit code")
        t.has(last(r), "symlink", f"symlinked map/ {flags[-1]}: last line names the link")
    t.eq(os.listdir(elsewhere), [], "nothing written through the map/ link")
    os.remove(ctx.path(BRAIN + "/map"))
    os.makedirs(ctx.path(BRAIN + "/map"))
    target = ctx.write("elsewhere/target.md", "outside\n")
    os.symlink(target, ctx.path(BRAIN + "/map/patterns.md"))
    r = refresh(ctx, "--project", "projects/acme", "--brain", BRAIN)
    t.eq(r.rc, 2, "symlinked map file: exit code")
    t.eq(sorted(os.listdir(ctx.path(BRAIN + "/map"))), ["patterns.md"], "no other map file written either")
    with open(target, encoding="utf-8") as fh:
        t.eq(fh.read(), "outside\n", "the link target is untouched")


def case_multi_project_blocks_do_not_clobber(ctx, t):
    writer_tree(ctx, "acme")
    writer_tree(ctx, "billing-api", {"src/shared/invoice-total.ts": generic_fn("invoiceTotal")})
    for name in ("acme", "billing-api"):
        r = refresh(ctx, "--project", "projects/" + name, "--brain", BRAIN)
        t.eq((r.rc, last(r)), (0, "MAP: written"), f"render {name}")
    fill(ctx.path(BRAIN + "/map/utilities.md"), "`invoiceTotal`", ["Sums an invoice", "Totals"])
    u = map_text(ctx, "utilities.md")
    t.eq([m[1] for m in re.findall(MARKER_RX, u, re.M)], ["projects/acme", "projects/billing-api"],
         "one block per project, in the order they were first written")
    other = u[u.index("project projects/billing-api"):]
    ctx.write("projects/acme/src/shared/to-cents.ts", generic_fn("toCents"))
    r = refresh(ctx, "--project", "projects/acme", "--brain", BRAIN)
    t.eq(last(r), "MAP: written", "refresh acme again")
    u = map_text(ctx, "utilities.md")
    t.eq(u[u.index("project projects/billing-api"):], other, "the billing-api block is byte-identical")
    t.has(u[:u.index("project projects/billing-api")], "toCents", "the acme block took the new row")
    c = refresh(ctx, "--brain", BRAIN, "--check")
    t.eq((c.rc, last(c)), (0, "MAP: fresh"), "--check rescans both projects")


def case_no_absolute_paths_in_output(ctx, t):
    writer_tree(ctx, extra={"README.md": "# Acme\n", "docs/guide.md": "# Guide\n"})
    os.makedirs(ctx.path("acme-context/references"))
    ctx.write("acme-context/references/security.md", "# Security\n")
    r = refresh(ctx, "--project", "projects/acme", "--brain", BRAIN, "--context-skill", "acme-context",
                "--update", MONEY, "--human", "Ghost@src/none.ts=a|b")
    j = refresh(ctx, "--brain", BRAIN, "--check", "--json")
    t.eq(r.rc, 0, "render: exit code")
    t.eq(sorted(json.loads(j.out)), ["brain", "files", "new_rows", "projects", "state", "text"], "--json keys")
    real_home = os.path.expanduser("~")
    user = os.path.basename(real_home)
    texts = {"stdout": r.out + r.err + j.out}
    texts.update({name: map_text(ctx, name) for name in MAP_FILES})
    for what, text in texts.items():
        t.lacks(text, ctx.root, f"{what}: no absolute case path")
        t.lacks(text, real_home, f"{what}: no home folder")
        if len(user) >= 4:
            t.lacks(text, user, f"{what}: no user name")
        t.ok(not re.search(r"(^|[\s`(])/[A-Za-z]", text), f"{what}: no absolute path at all")


def case_where_to_look_rows(ctx, t):
    writer_tree(ctx, extra={"CLAUDE.md": "# Rules\n", "docs/guide.md": "# Team guide\n",
                            "openapi.yaml": "openapi: 3.0.0\n"})
    ctx.write(BRAIN + "/plan.md", "# Master plan\n")
    ctx.write(BRAIN + "/decisions/0001-cache.md", "# Cache invoices\n")
    ctx.write(BRAIN + "/execute" + ".md", "Load the skill `code-project-context-acme`, read\n")
    ctx.write("acme-context/usage-map.md", "# Usage map\n")
    ctx.write("acme-context/references/tech-debt.md", "# Tech debt\n")
    r = refresh(ctx, "--project", "projects/acme", "--brain", BRAIN, "--context-skill", "acme-context")
    t.eq(r.rc, 0, "render with a context skill: exit code")
    w = map_text(ctx, "where-to-look.md")
    block = w[:w.index("<!-- end map-refresh -->")]
    got = [tuple(c.strip() for c in re.split(r"(?<!\\)\|", x)[1:4]) for x in block.splitlines()
           if x.startswith("| `")]
    t.eq(got, [("`CLAUDE.md`", "agent-instructions", "Claude instructions"),
               ("`README.md`", "readme", "Project README"),
               ("`acme-context/references/tech-debt.md`", "context", "Tech debt"),
               ("`acme-context/usage-map.md`", "context", "Usage map"),
               ("`ai-brain/decisions/0001-cache.md`", "decision", "Cache invoices"),
               ("`ai-brain/execute" + ".md`", "brain-doc", "execute"),
               ("`ai-brain/plan.md`", "brain-doc", "Master plan"),
               ("`code-project-context-acme`", "skill", "skill loaded by the protocol"),
               ("`docs/guide.md`", "doc", "Team guide"),
               ("`openapi.yaml`", "openapi", "OpenAPI spec")],
         "repo docs, brain docs, decisions, the protocol's skills and the context docs, sorted by path")
    r = refresh(ctx, "--project", "projects/acme", "--brain", BRAIN)
    t.eq(last(r), "MAP: unchanged", "a refresh without --context-skill keeps the context rows")
    c = refresh(ctx, "--brain", BRAIN, "--check")
    t.eq((c.rc, last(c)), (0, "MAP: fresh"), "--check ignores the context rows it cannot rescan")


def case_init_writes_three_shells(ctx, t):
    os.makedirs(ctx.path(BRAIN))
    r = refresh(ctx, "--brain", BRAIN, "--init")
    t.eq((r.rc, last(r)), (0, "MAP: written"), "--init: exit code and last line")
    t.eq(sorted(os.listdir(ctx.path(BRAIN + "/map"))), sorted(MAP_FILES), "--init writes the three shells")
    for name in MAP_FILES:
        text = map_text(ctx, name)
        t.has(text, "map-refresh: scan", f"{name}: names the marker in prose")
        t.ok(not re.search(r"^<!-- map-refresh: scan", text, re.M), f"{name}: holds no project block")
        for head in ("## Curated (human)", "## Retired (review)"):
            t.has(text, head, f"{name}: {head}")
        t.lacks(text, "{{", f"{name}: no placeholder left")
    t.has(map_text(ctx, "patterns.md"), "ProvidersService extends BaseApiService<Provider>", "the least-code card")
    path = ctx.path(BRAIN + "/map/utilities.md")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("human note\n")
    before = snapshot(ctx.path(BRAIN))
    r = refresh(ctx, "--brain", BRAIN, "--init")
    t.eq((r.rc, last(r)), (0, "MAP: unchanged"), "a second --init")
    t.ok(snapshot(ctx.path(BRAIN)) == before, "--init never rewrites an existing file")
    ctx.tree("projects/acme", service_tree())
    r = refresh(ctx, "--project", "projects/acme", "--brain", BRAIN)
    t.eq(r.rc, 0, "a render into the shells: exit code")
    t.has(map_text(ctx, "utilities.md"), "human note", "the render keeps the shell's human text")


def case_human_flag_fills_only_named_key(ctx, t):
    writer_tree(ctx)
    r = refresh(ctx, "--project", "projects/acme", "--brain", BRAIN,
                "--human", f"formatMoney@{MONEY}=Formats cents as money|Any amount shown to a user",
                "--human", "Ghost@src/shared/ghost.ts=Nothing|Never")
    t.eq(r.rc, 0, "--human: exit code")
    t.has(r.out, f"human: filled formatMoney@{MONEY}", "the known key is reported filled")
    t.has(r.out, "human: unknown key (not written) Ghost@src/shared/ghost.ts", "the unknown key is reported")
    u = map_text(ctx, "utilities.md")
    t.eq(row_cells(u, "`formatMoney`")[-2:], ["Formats cents as money", "Any amount shown to a user"],
         "the named row gets both ✍ cells")
    t.eq(row_cells(u, "`roundCents`")[-2:], ["—", "—"], "another row stays empty")
    t.lacks(u, "Ghost", "an unknown key never becomes a row")
    r = refresh(ctx, "--project", "projects/acme", "--brain", BRAIN, "--human", f"roundCents@{ROUND}=Rounds|")
    t.eq(row_cells(map_text(ctx, "utilities.md"), "`roundCents`")[-2:], ["Rounds", "—"],
         "an empty part leaves its cell alone")
    t.eq(row_cells(map_text(ctx, "utilities.md"), "`formatMoney`")[-2:],
         ["Formats cents as money", "Any amount shown to a user"], "earlier text survives a later --human")


def case_marker_contract(ctx, t):
    writer_tree(ctx)
    refresh(ctx, "--project", "projects/acme", "--brain", BRAIN)
    for name in MAP_FILES:
        text = map_text(ctx, name)
        found = [x for x in text.splitlines() if x.startswith("<!-- map-refresh")]
        t.eq(len(found), 1, f"{name}: one marker line")
        t.ok(all(re.fullmatch(MARKER_RX[1:-1], x) for x in found), f"{name}: the marker matches the contract")
        t.eq([m[0] for m in re.findall(MARKER_RX, text, re.M)], [TODAY], f"{name}: the marker carries the scan date")
        t.ok(re.search("map-refresh: scan", text) is not None, f"{name}: the renovate regex finds it")
        t.ok(not any(x.lstrip().startswith("<!-- auto-generated") for x in text.splitlines()),
             f"{name}: no line starts with auto-generated")
        t.eq(text.count("<!-- end map-refresh -->"), 1, f"{name}: the block is closed")


def case_caps_and_determinism(ctx, t):
    files = {"package.json": '{"name": "acme"}\n', "README.md": "# Acme\n",
             "apps/api/package.json": '{"name": "api"}\n'}
    for n in range(45):
        files[f"shared/widgets/base-widget{n:02d}.ts"] = abstract_class("BaseWidget%02d" % n)
    for n in range(22):
        add_family(files, n, f"shared/fam/base-fam{n:02d}.ts")
    for n in range(30):
        files[f"apps/api/services/svc{n:02d}/svc{n:02d}.service.ts"] = generic_fn("serve%02d" % n)
    ctx.tree("projects/acme", files)
    for brain in (BRAIN, "docs/ai-brain"):
        os.makedirs(ctx.path(brain))
        r = refresh(ctx, "--project", "projects/acme", "--brain", brain)
        t.eq(r.rc, 0, f"render into {brain}")
    u, p = map_text(ctx, "utilities.md"), map_text(ctx, "patterns.md")
    count = lambda text: sum(x.startswith("| `") for x in text[:text.index("<!-- end map-refresh -->")].splitlines())
    t.eq(count(u), 40, "utilities stay capped at 40")
    t.eq(count(p), 20, "patterns stay capped at 20")
    t.lacks(u, "serve0", "an application's services/ folder does not flood the utilities")
    for name in MAP_FILES:
        t.eq(map_text(ctx, name, "docs/ai-brain").replace("Project `projects/acme`", ""),
             map_text(ctx, name).replace("Project `projects/acme`", ""), f"{name}: the same tree renders the same bytes")


def case_usage_errors_exit_64(ctx, t):
    os.makedirs(ctx.path(BRAIN))
    for flags in (("--bogus",), ("--brain", BRAIN), ("--check",), ("--brain", BRAIN, "--check", "--init"),
                  ("--brain", BRAIN, "--check", "--human", "A@b=c|d"), ("--project", ".", "--human", "nokey")):
        t.eq(refresh(ctx, *flags).rc, 64, f"usage error {' '.join(flags)}")
    h = refresh(ctx, "--help")
    t.eq(h.rc, 0, "--help: exit code")
    for flag in ("--project", "--brain", "--update", "--human", "--context-skill", "--max-depth", "--dry-run",
                 "--json", "--check", "--init"):
        t.has(h.out, flag, "--help lists " + flag)
    t.lacks(h.out, "--module", "--help has no module flag")


def case_output_line_limit(ctx, t):
    writer_tree(ctx)
    flags = ["--project", "projects/acme", "--brain", BRAIN, "--dry-run"]
    for n in range(60):
        flags += ["--human", f"Ghost{n:02d}@src/none.ts=a|b"]
    r = refresh(ctx, *flags)
    lines = r.out.strip().splitlines()
    t.ok(len(lines) <= 40, f"at most 40 lines (got {len(lines)})")
    t.eq(lines[-1], "MAP: stale(utilities.md,patterns.md,where-to-look.md)", "a dry run names what it would write")
    t.eq(r.rc, 1, "a dry run with pending changes exits 1")
    t.ok(not os.path.exists(ctx.path(BRAIN + "/map")), "a dry run writes nothing")


def case_backtick_cells_round_trip(ctx, t):
    long_tag = "export function tagOf<T>(x: T): string { return `id-${x}-" + "a" * 60 + "` }\n"
    writer_tree(ctx, extra={"src/shared/label.ts": "export function labelOf<T>(x: T): string { return `id-${x}` }\n",
                            "src/shared/tag.ts": long_tag})
    refresh(ctx, "--project", "projects/acme", "--brain", BRAIN)
    path = ctx.path(BRAIN + "/map/utilities.md")
    u = map_text(ctx, "utilities.md")
    cut = row_line(u, "`tagOf`")
    t.ok(cut is not None and cut.count("`") % 2 == 0, "a signature cut inside a template literal emits paired backticks")
    t.has(cut, "return 'id-", "the unpaired backtick of the cut signature becomes a quote")
    t.has(row_line(u, "`labelOf`"), "return `id-${x}`", "a paired template literal stays as written")
    for sym in ("`labelOf`", "`tagOf`"):
        fill(path, sym, ["Builds an id", "Any id shown to a user"])
    ctx.write("projects/acme/src/shared/to-cents.ts", generic_fn("toCents"))
    r = refresh(ctx, "--project", "projects/acme", "--brain", BRAIN)
    t.eq(r.rc, 0, "refresh with backticks in signatures: exit code")
    u = map_text(ctx, "utilities.md")
    for sym in ("`labelOf`", "`tagOf`"):
        t.eq(row_cells(u, sym)[-2:], ["Builds an id", "Any id shown to a user"], f"{sym}: ✍ text survives the refresh")
    c = refresh(ctx, "--brain", BRAIN, "--check")
    t.eq((c.rc, last(c)), (0, "MAP: fresh"), "backtick signatures read back equal")
    fill(path, "`formatMoney`", ["Wraps `money", "Any amount"])
    refresh(ctx, "--project", "projects/acme", "--brain", BRAIN, "--human", f"roundCents@{ROUND}=Rounds `cents|Totals")
    refresh(ctx, "--project", "projects/acme", "--brain", BRAIN)
    u = map_text(ctx, "utilities.md")
    t.eq(row_cells(u, "`formatMoney`")[-2:], ["Wraps 'money", "Any amount"],
         "an odd backtick typed into a ✍ cell stays in its own cell")
    t.eq(row_cells(u, "`roundCents`")[-2:], ["Rounds 'cents", "Totals"],
         "an odd backtick passed with --human stays in its own cell")
    c = refresh(ctx, "--brain", BRAIN, "--check")
    t.eq((c.rc, last(c)), (0, "MAP: fresh"), "--check after the ✍ backticks")


def case_retired_text_stays_with_its_project(ctx, t):
    writer_tree(ctx, "acme")
    writer_tree(ctx, "billing")
    os.remove(ctx.path("projects/billing/" + MONEY))
    for name in ("acme", "billing"):
        refresh(ctx, "--project", "projects/" + name, "--brain", BRAIN)
    path = ctx.path(BRAIN + "/map/utilities.md")
    fill(path, "`formatMoney`", ["Formats cents as money", "Any amount shown to a user"])
    os.remove(ctx.path("projects/acme/" + MONEY))
    refresh(ctx, "--project", "projects/acme", "--brain", BRAIN)
    ctx.write("projects/billing/" + MONEY, generic_fn("formatMoney"))
    r = refresh(ctx, "--project", "projects/billing", "--brain", BRAIN)
    t.eq(r.rc, 0, "billing gains formatMoney: exit code")
    u = map_text(ctx, "utilities.md")
    billing = u[u.index("project projects/billing"):u.index("## Curated (human)")]
    t.eq(row_cells(billing, "`formatMoney`")[-2:], ["—", "—"], "billing's new row does not inherit acme's text")
    found = row_cells(section(u, "## Retired (review)"), "`formatMoney`")
    t.eq(found[-3:] if found else None, ["Formats cents as money", "Any amount shown to a user", f"{TODAY} · projects/acme"],
         "Retired keeps acme's row, dated and naming its project")
    ctx.write("projects/acme/" + MONEY, generic_fn("formatMoney"))
    refresh(ctx, "--project", "projects/acme", "--brain", BRAIN)
    u = map_text(ctx, "utilities.md")
    acme = u[u.index("project projects/acme"):u.index("project projects/billing")]
    t.eq(row_cells(acme, "`formatMoney`")[-2:], ["Formats cents as money", "Any amount shown to a user"],
         "acme's restored row takes its text back")
    t.lacks(section(u, "## Retired (review)"), "formatMoney", "and leaves Retired")


def case_brain_inside_project(ctx, t):
    project, _ = writer_tree(ctx, extra={"docs/ai-brain/roadmap.md": "# Master plan\n",
                                         "docs/guide.md": "# Guide\n"})
    brain = os.path.join(project, "docs", "ai-brain")
    try:
        os.makedirs(os.path.join(project, "ai"))
        os.symlink(os.path.relpath(brain, os.path.join(project, "ai")), os.path.join(project, "ai", "ai-brain"))
        os.symlink(os.path.relpath(brain, project), os.path.join(project, "ai-brain"))
    except (OSError, NotImplementedError):
        raise Skip("this filesystem cannot create symlinks")
    r = refresh(ctx, "--project", "projects/acme")
    t.eq((r.rc, last(r)), (0, "MAP: written"), "run 1 through the project's ai-brain symlink")
    c = refresh(ctx, "--brain", "projects/acme/ai-brain", "--check")
    t.eq((c.rc, last(c)), (0, "MAP: fresh"), "--check right after run 1")
    before = snapshot(os.path.join(brain, "map"))
    r = refresh(ctx, "--project", "projects/acme")
    t.eq(last(r), "MAP: unchanged", "run 2")
    t.ok(snapshot(os.path.join(brain, "map")) == before, "run 2 leaves the map byte-identical")
    with open(os.path.join(brain, "map", "where-to-look.md"), encoding="utf-8") as fh:
        w = fh.read()
    paths = [x.split(" | ")[0][2:] for x in w[:w.index("<!-- end map-refresh -->")].splitlines() if x.startswith("| `")]
    t.ok(not any("map/" in p for p in paths), "the brain's map/ is never listed")
    t.eq([p for p in paths if "roadmap" in p], ["`ai-brain/roadmap.md`"], "the brain doc is listed once")
    t.ok("`docs/guide.md`" in paths, "repo docs outside the brain stay")


def case_consumers_buckets(ctx, t):
    files = {}
    for n in range(25):
        files[f"src/use/u{n:02d}.ts"] = "formatMoney(1)\n"
    writer_tree(ctx, extra=files)
    refresh(ctx, "--project", "projects/acme", "--brain", BRAIN)
    u = map_text(ctx, "utilities.md")
    got = [row_cells(u, x.split(" | ")[0][2:])[4] for x in u[:u.index("<!-- end map-refresh -->")].splitlines()
           if x.startswith("| `")]
    t.ok(got and set(got) <= {"0", "1", "2–5", "6–20", "20+"}, f"every Consumers cell is a documented bucket: {got}")
    t.ok("20+" in got and "0" in got, "the fixture reaches both ends of the buckets")


def case_ascii_stdout_help(ctx, t):
    if not os.path.isfile(ctx.script):
        raise Skip("map writer not found")
    env = dict(ctx.env, PYTHONIOENCODING="ascii", PYTHONUTF8="0")
    p = subprocess.run([sys.executable, ctx.script, "--help"], capture_output=True, env=env, cwd=ctx.root, timeout=60)
    t.eq(p.returncode, 0, "--help under an ascii stdout: exit code")
    t.lacks(p.stderr.decode("utf-8", "replace"), "Traceback", "--help under an ascii stdout: no traceback")


def case_project_too_far_refused(ctx, t):
    writer_tree(ctx)
    os.makedirs(ctx.path("d1/d2/d3/d4/ai/ai-brain"))
    before = snapshot(ctx.root)
    r = refresh(ctx, "--project", "projects/acme", "--brain", "d1/d2/d3/d4/ai/ai-brain")
    t.eq(r.rc, 2, "a project four levels above the brain container: exit code")
    t.eq(last(r), "MAP: unresolved (project too far from the brain container)", "last line")
    t.ok(snapshot(ctx.root) == before, "nothing written")
    near = ctx.tree("sibling/acme", service_tree())
    os.makedirs(ctx.path("box/ai/ai-brain"))
    r = refresh(ctx, "--project", near, "--brain", "box/ai/ai-brain")
    t.eq(r.rc, 0, "a project one level out still renders")
    t.eq(re.findall(MARKER_RX, map_text(ctx, "utilities.md", "box/ai/ai-brain"), re.M)[0][1], "/".join(["..", "sibling", "acme"]),
         "its block names the one-level path")


def case_hand_notes_file_gains_sections(ctx, t):
    writer_tree(ctx)
    ctx.write(BRAIN + "/map/utilities.md", "# Utilities\n\nHand notes kept here.\n")
    r = refresh(ctx, "--project", "projects/acme", "--brain", BRAIN)
    t.eq(r.rc, 0, "refresh into a hand-notes file: exit code")
    u = map_text(ctx, "utilities.md")
    t.has(u, "Hand notes kept here.", "the notes are kept")
    t.eq((u.count("\n## Curated (human)\n"), u.count("\n## Retired (review)\n")), (1, 1),
         "one Curated and one Retired heading are added")
    t.ok(u.index("<!-- end map-refresh -->") < u.index("## Curated (human)"), "the sections follow the block")
    r = refresh(ctx, "--project", "projects/acme", "--brain", BRAIN)
    t.eq(last(r), "MAP: unchanged", "the second refresh leaves it alone")


CASES = [
    ("scan_usage_map_golden", case_usage_map_golden),
    ("scan_map_block_keys", case_map_block_keys),
    ("scan_ts_generic_base_family", case_ts_generic_base_family),
    ("scan_hooks_and_composables", case_hooks_and_composables),
    ("scan_shape_without_base", case_shape_without_base),
    ("scan_shape_base_status", case_shape_base_status),
    ("scan_utility_type_counts", case_utility_type_counts),
    ("scan_shared_hints_extended", case_shared_hints_extended),
    ("scan_app_root_guard", case_app_root_guard),
    ("scan_utility_exemplar", case_utility_exemplar),
    ("scan_where_to_look", case_where_to_look),
    ("scan_docs_symlink", case_docs_symlink),
    ("scan_update_affected_map_rows", case_update_affected_map_rows),
    ("scan_python_only_degrades", case_python_only_degrades),
    ("scan_other_languages", case_other_languages),
    ("scan_map_caps", case_map_caps),
    ("scan_workspace_packages", case_workspace_packages),
    ("scan_nested_app_in_root", case_nested_app_in_root),
    ("scan_signature_start", case_signature_start),
    ("scan_exemplar_past_sample", case_exemplar_past_sample),
    ("scan_update_beyond_evidence", case_update_beyond_evidence),
    ("scan_shape_excludes_base_file", case_shape_excludes_base_file),
    ("scan_pattern_slots", case_pattern_slots),
    ("scan_detector_order", case_detector_order),
    ("scan_test_file_rule", case_test_file_rule),
    ("render_creates_three_files", case_render_creates_three_files),
    ("check_init_shells_fresh", case_check_init_shells_fresh),
    ("render_preserves_human_columns", case_render_preserves_human_columns),
    ("retired_rows_keep_human_text", case_retired_rows_keep_human_text),
    ("moved_symbol_carries_human_text", case_moved_symbol_carries_human_text),
    ("pipe_escaping_in_signature", case_pipe_escaping_in_signature),
    ("check_exit_codes", case_check_exit_codes),
    ("idempotent_second_run", case_idempotent_second_run),
    ("module_brain_via_symlink", case_module_brain_via_symlink),
    ("modules_brain_without_symlink", case_modules_brain_without_symlink),
    ("no_write_without_brain_or_symlink", case_no_write_without_brain_or_symlink),
    ("symlinked_map_dir_refused", case_symlinked_map_dir_refused),
    ("multi_project_blocks_do_not_clobber", case_multi_project_blocks_do_not_clobber),
    ("no_absolute_paths_in_output", case_no_absolute_paths_in_output),
    ("where_to_look_rows", case_where_to_look_rows),
    ("init_writes_three_shells", case_init_writes_three_shells),
    ("human_flag_fills_only_named_key", case_human_flag_fills_only_named_key),
    ("marker_contract", case_marker_contract),
    ("caps_and_determinism", case_caps_and_determinism),
    ("usage_errors_exit_64", case_usage_errors_exit_64),
    ("output_line_limit", case_output_line_limit),
    ("backtick_cells_round_trip", case_backtick_cells_round_trip),
    ("retired_text_stays_with_its_project", case_retired_text_stays_with_its_project),
    ("brain_inside_project", case_brain_inside_project),
    ("consumers_buckets", case_consumers_buckets),
    ("ascii_stdout_help", case_ascii_stdout_help),
    ("project_too_far_refused", case_project_too_far_refused),
    ("hand_notes_file_gains_sections", case_hand_notes_file_gains_sections),
]


def run_case(fn, scanner, script, keep):
    root = os.path.realpath(tempfile.mkdtemp(prefix="map-refresh-selftest-"))
    t = Check()
    try:
        fn(Ctx(scanner, script, root), t)
        verdict, why = ("FAIL", "; ".join(p[:150] for p in t.problems[:8])) if t.problems else ("PASS", "")
    except Skip as s:
        verdict, why = "SKIP", str(s)
    except (Exception, SystemExit) as exc:  # a broken harness or a crashing scanner is a failure, not a crash
        verdict, why = "FAIL", f"harness error: {exc!r}"
    finally:
        if keep:
            print(f"  kept {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)
    return verdict, why


def main():
    ap = argparse.ArgumentParser(description="Behavioural tests for the map detectors of scan_project.py")
    ap.add_argument("--scanner", default=os.path.join(HERE, "scan_project.py"),
                    help="scan_project.py under test")
    ap.add_argument("--script", default=os.path.join(HERE, "map_refresh.py"),
                    help="map writer under test; the cases that drive it skip when it is absent")
    ap.add_argument("--only", help="run a single case by name")
    ap.add_argument("--keep", action="store_true", help="leave the temp trees on disk")
    args = ap.parse_args()
    scanner = os.path.abspath(os.path.expanduser(args.scanner))
    script = os.path.abspath(os.path.expanduser(args.script))
    if not os.path.isfile(scanner):
        print(f"scanner not found: {scanner}")
        return 2
    cases = [c for c in CASES if not args.only or c[0] == args.only]
    if not cases:
        print(f"unknown case {args.only!r}; known: {', '.join(n for n, _ in CASES)}")
        return 2
    tally = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    for name, fn in cases:
        verdict, why = run_case(fn, scanner, script, args.keep)
        tally[verdict] += 1
        print(f"{verdict} {name}" + (f" — {why}" if why else ""))
    print(f"{tally['PASS']} PASS · {tally['FAIL']} FAIL · {tally['SKIP']} SKIP (of {len(cases)})")
    return 1 if tally["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
