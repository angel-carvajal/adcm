#!/usr/bin/env python3
"""artifact-guard — Stop hook de Claude Code (determinista, sin dependencias).

Garantiza dos cosas cada vez que un turno intenta cerrar:

  1. FRESCURA — todo HTML registrado en un `artifacts.json` que cambió en disco durante
     la sesión tiene que estar republicado a su MISMA URL DESPUÉS del último cambio.
     v5: la evidencia puede ser (a) un publish del tool Artifact en el transcript
     principal, (b) el sello de la fila — `published_at` >= mtime del archivo — o (c) el
     `sha256` de la fila igual al del archivo hoy (una regeneración idéntica es fresca
     aunque su mtime sea nuevo). Los sellos los escribe el sub-agente artifact-courier
     tras cada publish: el guard solo ve el transcript principal, no el de los
     sub-agentes. El sha256 se calcula de forma perezosa, solo si la fila sería stale.
     Los sellos son por cuenta: además del canónico (`published_at`, `sha256`) cuenta cualquier
     familia `published_at_<cuenta>` / `sha256_<cuenta>` (y el alias `*_cuenta_<cuenta>`) de la
     fila — una sesión bajo otra cuenta de claude.ai sella SU familia; la fila es stale solo si
     NINGUNA familia la prueba.
     Si no hay evidencia, bloquea el cierre y apunta al courier (no a leer/publicar
     desde la sesión principal).
  2. LINKS AL CIERRE — links Markdown, uno por línea, como ÚLTIMAS líneas del mensaje, nada
     después del último link (v3) · una URL con IP de LAN exige su gemelo `localhost` (v4) ·
     el bloque se evalúa UNA vez sobre la UNIÓN de los módulos que cierran (v5) · v6: el
     bloque se imprime UNA vez por cierre, en el mensaje FINAL y solo tras el RETURN del
     courier. Se exige cuando ese RETURN trajo un bloque de links este turno (llega por
     hand-back, task-notification, cola o tool_result) o la sesión principal publicó un
     artifact; se juzga el ÚLTIMO mensaje del asistente contra la unión = filas de cierre +
     filas cuyas URLs trae el RETURN. Si cambia un doc de cierre (`close_markers`: task.md /
     execute.md / detailed-plan.md) sin entrega ni courier (lanzado o ya corrido), bloquea
     una vez: delega en el courier, no pegues links a mano. El guard nunca arma el bloque
     ni imprime el marcador en sus razones; con `stop_hook_active` solo avisa (systemMessage).
     Calla (sin bloquear ni avisar) mientras haya un courier pendiente — lanzado por tipo, por
     descripción o por brief `artifact-courier` (ruta sin plugin) y sin RETURN — y no exige
     courier mientras otro sub-agente del turno siga en vuelo: su RETURN despierta un stop nuevo.
     Un doc de cierre editado DESPUÉS del último RETURN que entregó (+2 s) cuenta como sin
     entregar. Solo cuenta como RETURN lo que manda un sub-agente: un prompt humano encolado no.

Descubrimiento del registro: sube desde `cwd` buscando `ai/ai-brain/artifacts.json` o
`ai-brain/artifacts.json`, deteniéndose en el home del usuario (nunca lo rebasa, para
que un registro ajeno no capture proyectos no relacionados). Sin registro → no-op
(exit 0, sin output). Cualquier excepción → exit 0 sin output: este hook nunca rompe
una sesión.

Formato de artifacts.json (paths relativos a su carpeta):
  {"close_markers": ["task.md", ...],
   "artifacts": [{"file": "modules/x/plans.html", "url": "https://claude.ai/code/artifact/…",
                  "title": "…", "favicon": "📒", "in_close_block": true,
                  "published_at": "2026-01-01T12:00:00.000Z", "version": "v3",
                  "sha256": "<hex digest of the file as published>"}]}
  (`published_at`, `version` y `sha256` son opcionales: los sella el courier.)

Instalación (user settings, event Stop):
  {"hooks": {"Stop": [{"matcher": "", "hooks": [{"type": "command",
     "command": "python3 ~/.claude/hooks/artifact-guard.py", "timeout": 20}]}]}}

Fuente canónica: plugin adcm-toolkits → skills/execution-prompt-architect/templates/artifact-guard.py
"""
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

REGISTRY_CANDIDATES = ("ai/ai-brain/artifacts.json", "ai-brain/artifacts.json")
DEFAULT_MARKERS = ("task.md", "execute.md", "detailed-plan.md")
CLOCK_SKEW = 60  # segundos de tolerancia antes de tratar un mtime futuro como inválido
LINKS_MARK = "=== LINKS ==="  # cabecera del bloque de links en el RETURN del courier (solo se DETECTA, nunca se imprime)
LINKS_RE = re.compile(r"^\s*" + re.escape(LINKS_MARK) + r"\s*$", re.M)
COURIER_HEAD = re.compile(r"^\s*COURIER\b", re.M)
RETURN_SKEW = 2  # segundos de tolerancia entre el sello del RETURN y el mtime de un doc de cierre


def real(path):
    return os.path.realpath(os.path.expanduser(path))


def iso_to_epoch(ts):
    if not ts:
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def file_sha256(path):
    """Hex sha256 del archivo, o None si no se puede leer. Solo se llama cuando una fila
    sería stale: el caso normal (fresca por transcript o por sello) no paga la lectura."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def norm_sha(value):
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    if value.startswith("sha256:"):
        value = value[len("sha256:"):]
    return value or None


def family_values(a, base):
    """Valores de `base` (sello canónico) y de todo `<base>_<cuenta>` de la fila; el alias
    `<base>_cuenta_<cuenta>` también empieza por `<base>_`, así que queda cubierto."""
    return [v for k, v in a.items() if isinstance(k, str) and (k == base or k.startswith(base + "_"))]


def find_registries(cwd):
    found, seen = [], set()
    d = real(cwd) if cwd else os.getcwd()
    home = real(os.path.expanduser("~"))
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
        # Nunca subir más allá del home: un registro colgado arriba de proyectos
        # ajenos no debe capturar sus sesiones.
        if d == home:
            break
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return found


def is_human_prompt(entry):
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isCompactSummary"):
        return False
    origin = entry.get("origin") or {}
    if isinstance(origin, dict) and origin.get("kind") and origin.get("kind") != "human":
        return False
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        kinds = {b.get("type") for b in content if isinstance(b, dict)}
        return "text" in kinds and "tool_result" not in kinds
    return False


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text") or "" for b in content if isinstance(b, dict))
    return ""


def entry_returns(e, agent_ids):
    """Textos que un sub-agente devolvió a la sesión en esta entrada del transcript. El tool Agent
    es asíncrono: el RETURN no viene en su tool_result ("Async agent launched"), llega por un
    portador (formas del harness 2.1.285/286): mensaje `peer` con `handback`, `task-notification`
    (el RETURN va dentro de `<result>`), adjunto `queued_command` enviado por un sub-agente (no un prompt
    humano encolado), o el tool_result de un Agent/Task."""
    kind, origin = e.get("type"), e.get("origin")
    origin = origin if isinstance(origin, dict) else {}
    message = e.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if kind == "attachment":
        att = e.get("attachment")
        att = att if isinstance(att, dict) else {}
        att_origin = att.get("origin")
        att_kind = att_origin.get("kind") if isinstance(att_origin, dict) else None
        prompt = att.get("prompt")
        # Un `queued_command` también es lo que se encola cuando el humano escribe con Claude ocupado:
        # solo cuenta como RETURN si lo envió un sub-agente (origin peer / task-notification, o el marco del prompt).
        from_agent = att_kind in ("peer", "task-notification") or (
            isinstance(prompt, str) and prompt.lstrip().startswith(("<agent-message", "<task-notification")))
        texts = [prompt] if att.get("type") == "queued_command" and from_agent else []
    elif kind != "user":
        texts = []
    elif origin.get("kind") == "task-notification" or (origin.get("kind") == "peer" and origin.get("handback")):
        texts = [text_of(content)]
    else:
        texts = [text_of(b.get("content")) for b in (content if isinstance(content, list) else [])
                 if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in agent_ids]
    rets = []
    for t in texts:
        if isinstance(t, str) and not t.lstrip().startswith("Async agent launched"):
            m = re.search(r"<result>(.*?)</result>", t, re.S)
            rets.append(m.group(1) if m else t)
    return rets


def has_links_block(ret):
    """El RETURN trae el bloque: la cabecera LINKS_MARK seguida de al menos una línea-link."""
    m = LINKS_RE.search(ret)
    return bool(m) and any(LINK_LINE.match(l) for l in ret[m.end():].split("\n"))


def is_courier_launch(inp):
    """Lanzamiento de un courier: el tipo `adcm-toolkits:courier`, o la ruta sin plugin (`general-purpose` +
    el brief del courier): `courier` en subagent_type/description, o `artifact-courier` en los primeros 600 del prompt."""
    probe = (str(inp.get("subagent_type") or "") + " " + str(inp.get("description") or "")).lower()
    return "courier" in probe or "artifact-courier" in str(inp.get("prompt") or "")[:600].lower()


def parse_transcript(path):
    """Devuelve un dict: session_start, turn_start, publishes, last_text, delivered, pending, ran, running, return_ts.
    publishes: lista de (epoch, realpath, url) de tool Artifact publish (toda la sesión).
    last_text: texto del ÚLTIMO mensaje del asistente del turno actual (desde el último prompt
    humano; los bloques `text` se agrupan por message.id): es el que ve el dueño y el único que se juzga.
    delivered: RETURNs de este turno con bloque de links (ver entry_returns / has_links_block).
    pending: hay más couriers lanzados (is_courier_launch) que RETURNs de courier (con bloque o con cabecera
    COURIER); ran: volvió un RETURN con cabecera COURIER pero sin bloque (corrió y falló); running: hay más
    Agent/Task lanzados este turno que RETURNs de cualquier sub-agente (alguno sigue en vuelo);
    return_ts: sello del último RETURN que entregó el bloque (None si no hay o no trae timestamp)."""
    session_start = turn_start = None
    publishes, agent_ids = [], set()
    delivered, ran, last_key, last_parts = [], False, None, []
    agents, couriers, n_returns, n_courier_returns, return_ts = set(), set(), 0, 0, None
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh):
            try:
                e = json.loads(line)
            except Exception:
                continue
            if not isinstance(e, dict):
                continue
            ts = iso_to_epoch(e.get("timestamp"))
            if is_human_prompt(e):
                if ts is not None:
                    if session_start is None:
                        session_start = ts
                    turn_start = ts
                delivered, ran, last_key, last_parts = [], False, None, []
                agents, couriers, n_returns, n_courier_returns, return_ts = set(), set(), 0, 0, None
                continue
            for ret in entry_returns(e, agent_ids):
                n_returns += 1
                if has_links_block(ret):
                    delivered.append(ret)
                    n_courier_returns += 1
                    if ts is not None:
                        return_ts = ts if return_ts is None else max(return_ts, ts)
                elif COURIER_HEAD.search(ret):
                    ran = True
                    n_courier_returns += 1
            if e.get("type") != "assistant":
                continue
            message = e.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            key = (message.get("id") if isinstance(message, dict) else None) or e.get("uuid") or n
            for b in content or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    inp = b.get("input")
                    inp = inp if isinstance(inp, dict) else {}
                    if b.get("name") == "Artifact":
                        action = inp.get("action") or "publish"
                        fp = inp.get("file_path")
                        if action == "publish" and fp and ts is not None:
                            publishes.append((ts, real(fp), inp.get("url")))
                    elif b.get("name") in ("Agent", "Task"):
                        agent_ids.add(b.get("id"))
                        agents.add(b.get("id") or n)
                        if is_courier_launch(inp):
                            couriers.add(b.get("id") or n)
                elif b.get("type") == "text":
                    if key != last_key:
                        last_key, last_parts = key, []
                    last_parts.append(b.get("text") or "")
    return {"session_start": session_start, "turn_start": turn_start, "publishes": publishes,
            "last_text": "\n".join(last_parts), "delivered": delivered, "ran": ran and not delivered,
            "pending": len(couriers) > n_courier_returns, "running": len(agents) > n_returns,
            "return_ts": return_ts}


def module_root(reg_dir, rel_file, markers):
    d = os.path.dirname(os.path.join(reg_dir, rel_file))
    while True:
        if any(os.path.exists(os.path.join(d, m)) for m in markers):
            return d
        if real(d) == real(reg_dir) or len(d) <= len(reg_dir):
            return reg_dir
        d = os.path.dirname(d)


def normalize_markers(value):
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)) and value:
        return tuple(str(m) for m in value)
    return DEFAULT_MARKERS


def check(hook_input):
    cwd = hook_input.get("cwd") or os.getcwd()
    transcript = hook_input.get("transcript_path")
    if not transcript or not os.path.isfile(os.path.expanduser(transcript)):
        return [], None, False
    registries = find_registries(cwd)
    if not registries:
        return [], None, False
    t = parse_transcript(os.path.expanduser(transcript))
    session_start, turn_start, publishes, last_text = t["session_start"], t["turn_start"], t["publishes"], t["last_text"]
    returns, pending, ran, running, return_ts = t["delivered"], t["pending"], t["ran"], t["running"], t["return_ts"]
    if turn_start is None:
        return [], None, False

    now = time.time()
    stale = []
    union, all_missing = [], []  # módulos que cierran en este turno: links requeridos y faltantes
    marker_mods = []  # módulos cuyo doc de cierre (close_markers) cambió en este turno
    after_mods = []  # ...y cambió DESPUÉS del último RETURN del courier que entregó (la entrega ya no lo cubre)
    ret_text = "\n".join(returns)
    # Entrega = un RETURN del courier con bloque de links, o un publish de la sesión principal este turno.
    delivered = bool(returns) or any(t >= turn_start for t, p, u in publishes)
    for reg_dir, data in registries:
        markers = normalize_markers(data.get("close_markers"))
        entries = [
            a for a in data.get("artifacts") or []
            if isinstance(a, dict)
            and isinstance(a.get("file"), str) and a["file"]
            and isinstance(a.get("url"), str) and a["url"]
        ]
        by_module = {}
        for a in entries:
            abs_file = real(os.path.join(reg_dir, a["file"]))
            a["_abs"] = abs_file
            a["_module"] = module_root(reg_dir, a["file"], markers)
            by_module.setdefault(a["_module"], []).append(a)
            if not os.path.isfile(abs_file):
                continue
            mtime = os.path.getmtime(abs_file)
            a["_mtime"] = mtime
            # Un publish cuenta por path O por URL canónica (un file_path relativo en
            # la llamada al tool no siempre resuelve al mismo realpath desde el hook).
            pubs = [t for t, p, u in publishes if p == abs_file or (u and u == a["url"])]
            last_pub = max(pubs, default=None)
            # Sellos `published_at` de toda familia (canónica + por cuenta). Uno futuro (editado
            # a mano o reloj corrido) no es evidencia — de lo contrario un published_at lejano
            # apagaría la revisión de frescura.
            reg_pubs = [e for e in (iso_to_epoch(v) for v in family_values(a, "published_at"))
                        if e is not None and e <= now + CLOCK_SKEW]
            if mtime > now + CLOCK_SKEW:
                # mtime futuro (reloj corrido, restore de backup, touch -t): no es
                # comparable — un publish de esta sesión (o un sello del courier de esta
                # sesión) lo da por fresco; sin evidencia sigue contando como stale para
                # no perder la garantía.
                sealed_now = any(e >= session_start for e in reg_pubs)
                if last_pub is None and not sealed_now and mtime >= session_start:
                    stale.append((a, abs_file))
                continue
            if mtime < session_start:
                continue
            if last_pub is not None and last_pub >= mtime:
                continue  # publicado desde la sesión principal después del último cambio
            if any(e >= mtime for e in reg_pubs):
                continue  # sello del courier (de cualquier cuenta) posterior al último cambio
            stamps = {h for h in map(norm_sha, family_values(a, "sha256")) if h}
            if stamps and file_sha256(abs_file) in stamps:
                continue  # contenido idéntico al publicado (en alguna cuenta): el mtime nuevo no importa
            stale.append((a, abs_file))

        def touched_this_turn(p):
            # mtime futuro (más allá del skew) no es evidencia de actividad del turno:
            # sin este guard, un archivo con reloj corrido marca "cerrando" cada turno.
            if not os.path.isfile(p):
                return False
            mt = os.path.getmtime(p)
            return turn_start <= mt <= now + CLOCK_SKEW

        for mod, arts in by_module.items():
            closing = marker_touched = False
            for m in markers:
                mp = os.path.join(mod, m)
                if touched_this_turn(mp):
                    closing = marker_touched = True
                    if return_ts is not None and os.path.getmtime(mp) > return_ts + RETURN_SKEW and mod not in after_mods:
                        after_mods.append(mod)
            if marker_touched:
                marker_mods.append(mod)
            for a in arts:
                if touched_this_turn(a["_abs"]):
                    closing = True
                if any((p == a["_abs"] or (u and u == a["url"])) and t >= turn_start for t, p, u in publishes):
                    closing = True
            # Las filas del bloque que trae el RETURN se exigen aunque su módulo no se haya tocado:
            # un courier que solo republica deja la unión vacía si solo se mira lo que cambió.
            required = [a for a in arts if any(u in ret_text for u in urls_of(a))
                        or (closing and a.get("in_close_block", True))]
            if not delivered or not required:
                continue
            for a in required:
                if all(a["url"] != x["url"] for x in union):
                    union.append(a)
            missing = [a for a in required if not any(u in last_text for u in urls_of(a))]
            if missing:
                all_missing.append((mod, missing))

    # Un sub-agente en vuelo (courier u otro) despertará un stop nuevo con su RETURN: ahí se vuelve a revisar.
    if marker_mods and not pending and not running:
        if not delivered and not ran:
            return stale, {"no_courier": marker_mods}, pending
        if after_mods:
            return stale, {"no_courier": after_mods, "after_return": True}, pending
    links = None
    if union:
        # Un solo mensaje, un solo bloque: se evalúa la unión de todos los módulos que
        # cierran, así dos módulos en el mismo turno no se estorban entre sí.
        probs = []
        if not all_missing:
            probs = links_format_problems(last_text, union) + local_link_problems(last_text)
        if all_missing or probs:
            links = {"union": union, "missing": all_missing, "probs": probs}
    return stale, links, pending


def urls_of(a):
    """La `url` de la fila más todo `url_<cuenta>`: una sesión bajo otra cuenta pega su propio bloque."""
    vals = [a.get("url")] + [v for k, v in a.items() if isinstance(k, str) and k.startswith("url_")]
    return [v for v in vals if isinstance(v, str) and v]


LINK_LINE = re.compile(r"^\s*(?:[-*•]\s*)?\[[^\]]+\]\(\S+\)\s*$")


def links_format_problems(turn_text, required):
    """Formato del bloque final (regla del dueño, 28-ago-2026): los links son las ÚLTIMAS líneas del
    mensaje, uno por línea como link Markdown `- [emoji Título](url)`; nada después del
    último link; nunca varias URLs en una línea. Se evalúa la COLA del texto (el bloque =
    corrida de líneas-link que termina en la última línea con una URL requerida), así una
    mención en prosa más arriba no cuenta ni estorba. Devuelve lista de problemas."""
    urls = [u for a in required for u in urls_of(a)]
    lines = [l.rstrip() for l in turn_text.rstrip().split("\n")]
    hits = [i for i, l in enumerate(lines) if any(u in l for u in urls)]
    if not hits:
        return []
    last = hits[-1]
    probs = []
    after = [l.strip() for l in lines[last + 1:] if l.strip()]
    if after:
        probs.append("hay texto DESPUÉS del último link (nada va después): " + " | ".join(a[:60] for a in after[:2]))
    j = last
    while j - 1 >= 0 and (LINK_LINE.match(lines[j - 1]) or not lines[j - 1].strip()):
        j -= 1
    block = lines[j:last + 1]
    for l in block:
        if l.strip() and not LINK_LINE.match(l):
            probs.append("línea del bloque que no es un link Markdown `- [Título](url)`: " + l.strip()[:80])
        if sum(l.count(u) for u in urls) > 1:
            probs.append("varios links en la misma línea (uno por línea): " + l.strip()[:80])
    block_text = "\n".join(block)
    for a in required:
        if not any(u in block_text for u in urls_of(a)):
            probs.append(f"{a.get('title') or a['file']} no está en el bloque final (aparece más arriba, en prosa)")
    return probs


# Rangos privados de la RFC 1918: lo que sale de `ipconfig getifaddr en0` en casa.
LAN_URL = re.compile(
    r"https?://(?:"
    r"10(?:\.\d{1,3}){3}"
    r"|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}"
    r"|192\.168(?:\.\d{1,3}){2}"
    r")(?::(?P<port>\d{1,5}))?"
)
LOCAL_URL = re.compile(r"https?://(?:localhost|127\.0\.0\.1)(?::(?P<port>\d{1,5}))?")


def local_link_problems(turn_text):
    """Regla del dueño (1-sep-2026): un link con IP de LAN sirve para abrirlo desde el cel,
    pero él valida desde iTerm en la Mac — ahí la que funciona es `localhost`. Nunca una
    sin la otra. Además la IP de LAN caduca (cambia de red y el link llega muerto), así
    que `localhost` es la que siempre sigue viva. Se exige por PUERTO: si entregas
    192.168.x.y:3000, tiene que estar también localhost:3000."""
    lan = {m.group("port") or "80" for m in LAN_URL.finditer(turn_text)}
    if not lan:
        return []
    local = {m.group("port") or "80" for m in LOCAL_URL.finditer(turn_text)}
    return [
        "el puerto {p} se entregó SOLO con IP de LAN: falta su gemelo "
        "`http://localhost:{p}/` en el mismo bloque (el dueño valida desde una terminal en la Mac; "
        "la IP de LAN además caduca al cambiar de red)".format(p=p)
        for p in sorted(lan - local)
    ]


def safe_rel(path):
    try:
        return os.path.relpath(path, os.path.expanduser("~"))
    except Exception:
        return path


def main():
    try:
        hook_input = json.load(sys.stdin)
        if not isinstance(hook_input, dict):
            hook_input = {}
    except Exception:
        hook_input = {}
    try:
        stale, links, pending = check(hook_input)
        if not stale and not links:
            return 0
        if pending:
            return 0  # el courier ya está en camino: su RETURN despertará un stop nuevo que vuelve a revisar

        lines = ["⛔ artifact-guard: el cierre está incompleto."]
        if stale:
            lines.append("Artifacts DESACTUALIZADOS (cambiaron en disco y no hay publish ni sello posterior):")
            for a, abs_file in stale:
                mt = datetime.fromtimestamp(a.get("_mtime", os.path.getmtime(abs_file)), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
                sello = a.get("published_at") or "sin sello"
                lines.append(f"  • {a['file']} (mtime {mt} · published_at {sello})")
            lines.append(
                "  No la leas ni la publiques desde esta sesión: delega el cierre en UN sub-agente "
                "artifact-courier (tipo `adcm-toolkits:courier`; sin el plugin: Agent general-purpose, model \"sonnet\"; brief = "
                "templates/courier-brief.md del skill adcm-toolkits:artifact-courier). Él republica, "
                "sella el registro y devuelve el bloque de links."
            )
        if links and "no_courier" in links:
            lines.append(
                "Cambiaron docs de cierre sin courier: delega el cierre en adcm-toolkits:courier "
                "(regen + republish); no pegues links a mano."
                + (" (docs cambiaron después del RETURN del courier)" if links.get("after_return") else "")
            )
        elif links:
            if links["probs"]:
                lines.append("El BLOQUE DE LINKS existe pero NO cumple formato/posición:")
                for pr in links["probs"]:
                    lines.append(f"  • {pr}")
                lines.append("Regla: las ÚLTIMAS líneas del mensaje son la lista de links, uno por línea, tocables en el cel; rutas/hashes ARRIBA.")
            else:
                lines.append("Falta el BLOQUE DE LINKS al final del mensaje. Links que faltan, por módulo:")
                for mod, missing in links["missing"]:
                    lines.append(f"  • módulo {safe_rel(mod)}: " + ", ".join(str(a.get("title") or a["file"]) for a in missing))
                lines.append(
                    "Pégalo como lista Markdown plana — NUNCA dentro de un bloque de código, "
                    "backticks ni sangría de 4 espacios (en el cel eso se ve como código muerto, "
                    "no clickeable)."
                )
            lines.append("Pega el bloque del último RETURN del courier, tal cual, como últimas líneas.")
        lines.append("Corrige lo anterior (delega en el courier; el bloque de links es el de su RETURN) y vuelve a cerrar.")
        reason = "\n".join(lines).replace(LINKS_MARK, "LINKS")  # el guard nunca imprime el marcador: no se dispara solo

        if hook_input.get("stop_hook_active"):
            print(json.dumps({"systemMessage": "artifact-guard: cierre con pendientes (ya se bloqueó una vez; no se vuelve a bloquear).\n" + reason}, ensure_ascii=False))
            return 0
        print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
        return 0
    except Exception:
        # Este hook nunca rompe una sesión: cualquier fallo interno cede el paso.
        return 0


if __name__ == "__main__":
    sys.exit(main())
