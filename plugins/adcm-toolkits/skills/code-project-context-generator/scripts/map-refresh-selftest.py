#!/usr/bin/env python3
"""map-refresh-selftest - behavioural tests for the map detectors of scan_project.py (stdlib only).

Usage:
  python3 map-refresh-selftest.py [--scanner PATH] [--script PATH] [--only NAME] [--keep]

Every case builds one throwaway `tempfile` project (generic "Acme" code), runs scan_project.py on it as a
subprocess (`<project> [--update PATHS]`, PYTHONDONTWRITEBYTECODE=1) and prints
`PASS|FAIL|SKIP <case> [- why]`, then the tally `N PASS · N FAIL · N SKIP (of N)`. Exit code 1 when any
case FAILs. No real project tree is ever scanned.

What is asserted (JSON structure of the scanner output, never prose):
  - the `usage_map` block (shared roots, surfaces and their consumer census) and the legacy `update` keys
    keep their exact content, so extending the scanner cannot move them;
  - the additive `map` block and `update.affected_map_rows`: keys, row shapes, caps and determinism.

The scanner under test defaults to the scan_project.py next to this file; pass --scanner to test another
copy. --script names the map writer (map_refresh.py), which the writer cases drive and skip when it is
absent. --keep leaves the temp trees on disk.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

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
        "tests/fixtures/rates.repository.ts": "export const rates = 1\n",
        "src/__tests__/users.repository.ts": "export const users = 1\n",
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
        "shape:repository (tests, in a test folder or named test_*, are excluded)")
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
    t.eq(sorted(u["symbol"] for u in rows(out, "utilities")), ["BaseMailer", "BaseWebStore"],
         "apps/api, a folder with its own manifest and a services/ folder under apps/ are not "
         "mistaken for shared code; a plain src/services is")


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
    key = ["affected_folders", "affected_map_rows", "affected_surfaces", "paths"]

    out = ctx.scan("acme", "--update", base)
    t.eq(sorted(out["update"]), key, "update keys")
    t.eq(out["update"]["affected_map_rows"],
         {"utilities": ["BaseApiService@" + base], "patterns": ["shape:service", "types:utility"]},
         "touching the defining file affects its utility row and the patterns that list it as evidence")

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
        files[f"shared/fam/base-fam{n:02d}.ts"] = "export class BaseFam%02d {}\n" % n
        for side in "ab":
            files[f"src/ext/fam{n:02d}{side}.ts"] = "export class Fam%02d%s extends BaseFam%02d {}\n" % (n, side, n)
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
]


def run_case(fn, scanner, script, keep):
    root = os.path.realpath(tempfile.mkdtemp(prefix="map-refresh-selftest-"))
    t = Check()
    try:
        fn(Ctx(scanner, script, root), t)
        verdict, why = ("FAIL", "; ".join(p[:150] for p in t.problems[:8])) if t.problems else ("PASS", "")
    except Skip as s:
        verdict, why = "SKIP", str(s)
    except Exception as exc:  # a broken harness or a crashing scanner is a failure, not a crash
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
