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
# Xvfb directo (NO xvfb-run: requiere xdpyinfo, ausente en la imagen, y se
# queda colgado esperando el server). GEICO corre HEADFUL (Imperva bloquea el
# chromium-headless-shell con Error 15 'Access denied', 2026-07-31) y
# necesita este display virtual.
CMD ["sh", "-c", "Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp & for i in $(seq 1 50); do [ -e /tmp/.X11-unix/X99 ] && break; sleep 0.1; done; DISPLAY=:99 exec python -u -m modules.quote_queue.runner"]
