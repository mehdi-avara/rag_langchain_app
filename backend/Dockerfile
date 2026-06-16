# Base (minimal, shared)
FROM python:3.11-slim AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Python dependencies (shared)
FROM base AS deps

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Celery system deps
FROM deps AS celery-deps

RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

COPY requirements_celery.txt .
RUN pip install --no-cache-dir -r requirements_celery.txt \
    --extra-index-url https://download.pytorch.org/whl/cu121


# App code (backend)
FROM deps AS backend

COPY . .
EXPOSE 8000
RUN chmod +x /app/entrypoint.sh
CMD ["/app/entrypoint.sh"]

# App code (celery)
FROM celery-deps AS celery

COPY . .
CMD ["celery", "-A", "core.celery.celery_app.celery_app", "worker", "-l", "info"]