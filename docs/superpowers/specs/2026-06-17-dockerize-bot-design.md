# Dockerizar el bot autónomo de cotizaciones — diseño

**Fecha:** 2026-06-17
**Estado:** Diseño aprobado por el usuario, pendiente plan de implementación
**Branch destino:** progressive-basepage-hardening (o branch nuevo)
**Specs relacionados:** `2026-06-17-autonomous-gmail-bot-design.md` (el bot que se dockeriza) · `2026-06-15-rpa-quote-queue-design.md` (la cola)

## Objetivo

Empaquetar el bot autónomo completo (runner: monitor Gmail + cola SQLite + RPA
Playwright de GEICO/Progressive + análisis por Gmail API) en **un solo
contenedor Docker**, corriendo en **el mismo host Windows vía Docker Desktop**,
con `restart: unless-stopped` para operación 24/7.

## Contexto / estado actual

Ya existe infra Docker, pero **vieja e incompleta para el bot nuevo**:

- `Dockerfile`: `python:3.11-slim`, instala `requirements.txt`, copia
  `modules/` + `workflow_orchestrator.py`, `CMD ["python","-u","workflow_orchestrator.py"]`.
  Dos problemas: (1) **no instala Playwright/Chromium** ni sus libs de sistema →
  el RPA no puede correr; (2) el `CMD` apunta a `workflow_orchestrator.py`, cuyo
  `main()`/`__main__` **se eliminó** al migrar el monitor al runner (el entrypoint
  real ahora es `python -m modules.quote_queue.runner`).
- `docker-compose.yml`: monta `./config:ro`, `./data`, `./logs`; `env_file: .env`;
  `restart: unless-stopped`; healthcheck `pgrep -f workflow_orchestrator.py`.
- `requirements.txt`: **sí** incluye `playwright>=1.44.0` (pero el Dockerfile no
  lo "instala" como navegador), `google-api-python-client`, `openai`, etc.
- El **proxy de IA** (clasificador de commodities) corre como **servicio Windows
  en el host** (`http://localhost:3000/v1`, `config.openai_base_url` =
  `OPENAI_BASE_URL` o ese default). Desde un contenedor, `localhost` NO lo
  alcanza → hay que usar `host.docker.internal:3000`.
- **Anti-bot:** GEICO está detrás de Imperva **Incapsula**; `modules/geico/stealth.py`
  emite un fingerprint **Windows** (UA Windows, `sec-ch-ua-platform:"Windows"`,
  timezone Chicago) validado contra Chromium **en el host Windows** (5 quotes
  GEICO el 2026-06-17). En un contenedor **Linux**, el Chromium real es Linux →
  el fingerprint de SO (TLS/JA3, fuentes) cambia y Incapsula **podría bloquear**
  GEICO aunque el UA diga Windows. Progressive no usa Incapsula (menor riesgo).

## Decisiones (acordadas con el usuario)

1. **Alcance: TODO en un contenedor**, incluido el RPA. (La alternativa —RPA en
   host + intake en contenedor— se descartó: partiría el runner en dos procesos
   compartiendo la SQLite por un bind-mount host/contenedor, frágil por el
   file-locking de WAL, y duplica lo que hay que operar.)
2. **Dónde corre:** mismo host Windows, **Docker Desktop**. → proxy de IA por
   `host.docker.internal`; `token.json`/`credentials`/sesiones por el volumen
   `./data`; egress igual que hoy (todo 443).
3. **Imagen base:** oficial de Playwright (`mcr.microsoft.com/playwright/python`)
   — Chromium + libs de sistema ya emparejados. (Alternativas descartadas:
   slim + `playwright install --with-deps` = manejar el drift a mano; slim + libs
   manuales = frágil.)
4. **GEICO detrás del flag al arrancar:** primera corrida del contenedor con
   **Progressive ON / GEICO OFF**; GEICO se enciende tras validar Incapsula
   dentro del contenedor. El flag pasa a ser **env-driven** para togglearlo sin
   editar el yaml.
5. **Sesión única:** una vez dockerizado, el bot corre **solo en el contenedor**
   (no el runner en el host) para no pelear las sesiones GEICO/Progressive
   (archivos compartidos por el volumen `./data`). El host conserva solo el
   servicio del proxy de IA.

## Arquitectura

### `Dockerfile` (reescritura)

```dockerfile
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 PYTHONUTF8=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt \
    && python -m playwright install chromium

COPY modules/ ./modules/
COPY workflow_orchestrator.py ./

RUN mkdir -p /app/data /app/logs
CMD ["python", "-u", "-m", "modules.quote_queue.runner"]
```

- La base de Playwright ya trae Chromium + deps; `playwright install chromium`
  re-sincroniza el navegador con la versión de `playwright` que quede instalada
  por `requirements.txt` (defensivo ante drift). `config/`, `data/`, `.env` y
  `logs/` entran por volumen/env_file, NO se hornean (los secretos no quedan en
  la imagen; `.env` ya está en `.dockerignore`).

### `docker-compose.yml` (update)

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
      - OPENAI_BASE_URL=http://host.docker.internal:3000/v1   # proxy IA en el host
      - GEICO_HEADLESS=true
      - PROGRESSIVE_HEADLESS=true
      - GEICO_QUEUE_ENABLED=false        # de-risk: Progressive ON, GEICO OFF al inicio
    extra_hosts:
      - "host.docker.internal:host-gateway"
    shm_size: "1gb"                       # Chromium
    volumes:
      - ./config:/app/config:ro
      - ./data:/app/data                  # token/credenciales/sesiones/cola/PDFs/cutoff
      - ./logs:/app/logs
    healthcheck:
      test: ["CMD", "pgrep", "-f", "modules.quote_queue.runner"]
      interval: 60s
      timeout: 10s
      retries: 3
```

### Flag de GEICO env-driven (cambio de código chico)

`config/settings.yaml`: cambiar `rule_engine.geico_queue_enabled: true` por
`geico_queue_enabled: "${GEICO_QUEUE_ENABLED}"`. Agregar `GEICO_QUEUE_ENABLED=true`
al `.env` (host sigue ON). `_rpa_mgas_enabled` ya hace
`str(config.get("rule_engine.geico_queue_enabled", False)).lower() in ("true","1","yes")`,
que tolera el string resuelto. En compose, `environment: GEICO_QUEUE_ENABLED=false`
override el `.env` para la validación inicial; se flipa a true (o se quita el
override) cuando Incapsula pase en el contenedor.

(Nota: hoy `.env` NO tiene `GEICO_QUEUE_ENABLED`; al pasar el yaml a `${...}` hay
que agregarlo al `.env` o el host quedaría con GEICO OFF. Tarea del plan.)

### Networking / AI proxy

- `host.docker.internal:host-gateway` + `OPENAI_BASE_URL=http://host.docker.internal:3000/v1`
  → el clasificador de commodities alcanza el servicio Windows. La IA es un
  **fallback** (si está caída, el commodity cae a tabla/learned cache; no tumba
  el bot). El contenedor depende de que el servicio "OpenAI Local Proxy" esté
  arriba en el host (ver [[reference-ai-proxy-service]]).
- Gmail (443), GEICO/Progressive (443) y Google Drive (443): egress directo,
  igual que hoy.

### Secretos y volúmenes

- `token.json`, `credentials.json`, `geico_session.json`, `progressive_session.json`,
  `quote_queue.db`, `quote_pdfs/`, `learned_mappings.xlsx`, `submissions/`,
  `bot_since_epoch.txt` → todos en `./data` → montados, persisten entre rebuilds.
  `GmailClient` resuelve `data/token.json` vía `Path(__file__).parents[1]` = `/app`
  → `/app/data/token.json`. ✓
- `.env` por `env_file` (no se hornea). Nada sensible queda en la imagen.

## Validación anti-bot (plan en vivo, post-build)

1. Contenedor con **Progressive ON / GEICO OFF** → mandar un correo de prueba con
   BlueQuote Progressive-elegible; verificar ciclo completo (cotiza, responde en
   hilo + CC + PDF, etiqueta).
2. Corrida controlada de **GEICO** en el contenedor (flag ON temporal): si pasa
   Incapsula → GEICO ON. Si bloquea (página "There was a problem…"): afinar
   `stealth.py` para Linux (UA/headers, o canal de Chrome estable) y reintentar.
3. Confirmar que el RPA headless genera el PDF (`page.pdf()` headless OK).

## Testing (sin red, en el host)

- `docker build .` exitoso.
- Smoke de imports dentro del contenedor:
  `docker run --rm h2o-quote-rpa:latest python -c "from modules.quote_queue import runner; from modules.gmail_client import GmailClient; import workflow_orchestrator; print('ok')"`.
- Arranque: `docker compose up -d` → el log imprime el corte por fecha
  (`[runner] corte por fecha: ...`) y el healthcheck pasa a verde.
- Los unit tests (la suite completa del repo) siguen corriendo en el host (`tests/` está en
  `.dockerignore`, no se hornean). El cambio del flag GEICO no debe romper la
  suite (verificar `_rpa_mgas_enabled` con el string resuelto).

## Fuera de alcance (YAGNI)

- Mover el proxy de IA a un contenedor (sigue como servicio Windows del host).
- CI/registry/push de la imagen; despliegue multi-host; orquestadores (k8s).
- Resolver el anti-bot de GEICO en Linux por adelantado (se valida/afina en vivo;
  GEICO queda tras el flag hasta entonces).
- Xvfb / modo headed en el contenedor (se corre headless; `page.pdf()` lo soporta).
