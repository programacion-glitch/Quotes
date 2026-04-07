FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps for PyMuPDF / pdfplumber
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libxml2 \
        libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY modules/ ./modules/
COPY workflow_orchestrator.py ./

# Config, .env and data are mounted as volumes at runtime
RUN mkdir -p /app/config /app/data/input /app/data/output /app/logs

CMD ["python", "-u", "workflow_orchestrator.py"]
