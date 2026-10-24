#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
set -a
. ./.env
set +a
exec .venv/bin/python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port "${PORT:-8000}" --workers 1 --no-access-log
