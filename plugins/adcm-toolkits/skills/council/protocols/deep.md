# Protocolo: Deep (Stage 2 — Cross-review)

**Estado actual: STUB.** Esta versión del Council no ejecuta cross-review real. El flag `--deep` solo agrega una nota al output del Chairman explicando que Stage 2 está pendiente de implementación.

Este archivo documenta el **diseño objetivo** para cuando se implemente, no el comportamiento actual.

---

## Diseño objetivo (a implementar)

### Cuándo se activa
Cuando el usuario invoca el Council con el flag `--deep`. Ejemplo:

```
ask the council --deep: ¿debería contratar a una segunda persona para mi equipo?
ask the council --deep --context example: ¿debería contratar a una segunda persona para mi equipo?
```

### Cómo funcionará

Después de Stage 1 (los 5 asesores ya respondieron), antes del Chairman:

1. **Anonimizar las 5 respuestas.** Cada asesor recibe las respuestas de los otros 4 etiquetadas como "Asesor A / B / C / D" — sin saber cuál es el Strategist, Adversary, etc. (Esto es lo que Karpathy hace en LLM Council para matar la sicofancia: si no sabes quién dijo qué, no puedes estar de acuerdo por deferencia).

2. **Cada asesor responde a 3 preguntas:**
   - **Insight más fuerte que yo no vi:** ¿Cuál de las 4 respuestas trae algo que mi propio razonamiento no incluyó y que cambia mi postura?
   - **Insight más débil:** ¿Cuál de las 4 respuestas tiene una grieta lógica o un supuesto débil que puedo desmontar con evidencia?
   - **Refinamiento de mi propia respuesta:** A la luz de lo que leí, ¿qué corrijo, refuerzo, o abandono de mi respuesta original?

3. **El Chairman recibe ahora 5 respuestas originales + 5 reviews + 5 respuestas refinadas.** Su síntesis usa principalmente las refinadas, pero puede citar las originales si hubo un cambio importante (porque el cambio mismo es información).

### Costo

- Aproximadamente 2x los tokens y 2x el tiempo de Stage 1.
- Solo se justifica para decisiones de alto costo de error o alta ambigüedad.

### Output del Chairman en modo deep

El Chairman agrega una sección breve al final:

```
**Cambios tras cross-review:** [1-2 oraciones. Qué se modificó en el veredicto al hacer Stage 2. Si el veredicto no cambió, dilo — es información valiosa que el primer instinto era correcto.]
```

---

## Por qué es stub por ahora

Implementar cross-review aislado de contexto en claude.ai requiere coordinar lecturas secuenciales con anonimización limpia, lo cual añade complejidad operativa que no agrega valor hasta que el Council ya haya probado utilidad en Stage 1. Se implementará una vez confirmado que el flujo standard funciona bien en producción.
