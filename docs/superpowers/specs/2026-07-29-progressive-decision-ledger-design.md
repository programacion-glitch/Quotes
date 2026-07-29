# Decision Ledger + Análisis explicado — Diseño

**Fecha:** 2026-07-29
**Estado:** Aprobado en brainstorm (opción A de tres evaluadas) + requisitos de servicio agregados
**Alcance:** Progressive **y GEICO** desde el arranque + cambios al servicio (runner/email)

## Problema

Cada cotización nueva genera correcciones de negocios (Diana): el bot eligió
una opción y negocios dice que debía ser otra, o un perfil nuevo revela
bifurcaciones nunca vistas. Diagnóstico del brainstorm:

1. **El criterio de negocios es inconsistente** — no existen reglas fijas
   escritas; se decide caso a caso.
2. **Las correcciones se evaporan** — llegan por chat/verbal, se arreglan en
   código, y la única "documentación" termina siendo el commit (ilegible para
   negocios). Nadie puede consultar qué se decidió la vez anterior.
3. Las decisiones del bot son **opacas para quien revisa la quote**: negocios
   ve el resultado final pero no qué eligió el bot ni por qué, ni por qué el
   motor de reglas incluyó/excluyó cada MGA.

No es un problema de extracción de datos ni de selectores: es conocimiento de
negocio no capturado.

## Solución: el bot como notario

El que mejor conoce las bifurcaciones es el bot — las ve todas, en vivo, en
cada corrida. La solución es que las **cuente**:

1. Cada decisión de la corrida se registra en un **Decision Ledger**
   (compartido Progressive + GEICO).
2. El email de análisis incluye: el **"por qué" del motor de reglas**
   (elegibilidad por MGA según `config/REGLAS_quotes.xlsx`) y la tabla
   **"Decisiones tomadas"** por cada MGA que logró cotizar.
3. Las correcciones de Diana llegan atadas a una fila concreta y se vuelcan a
   un **registro de reglas en Excel** versionado en git.
4. Con el tiempo el Excel ES el manual — construido con casos reales, no
   pedido en abstracto a negocios.

## Contexto del servicio (requisitos confirmados con el usuario)

- **Lectura desde los correos de ventas** — comportamiento existente, se
  mantiene.
- **Servicio 100% transparente sobre el buzón monitoreado:** NO se agregan
  etiquetas (se elimina 'Cotizado-Bot'), NO se marca como leído, NO se
  modifica el correo original de ninguna forma. El bot solo lee la Blue
  Quote y realiza el análisis.
  - Consecuencia técnica: la deduplicación de correos procesados NO puede
    depender de etiquetas ni del estado leído/no-leído. Debe hacerse por
    Gmail message-id en la cola SQLite local (verificar que la cola actual
    ya lo cubra; si depende de la etiqueta, migrar).
- **Destino del análisis (etapa de estabilización):** correo **NUEVO**
  (asunto propio, ej. "Análisis Bot — {cliente}") dirigido **solo a**
  `dianarubio@h2oins.com`. No se responde el hilo de ventas ni se copia a
  nadie más. El destinatario va en configuración (env var, ej.
  `ANALYSIS_EMAIL_TO`) porque es temporal — al salir de estabilización se
  cambia sin tocar código.

## No-objetivos (YAGNI)

- El bot **NO lee el Excel de reglas de decisión en runtime**. El código
  sigue siendo la fuente ejecutable; el Excel es la fuente humana.
  (Runtime-driven rules = opción B descartada por ahora.)
- **NO** se parsean automáticamente las respuestas de Diana
  (HALT-and-ask automático = opción C, fuera de alcance).

## Componentes

### 1. Registro de reglas: `config/mga_decision_rules.xlsx`

Excel versionado en git (mismo patrón que `config/REGLAS_quotes.xlsx`).
Una fila por punto de decisión, de **ambas MGAs**. Columnas:

| Columna | Descripción | Ejemplo |
|---|---|---|
| `ID` | Identificador estable, citado en código y commits | R-007 |
| `MGA` | Progressive / GEICO | Progressive |
| `Página` | Página del wizard donde ocurre | Coverages/RATES |
| `Campo` | El campo/radio/combo concreto | Roadside Assistance |
| `Contexto` | Cuándo aplica la regla | Siempre / Solo Trucker / USDOT < 60 días |
| `Decisión` | Qué elige el bot | Yes |
| `Fuente` | Quién definió la regla | Negocio (Diana) / Default técnico / AI / Learned |
| `Quote de referencia` | Caso que originó la regla | USDOT 9648609 |
| `Estado` | VIGENTE / EN-DUDA / PENDIENTE-código | EN-DUDA |
| `Notas` | Contexto libre: fecha del feedback, commit, matices | feedback 2026-06, commit f257f96 |

**Seed:** se genera con una auditoría del código actual de Progressive y
GEICO — todo punto donde el bot elige un valor que no viene copiado directo
del BlueQuote. Reglas que vinieron de feedback de Diana (Roadside, filings,
USDOT-60-días, Verify-USDOT Skip…) entran con `Fuente=Negocio` y
`Estado=VIGENTE`. Defaults técnicos sin validación de negocio entran con
`Estado=EN-DUDA`.

**La lista EN-DUDA es la agenda de la sesión de validación con Diana** — en
vez de pedirle a negocios que documente todo, se le presenta el mapa completo
para que confirme o corrija fila por fila.

### 2. Runtime: `modules/decision_ledger.py` (compartido)

Módulo puro (sin Playwright), usado por Progressive y GEICO.

- **API:** `start_run()` al inicio de la corrida de cada MGA;
  `record(mga, page, field, chosen, options, source, rule_id=None, note="")`
  acumula entradas; `entries()` devuelve la lista para serializar.
- **Estado por proceso:** ledger module-level reseteado por `start_run()`
  (misma asunción que `learned_mappings`: un proceso == una corrida).
- **Alimentación automática:** `choice_resolver.resolve_choice()` (Progressive)
  registra cada `Resolution` en el ledger (import directo — ambos módulos son
  lógica pura, sin ciclo). GEICO se integra en sus puntos de decisión
  equivalentes.
- **Sitios hardcodeados** (Roadside, filings, Verify-USDOT Skip, etc.):
  agregan una llamada explícita con `rule_id="R-007"`. El `rule_id` ata
  código ↔ Excel.
- **Salida:** el resultado de la corrida de cada MGA suma la clave
  `decisions` con las entradas serializadas.

### 3. Email de análisis (correo nuevo a Diana)

Estructura del correo (reemplaza al reply-en-hilo durante estabilización):

1. **Resumen** — cliente, USDOT, effective date, resultado por MGA
   (premium / fallo / no elegible).
2. **Por qué del análisis (motor de reglas)** — por cada MGA evaluada,
   renderizado desde `MGAEvaluation` (ya existente en
   `modules/rule_engine.py`): veredicto de elegibilidad, `failed_rules`
   con razón + valor actual vs requerido cuando NO es elegible, y
   `warnings`. Diana ve exactamente qué regla del Excel
   `REGLAS_quotes.xlsx` incluyó o excluyó cada MGA.
3. **Decisiones tomadas** — una tabla por cada MGA que **logró cotizar**
   (si Progressive cotizó y GEICO falló, va solo la de Progressive; en
   fallos no va tabla). Columnas: Campo · Valor elegido · Fuente (y regla
   si tiene ID). **Orden: dudosas primero** — decisiones con fuente AI o
   default sin `rule_id` arriba con ⚠️; las respaldadas por regla de
   negocio abajo.

Si el ledger llegó vacío, la sección 3 se omite — nunca rompe el armado
del email.

### 4. Circuito de corrección (proceso humano)

1. Diana responde el correo de análisis señalando una fila
   ("Filings debía ser No").
2. El dev actualiza la fila del Excel: nueva `Decisión`, `Fuente=Negocio`,
   `Quote de referencia`, fecha en `Notas`, `Estado=PENDIENTE-código`.
3. Fix en código citando el ID en el mensaje del commit (`R-012`).
4. `Estado=VIGENTE`. La próxima quote muestra la decisión con su regla.

Este workflow queda documentado en el propio Excel (hoja "instrucciones") y
en `docs/AGENTS_CONTEXT.md`.

## Flujo de datos

```
Correo de ventas (solo lectura, sin marcar/etiquetar)
      │  dedup por message-id (cola SQLite)
      ▼
BlueQuote → rule_engine ──► MGAEvaluation (por qué elegible/no)
      │
      ▼
field_mapper / pages (Progressive y GEICO)
      │  (cada decisión: resolve_choice o sitio hardcodeado)
      ▼
decision_ledger ──► result["decisions"] por MGA
      │
      ▼
runner → correo NUEVO a ANALYSIS_EMAIL_TO (dianarubio@h2oins.com):
         resumen + por-qué reglas + decisiones tomadas
```

## Manejo de errores

- El ledger es **best-effort**: `record()` nunca lanza hacia el caller
  (try/except interno + WARN log). Una falla de registro jamás rompe una
  cotización.
- El render del email tolera ledger vacío o entradas malformadas (omite la
  fila, WARN).
- La sección "por qué" tolera `MGAEvaluation` ausente (corrida vieja):
  se omite con nota.

## Testing

- Unit tests de `decision_ledger`: record, reset por `start_run`, orden,
  serialización, best-effort ante entradas malformadas.
- Test del hook en `choice_resolver`: MATCHED y DEFAULTED quedan registrados.
- Tests del render del email: sección por-qué (elegible, no-elegible con
  failed_rules, warnings), tabla de decisiones (dudosas arriba, vacío omite
  sección, solo MGAs que cotizaron).
- Test de transparencia del runner: procesar un correo NO invoca
  etiquetado ni mark-as-read (mock de GmailClient que falla si se llama).
- Test de dedup por message-id sin depender de etiquetas.
- `tests/simulate_progressive.py` valida end-to-end que una corrida simulada
  llena el ledger y el resultado incluye `decisions`.

## Fases de implementación

1. **Cambios de servicio (runner):** transparencia total (sin etiqueta,
   sin marcar leído, dedup por message-id) + correo nuevo a
   `ANALYSIS_EMAIL_TO` en vez de reply-en-hilo.
2. **Sección "por qué" del motor de reglas** en el email (la data ya
   existe en `MGAEvaluation` — es render).
3. **Auditoría del código** (Progressive + GEICO) → seed del Excel
   `config/mga_decision_rules.xlsx` + mapa de bifurcaciones (entregable
   independiente para la sesión con Diana).
4. `decision_ledger.py` + hook en `choice_resolver` + integración GEICO +
   sitios hardcodeados citando IDs del seed.
5. **Sección "Decisiones tomadas"** en el email.
6. Documentar el circuito de corrección (Excel hoja instrucciones +
   AGENTS_CONTEXT).
