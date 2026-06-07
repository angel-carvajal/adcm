# Hooks de Contexto

Los hooks viven en este folder como archivos `.md`. Cada uno resume un dominio (negocio, proyecto, persona) que se puede inyectar a los asesores del Council cuando el usuario invoca con `--context <nombre>`.

## Sintaxis de invocación

```
ask the council --context example: <pregunta>
ask the council --context miempresa: <pregunta>
ask the council --context miempresa,otroproyecto: <pregunta>
```

El nombre del hook corresponde al nombre del archivo sin la extensión `.md`. `--context example` lee `contexts/example.md`. Tú agregas tus propios hooks creando archivos `.md` en este folder.

## Reglas de escritura de un hook

1. **Máximo 500 palabras.** Si es más largo, es para un skill de business-init, no para un hook del Council. Los hooks son el destilado táctico, no la enciclopedia.

2. **Estructura recomendada:**

   ```markdown
   # Context: <Nombre>
   
   ## Qué es
   1-3 oraciones. Identidad del negocio/proyecto/dominio.
   
   ## Modelo / Cómo opera
   3-6 oraciones. Cómo gana dinero, qué hace, para quién.
   
   ## Estado actual
   2-4 oraciones. Fase del negocio, qué funciona, qué está roto.
   
   ## Restricciones reales
   Lista corta. Lo que NO se puede hacer (financieras, legales, de capacidad).
   
   ## Apetito de riesgo
   1-2 oraciones. Cuánto está dispuesto a apostar el dueño en esta decisión.
   
   ## Lo que NO mencionar al exterior
   Lista corta. Info confidencial que el usuario protege.
   ```

3. **Sin floritura.** No es marketing. Es un cable de información para que los asesores tengan contexto real.

4. **Honestidad antes que aspiración.** Si el negocio está luchando, dilo. Si está creciendo, dilo. Los asesores aconsejan mejor con la realidad, no con la versión LinkedIn.

## Hooks incluidos

- `example.md` — hook de muestra sanitizado (empresa ficticia "Acme Widgets Co."). Sirve solo para mostrar el formato. Cópialo, adáptalo a tu dominio real, o bórralo. No metas información confidencial real en un repo público.

## Privacidad

Los hooks pueden contener información sensible de tu negocio. Si vas a publicar o compartir tu copia de este skill, **no incluyas tus hooks reales en `contexts/`** — mantenlos locales o en un repo privado. El framework público solo trae `example.md`.

## Recordatorio sobre el Outsider

El Outsider **nunca** recibe estos hooks, aunque el usuario los active. Eso es por diseño — su valor es ser ciego al contexto. No intentes "ayudarlo" pasándole el hook.
