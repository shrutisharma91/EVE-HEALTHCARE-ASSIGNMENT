#!/bin/sh
set -eu

python <<'PY'
import os
import sys
import time

import psycopg

url = os.environ.get("DATABASE_URL", "")
if url.startswith("postgres://"):
    url = "postgresql://" + url[len("postgres://") :]

for attempt in range(30):
    try:
        with psycopg.connect(url) as conn:
            conn.execute("SELECT 1")
        break
    except Exception:
        if attempt == 29:
            print("database did not become ready", file=sys.stderr)
            sys.exit(1)
        time.sleep(1)
PY

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  python manage.py migrate --noinput
fi

if [ "${SEED_DATA:-false}" = "true" ]; then
  python manage.py seed_data
fi

exec "$@"
