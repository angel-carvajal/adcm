# Templates — code-project-context-generator

Estos templates son la base para generar el skill `code-project-context:[project-name]`. Cuando el flujo del generador llega al Paso 4, Claude toma cada template, rellena los placeholders `{{...}}` con datos del scan + respuestas del usuario, y los escribe al output del skill.

## Inventario

| Template | Destino en el skill generado | Qué contiene |
|----------|------------------------------|--------------|
| `SKILL.md.tmpl` | `SKILL.md` (root) | Índice de alto nivel — SIEMPRE se carga |
| `architecture.md.tmpl` | `architecture.md` | Árbol completo + short descriptions — on-demand |
| `stack.md.tmpl` | `stack.md` | Stack, deps, versiones, DB, testing — on-demand |
| `entry-points.md.tmpl` | `entry-points.md` | Comandos, rutas, flujos, jobs — on-demand |
| `conventions.md.tmpl` | `conventions.md` | Convenciones de código detectadas — on-demand |
| `glossary.md.tmpl` | `glossary.md` | Términos del dominio — on-demand |
| `folder.md.tmpl` | `folders/[slug].md` | Detalle de una carpeta específica — on-demand |

## Placeholders usados

Los placeholders tienen formato `{{NOMBRE_MAYUSCULAS}}` y son reemplazados por Claude al renderizar. Son descriptivos por diseño — no hay una lista rígida, Claude decide qué poner basándose en lo que el scanner extrajo y lo que el usuario aportó.

Placeholders comunes:

- `{{PROJECT_NAME}}` — nombre humano del proyecto
- `{{PROJECT_SLUG}}` — slug kebab-case para el nombre del skill
- `{{ONE_LINE_DESCRIPTION}}` — qué hace el proyecto en una oración de negocio
- `{{STACK_ONELINER}}` — stack resumido en una línea tipo `Node 20 • Next.js 14 • TypeScript • Prisma • PostgreSQL`
- `{{HIGH_LEVEL_TREE}}` — árbol hasta 2 niveles con 1 línea por carpeta
- `{{FULL_TREE}}` — árbol completo
- `{{ALIASES_LIST}}` — aliases y triggers adicionales separados por comas
- `{{SCAN_DATE}}` — fecha del escaneo en formato `YYYY-MM-DD`
- `{{ROOT_HINT}}` — path habitual donde vive el proyecto (si es recurrente)

## Filosofía

Los templates son guías, no camisas de fuerza. Si un proyecto no tiene base de datos, omite la sección de DB. Si no tiene CI/CD, omite esa parte. Es mejor tener un skill corto y útil que uno largo con secciones vacías "por completitud".

**Lo único que NO se puede cambiar:** el SKILL.md resultante tiene que respetar el patrón de lazy-loading. Nunca inlinear los detalles de cada carpeta en el SKILL.md — eso mata el punto del skill.
