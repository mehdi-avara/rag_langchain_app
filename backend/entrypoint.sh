#!/bin/sh
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Seeding database..."
python -m db.seed_rbac

echo "Provisioning starter defaults for all companies..."
python -m db.provision_company_defaults

echo "Starting server..."
exec uvicorn api:app --host 0.0.0.0 --port 8000
