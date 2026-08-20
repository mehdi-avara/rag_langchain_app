# Base (minimal, shared)
ARG PYTHON_BASE_IMAGE=python:3.11-slim
FROM ${PYTHON_BASE_IMAGE} AS base

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
    build-essential \
    libgl1 \
    libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

COPY requirements_celery.txt .
RUN pip install --no-cache-dir -r requirements_celery.txt \
    --extra-index-url https://download.pytorch.org/whl/cu121


# App code (backend)
FROM deps AS backend

RUN groupadd --gid 1007 porsa \
 && useradd \
    --uid 1006 \
    --gid 1007 \
    --no-create-home \
    --home-dir /nonexistent \
    --shell /usr/sbin/nologin \
    porsa

COPY --chown=0:1007 . .

RUN chgrp 1007 /app \
 && find /app -xdev -type d -exec chmod g+rx,g-w,o-rwx {} + \
 && find /app -xdev -type f -exec chmod g+r,g-w,o-rwx {} + \
 && chmod 750 /app/entrypoint.sh

ENV HOME=/tmp

EXPOSE 8000
USER 1006:1007
CMD ["/app/entrypoint.sh"]

# App code (celery)
FROM celery-deps AS celery

RUN groupadd --gid 1007 porsa \
 && useradd \
    --uid 1006 \
    --gid 1007 \
    --no-create-home \
    --home-dir /nonexistent \
    --shell /usr/sbin/nologin \
    porsa

COPY --chown=0:1007 . .

RUN chgrp 1007 /app \
 && find /app -xdev -type d -exec chmod g+rx,g-w,o-rwx {} + \
 && find /app -xdev -type f -exec chmod g+r,g-w,o-rwx {} +

ENV HOME=/tmp

USER 1006:1007
CMD ["celery", "-A", "core.celery.celery_app.celery_app", "worker", "-l", "info"]
