# Protocolo: Standard

Flujo default del Council. No requiere flags. Es el modo más rápido y suficiente para 90% de las decisiones.

## Pasos

1. Parsear pregunta del usuario y flags (`--context` si está).
2. Cargar hooks de contexto si aplica.
3. Convocar a los 5 asesores en paralelo (Claude Code) o secuencialmente con aislamiento de contexto (claude.ai / Cowork).
4. El Outsider NUNCA recibe contexto inyectado, aunque haya `--context`. Los otros 4 sí.
5. Convocar al Chairman con las 5 respuestas + la pregunta original.
6. Presentar al usuario: veredicto del Chairman primero, respuestas individuales después.

## Lo que NO se hace en Standard

- No hay Stage 2 (cross-review).
- No hay segundas rondas.
- No hay "consenso forzado". Si el Chairman tiene que tomar postura sin consenso, lo hace.

## Cuándo usar

- Decisiones de táctica de día a día.
- Cuestiones con bajo costo de error.
- Cuando hay límites de tiempo o tokens.
- Cuando el usuario no especificó `--deep`.
