# Filtro de correos del buzón Quotes — remitente de ventas + asunto exacto

**Fecha:** 2026-07-06
**Estado:** Diseño aprobado por el usuario (2026-07-06)
**Ámbito:** Bot autónomo (`modules/quote_queue/runner.py` + `modules/gmail_client.py`)

## Problema

El monitor del bot autónomo lee el buzón **quotes@h2oins.com** con el query
Gmail `is:unread subject:"Submission" after:<cutoff> -label:"Procesado-Bot"`.

Dos defectos:
1. **`subject:"Submission"` matchea también las respuestas** (`Re: Submission …`),
   así que el bot procesa hilos/replies innecesariamente.
2. **`poll_once` etiqueta TODO lo que fetchea** (en el `finally`), aun lo que no
   procesa → aparecen etiquetas (`Procesado-Bot`/`Cotizado-Bot`) sobre correos de
   hilo que no debían tocarse.
3. **No hay filtro de remitente**: cualquiera que mande un asunto con "Submission"
   entra, no solo el equipo de ventas.

## Objetivo

El bot debe procesar **únicamente** los correos de submission originales que
manda el equipo de ventas, con el asunto vigente. Todo lo demás (replies,
reenvíos, remitentes ajenos, grupo≠asunto) **no se procesa ni se etiqueta**.

## Regla de aceptación

Un correo se procesa **solo si** cumple las tres:

1. **Asunto original:** `subject.strip().lower()` **empieza con** `"submission"`
   (excluye `Re:`, `Fwd:`, `[ANALISIS]`, etc.).
2. **Remitente de ventas:** la dirección `From` (case-insensitive) está en una de
   las dos listas.
3. **Grupo ↔ asunto coincide:**
   - Grupo **RT** → asunto de **cliente existente**: empieza con `submission` y
     **NO** contiene `"new venture"`.
   - Grupo **VENTAS NUEVAS** → asunto **new venture**: empieza con `submission` y
     contiene `"new venture"`.

Mapeo confirmado: **RT = cliente existente** (`Submission …`),
**VENTAS NUEVAS = new venture** (`Submission New Venture …`).

Detección de "new venture" por substring `"new venture" in subject.lower()`, para
ser consistente con la lógica ya existente en `workflow_orchestrator._process_submission`.

## Componentes

### 1. Función pura de decisión (nueva)

`modules/quote_queue/sender_filter.py`

```python
def is_processable_submission(
    sender_email: str,
    subject: str,
    rt_senders: set[str],
    new_venture_senders: set[str],
) -> bool:
    """True solo si el correo es una submission original de ventas cuyo grupo
    (RT / VENTAS NUEVAS) coincide con la variante del asunto. sets ya en minúscula."""
    s = (subject or "").strip().lower()
    if not s.startswith("submission"):
        return False                       # replies / forwards / [ANALISIS]
    sender = (sender_email or "").strip().lower()
    is_new_venture = "new venture" in s
    if is_new_venture:
        return sender in new_venture_senders
    return sender in rt_senders
```

- Testeable en aislamiento, sin red ni estado.
- Los sets se pasan ya normalizados (minúscula) desde el runner.

### 2. `GmailClient.fetch_unread` — filtro de remitente en el query

Nuevo parámetro **opcional** `from_allowlist: Optional[List[str]] = None`.
Si se da y no está vacío, agrega al query:

```
from:(a@h2oins.com OR b@h2oins.com OR ... )
```

Efecto: los correos de **no-ventas ni se descargan** (no `messages.get`, no se
etiquetan). Firma retrocompatible (param nuevo al final, default `None`).

Query resultante (ejemplo):
```
is:unread subject:"Submission" after:1751000000 -label:"Procesado-Bot"
  from:(simon@h2oins.com OR esteban@h2oins.com OR ... OR cindyr@h2oins.com)
```

### 3. `poll_once` — guard antes de procesar/etiquetar

Firma nueva (params opcionales, retrocompatible):
```python
def poll_once(gmail, orchestrator, subject_filter, after_epoch=None,
              seen_label="Procesado-Bot",
              rt_senders=None, new_venture_senders=None) -> int:
```

- Construye la allowlist unión (`rt_senders | new_venture_senders`) y la pasa a
  `fetch_unread(from_allowlist=...)`.
- Para cada correo fetcheado: si **NO** `is_processable_submission(...)` →
  **`continue`** (no `process_email`, no `add_label`). Si pasa → como hoy
  (`process_email` + etiquetar en `finally`).
- **Fail-closed:** si ambos sets están vacíos (config faltante/rota), se loguea un
  WARNING claro y **no se procesa nada** — el guard rechaza todo por diseño (el
  remitente nunca está en un set vacío). Se prefiere fail-closed (bot no procesa)
  sobre fail-open (procesar todo, el bug original). Con la config nueva presente
  esto no ocurre. Nota: con allowlist vacía NO se agrega la cláusula `from:()` al
  query (paréntesis vacíos = query inválido); se fetchea el set amplio y el guard
  lo descarta.

### 4. `run_forever` — carga de config

Lee las dos listas de `config/settings.yaml`, las normaliza a minúscula en sets,
y las pasa a `poll_once`. Loguea al arrancar cuántos remitentes hay por grupo.

### 5. Config (`config/settings.yaml`)

```yaml
email:
  monitoring:
    subject_filter: "Submission"
    check_interval_seconds: 60
    senders:
      rt:                        # cliente existente -> "Submission ..."
        - simon@h2oins.com
        - esteban@h2oins.com
        - victor@h2oins.com
        - luisgomez@h2oins.com
        - juanmanuel@h2oins.com
      new_venture:               # new venture -> "Submission New Venture ..."
        - duvan@h2oins.com
        - veronica@h2oins.com
        - jhonfredy@h2oins.com
        - felipemartinez@h2oins.com
        - juanfelipe@h2oins.com
        - juandavid@h2oins.com
        - danielramirez@h2oins.com
        - johan@h2oins.com
        - sirley@h2oins.com
        - brandon@h2oins.com
        - cindyr@h2oins.com
```

El equipo puede editar las listas sin tocar código.

## Comportamiento del etiquetado

Sin cambios en la mecánica (`Procesado-Bot` / `Cotizado-Bot`). El efecto neto: solo
se etiqueta lo que efectivamente se procesa (submissions válidas de ventas). Los
correos salteados quedan **no leídos y sin etiqueta**.

## Casos borde / consecuencias

- **Re: de un vendedor** (reply en hilo, no leído, de ventas): pasa el `from:` del
  query pero el guard lo rechaza (no empieza con "submission") → no se procesa ni
  etiqueta. Se **re-fetchea cada ciclo** (read-only, sin efecto visible). Costo
  menor de cuota API, acotado por `after:` + allowlist.
- **RT manda "Submission New Venture"** (o VENTAS NUEVAS manda "Submission"): el
  guard lo rechaza (grupo≠asunto). No se procesa. Queda no leído para revisión
  humana.
- **Correo de no-ventas:** excluido en el query (`from:`), ni se descarga.

## Fuera de alcance

- El flujo de aprobación **APROBAR** (`Re: [ANALISIS] … APROBAR`) NO se usa
  actualmente (confirmado por el usuario, es implementación futura). Se deja el
  código intacto; con el filtro nuevo esas respuestas simplemente nunca se leen.
- La lógica interna de `workflow_orchestrator` (extracción, encolado, envío de
  análisis) **no se toca**.

## Testing (TDD)

`tests/quote_queue/test_sender_filter.py` (nuevo):
- RT + "Submission // X" → True
- RT + "Submission New Venture // X" → False (grupo≠asunto)
- NEW_VENTURE + "Submission New Venture // X" → True
- NEW_VENTURE + "Submission // X" → False
- "Re: Submission // X" (cualquier remitente) → False
- "[ANALISIS] Submission // X" → False
- Remitente fuera de ambas listas → False
- Case-insensitivity en remitente y asunto (Duvan@ vs duvan@, "SUBMISSION")

`tests/quote_queue/test_runner.py` (extender):
- `poll_once` con guard: correo válido → `process_email` + `add_label`; correo
  inválido → NO `process_email`, NO `add_label`.
- `poll_once` pasa `from_allowlist` (unión) a `fetch_unread`.

`tests/test_gmail_client.py` (extender):
- `fetch_unread(from_allowlist=[...])` incluye `from:(...)` en el query.
- `from_allowlist=None` → query sin cláusula `from:` (retrocompat).
