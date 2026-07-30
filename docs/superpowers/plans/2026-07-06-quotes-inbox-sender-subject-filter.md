# Filtro de correos Quotes (remitente de ventas + asunto) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que el bot autónomo procese y etiquete SOLO las submissions originales del equipo de ventas con el asunto vigente, ignorando replies/reenvíos/remitentes ajenos.

**Architecture:** Doble capa de filtro sobre el monitor del inbox: (1) `GmailClient.fetch_unread` gana una allowlist de remitentes que se traduce en `from:(...)` en el query Gmail (los no-ventas ni se descargan), y (2) `poll_once` mete un guard puro `is_processable_submission` que exige asunto que empieza con "Submission" + grupo(RT/VENTAS NUEVAS)↔variante-de-asunto ANTES de procesar/etiquetar. Config de remitentes en `settings.yaml`.

**Tech Stack:** Python 3.12, Gmail API (`google-api-python-client`), pytest, YAML (`config/settings.yaml`).

## Global Constraints

- Intérprete Python: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe` (no está en PATH).
- Correr tests con: `<python> -m pytest <ruta> -v`.
- Firmas nuevas SIEMPRE retrocompatibles: parámetros nuevos al final con default (`None`). Los tests existentes de `fetch_unread`/`poll_once` deben seguir pasando sin cambios.
- Match de remitentes y asunto: **case-insensitive**. Los sets de remitentes se pasan y comparan en **minúscula**.
- Detección de "new venture": substring `"new venture" in subject.lower()` (consistente con `workflow_orchestrator._process_submission`).
- Mapeo confirmado: **RT = cliente existente** (`Submission …`), **VENTAS NUEVAS = new venture** (`Submission New Venture …`).
- **Fail-closed:** si no hay remitentes configurados, el guard rechaza todo (no procesar) + WARNING. Nunca fail-open.
- Commits: cada commit termina con el trailer del proyecto:
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_013KyDtAX1fj3ZKoWymRqkLo
  ```
  (Confirmar con el usuario antes de commitear — regla del repo: commitear solo cuando lo pide.)

---

### Task 1: Función pura `is_processable_submission`

**Files:**
- Create: `modules/quote_queue/sender_filter.py`
- Test: `tests/quote_queue/test_sender_filter.py`

**Interfaces:**
- Produces: `is_processable_submission(sender_email: str, subject: str, rt_senders: set[str], new_venture_senders: set[str]) -> bool`. Los sets llegan ya en minúscula.

- [ ] **Step 1: Write the failing test**

Create `tests/quote_queue/test_sender_filter.py`:

```python
"""Unit de la regla de aceptación de submissions de ventas."""
from modules.quote_queue.sender_filter import is_processable_submission

RT = {"simon@h2oins.com", "esteban@h2oins.com"}
NV = {"duvan@h2oins.com", "veronica@h2oins.com"}


def test_rt_sender_existing_subject_ok():
    assert is_processable_submission(
        "simon@h2oins.com", "Submission // ACME LLC", RT, NV) is True


def test_rt_sender_new_venture_subject_rejected():
    # RT no puede mandar new venture (grupo != asunto)
    assert is_processable_submission(
        "simon@h2oins.com", "Submission New Venture // ACME", RT, NV) is False


def test_new_venture_sender_new_venture_subject_ok():
    assert is_processable_submission(
        "duvan@h2oins.com", "Submission New Venture // ACME", RT, NV) is True


def test_new_venture_sender_existing_subject_rejected():
    assert is_processable_submission(
        "duvan@h2oins.com", "Submission // ACME", RT, NV) is False


def test_reply_subject_rejected():
    assert is_processable_submission(
        "simon@h2oins.com", "Re: Submission // ACME", RT, NV) is False


def test_forward_subject_rejected():
    assert is_processable_submission(
        "simon@h2oins.com", "Fwd: Submission // ACME", RT, NV) is False


def test_analysis_subject_rejected():
    assert is_processable_submission(
        "simon@h2oins.com", "[ANALISIS] Submission // ACME", RT, NV) is False


def test_unknown_sender_rejected():
    assert is_processable_submission(
        "ajeno@gmail.com", "Submission // ACME", RT, NV) is False


def test_case_insensitive_sender_and_subject():
    assert is_processable_submission(
        "Duvan@H2OINS.com", "SUBMISSION NEW VENTURE // X", RT, NV) is True


def test_empty_sets_reject_all():
    assert is_processable_submission(
        "simon@h2oins.com", "Submission // ACME", set(), set()) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/quote_queue/test_sender_filter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.quote_queue.sender_filter'`

- [ ] **Step 3: Write minimal implementation**

Create `modules/quote_queue/sender_filter.py`:

```python
"""Decide si un correo entrante es una submission original de ventas procesable.

Regla (las tres deben cumplirse):
  1. El asunto EMPIEZA con "submission" (excluye "Re:", "Fwd:", "[ANALISIS]", ...).
  2. El remitente pertenece a un grupo de ventas.
  3. El grupo coincide con la variante del asunto:
       - "Submission New Venture ..."  -> new_venture_senders (VENTAS NUEVAS)
       - "Submission ..." (existente)  -> rt_senders (RT)

Los sets de remitentes se pasan YA normalizados en minúscula.
"""
from typing import Set


def is_processable_submission(
    sender_email: str,
    subject: str,
    rt_senders: Set[str],
    new_venture_senders: Set[str],
) -> bool:
    s = (subject or "").strip().lower()
    if not s.startswith("submission"):
        return False
    sender = (sender_email or "").strip().lower()
    if "new venture" in s:
        return sender in new_venture_senders
    return sender in rt_senders
```

- [ ] **Step 4: Run test to verify it passes**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/quote_queue/test_sender_filter.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add modules/quote_queue/sender_filter.py tests/quote_queue/test_sender_filter.py
git commit -m "feat(monitor): regla pura is_processable_submission (asunto+grupo de ventas)"
```

---

### Task 2: `GmailClient.fetch_unread` gana `from_allowlist`

**Files:**
- Modify: `modules/gmail_client.py:70-94` (firma + construcción del query `q`)
- Test: `tests/test_gmail_client.py` (agregar 2 tests)

**Interfaces:**
- Consumes: nada de tasks previas.
- Produces: `fetch_unread(subject_filter=None, after_epoch=None, exclude_label=None, from_allowlist: Optional[List[str]] = None)`. Si `from_allowlist` es truthy, agrega `from:(a OR b OR ...)` al query.

- [ ] **Step 1: Write the failing test**

Agregar al final de `tests/test_gmail_client.py`:

```python
def test_fetch_unread_includes_from_allowlist_when_given():
    svc = _fake_service_with_messages([])
    client = GmailClient(service=svc)
    client.fetch_unread("Submission",
                        from_allowlist=["a@h2oins.com", "b@h2oins.com"])
    _, kwargs = svc.users().messages().list.call_args
    assert "from:(a@h2oins.com OR b@h2oins.com)" in kwargs["q"]
    assert "is:unread" in kwargs["q"]


def test_fetch_unread_no_from_clause_when_allowlist_absent():
    svc = _fake_service_with_messages([])
    client = GmailClient(service=svc)
    client.fetch_unread("Submission")
    _, kwargs = svc.users().messages().list.call_args
    assert "from:(" not in kwargs["q"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_gmail_client.py::test_fetch_unread_includes_from_allowlist_when_given -v`
Expected: FAIL — `TypeError: fetch_unread() got an unexpected keyword argument 'from_allowlist'`

- [ ] **Step 3: Write minimal implementation**

En `modules/gmail_client.py`, cambiar la firma y el docstring de `fetch_unread` (línea 70) y agregar la cláusula `from:` en la construcción del query.

Reemplazar la firma:

```python
    def fetch_unread(self, subject_filter: Optional[str] = None,
                     after_epoch: Optional[float] = None,
                     exclude_label: Optional[str] = None,
                     from_allowlist: Optional[List[str]] = None) -> List[dict]:
```

Y dentro del método, DESPUÉS del bloque `if exclude_label:` (línea 88-89) y ANTES de `resp = (`:

```python
        if from_allowlist:
            # from:(a@x OR b@x ...) — los remitentes fuera de la lista ni se
            # descargan (no messages.get, no se etiquetan).
            addrs = " OR ".join(from_allowlist)
            q += f" from:({addrs})"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_gmail_client.py -v`
Expected: PASS (todos, incluidos los 2 nuevos y los previos sin cambios)

- [ ] **Step 5: Commit**

```bash
git add modules/gmail_client.py tests/test_gmail_client.py
git commit -m "feat(gmail): fetch_unread acepta from_allowlist -> query from:(...)"
```

---

### Task 3: Guard de `poll_once` (asunto + grupo de ventas)

**Files:**
- Modify: `modules/quote_queue/runner.py:28-54` (`poll_once`) + import
- Test: `tests/quote_queue/test_runner.py` (agregar 3 tests)

**Interfaces:**
- Consumes: `is_processable_submission(...)` (Task 1); `fetch_unread(..., from_allowlist=...)` (Task 2).
- Produces: `poll_once(gmail, orchestrator, subject_filter, after_epoch=None, seen_label="Procesado-Bot", rt_senders=None, new_venture_senders=None) -> int`. Devuelve la cantidad **procesada** (no la fetcheada). Cuando `rt_senders` y `new_venture_senders` son ambos `None` (llamador legacy) el guard NO se aplica; si al menos uno se pasa (aunque sea `set()`), el guard se aplica.

- [ ] **Step 1: Write the failing test**

Agregar al final de `tests/quote_queue/test_runner.py`:

```python
def test_poll_once_guard_skips_non_matching_sender():
    gmail = MagicMock()
    gmail.fetch_unread.return_value = [
        {"id": "m1", "subject": "Submission // ACME", "sender_email": "simon@h2oins.com"},
        {"id": "m2", "subject": "Submission // OTHER", "sender_email": "ajeno@gmail.com"},
    ]
    orch = MagicMock()
    n = runner.poll_once(gmail, orch, "Submission",
                         rt_senders={"simon@h2oins.com"},
                         new_venture_senders=set())
    assert n == 1
    orch.process_email.assert_called_once()
    gmail.add_label.assert_called_once_with("m1", "Procesado-Bot")


def test_poll_once_guard_skips_reply_subject():
    gmail = MagicMock()
    gmail.fetch_unread.return_value = [
        {"id": "m1", "subject": "Re: Submission // ACME",
         "sender_email": "simon@h2oins.com"},
    ]
    orch = MagicMock()
    n = runner.poll_once(gmail, orch, "Submission",
                         rt_senders={"simon@h2oins.com"},
                         new_venture_senders=set())
    assert n == 0
    orch.process_email.assert_not_called()
    gmail.add_label.assert_not_called()


def test_poll_once_passes_from_allowlist_union():
    gmail = MagicMock()
    gmail.fetch_unread.return_value = []
    orch = MagicMock()
    runner.poll_once(gmail, orch, "Submission",
                     rt_senders={"simon@h2oins.com"},
                     new_venture_senders={"duvan@h2oins.com"})
    _, kwargs = gmail.fetch_unread.call_args
    assert sorted(kwargs.get("from_allowlist")) == [
        "duvan@h2oins.com", "simon@h2oins.com"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/quote_queue/test_runner.py::test_poll_once_guard_skips_non_matching_sender -v`
Expected: FAIL — `orch.process_email` se llama 2 veces (o `add_label` para m2), porque el guard aún no existe.

- [ ] **Step 3: Write minimal implementation**

En `modules/quote_queue/runner.py`, agregar el import cerca de los otros (bajo `from modules.quote_queue.worker import QuoteWorker`):

```python
from modules.quote_queue.sender_filter import is_processable_submission
```

Reemplazar la función `poll_once` completa (líneas 28-54) por:

```python
def poll_once(gmail, orchestrator, subject_filter: str,
              after_epoch=None, seen_label: str = "Procesado-Bot",
              rt_senders=None, new_venture_senders=None) -> int:
    """Un ciclo del monitor: procesa cada submission ORIGINAL de ventas y la marca
    como PROCESADA con una etiqueta (siempre, aun si el procesamiento falla, para
    no reprocesarla). Devuelve cuántas PROCESÓ (no cuántas fetcheó).

    Guard: si se pasan sets de remitentes (aunque vacíos), solo procesa correos que
    cumplan `is_processable_submission` (asunto empieza con "Submission" + grupo
    RT/VENTAS NUEVAS que coincide con la variante del asunto). Lo que no pasa NO se
    procesa NI se etiqueta (queda no leído, sin tocar). Si ambos sets son None
    (llamador legacy), el guard no se aplica.

    IMPORTANTE: NO marca leído — el correo queda NO LEÍDO para el equipo humano.
    La dedup se hace por la etiqueta `seen_label`, que `fetch_unread` excluye en
    el query (`-label:`).

    after_epoch: corte por fecha — solo correos recibidos después de ese epoch.
    """
    guard_active = not (rt_senders is None and new_venture_senders is None)
    rt = rt_senders or set()
    nv = new_venture_senders or set()
    from_allowlist = sorted(rt | nv) if guard_active else None

    emails = gmail.fetch_unread(subject_filter, after_epoch=after_epoch,
                                exclude_label=seen_label,
                                from_allowlist=from_allowlist)
    processed = 0
    for email_data in emails:
        if guard_active and not is_processable_submission(
                email_data.get("sender_email", ""),
                email_data.get("subject", ""), rt, nv):
            continue  # no es submission original de ventas: no procesar, no etiquetar
        processed += 1
        try:
            orchestrator.process_email(email_data)
        except Exception as e:  # un correo malo no frena el monitor
            print(f"  [monitor] error procesando "
                  f"{email_data.get('subject', '')[:50]}: {e}")
        finally:
            try:
                gmail.add_label(email_data["id"], seen_label)
            except Exception as e:
                print(f"  [monitor] no se pudo etiquetar como procesado: {e}")
    return processed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/quote_queue/test_runner.py -v`
Expected: PASS (los 3 nuevos + los previos sin cambios; `test_poll_once_processes_and_labels_seen_keeps_unread` sigue en verde porque no pasa sender sets → guard inactivo).

- [ ] **Step 5: Commit**

```bash
git add modules/quote_queue/runner.py tests/quote_queue/test_runner.py
git commit -m "feat(monitor): poll_once filtra por remitente de ventas + asunto original"
```

---

### Task 4: Config de remitentes + wiring en `run_forever`

**Files:**
- Modify: `config/settings.yaml:88-99` (bloque `email.monitoring`)
- Modify: `modules/quote_queue/runner.py` (nuevo helper `_load_sender_sets` + wiring en `run_forever`)
- Test: `tests/quote_queue/test_runner.py` (agregar 1 test para el helper)

**Interfaces:**
- Consumes: `poll_once(..., rt_senders=, new_venture_senders=)` (Task 3).
- Produces: `_load_sender_sets(config) -> tuple[set[str], set[str]]` (rt, new_venture), en minúscula.

- [ ] **Step 1: Write the failing test**

Agregar al final de `tests/quote_queue/test_runner.py`:

```python
def test_load_sender_sets_lowercases_and_splits_groups():
    class FakeConfig:
        def get(self, key, default=None):
            data = {
                "email.monitoring.senders.rt":
                    ["Simon@H2Oins.com", "esteban@h2oins.com"],
                "email.monitoring.senders.new_venture":
                    ["Duvan@h2oins.com"],
            }
            return data.get(key, default)

    rt, nv = runner._load_sender_sets(FakeConfig())
    assert rt == {"simon@h2oins.com", "esteban@h2oins.com"}
    assert nv == {"duvan@h2oins.com"}


def test_load_sender_sets_empty_when_missing():
    class FakeConfig:
        def get(self, key, default=None):
            return default

    rt, nv = runner._load_sender_sets(FakeConfig())
    assert rt == set()
    assert nv == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/quote_queue/test_runner.py::test_load_sender_sets_lowercases_and_splits_groups -v`
Expected: FAIL — `AttributeError: module 'modules.quote_queue.runner' has no attribute '_load_sender_sets'`

- [ ] **Step 3: Write minimal implementation**

En `modules/quote_queue/runner.py`, agregar el helper (por ejemplo después de `_load_or_init_cutoff`):

```python
def _load_sender_sets(config):
    """Devuelve (rt_set, new_venture_set) en minúscula desde la config."""
    rt = {str(a).strip().lower() for a in
          (config.get("email.monitoring.senders.rt", []) or [])}
    nv = {str(a).strip().lower() for a in
          (config.get("email.monitoring.senders.new_venture", []) or [])}
    return rt, nv
```

En `run_forever`, después de leer `seen_label` (línea ~110) y antes del `cutoff`, cargar los sets y loguear:

```python
    rt_senders, new_venture_senders = _load_sender_sets(config)
    print(f"[runner] remitentes ventas: RT={len(rt_senders)} "
          f"NEW_VENTURE={len(new_venture_senders)}")
    if not rt_senders and not new_venture_senders:
        print("[runner] ⚠️ WARNING: sin remitentes de ventas configurados "
              "(email.monitoring.senders) — el filtro rechazará TODO (fail-closed)")
```

Y en la llamada a `poll_once` dentro del `while True` (línea ~137), pasar los sets:

```python
                n = poll_once(gmail, orchestrator, subject_filter,
                              after_epoch=cutoff, seen_label=seen_label,
                              rt_senders=rt_senders,
                              new_venture_senders=new_venture_senders)
```

- [ ] **Step 4: Editar `config/settings.yaml`**

En `config/settings.yaml`, dentro de `email: -> monitoring:` (después de `check_interval_seconds: 60`, línea 93), agregar:

```yaml
    # Remitentes de ventas permitidos. RT = cliente existente ("Submission ...");
    # VENTAS NUEVAS = new venture ("Submission New Venture ..."). Match
    # case-insensitive por dirección exacta. Editar acá al alta/baja de vendedores.
    senders:
      rt:
        - simon@h2oins.com
        - esteban@h2oins.com
        - victor@h2oins.com
        - luisgomez@h2oins.com
        - juanmanuel@h2oins.com
      new_venture:
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

- [ ] **Step 5: Run tests to verify they pass**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/quote_queue/test_runner.py -v`
Expected: PASS (helper + previos).

Verificación de carga real de la config (opcional pero recomendado):
Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -c "from modules.config_manager import reload_config; from modules.quote_queue import runner; c=reload_config(); rt,nv=runner._load_sender_sets(c); print('RT', sorted(rt)); print('NV', sorted(nv))"`
Expected: RT con 5 correos, NV con 11 correos, todos en minúscula.

- [ ] **Step 6: Commit**

```bash
git add modules/quote_queue/runner.py config/settings.yaml tests/quote_queue/test_runner.py
git commit -m "feat(monitor): config de remitentes de ventas + wiring en run_forever"
```

---

### Task 5: Suite completa verde

**Files:** ninguno (verificación).

- [ ] **Step 1: Correr toda la suite**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest -q`
Expected: PASS (sin regресiones). Si hay fallos PRE-EXISTENTES no relacionados (ej. 2 fails conocidos de `rule_engine`), documentarlos como pre-existentes y NO atribuirlos a este cambio.

- [ ] **Step 2: (Sin commit)** — reportar resultado al usuario.
