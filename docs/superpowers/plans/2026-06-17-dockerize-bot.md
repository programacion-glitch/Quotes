# Dockerizar el bot autónomo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Empaquetar el bot autónomo (runner: monitor Gmail + cola + RPA Playwright + análisis Gmail) en un contenedor Docker que corre en el host Windows (Docker Desktop), 24/7.

**Architecture:** Imagen base oficial de Playwright (Chromium + deps), entrypoint `python -m modules.quote_queue.runner`. El proxy de IA (servicio Windows del host) se alcanza por `host.docker.internal`. Secretos/sesiones/cola por el volumen `./data`. GEICO detrás de un flag **env-driven** (Progressive ON / GEICO OFF al arrancar; GEICO ON tras validar Incapsula en Linux).

**Tech Stack:** Docker / Docker Compose, `mcr.microsoft.com/playwright/python`, Python 3.x, Playwright/Chromium. Python host (tests): `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe`.

**Spec:** `docs/superpowers/specs/2026-06-17-dockerize-bot-design.md`

**Notas para el ejecutor:**
- Las tareas 1–2 son cambios de código (con verificación offline: pytest + pyflakes). Las tareas 3–5 son archivos Docker (verificación offline: `yaml.safe_load`, lectura). El `docker build` / `docker compose up` reales son una **validación LIVE en el host** (sección al final) — NO se corren como parte del subagent-driven (requieren Docker Desktop y bajan una imagen grande).
- Intérprete: SIEMPRE `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe`.
- Tras cada cambio de código: `pyflakes` sobre lo tocado.
- Commits frecuentes. Branch: `progressive-basepage-hardening`. Mensajes terminan con `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- NUNCA commitear `.env`, `data/token.json`, `data/credentials.json`, sesiones ni PDFs de clientes.

---

## File Structure

| Archivo | Cambio | Responsabilidad |
|---|---|---|
| `config/settings.yaml` | modificar | `rule_engine.geico_queue_enabled` pasa a `${GEICO_QUEUE_ENABLED}` (env-driven) |
| `.env` | modificar (NO commit) | agregar `GEICO_QUEUE_ENABLED=true` (host queda ON) |
| `tests/test_rpa_mgas_flag.py` | crear | guard de `_rpa_mgas_enabled` (true/bool/false/placeholder) |
| `modules/progressive/client.py` | modificar | `chromium.launch` con `--no-sandbox --disable-dev-shm-usage` (root en contenedor) |
| `Dockerfile` | reescribir | base Playwright + `playwright install chromium` + entrypoint runner |
| `docker-compose.yml` | modificar | env (OPENAI_BASE_URL/headless/GEICO flag), extra_hosts, shm, healthcheck |
| `.dockerignore` | modificar | excluir `data/` del build context (PDFs/secretos/db) |

---

## Task 1: Flag de GEICO env-driven

**Files:**
- Modify: `config/settings.yaml` (sección `rule_engine:`)
- Modify: `.env` (NO commit)
- Create: `tests/test_rpa_mgas_flag.py`

`_rpa_mgas_enabled(config)` en `workflow_orchestrator.py` ya hace
`str(config.get("rule_engine.geico_queue_enabled", False)).lower() in ("true","1","yes")`,
así que tolera strings. El test fija ese contrato (incluido el caso peligroso:
placeholder `${...}` sin resolver ⇒ GEICO OFF, lo que obliga a setear la var en
`.env`).

- [ ] **Step 1: Crear `tests/test_rpa_mgas_flag.py`**

```python
"""Guard de _rpa_mgas_enabled: GEICO es env-driven (string/bool tolerante)."""
from workflow_orchestrator import _rpa_mgas_enabled


class _Cfg:
    def __init__(self, val):
        self._val = val

    def get(self, key, default=None):
        if key == "rule_engine.geico_queue_enabled":
            return self._val
        return default


def test_geico_on_when_string_true():
    assert _rpa_mgas_enabled(_Cfg("true")) == {"PROGRESSIVE", "GEICO"}


def test_geico_on_when_bool_true():
    assert _rpa_mgas_enabled(_Cfg(True)) == {"PROGRESSIVE", "GEICO"}


def test_geico_off_when_string_false():
    assert _rpa_mgas_enabled(_Cfg("false")) == {"PROGRESSIVE"}


def test_geico_off_when_unresolved_placeholder():
    # Si la var de entorno no está seteada, config deja el literal "${...}":
    # debe quedar GEICO OFF (señal de que hay que setear GEICO_QUEUE_ENABLED).
    assert _rpa_mgas_enabled(_Cfg("${GEICO_QUEUE_ENABLED}")) == {"PROGRESSIVE"}
```

- [ ] **Step 2: Correr el test (debe PASAR ya — es un guard del comportamiento actual)**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_rpa_mgas_flag.py -q`
Expected: 4 passed. (La función ya tolera strings; el test bloquea el contrato del que depende el cambio de yaml.)

- [ ] **Step 3: En `config/settings.yaml`, hacer el flag env-driven. REPLACE:**
```yaml
  # Encender GEICO en la cola RPA (Progressive siempre ON)
  geico_queue_enabled: true
```
con:
```yaml
  # Encender GEICO en la cola RPA (Progressive siempre ON). Env-driven para
  # poder togglear GEICO en el contenedor sin editar el yaml (de-risk Incapsula).
  geico_queue_enabled: "${GEICO_QUEUE_ENABLED}"
```

- [ ] **Step 4: En `.env`, agregar (NO se commitea) — el host queda con GEICO ON:**
```
GEICO_QUEUE_ENABLED=true
```
(Si ya existiera la clave, dejarla en `true`.)

- [ ] **Step 5: Verificar que la config resuelve el flag en el host**

Run:
```
C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -c "from modules.config_manager import reload_config; c=reload_config(); print(repr(c.get('rule_engine.geico_queue_enabled')))"
```
Expected: `'true'` (resuelto desde `.env`). Si imprime `'${GEICO_QUEUE_ENABLED}'`, falta la línea en `.env` (volver al Step 4).

- [ ] **Step 6: Suite verde + commit (solo yaml y test; NO el .env)**
```
C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_rpa_mgas_flag.py -q
git add config/settings.yaml tests/test_rpa_mgas_flag.py
git commit -m "feat(config): flag GEICO env-driven (GEICO_QUEUE_ENABLED) para togglear en el contenedor

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Progressive lanza Chromium con --no-sandbox (root en contenedor)

**Files:**
- Modify: `modules/progressive/client.py` (~L122, dentro de `_run_with_browser`)

En un contenedor corriendo como root, Chromium **se niega a arrancar sin
`--no-sandbox`**. GEICO ya lo pasa (vía `stealth.launch_kwargs`); Progressive
lanza plano. Agregar los args (inofensivos en el host).

- [ ] **Step 1: REPLACE en `modules/progressive/client.py`:**
```python
            browser = await pw.chromium.launch(headless=config.headless)
```
con:
```python
            browser = await pw.chromium.launch(
                headless=config.headless,
                # --no-sandbox: Chromium se niega a arrancar como root en el
                # contenedor sin esto. --disable-dev-shm-usage: evita crashes por
                # /dev/shm chico. Inofensivos en el host.
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
```

- [ ] **Step 2: pyflakes + suite de Progressive (no debe romperse nada)**
```
C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pyflakes modules/progressive/client.py
C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/progressive/ -q
```
Expected: pyflakes limpio; tests de Progressive verdes (el cambio es solo args de launch; no hay test de browser real).

- [ ] **Step 3: Commit**
```
git add modules/progressive/client.py
git commit -m "fix(progressive): lanzar Chromium con --no-sandbox para correr en contenedor (root)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Reescribir el Dockerfile (imagen RPA-capable)

**Files:**
- Modify: `Dockerfile` (reescritura completa)

La imagen actual (`python:3.11-slim`, sin navegador, CMD a un entrypoint que ya
no existe) no sirve para el bot. Reescribir con base de Playwright + entrypoint
runner.

- [ ] **Step 1: Reemplazar TODO el contenido de `Dockerfile` por:**
```dockerfile
# Imagen oficial de Playwright: trae Chromium + todas las libs de sistema.
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt \
    && python -m playwright install chromium

COPY modules/ ./modules/
COPY workflow_orchestrator.py ./

# config/, data/, .env y logs/ entran por volumen / env_file (no se hornean).
RUN mkdir -p /app/data /app/logs

# Entrypoint: el runner (monitor Gmail + workers por MGA + cola).
CMD ["python", "-u", "-m", "modules.quote_queue.runner"]
```

- [ ] **Step 2: Verificar que el Dockerfile referencia el entrypoint correcto**

Run: `grep -n "modules.quote_queue.runner" Dockerfile`
Expected: una línea con el `CMD`. (Confirma que NO quedó el `workflow_orchestrator.py` viejo.)

- [ ] **Step 3: Commit**
```
git add Dockerfile
git commit -m "build(docker): imagen base Playwright (Chromium) + entrypoint runner

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Actualizar docker-compose.yml

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Reemplazar TODO el contenido de `docker-compose.yml` por:**
```yaml
services:
  h2o-quote-bot:
    build: .
    image: h2o-quote-rpa:latest
    container_name: h2o-quote-bot
    restart: unless-stopped
    env_file:
      - .env
    environment:
      # Proxy de IA (clasificador de commodities) = servicio Windows del host.
      - OPENAI_BASE_URL=http://host.docker.internal:3000/v1
      # Sin display en el contenedor: ambos MGAs headless (page.pdf() lo soporta).
      - GEICO_HEADLESS=true
      - PROGRESSIVE_HEADLESS=true
      # De-risk Incapsula: Progressive ON, GEICO OFF hasta validar en Linux.
      # Cambiar a true (o quitar) cuando GEICO pase Incapsula en el contenedor.
      - GEICO_QUEUE_ENABLED=false
    extra_hosts:
      - "host.docker.internal:host-gateway"
    shm_size: "1gb"            # estabilidad de Chromium
    volumes:
      - ./config:/app/config:ro
      - ./data:/app/data       # token/credenciales/sesiones/cola/PDFs/cutoff (persistente)
      - ./logs:/app/logs
    healthcheck:
      test: ["CMD", "pgrep", "-f", "modules.quote_queue.runner"]
      interval: 60s
      timeout: 10s
      retries: 3
```

- [ ] **Step 2: Validar que el YAML es sintácticamente correcto (offline)**

Run:
```
C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -c "import yaml; d=yaml.safe_load(open('docker-compose.yml',encoding='utf-8')); s=d['services']['h2o-quote-bot']; assert 'modules.quote_queue.runner' in ' '.join(s['healthcheck']['test']); assert s['environment']; print('compose OK')"
```
Expected: `compose OK`.

- [ ] **Step 3: Commit**
```
git add docker-compose.yml
git commit -m "build(docker): compose para el bot (host.docker.internal IA, headless, GEICO flag, shm, healthcheck runner)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: .dockerignore — excluir data/ del build context

**Files:**
- Modify: `.dockerignore`

`data/` tiene PDFs de clientes, `token.json`, `credentials.json`, sesiones y la
DB. No deben entrar al build context (la imagen solo copia `modules/` +
`workflow_orchestrator.py`; igual conviene excluir `data/` para que no se suba al
daemon ni quede en capas por accidente).

- [ ] **Step 1: Agregar `data/` a `.dockerignore`** (después de la línea `.env`):
```
data
```

- [ ] **Step 2: Verificar**

Run: `grep -nx "data" .dockerignore`
Expected: una línea `data`.

- [ ] **Step 3: Commit**
```
git add .dockerignore
git commit -m "build(docker): excluir data/ (PDFs/secretos/db) del build context

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Verificación offline final (host, sin Docker)

**Files:** ninguno (solo verificación).

- [ ] **Step 1: Suite completa verde**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/ -q`
Expected: todo verde salvo los 2 fallos PRE-EXISTENTES de `tests/test_rule_engine.py` (TestBusinessYears::test_business_years_too_low, TestInformational::test_informational_passed_through). Ningún fallo nuevo (el flag GEICO y el arg de Progressive no rompen nada).

- [ ] **Step 2: Import-smoke del runner (host)**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -c "from modules.quote_queue import runner; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: pyflakes de lo tocado**

Run: `C:\Users\Usuario\AppData\Local\Programs\Python\Python312\python.exe -m pyflakes modules/progressive/client.py workflow_orchestrator.py`
Expected: sin salida.

(No hay commit en esta tarea salvo que algún paso requiera un ajuste.)

---

## Validación LIVE (host con Docker Desktop — la corre el operador, NO el subagent-driven)

Requiere Docker Desktop corriendo + el servicio "OpenAI Local Proxy" arriba en el host. Bajar la imagen base de Playwright tarda varios minutos la primera vez.

1. **Build:** `docker compose build` (o `docker build -t h2o-quote-rpa:latest .`). Esperado: build OK.
2. **Smoke de imports en la imagen:**
   `docker run --rm h2o-quote-rpa:latest python -c "from modules.quote_queue import runner; from modules.gmail_client import GmailClient; import workflow_orchestrator; print('ok')"`
   Esperado: `ok`.
3. **Arranque:** `docker compose up -d` → `docker compose logs -f`. Esperado: el log imprime `[runner] corte por fecha: ...` y los workers; healthcheck pasa a verde (`docker ps` → healthy).
4. **Ciclo Progressive (GEICO OFF):** mandar a quotes@ un correo de prueba (asunto matchea "Submission" + BlueQuote Progressive-elegible) → verificar que cotiza y responde en hilo a quotes@ con CC programacion@ + PDF adjunto + etiqueta `Cotizado-Bot`. Confirma que el RPA headless + `page.pdf()` andan en el contenedor.
5. **Validar GEICO/Incapsula en el contenedor:** poner `GEICO_QUEUE_ENABLED=true` (compose `environment`), `docker compose up -d`, mandar un correo GEICO-elegible. Si cotiza → GEICO ON. Si aparece "There was a problem while processing…" (Incapsula bloqueó el Chromium Linux) → afinar `modules/geico/stealth.py` para Linux (UA/headers, o instalar/forzar canal Chrome estable) y reintentar; mientras tanto GEICO queda OFF.
6. **Apagar el runner del host** si estaba corriendo, para que el contenedor sea el único usando las sesiones (sesión única por MGA). El host conserva solo el servicio del proxy de IA.

---

## Self-Review (autor del plan)

**Cobertura del spec:**
- Imagen base Playwright + entrypoint runner → Task 3. ✓
- compose (OPENAI_BASE_URL host.docker.internal, extra_hosts, headless, GEICO flag, shm, healthcheck) → Task 4. ✓
- Flag GEICO env-driven (yaml `${...}` + .env + guard test) → Task 1. ✓
- Progressive `--no-sandbox` (root en contenedor) → Task 2. ✓
- `.dockerignore` excluye `data/` → Task 5. ✓
- Secretos/sesiones por volumen → cubierto por el compose (Task 4) + .dockerignore (Task 5). ✓
- Validación anti-bot + build + arranque → sección LIVE (manual). ✓

**Placeholders:** ninguno — cada step tiene contenido/comando real.

**Consistencia:** el entrypoint `modules.quote_queue.runner` es idéntico en Dockerfile (Task 3) y el healthcheck (Task 4). El flag `GEICO_QUEUE_ENABLED` es coherente entre `settings.yaml` (`${GEICO_QUEUE_ENABLED}`, Task 1), `.env` (=true, host, Task 1) y compose (`environment: =false`, container, Task 4). `OPENAI_BASE_URL` lo lee `config.openai_base_url` (ya existe en config_manager). `GEICO_HEADLESS`/`PROGRESSIVE_HEADLESS` son los nombres reales que leen los clientes. ✓
