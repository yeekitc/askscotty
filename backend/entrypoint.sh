#!/bin/bash
set -e

echo "Waiting for database..."
python - <<'PY'
import os
import time

import psycopg2

host = os.environ.get("POSTGRES_HOST", "db")
port = int(os.environ.get("POSTGRES_PORT", "5432"))
name = os.environ.get("POSTGRES_DB", "askscotty")
user = os.environ.get("POSTGRES_USER", "askscotty")
password = os.environ.get("POSTGRES_PASSWORD", "askscotty")

for attempt in range(60):
    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            dbname=name,
            user=user,
            password=password,
        )
        conn.close()
        print("Database is ready.")
        break
    except psycopg2.OperationalError:
        time.sleep(1)
else:
    raise SystemExit("Database did not become ready in time.")
PY

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"
