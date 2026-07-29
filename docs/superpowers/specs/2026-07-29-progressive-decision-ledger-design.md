# Progressive Decision Ledger — Diseño

**Fecha:** 2026-07-29
**Estado:** Aprobado en brainstorm (opción A de tres evaluadas)
**Alcance:** módulo Progressive (diseño generalizable a GEICO en fase futura)

## Problema

Cada cotización nueva de Progressive genera correcciones de negocios (Diana):
el bot eligió una opción y negocios dice que debía ser otra, o un perfil nuevo
revela bifurcaciones nunca vistas. Diagnóstico del brainstorm:

1. **El criterio de negocios es inconsistente** — no existen reglas fijas
   escritas; se decide caso a caso.
2. **Las correcciones se evaporan** — llegan por chat/verbal, se arreglan en
   código, y la única "documentación" termina siendo el commit (ilegible para
   negocios). Nadie puede consultar qué se decidió la vez anterior.
3. Las decisiones del bot son **opacas para quien revisa la quote**: negocios
   ve el resultado final pero no qué eligió el bot ni por qué.

No es un problema de extracción de datos ni de selectores: es conocimiento de
negocio no capturado.

## Solución: el bot como notario

El que mejor conoce las bifurcaciones de Progressive es el bot — las ve todas,
en vivo, en cada corrida. La solución es que las **cuente**:

1. Cada decisión de la corrida se registra en un **Decision Ledger**.
2. El email de análisis (que ya va al hilo de quotes@) incluye la tabla
   **"Decisiones tomadas"** — legible por negocios.
3. Las correcciones de Diana llegan atadas a una fila concreta y se vuelcan a
   un **registro de reglas en Excel** versionado en git.
4. Con el tiempo el Excel ES el manual — construido con casos reales, no
   pedido en abstracto a negocios.

## No-objetivos (YAGNI)

- El bot **NO lee el Excel en runtime**. El código sigue siendo la fuente
  ejecutable; el Excel es la fuente humana. (Runtime-driven rules = opción B
  descartada por ahora; se reevalúa solo si negocios demuestra mantener el
  Excel.)
- **NO** se parsean automáticamente las respuestas de Diana en el hilo
  (HALT-and-ask automático = opción C, fuera de alcance).
- **NO** cubre GEICO en esta fase.

## Componentes

### 1. Registro de reglas: `config/progressive_decision_rules.xlsx`

Excel versionado en git (mismo patrón que `config/REGLAS_quotes.xlsx`).
Una fila por punto de decisión. Columnas:

| Columna | Descripción | Ejemplo |
|---|---|---|
| `ID` | Identificador estable, citado en código y commits | R-007 |
| `Página` | Página de Progressive donde ocurre | Coverages/RATES |
| `Campo` | El campo/radio/combo concreto | Roadside Assistance |
| `Contexto` | Cuándo aplica la regla | Siempre / Solo Trucker / USDOT < 60 días |
| `Decisión` | Qué elige el bot | Yes |
| `Fuente` | Quién definió la regla | Negocio (Diana) / Default técnico / AI / Learned |
| `Quote de referencia` | Caso que originó la regla | USDOT 9648609 |
| `Estado` | VIGENTE / EN-DUDA / PENDIENTE-código | EN-DUDA |
| `Notas` | Contexto libre: fecha del feedback, commit, matices | feedback 2026-06, commit f257f96 |

**Seed:** se genera con una auditoría del código actual — todo punto donde el
bot elige un valor que no viene copiado directo del BlueQuote. Reglas que
vinieron de feedback de Diana (Roadside, filings, USDOT-60-días) entran con
`Fuente=Negocio` y `Estado=VIGENTE`. Defaults técnicos sin validación de
negocio entran con `Estado=EN-DUDA`.

**La lista EN-DUDA es la agenda de la sesión de validación con Diana** — en
vez de pedirle a negocios que documente todo, se le presenta el mapa completo
para que confirme o corrija fila por fila.

### 2. Runtime: `modules/progressive/decision_ledger.py`

Módulo puro (sin Playwright), mismo espíritu que `choice_resolver.py`.

- **API:** `start_run()` al inicio de la corrida (quote_flow);
  `record(page, field, chosen, options, source, rule_id=None, note="")`
  acumula entradas; `entries()` devuelve la lista para serializar.
- **Estado por proceso:** ledger module-level reseteado por `start_run()`
  (misma asunción que `learned_mappings`: un proceso == una corrida).
- **Alimentación automática:** `choice_resolver.resolve_choice()` registra
  cada `Resolution` en el ledger (import directo — ambos módulos son lógica
  pura, sin ciclo). Nada que recordar en los callers.
- **Sitios hardcodeados** (Roadside, filings, etc.): agregan una llamada
  explícita `decision_ledger.record(..., rule_id="R-007")`. El `rule_id`
  ata código ↔ Excel.
- **Salida:** el resultado de la corrida (dict que retorna quote_flow) suma
  la clave `decisions` con las entradas serializadas.

### 3. Email: sección "Decisiones tomadas"

El runner ya manda el análisis en el hilo de quotes@ (+ CC programacion@).
Se agrega una tabla renderizada desde `decisions`:

- Columnas: Campo · Valor elegido · Fuente (y regla si tiene ID).
- **Orden: dudosas primero** — decisiones con fuente AI o default sin
  `rule_id` van arriba con ⚠️; las respaldadas por regla de negocio abajo.
- Si el ledger llegó vacío (corrida vieja, fallo), la sección se omite —
  nunca rompe el armado del email.

### 4. Circuito de corrección (proceso humano)

1. Diana responde en el hilo señalando una fila ("Filings debía ser No").
2. El dev actualiza la fila del Excel: nueva `Decisión`,
   `Fuente=Negocio`, `Quote de referencia`, fecha en `Notas`,
   `Estado=PENDIENTE-código`.
3. Fix en código citando el ID en el mensaje del commit (`R-012`).
4. `Estado=VIGENTE`. La próxima quote muestra la decisión con su regla.

Este workflow queda documentado en el propio Excel (hoja "instrucciones") y
en `docs/AGENTS_CONTEXT.md`.

## Flujo de datos

```
BlueQuote → field_mapper / pages
              │  (cada decisión: resolve_choice o sitio hardcodeado)
              ▼
        decision_ledger  ──►  result["decisions"] (quote_flow)
                                    │
                                    ▼
                        runner → email en hilo (tabla "Decisiones tomadas")
```

## Manejo de errores

- El ledger es **best-effort**: `record()` nunca lanza hacia el caller
  (try/except interno + WARN log). Una falla de registro jamás rompe una
  cotización.
- El render del email tolera ledger vacío o entradas malformadas (omite la
  fila, WARN).

## Testing

- Unit tests de `decision_ledger`: record, reset por `start_run`, orden,
  serialización, best-effort ante entradas malformadas.
- Test del hook en `choice_resolver`: MATCHED y DEFAULTED quedan registrados.
- Test del render de la sección email (dudosas arriba, vacío omite sección).
- `tests/simulate_progressive.py` valida end-to-end que una corrida simulada
  llena el ledger y el resultado incluye `decisions`.

## Fases de implementación

1. **Auditoría del código** → seed del Excel + mapa de bifurcaciones
   (entregable independiente: sirve para la sesión con Diana aunque el resto
   no esté).
2. `decision_ledger.py` + hook en `choice_resolver` + llamadas en sitios
   hardcodeados citando IDs del seed.
3. Sección "Decisiones tomadas" en el email del runner.
4. Documentar el circuito de corrección (Excel hoja instrucciones +
   AGENTS_CONTEXT).
