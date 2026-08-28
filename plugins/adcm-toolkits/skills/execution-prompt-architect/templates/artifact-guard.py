#!/usr/bin/env python3
"""artifact-guard — Stop hook de Claude Code (determinista, sin dependencias).

Garantiza dos cosas cada vez que un turno intenta cerrar:

  1. FRESCURA — todo HTML registrado en un `artifacts.json` que cambió en disco durante
     la sesión fue republicado a su MISMA URL (tool Artifact con `url`) DESPUÉS del
     último cambio. Si no, bloquea el cierre y dice exactamente qué publicar.
  2. LINKS AL CIERRE — si el turno publicó un artifact, cambió un HTML registrado o tocó
     un doc de cierre (`close_markers`: task.md / execute.md / detailed-plan.md) del
     módulo, el mensaje final debe incluir las URLs canónicas de ese módulo. Si faltan,
     bloquea el cierre y entrega el bloque de links listo para pegar.

Descubrimiento del registro: sube desde `cwd` buscando `ai/ai-brain/artifacts.json` o
`ai-brain/artifacts.json`. Sin registro → no-op (exit 0, sin output). Cualquier
excepción → exit 0 sin output: este hook nunca rompe una sesión.

Formato de artifacts.json (paths relativos a su carpeta):
  {"close_markers": ["task.md", ...],
   "artifacts": [{"file": "modules/x/plans.html", "url": "https://claude.ai/code/artifact/…",
                  "title": "…", "favicon": "📒", "in_close_block": true}]}

Instalación (user settings, event Stop):
  {"hooks": {"Stop": [{"matcher": "", "hooks": [{"type": "command",
     "command": "python3 ~/.claude/hooks/artifact-guard.py", "timeout": 20}]}]}}

Fuente canónica: plugin adcm-toolkits → skills/execution-prompt-architect/templates/artifact-guard.py
"""
import json
import os
import sys
from datetime import datetime, timezone

REGISTRY_CANDIDATES = ("ai/ai-brain/artifacts.json", "ai-brain/artifacts.json")
DEFAULT_MARKERS = ("task.md", "execute.md", "detailed-plan.md")


def real(path):
    return os.path.realpath(os.path.expanduser(path))


def iso_to_epoch(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def find_registries(cwd):
    found, seen = [], set()
    d = real(cwd) if cwd else os.getcwd()
    while True:
        for rel in REGISTRY_CANDIDATES:
            p = os.path.join(d, rel)
            if os.path.isfile(p):
                rp = real(p)
                if rp not in seen:
                    seen.add(rp)
                    try:
                        with open(rp, encoding="utf-8") as fh:
                            found.append((os.path.dirname(rp), json.load(fh)))
                    except Exception:
                        pass
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return found


def is_human_prompt(entry):
    if entry.get("type") != "user" or entry.get("isMeta"):
        return False
    origin = entry.get("origin") or {}
    if isinstance(origin, dict) and origin.get("kind") and origin.get("kind") != "human":
        return False
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        kinds = {b.get("type") for b in content if isinstance(b, dict)}
        return "text" in kinds and "tool_result" not in kinds
    return False


def parse_transcript(path):
    """Devuelve (session_start, turn_start, publishes, final_text).
    publishes: lista de (epoch, realpath) de tool Artifact publish (toda la sesión).
    final_text: texto del asistente del turno actual, posterior al último tool_use."""
    session_start = turn_start = None
    publishes = []
    texts_after_last_tool = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                e = json.loads(line)
            except Exception:
                continue
            ts = iso_to_epoch(e.get("timestamp"))
            if is_human_prompt(e):
                if ts is not None:
                    if session_start is None:
                        session_start = ts
                    turn_start = ts
                texts_after_last_tool = []
                continue
            if e.get("type") != "assistant":
                continue
            for b in (e.get("message") or {}).get("content") or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    texts_after_last_tool = []
                    if b.get("name") == "Artifact":
                        inp = b.get("input") or {}
                        action = inp.get("action") or "publish"
                        fp = inp.get("file_path")
                        if action == "publish" and fp and ts is not None:
                            publishes.append((ts, real(fp)))
                elif b.get("type") == "text":
                    texts_after_last_tool.append(b.get("text") or "")
    return session_start, turn_start, publishes, "\n".join(texts_after_last_tool)


def module_root(reg_dir, rel_file, markers):
    d = os.path.dirname(os.path.join(reg_dir, rel_file))
    while True:
        if any(os.path.exists(os.path.join(d, m)) for m in markers):
            return d
        if real(d) == real(reg_dir) or len(d) <= len(reg_dir):
            return reg_dir
        d = os.path.dirname(d)


def check(hook_input):
    cwd = hook_input.get("cwd") or os.getcwd()
    transcript = hook_input.get("transcript_path")
    if not transcript or not os.path.isfile(os.path.expanduser(transcript)):
        return [], []
    registries = find_registries(cwd)
    if not registries:
        return [], []
    session_start, turn_start, publishes, final_text = parse_transcript(os.path.expanduser(transcript))
    if turn_start is None:
        return [], []

    stale, links_missing = [], []
    for reg_dir, data in registries:
        markers = tuple(data.get("close_markers") or DEFAULT_MARKERS)
        entries = [a for a in data.get("artifacts") or [] if a.get("file") and a.get("url")]
        by_module = {}
        for a in entries:
            abs_file = real(os.path.join(reg_dir, a["file"]))
            a["_abs"] = abs_file
            a["_module"] = module_root(reg_dir, a["file"], markers)
            by_module.setdefault(a["_module"], []).append(a)
            if not os.path.isfile(abs_file):
                continue
            mtime = os.path.getmtime(abs_file)
            last_pub = max((t for t, p in publishes if p == abs_file), default=None)
            if mtime >= session_start and (last_pub is None or last_pub < mtime):
                stale.append((a, abs_file))

        for mod, arts in by_module.items():
            closing = False
            for m in markers:
                mp = os.path.join(mod, m)
                if os.path.isfile(mp) and os.path.getmtime(mp) >= turn_start:
                    closing = True
            for a in arts:
                if os.path.isfile(a["_abs"]) and os.path.getmtime(a["_abs"]) >= turn_start:
                    closing = True
                if any(p == a["_abs"] and t >= turn_start for t, p in publishes):
                    closing = True
            if not closing:
                continue
            required = [a for a in arts if a.get("in_close_block", True)]
            missing = [a for a in required if a["url"] not in final_text]
            if missing:
                links_missing.append((mod, required, missing))
    return stale, links_missing


def fmt_link(a):
    return f"{a.get('favicon', '🔗')} {a.get('title') or a['file']}: {a['url']}"


def main():
    try:
        hook_input = json.load(sys.stdin)
    except Exception:
        hook_input = {}
    try:
        stale, links_missing = check(hook_input)
    except Exception:
        return 0
    if not stale and not links_missing:
        return 0

    lines = ["⛔ artifact-guard: el cierre está incompleto."]
    if stale:
        lines.append("Artifacts DESACTUALIZADOS (cambiaron en disco y no se republicaron a su URL):")
        for a, abs_file in stale:
            lines.append(f"  • {a['file']} → Artifact(file_path=\"{abs_file}\", url=\"{a['url']}\")")
        lines.append("  Antes de publicar, lee la versión viva (Artifact action=read con esa url) — el publish exige haberla visto.")
    if links_missing:
        for mod, required, missing in links_missing:
            lines.append(f"Falta el BLOQUE DE LINKS al final del mensaje (módulo {os.path.relpath(mod, os.path.expanduser('~'))}). Pégalo tal cual, al final:")
            for a in required:
                lines.append(f"  - {fmt_link(a)}")
    lines.append("Corrige lo anterior (republica y/o agrega el bloque de links) y vuelve a cerrar.")
    reason = "\n".join(lines)

    if hook_input.get("stop_hook_active"):
        print(json.dumps({"systemMessage": "artifact-guard: cierre con pendientes (ya se bloqueó una vez; no se vuelve a bloquear).\n" + reason}, ensure_ascii=False))
        return 0
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
