#!/usr/bin/env python3
"""Local audit of a live site — the checks is-agentic does not perform.

Everything here is measured by fetching the public site directly. Nothing is
uploaded anywhere, no credentials are used, no third-party crawler is involved.
That is a hard requirement, not an implementation detail: this skill may run
against sites whose content is confidential.

Each check returns Findings carrying the command that reproduces them. A finding
without a reproducing command is an opinion, and opinions do not belong in a
report that becomes an execution wave.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict, field

UA = "agentic-seo-report/1.0 (+adcm-toolkits; audits the site it is pointed at)"
TIMEOUT = 20

# Crawlers that feed AI answer/generative engines. Allowing them is what makes a
# site quotable in AI answers; blocking them is a legitimate choice, but it must
# be a choice, not an accident.
AI_CRAWLERS = [
    "GPTBot", "OAI-SearchBot", "ChatGPT-User",          # OpenAI
    "ClaudeBot", "Claude-User", "anthropic-ai",          # Anthropic
    "PerplexityBot", "Perplexity-User",                  # Perplexity
    "Google-Extended",                                   # Gemini / AI Overviews
    "Applebot-Extended", "CCBot", "Bytespider", "meta-externalagent",
]

# Schema.org types Google retired or demoted for rich results. Emitting them is
# not an error, it just no longer buys anything — and it crowds the payload an
# agent has to read. Sourced from references/deprecated-schema.md.
RETIRED_TYPES = {
    "HowTo": "rich result removed by Google (2023) — no longer earns enhanced display",
    "FAQPage": "restricted (Aug 2023) to authoritative government and health sites",
    "Book": "Book Actions limited to a small set of approved partners",
    "Course": "list-format only; standalone Course rich result withdrawn",
    "Sitelinks Searchbox": "rich result removed by Google (Nov 2024)",
    "VehicleListing": "limited availability; not a general rich result",
}

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}


@dataclass
class Finding:
    check: str
    severity: str          # high | medium | low | info
    passed: bool
    summary: str
    detail: str = ""
    command: str = ""      # reproduces it today, proves it fixed tomorrow
    fix: str = ""
    where: str = ""        # file or surface to touch
    tags: list = field(default_factory=list)


def get(url: str, headers: dict | None = None) -> tuple[int, dict, str]:
    """Fetch a URL. Returns (status, headers, body); status 0 means unreachable."""
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read().decode("utf-8", errors="replace")
            return r.status, {k.lower(): v for k, v in r.headers.items()}, body
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, ""
    except Exception:
        return 0, {}, ""


def visible_text(html: str) -> str:
    """Roughly what an agent reads with JavaScript disabled."""
    stripped = re.sub(r"(?is)<(script|style|template|noscript)\b.*?</\1>", " ", html)
    return re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]*>", " ", stripped)).strip()


# ---------------------------------------------------------------- checks

def check_llms_txt(base: str) -> list[Finding]:
    """llms.txt is the emerging convention for telling agents what a site is for."""
    paths = ["/llms.txt", "/llms-full.txt", "/.well-known/llms.txt"]
    found = [p for p in paths if get(urllib.parse.urljoin(base, p))[0] == 200]
    cmd = f"curl -s -o /dev/null -w '%{{http_code}}' {base.rstrip('/')}/llms.txt"
    if found:
        return [Finding("llms-txt", "info", True, f"llms.txt present at {found[0]}", command=cmd)]
    return [Finding(
        "llms-txt", "medium", False,
        "No llms.txt — agents have no map of what this site is for",
        detail="Checked /llms.txt, /llms-full.txt and /.well-known/llms.txt; all 404. "
               "This is also what fails is-agentic's `agent-instruction` check.",
        command=cmd,
        fix="Publish /llms.txt: what the business does, who it serves, the canonical pages, "
            "and a 'when to use this' section naming the questions the site can answer. "
            "Keep it short and factual — it is read, not ranked.",
        where="the site's static/public directory",
        tags=["AEO", "GEO", "quick-win"])]


def check_markdown_negotiation(base: str) -> list[Finding]:
    """Agents ask for markdown; serving HTML without Vary poisons shared caches."""
    _, h, _ = get(base, {"Accept": "text/markdown"})
    ctype = h.get("content-type", "")
    vary = h.get("vary", "")
    ok_type = "markdown" in ctype
    ok_vary = "accept" in [v.strip().lower() for v in vary.split(",")]
    cmd = f"curl -sI -H 'Accept: text/markdown' {base} | grep -iE 'content-type|vary'"
    if ok_type and ok_vary:
        return [Finding("markdown-negotiation", "info", True,
                        "Serves markdown on request and varies on Accept", command=cmd)]
    bits = []
    if not ok_type:
        bits.append(f"Accept: text/markdown returned {ctype or 'nothing'}")
    if not ok_vary:
        bits.append(f"Vary lacks Accept (got {vary or 'nothing'})")
    return [Finding(
        "markdown-negotiation", "medium", False,
        "No markdown content negotiation",
        detail="; ".join(bits) + ". Without Vary: Accept a CDN can serve a cached HTML "
               "response to an agent that asked for markdown.",
        command=cmd,
        fix="Serve text/markdown when the Accept header asks for it, and always send "
            "Vary: Accept on those routes. Even adding Vary alone removes the cache hazard.",
        where="the HTTP layer (server middleware or edge config)",
        tags=["AEO"])]


def check_robots(base: str) -> list[Finding]:
    """Report the AI-crawler posture. Blocking is valid; blocking by accident is not."""
    status, _, body = get(urllib.parse.urljoin(base, "/robots.txt"))
    cmd = f"curl -s {base.rstrip('/')}/robots.txt"
    if status != 200:
        return [Finding("robots", "high", False, f"robots.txt returns {status}",
                        command=cmd, fix="Publish a robots.txt; without it crawler behaviour is undefined.",
                        tags=["SEO"])]

    named = [c for c in AI_CRAWLERS if re.search(rf"(?im)^user-agent:\s*{re.escape(c)}\s*$", body)]
    generic_delay = re.search(r"(?is)user-agent:\s*\*(.*?)(?=^user-agent:|\Z)", body, re.M)
    delay = None
    if generic_delay:
        m = re.search(r"(?im)^crawl-delay:\s*(\d+)", generic_delay.group(1))
        delay = int(m.group(1)) if m else None

    out = [Finding(
        "robots-ai-crawlers", "info", True,
        f"{len(named)} AI crawler(s) named explicitly; the rest inherit User-agent: *",
        detail=("Named: " + ", ".join(named)) if named else
               "None named — every AI crawler falls under the wildcard block.",
        command=cmd + " | grep -iE 'gptbot|claudebot|perplexity|google-extended'",
        tags=["AEO", "GEO"])]

    if not named:
        out.append(Finding(
            "robots-ai-posture", "low", False,
            "AI-crawler access is inherited, not decided",
            detail="No explicit block for GPTBot / ClaudeBot / PerplexityBot / Google-Extended, "
                   "so they follow User-agent: *. That may be exactly what you want — but it is "
                   "worth making it an explicit decision that survives the next robots.txt edit. "
                   "Careful: a named block REPLACES the wildcard block, it does not inherit from "
                   "it, so any private paths must be repeated inside each named block.",
            command=cmd,
            fix="Add explicit blocks for the AI crawlers you want, repeating every Disallow "
                "that matters. Document the choice in a comment.",
            where="robots.txt",
            tags=["AEO", "GEO"]))

    if delay:
        out.append(Finding(
            "robots-crawl-delay", "low", False,
            f"AI crawlers inherit Crawl-delay: {delay}",
            detail="Search engines with their own block may be exempt while AI crawlers are not. "
                   "Harmless on a small site; it throttles discovery as the site grows.",
            command=cmd + " | grep -i crawl-delay",
            fix="Either exempt the AI crawlers you want indexed, or keep the delay deliberately.",
            where="robots.txt", tags=["AEO"]))
    return out


def check_sitemap(base: str) -> list[Finding]:
    """Sitemap reachable, non-empty, and declaring language alternates if bilingual."""
    status, _, body = get(urllib.parse.urljoin(base, "/sitemap.xml"))
    cmd = f"curl -s {base.rstrip('/')}/sitemap.xml | grep -c '<loc>'"
    if status != 200:
        return [Finding("sitemap", "high", False, f"/sitemap.xml returns {status}", command=cmd,
                        fix="Publish a sitemap and declare it in robots.txt.", tags=["SEO"])]
    locs = re.findall(r"<loc>(.*?)</loc>", body)
    alts = len(re.findall(r'hreflang="', body))
    return [Finding(
        "sitemap", "info", True,
        f"Sitemap lists {len(locs)} URLs" + (f" with {alts} hreflang alternates" if alts else ""),
        detail="Language alternates declared inside each <url> block is the correct pattern; "
               "separate <loc> entries per language are not required."
               if alts else "No hreflang alternates declared.",
        command=cmd, tags=["SEO"])]


def check_page(base: str, path: str) -> list[Finding]:
    """Per-page: SSR text, canonical, hreflang reciprocity, JSON-LD health."""
    url = urllib.parse.urljoin(base, path)
    status, _, html = get(url)
    label = path or "/"
    if status != 200:
        return [Finding(f"page:{label}", "high", False, f"{label} returns {status}",
                        command=f"curl -sI {url}", tags=["SEO"])]

    out: list[Finding] = []
    text = visible_text(html)
    thin = len(text) < 1000
    out.append(Finding(
        f"ssr:{label}", "medium" if thin else "info", not thin,
        f"{len(text)} chars readable without JavaScript",
        detail="This is what an AI agent and a non-rendering crawler actually get."
               + (" Under ~1000 chars the page has little to be quoted for." if thin else ""),
        command=f"curl -s {url} | sed 's/<[^>]*>//g' | tr -s ' \\n' ' ' | wc -c",
        fix="Move the substance into server-rendered HTML." if thin else "",
        where=path or "home", tags=["AEO", "GEO"]))

    # hreflang reciprocity: every alternate must point back to this page's set.
    alts = dict(re.findall(r'<link[^>]*hreflang="([^"]+)"[^>]*href="([^"]+)"', html))
    if alts:
        bad = []
        for lang, href in alts.items():
            if lang == "x-default":
                continue
            s2, _, h2 = get(href)
            if s2 != 200:
                bad.append(f"{lang} → {href} returns {s2}")
                continue
            back = dict(re.findall(r'<link[^>]*hreflang="([^"]+)"[^>]*href="([^"]+)"', h2))
            if url.rstrip("/") not in {v.rstrip("/") for v in back.values()}:
                bad.append(f"{lang} → {href} does not link back")
        out.append(Finding(
            f"hreflang:{label}", "high" if bad else "info", not bad,
            f"{len(alts)} hreflang alternates, {'NOT ' if bad else ''}reciprocal",
            detail="; ".join(bad) if bad else "Every alternate links back to this page.",
            command=f"curl -s {url} | grep -o 'hreflang=\"[^\"]*\"'",
            fix="Each language version must list the full alternate set, including itself." if bad else "",
            where=path or "home", tags=["SEO", "i18n"]))

    # JSON-LD: parses, and does not lean on retired types.
    blocks = re.findall(r'(?is)<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html)
    types, broken = set(), 0
    for b in blocks:
        try:
            data = json.loads(b)
        except json.JSONDecodeError:
            broken += 1
            continue
        for node in (data if isinstance(data, list) else [data]):
            if isinstance(node, dict):
                t = node.get("@type")
                types.update(t if isinstance(t, list) else [t] if t else [])
    if broken:
        out.append(Finding(
            f"jsonld-parse:{label}", "high", False, f"{broken} JSON-LD block(s) do not parse",
            detail="Invalid JSON-LD is silently ignored by every consumer — the markup is dead weight.",
            command=f"curl -s {url} | grep -A20 'application/ld+json'",
            fix="Fix the JSON syntax; validate in CI.", where=path or "home", tags=["SEO", "AEO"]))
    retired = sorted(types & RETIRED_TYPES.keys())
    if retired:
        out.append(Finding(
            f"jsonld-retired:{label}", "low", False,
            f"Uses retired schema type(s): {', '.join(retired)}",
            detail="; ".join(f"{t}: {RETIRED_TYPES[t]}" for t in retired),
            command=f"curl -s {url} | grep -o '\"@type\": *\"[A-Za-z]*\"' | sort -u",
            fix="Keep them only if something other than Google rich results consumes them.",
            where=path or "home", tags=["SEO"]))
    out.append(Finding(
        f"jsonld-types:{label}", "info", True,
        f"Schema types: {', '.join(sorted(t for t in types if t)) or 'none'}",
        detail=f"{len(blocks)} JSON-LD block(s).",
        command=f"curl -s {url} | grep -o '\"@type\": *\"[A-Za-z]*\"' | sort -u",
        where=path or "home", tags=["SEO", "AEO"]))
    return out


def run(base: str, paths: list[str]) -> list[Finding]:
    findings = check_llms_txt(base) + check_markdown_negotiation(base) \
        + check_robots(base) + check_sitemap(base)
    for p in paths:
        findings += check_page(base, p)
    findings.sort(key=lambda f: (f.passed, SEVERITY_ORDER.get(f.severity, 9)))
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description="Local agent/SEO audit of a live site.")
    ap.add_argument("url")
    ap.add_argument("--paths", default="/", help="comma-separated paths to audit (default: /)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    base = args.url if args.url.startswith("http") else f"https://{args.url}"
    findings = run(base, [p.strip() for p in args.paths.split(",") if p.strip()])

    if args.json:
        print(json.dumps([asdict(f) for f in findings], indent=2, ensure_ascii=False))
        return 0

    failed = [f for f in findings if not f.passed]
    print(f"{len(failed)} finding(s), {len(findings) - len(failed)} check(s) passed\n")
    for f in findings:
        mark = "✓" if f.passed else "✗"
        print(f"{mark} [{f.severity:6}] {f.check}: {f.summary}")
        if f.detail:
            print(f"           {f.detail}")
        if not f.passed and f.fix:
            print(f"           fix: {f.fix}")
        if f.command:
            print(f"           $ {f.command}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
