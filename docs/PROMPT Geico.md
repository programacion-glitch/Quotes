# PROMPT — Módulo GEICO: cotizar end-to-end aplicando las prácticas de Progressive

> Prompt de arranque para la sesión de trabajo del módulo GEICO. Escrito el
> 2026-06-11, destilando las lecciones live del módulo Progressive
> (2026-06-02 → 2026-06-11). Pegar tal cual al iniciar la sesión.

## META

Cotizar Commercial Auto en el portal de GEICO de forma autónoma: desde una Blue
Quote (QuoteProfile ya extraído) hasta capturar **premium + quote number + PDF
de la quote**, parando SIEMPRE en "Final Quote Details". La medida de éxito es
la misma que en Progressive: un batch de Blue Quotes reales donde cada una
termina en QUOTED (con warnings revisables) o en un HALT con diagnóstico claro
— nunca en un fallo silencioso ni a medio configurar.

## CONTEXTO — leer ANTES de tocar código

1. `docs/Proceso GEICO.md` — mapa completo del flow (9 steps, selectores,
   eligibility checks, decisiones aprobadas, env vars, datos de prueba).
2. `modules/geico/` — módulo EXISTENTE (login+MFA, dashboard, 9 pages, field
   mapper, PDF downloader). OJO: es del 2026-06-01, ANTERIOR al refactor de
   primitivas y a todas las lecciones de Progressive. Auditarlo, no asumirlo.
3. `modules/progressive/` + CLAUDE.md — el patrón de referencia ya endurecido.
4. Memoria del proyecto: progressive_resume_2026_06_10 / _11 (lecciones live).

## REGLAS INNEGOCIABLES (pagadas con días de debugging en Progressive)

### Arquitectura

- **Page Object Model + BasePage hub de primitivas.** PROHIBIDO `page.fill/
  click/select_option` directo en pages. Primera tarea: auditar la BasePage de
  GEICO y llevarla al estándar de la de Progressive: `safe_*` con verificación
  bidireccional del valor commiteado + retry, `field_exists`, localización
  tolerante por label. GEICO usa shadow DOM y selects nativos — las primitivas
  serán distintas, la disciplina es la misma.
- **QuoteProfile es la única fuente de verdad.** El field_mapper de GEICO
  traduce; nunca leer del PDF directo en las pages.
- **Effective date** viene del subject del email (regex ya existente).

### Esperas — cero sleeps ciegos

- Identificar la señal de "idle" del framework del front de GEICO (equivalente
  al `wait_for_extjs_idle` de Progressive) y construir esperas por CONDICIÓN
  OBSERVABLE: opción visible, valor commiteado, texto que aparece/desaparece.
- **Lección DCT (Progressive 06-11):** hay toggles/reveals que son round-trips
  AL SERVIDOR que ningún idle del cliente ve. Para campos revelados en cascada:
  UN solo trigger + POLL del estado visible (cadencia 500ms, presupuesto ~8s).
  NUNCA re-clickear con el round-trip en vuelo — togglea el estado de vuelta.
- Si un `wait_for_timeout(N)` literal es inevitable, comentario justificándolo.

### Campos condicionales y fallos

- Todo campo CONDITIONAL: `field_exists(wait_ms)` antes de actuar.
- **Duplicados ocultos en el DOM**: siempre operar sobre el match VISIBLE,
  nunca `.first` a ciegas (mordió 3 veces en Progressive: tiles, boundlists,
  anchors de secciones).
- **Fail-soft en coberturas**: si un control no se puede configurar, WARN al
  resultado (`self.warnings` → QuoteResult.warnings) y la quote SIGUE.
- **Fail-loud (HALT) solo para**: datos sensibles que el bot no debe inventar
  (SSN o equivalente), y cualquier acción que avance hacia bind/payment.
- En cada WARN path: **instrumentación de aprendizaje** — dump de labels y
  opciones visibles + screenshot. El log del fallo debe enseñar el DOM real
  para que el siguiente fix sea quirúrgico, no adivinado.
- Al debuggear: leer el SCREENSHOT antes que el error string; verificar contra
  el PDF fuente antes de diseñar un fix.

### Sesión, OTP y contención

- **Sesión persistente** (`storage_state` en data/, gitignored): un login/OTP
  por batch, no por quote. GEICO usa Azure B2C + OTP email — asumir que tiene
  throttle de OTP igual que Progressive (lockout ~1h). NO martillar logins.
- El OTP reader BORRA cada correo usado (scope gmail.modify).
- `context.set_default_timeout(30_000)` + presupuesto duro por intento
  (asyncio.wait_for, calibrado al quote legítimo más largo + margen) + retry
  solo si el fallo fue en login + taskkill de browsers huérfanos en el batch.
- Timeouts explícitos en TODOS los clientes IA (45-60s, no el default 600s).

### Validación y ritmo

- Lógica pura (parsers, snaps, mappers) → tests unitarios. Flujo → simulador
  estructural con mocks QUE MODELEN ESTADO (el mock de login de Progressive
  mintió durante un día por ser stateless).
- Baselines de premium: re-cotizar un perfil validado debe dar IDÉNTICO al
  centavo. Toda optimización se valida con regresión.
- **General sobre per-quote**: distinguir siempre fixes GENERALES (afectan a
  todas las quotes) de fixes de COLA (campo raro del form). Los de cola se
  mapean UNA vez con fail-soft y no ameritan sesiones enteras de iteración.
- **No re-cotizar el mismo cliente/USDOT más de ~3 veces el mismo día** para
  validar refinamientos (en Progressive el estado acumulado wedgea el renderer
  a la 4ª-5ª; asumir que GEICO puede tener su propia patología equivalente).
  Validar refinamientos menores en el batch natural del día siguiente.
- Batch runner: subprocess por PDF (aislamiento total), timeout por quote,
  reporte JSON+MD incremental que sobrevive interrupciones.

### Líneas rojas

- **STOP en Final Quote Details.** El Next que va a MVR & CLUE / Payment NO se
  clickea JAMÁS. Dry-run por defecto.
- Steps 8 y 9 del doc: NO mapeados, NO ENTRAR.
- Nunca commitear: PDFs de clientes, .env, session state, OTPs.

## PLAN SUGERIDO (fases, cada una con entregable verificable)

1. **Auditoría**: diff del módulo GEICO actual contra estas reglas. Lista de
   gaps priorizada (general → cola). No escribir fixes todavía.
2. **BasePage hardening** + tests unitarios de primitivas.
3. **Login + sesión persistente + OTP** validado live UNA vez (probe script,
   sin quote completa).
4. **Flow end-to-end con UN perfil validado** del doc ("Datos de prueba
   validados") hasta premium + PDF. Ese resultado es el baseline.
5. **Batch con las Blue Quotes reales** de `data/input 10 Junio/` (las 23 que
   Progressive cotizó — comparar elegibilidad/precio entre MGAs es bonus).
6. **Reporte final**: tabla QUOTED/HALT con premium, quote#, PDF, warnings y
   data-issues para humano.

Empieza por la fase 1 y muéstrame la lista de gaps antes de modificar nada.
