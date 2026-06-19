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
