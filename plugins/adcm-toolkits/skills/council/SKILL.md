---
name: council
description: >
  Convenes a council of 5 advisors (Strategist, Adversary, Outsider, Operator,
  Futurist) plus a Chairman to deliberate on a decision and deliver an
  actionable verdict. Inspired by Karpathy's LLM Council and Oli Limán's Claude
  Council. Use when the user says 'ask the council', 'council:', 'convene the
  council', 'consult the council', 'consejo:', 'pregúntale al consejo',
  'convoca al consejo', 'consulta al consejo', 'qué dice el council', or any
  variation requesting multi-perspective deliberation on a technical, business,
  personal, or academic decision (Se activa con esos triggers). Supports a
  context flag (double-dash + the word context + comma-separated hook names that
  map to files in contexts/) to inject domain context into 4 of the 5 advisors.
  Supports a deep flag (double-dash + deep) to enable Stage 2 cross-review,
  currently a stub. Output language is auto-detected from the user's prompt
  (English or Spanish).
compatibility: >
  No runtime dependencies. Markdown-only skill read by Claude. In Claude Code,
  parallel advisor execution uses the built-in Task tool; in claude.ai/Cowork it
  falls back to sequential context-isolated reads. Works in Claude Code, Cowork,
  and claude.ai.
---

# The Council — Skill de Deliberación Multi-Asesor

Inspirado en el [LLM Council de Andrej Karpathy](https://github.com/karpathy/llm-council) y en el [Claude Council de Oli Limán](https://www.linkedin.com/in/olilo/), pero rediseñado para ser un **consejo asesor accionable** que vive como skill nativo de Claude y funciona en Claude Code, Cowork y claude.ai.

Cuando se activa, Claude convoca 5 asesores especializados que responden en paralelo (o secuencialmente con aislamiento de contexto, según el entorno), opcionalmente hacen cross-review, y un Chairman sintetiza un veredicto accionable.

---

## Cuándo se activa

Triggers explícitos del usuario:

- `ask the council: <pregunta>`
- `consejo: <pregunta>`
- `pregúntale al consejo <pregunta>`
- `convoca al consejo <pregunta>`
- `council: <pregunta>`
- Cualquier frase similar que indique "quiero deliberación multi-perspectiva sobre esto"

Flags opcionales:

- `--context <hook>` o `--context <hook1,hook2>` — inyecta contexto de negocio a 4 de los 5 asesores (el Outsider siempre es ciego al contexto por diseño). El nombre del hook corresponde a un archivo que el usuario coloca en `contexts/<hook>.md`. Hooks disponibles: ver carpeta `contexts/`.
- `--deep` — activa Stage 2 (cross-review entre asesores). **Actualmente es un stub** — el flag se acepta pero solo deja una nota en el output. Se implementará en una iteración futura.

Ejemplos:

```
ask the council: ¿debería contratar a una segunda persona para mi equipo?
consejo --context example: ¿lanzo el nuevo producto ya o espero a validar 10 clientes?
council --context example: ¿cómo divido mi semana entre dos prioridades?
ask the council --deep --context example: <pregunta grande>
```

(`example` corresponde al archivo de muestra `contexts/example.md`. Reemplázalo por tus propios hooks — ver "Hooks de contexto" más abajo.)

---

## Idioma del output

**Detecta automáticamente** el idioma del prompt del usuario. Si el usuario escribe en español, todo el output (asesores + Chairman) va en español. Si escribe en inglés, todo va en inglés. No mezclar idiomas dentro de una misma deliberación.

---

## Flujo de ejecución

### Paso 1 — Parsear la invocación

1. Extraer la **pregunta** (todo lo que va después del trigger y de los flags).
2. Detectar flags presentes:
   - `--context <lista>` → leer cada hook en `contexts/<hook>.md` y mantener su contenido como "contexto inyectable" para los asesores con contexto habilitado.
   - `--deep` → marcar para activar Stage 2 (por ahora stub).
3. Detectar idioma del prompt.

Si un hook de contexto referenciado no existe en `contexts/`, avisar al usuario y proceder sin contexto (no fallar).

### Paso 2 — Convocar a los 5 asesores

Cada asesor se ejecuta como un **bloque de pensamiento aislado** — Claude debe procesar su prompt sin que el output de los otros asesores lo contamine. En Claude Code esto se hace con sub-agentes paralelos vía el tool `Task`. En claude.ai/Cowork se hace secuencialmente pero leyendo el prompt de cada asesor por separado antes de redactar su respuesta.

Para cada asesor:

1. Leer su prompt desde `agents/<nombre>.md`.
2. Si el asesor recibe contexto (todos excepto el Outsider) y hay `--context` activo: inyectar el contenido de los hooks como sección "## Contexto adicional" al inicio del prompt del asesor.
3. Pasarle la pregunta del usuario.
4. Obtener su respuesta (forma estructurada que su propio prompt define).

Los 5 asesores son:

- **Strategist** (`agents/strategist.md`) — Reformula el problema, identifica el verdadero "job to be done".
- **Adversary** (`agents/adversary.md`) — Busca killer assumptions y modos de falla.
- **Outsider** (`agents/outsider.md`) — Ciego al contexto. Ve la pregunta como un extraño y aporta perspectiva lateral.
- **Operator** (`agents/operator.md`) — Aterriza la decisión en el siguiente paso accionable.
- **Futurist** (`agents/futurist.md`) — Proyecta a 6, 18, 60 meses. Identifica trayectorias.

### Paso 3 — Stage 2: Cross-review (opcional, actualmente stub)

Si `--deep` está activo: **por ahora**, no ejecutar cross-review real. Solo añadir al output del Chairman una nota:

> *Stage 2 (cross-review) está marcado como stub en esta versión del Council. Cuando se implemente, cada asesor recibirá las respuestas anonimizadas de los otros 4 e identificará el insight más fuerte, el más débil, y refinará su propia respuesta.*

(Cuando se implemente, leer `protocols/deep.md`.)

### Paso 4 — Convocar al Chairman

Leer `chairman.md`. Pasarle:

1. La pregunta original del usuario.
2. Las 5 respuestas de los asesores.
3. (Si Stage 2 estuviera activo) los reviews. Por ahora, solo las 5 respuestas.

El Chairman produce el output final estructurado (ver `chairman.md` para el formato exacto).

### Paso 5 — Presentar al usuario

Estructura del output al usuario:

```
# Veredicto del Council

[Output del Chairman — veredicto, razón, próximo paso, killer assumption, disidencias]

---

<details>
<summary>Ver respuestas individuales de los 5 asesores</summary>

## Strategist
[respuesta]

## Adversary
[respuesta]

## Outsider
[respuesta]

## Operator
[respuesta]

## Futurist
[respuesta]

</details>
```

En claude.ai, donde `<details>` puede no plegarse, presentar las respuestas individuales después del veredicto del Chairman con encabezados claros. **Lo importante es que el veredicto del Chairman vaya primero y arriba** — esa es la información accionable.

---

## Diseño: por qué el Outsider es ciego al contexto

Por diseño, el Outsider **nunca recibe los hooks de contexto inyectados**, aunque el usuario active `--context`. Su valor es ver la pregunta como un extraño que no sabe nada del negocio. Si conociera el contexto, sería redundante con los otros 4 asesores. Esto es deliberado, no un bug.

---

## Hooks de contexto

Los hooks viven en `contexts/<nombre>.md`. Cada uno es un resumen denso (300-500 palabras max) de un dominio (negocio, proyecto, persona) que Claude puede inyectar a 4 de los 5 asesores cuando el usuario activa `--context <nombre>`.

**Esta es la parte que tú personalizas.** El framework no trae hooks de negocio reales — eso sería tu información privada. Para usar contexto:

1. Crea un archivo en `contexts/<tu-nombre>.md` (p. ej. `contexts/miempresa.md`).
2. Invoca con `--context tu-nombre`.

Incluido en esta versión:

- `contexts/example.md` — un hook de muestra sanitizado (empresa ficticia) que ilustra el formato. Cópialo y adáptalo, o bórralo.

Para las reglas de escritura de un hook, ver `contexts/README.md`.

---

## Notas para Claude (operativas)

1. **No improvises los asesores.** Sigue el formato de salida que cada `agents/*.md` define. Si el prompt del Strategist dice "responde en 3 secciones: Reformulación / Insight central / Trampa típica", entonces el Strategist responde exactamente así.

2. **Mantén el aislamiento de contexto.** Antes de redactar la respuesta del asesor N, no leas las respuestas N-1, N-2, etc. Cada asesor responde como si fuera el único respondiendo. (Esto es lo que mata la sicofancia.)

3. **El Chairman sí ve todo.** Su trabajo es justamente sintetizar las 5 respuestas y tomar postura.

4. **No expandir la pregunta.** Si el usuario hace una pregunta corta, no la "rellenes" antes de pasarla a los asesores. Los asesores trabajan con la pregunta tal cual.

5. **Detección de idioma:** mira el prompt del usuario, no los nombres de los archivos. Los prompts de los asesores están escritos en español pero deben responder en el idioma del usuario.

6. **Si el usuario hace una pregunta sin trigger explícito pero pide "consejo"**, asume que quiere el Council y procede.

7. **No agregues asesores ni cambies el número.** El Council son 5 + Chairman. Punto.
