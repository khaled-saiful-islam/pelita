#!/usr/bin/env bash
# Everything that must happen between "Postgres is healthy" and "the API is
# serving". `make up` does no manual steps, so this script is where the steps go.
set -euo pipefail

echo "[entrypoint] running migrations"
alembic upgrade head

if [ -f app/scripts/seed.py ]; then
  echo "[entrypoint] seeding"
  python -m app.scripts.seed
fi

echo "[entrypoint] starting: $*"
exec "$@"
