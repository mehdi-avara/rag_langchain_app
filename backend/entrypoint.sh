#!/bin/sh
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Seeding database..."
python -m db.seed_rbac

echo "Starting server..."
exec uvicorn api:app --host 0.0.0.0 --port 8000
