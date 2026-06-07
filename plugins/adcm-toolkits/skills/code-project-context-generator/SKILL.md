---
name: code-project-context-generator
description: >
  Escanea un proyecto de código, arma un mapa estructurado de su arquitectura y genera
  un skill instalable tipo `code-project-context:[project-name]` con lazy-loading (el
  SKILL.md resultante carga solo el índice y los detalles por carpeta se leen on-demand).
  Se activa cuando el usuario pida 'crear contexto de proyecto', 'nuevo proyecto de código',
  'escanear repo', 'mapear arquitectura', 'code project context', 'analizar proyecto',
  'cargar contexto de código', 'nuevo repo', 'registrar proyecto', 'crear skill de proyecto',
  'project init', 'architecture map', 'dame contexto de otro proyecto', 'tengo otro repo',
  'mapear código', 'code map', o cualquier variación donde quiera que Claude entienda y
  recuerde la arquitectura de un proyecto de código para futuras sesiones de trabajo.
compatibility: >
  Python 3 (solo stdlib, sin dependencias externas) para el scanner.
---

# Code Project Context Generator

Este skill guía el proceso de analizar un proyecto de código y generar un skill de contexto instalable tipo `code-project-context:[project-name]`. El skill resultante está diseñado con **lazy-loading**: su SKILL.md solo carga el mapa de alto nivel (árbol + short descriptions por carpeta + stack + entry points), y los detalles de cada carpeta se leen bajo demanda con Read cuando la sesión de trabajo lo requiera. Esto mantiene el contexto ligero mientras permite profundizar donde sea necesario.

---

## Propósito

Resolver el problema de "empezar a trabajar sobre un proyecto sin tener que explicarle a Claude qué hace cada carpeta, qué stack usa, cuál es el entry point y cuáles son las convenciones". Después de correr este skill una vez sobre un proyecto, las sesiones futuras pueden invocar el skill resultante y Claude ya sabrá dónde está cada cosa.

---

## Dependencias

- Python 3 (solo stdlib, sin paquetes externos) para el scanner.
- Script bundleado en este skill: `scripts/scan_project.py` (relativo al root del skill).
- Cuando se necesite un path absoluto, el skill vive en
  `${CLAUDE_PLUGIN_ROOT}/skills/code-project-context-generator/`, así que el scanner está en
  `${CLAUDE_PLUGIN_ROOT}/skills/code-project-context-generator/scripts/scan_project.py`.

---

## Flujo de Trabajo

### PASO 0: Obtener el path del proyecto

El skill necesita el path absoluto del proyecto. Estrategia:

1. **Si hay un directorio de trabajo ya abierto/seleccionado en la sesión**, preguntar al usuario si ese es el proyecto a analizar.
2. **Si no hay carpeta seleccionada**, pedir al usuario que indique el root del proyecto (o usar el mecanismo de selección de directorio disponible en el entorno).
3. **Si el usuario prefiere pegar un path manual**, aceptarlo tal cual (útil para proyectos fuera del directorio de trabajo).

Verifica que el path exista y que tenga indicadores típicos de proyecto (`.git/`, `package.json`, `composer.json`, `pyproject.toml`, `requirements.txt`, `Cargo.toml`, `go.mod`, etc.). Si no hay ninguno, confirmar con el usuario que es realmente un proyecto de código antes de seguir.

### PASO 1: Recolectar metadata mínima

Usa AskUserQuestion para capturar lo que el scanner no puede inferir:

**Ronda 1 — Identidad del proyecto:**

- ¿Cómo se llama el proyecto? (nombre corto para el slug del skill, ej: `hub-plus`, `schools-backend`, `ancefoodtrailers-web`)
- ¿Hay algún nombre interno/comercial distinto al del repo?
- ¿Qué hace el proyecto en una oración? (valor de negocio, no tech)
- ¿Es un proyecto propio, de cliente, open source, o experimental?

**Ronda 2 — Contexto operativo (opcional, si aplica):**

- ¿Hay cliente asociado? (vincularlo con algún `client-context-*` existente si aplica)
- ¿Es frontend, backend, fullstack, mobile, CLI, library, infra?
- ¿Tiene deploy/entorno live? (URLs, staging, prod)
- ¿Hay documentación externa relevante? (Notion, Confluence, README remoto)

Si el usuario ya dio parte de esta info al invocar el skill, no preguntes de nuevo — extráela del contexto.

### PASO 2: Escanear el proyecto

El scanner está bundleado en este skill en `scripts/scan_project.py` (relativo al root del skill).
Ejecútalo apuntando al path del proyecto. Antes de correrlo, verifica las precondiciones:

```bash
# 1. Verificar que Python 3 esté disponible
command -v python3 >/dev/null 2>&1 || { echo "Error: se requiere Python 3 (no encontrado en PATH)."; exit 1; }

# 2. Resolver el scanner. En un plugin instalado usar ${CLAUDE_PLUGIN_ROOT};
#    como fallback, una ruta relativa al root del skill.
SCANNER="${CLAUDE_PLUGIN_ROOT:-.}/skills/code-project-context-generator/scripts/scan_project.py"
[ -f "$SCANNER" ] || SCANNER="scripts/scan_project.py"
[ -f "$SCANNER" ] || { echo "Error: no se encontró scan_project.py."; exit 1; }

# 3. Verificar que el path del proyecto exista y sea legible
PROJECT_PATH="<PROJECT_PATH>"
[ -d "$PROJECT_PATH" ] && [ -r "$PROJECT_PATH" ] || { echo "Error: el path '$PROJECT_PATH' no existe o no es legible."; exit 1; }

# 4. Escanear (el JSON va a un directorio temporal; ajusta el destino a tu <output-dir>)
python3 "$SCANNER" "$PROJECT_PATH" --output "${TMPDIR:-/tmp}/project_scan.json"
```

> Nota: el scanner ya valida internamente que el root exista (lanza `FileNotFoundError`).
> Las comprobaciones de arriba dan mensajes claros antes de invocarlo.

El scanner produce un JSON con:

- `meta` — nombre del root, tamaño, archivos escaneados
- `stack` — lenguajes detectados, frameworks, runtimes, gestor de paquetes
- `dependencies` — lista de deps críticas con versión (Node, PHP, Python, Go, Rust)
- `entry_points` — scripts en package.json, artisan commands, main modules, Dockerfiles CMD, scripts de CI
- `tree` — árbol de carpetas del proyecto con conteos y pesos
- `folders` — cada carpeta con ruta, cantidad de archivos, tipos predominantes y un hash-tag tentativo de propósito (routing, models, services, tests, config, docs, etc.)
- `configs` — archivos de configuración encontrados (`.env.example`, `docker-compose.yml`, CI, linters)
- `conventions` — pistas detectadas (MVC, feature-based, monorepo, workspaces, etc.)
- `domain_terms` — términos que aparecen repetidamente en nombres de archivos/clases (candidatos a glosario)

### PASO 3: Revisar con el usuario y completar huecos

Presenta al usuario un resumen del escaneo:

- Stack detectado
- Top 10 carpetas por tamaño/relevancia
- Entry points encontrados
- Términos de dominio candidatos

Pregunta lo que el scanner no puede saber:

- Para las carpetas ambiguas (las que tienen un propósito no-obvio), pedir al usuario que describa qué hacen en una línea.
- Confirmar o ajustar los términos del glosario de dominio.
- Identificar "zonas peligrosas" o módulos críticos que Claude debe tocar con cuidado.

### PASO 4: Generar el skill con lazy-loading

Construir la estructura de output:

```
code-project-context-[project-name]/
├── SKILL.md                    # Índice alto-nivel (SIEMPRE se carga)
├── architecture.md             # Árbol completo + short descriptions (on-demand)
├── stack.md                    # Stack, deps, versiones (on-demand)
├── entry-points.md             # Cómo arrancar, rutas, build/run/test (on-demand)
├── conventions.md              # Patrones de código detectados (on-demand)
├── glossary.md                 # Términos de dominio (on-demand)
└── folders/
    ├── [folder-1].md           # Detalle de src/, app/, etc. (on-demand)
    ├── [folder-2].md
    └── ...
```

**Regla de oro:** el SKILL.md NUNCA debe tener todos los detalles inline. Solo debe tener:

1. Identidad del proyecto (1 párrafo)
2. Stack en una línea (ej: `Node 20 • Next.js 14 • TypeScript • Prisma • PostgreSQL`)
3. Mapa de alto nivel (árbol hasta 2 niveles con 1 línea por carpeta)
4. Índice de archivos detallados: "Para detalles de X, leer `architecture.md`. Para stack completo, leer `stack.md`. Para la carpeta `src/api/`, leer `folders/src-api.md`."
5. Reglas para Claude sobre cómo usar este contexto

Usa los templates en `templates/` (relativo al root del skill) como base. Los templates incluyen placeholders que se rellenan con los datos del scanner.

### PASO 5: Empaquetar e instalar

1. Guardar todo bajo `<output-dir>/code-project-context-[project-name]/`, donde `<output-dir>` es
   el directorio de salida que use el entorno (p. ej. el directorio de outputs de la sesión o un
   path elegido por el usuario).
2. (Opcional) Si el entorno provee un script de empaquetado de skills, úsalo.
3. Zipearlo con extensión `.skill` para que el entorno lo muestre como instalable:
   ```bash
   OUT_DIR="<output-dir>"
   SLUG="code-project-context-[project-name]"
   ( cd "$OUT_DIR" && zip -r "$SLUG.skill" "$SLUG/" )
   ```
4. Entregar el archivo `.skill` resultante al usuario por el mecanismo disponible en el entorno.

---

## Estructura del SKILL.md resultante (template)

El SKILL.md del skill generado debe seguir este esqueleto estricto para mantener el contexto ligero:

```markdown
---
name: code-project-context:[project-name]
description: >
  Carga el contexto de arquitectura del proyecto [Name]. Carga solo el mapa de alto nivel — los
  detalles de cada carpeta se leen on-demand con Read desde los archivos complementarios en el
  mismo directorio.
  Se activa cuando el usuario mencione '[project-name]', '[aliases]', [triggers específicos del proyecto].
---

# [Project Name] — Contexto de Arquitectura

**Qué hace:** [1 oración de valor de negocio]
**Tipo:** [frontend/backend/fullstack/mobile/CLI/library]
**Cliente/Dueño:** [nombre o "propio"]
**Estado:** [activo / mantenimiento / archivado]

---

## Stack (one-liner)

[Lenguaje N.N] • [Framework N.N] • [Runtime] • [DB] • [otros críticos]

Para detalles completos: leer `stack.md`.

---

## Mapa de Alto Nivel

```
project-root/
├── src/              — código fuente principal
├── tests/            — test suites (unit + e2e)
├── docs/             — documentación interna
├── scripts/          — tareas administrativas y CI helpers
├── config/           — configuración por entorno
└── [otros]/          — [1 línea]
```

Para el árbol completo con profundidad: leer `architecture.md`.
Para detalles de una carpeta específica: leer `folders/[nombre].md`.

---

## Entry Points (resumen)

- **Arrancar dev:** `[comando]`
- **Build:** `[comando]`
- **Tests:** `[comando]`
- **Deploy:** [descripción breve]

Para rutas, APIs, y flujos completos: leer `entry-points.md`.

---

## Convenciones Clave

- [1 línea por convención: ej. "Controllers delgados, lógica en services/"]
- [1 línea: ej. "Tests viven junto al código en `*.test.ts`"]

Para el detalle completo: leer `conventions.md`.

---

## Glosario de Dominio (shortlist)

- **[Término 1]:** [1 línea]
- **[Término 2]:** [1 línea]

Para el glosario completo: leer `glossary.md`.

---

## Reglas Para Claude

1. **Carga perezosa:** NO leas todos los archivos complementarios al inicio. Lee solo los que la tarea actual requiera.
2. **Rutas:** Antes de tocar código, verifica la ubicación real con `Glob` o `Read`. El mapa es una referencia, no la verdad absoluta.
3. **Convenciones:** Respeta las convenciones detectadas. Si el código usa services/, no crees controladores gordos.
4. **Zonas peligrosas:** [módulos críticos que requieren cuidado extra — si aplica]
5. **Actualización:** Si descubres que el mapa está desactualizado, sugiere correr `code-project-context-generator` otra vez.
```

---

## Principios

- **Lazy-loading estricto:** el SKILL.md resultante debe ser corto (< 200 líneas). Todo el peso va a los archivos complementarios.
- **Short descriptions útiles:** cada carpeta del mapa debe tener 1 línea que responda "¿qué vive aquí y por qué me importaría?". Nada genérico tipo "source code folder".
- **Triggers generosos:** la descripción del skill resultante debe incluir el nombre del proyecto, aliases, rutas base, nombres de módulos clave — cualquier cosa que el usuario podría mencionar para traer contexto.
- **Agnóstico de stack:** el scanner detecta el stack, pero la lógica del skill no asume ninguno. Soporta Node/TS, PHP, Python, Go, Rust y cualquier mezcla.
- **Sin dump bruto:** no pegar el output crudo del scanner en el skill. Todo pasa por interpretación humana (o de Claude) para generar short descriptions útiles.
- **Vivo, no fósil:** el skill debe poder regenerarse fácil cuando el proyecto evolucione. Incluye al final del SKILL.md la fecha de último escaneo y un hint de cuándo re-correr.
