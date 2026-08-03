#!/bin/sh
set -e

echo "Waiting for MySQL..."
python - <<'PY'
import os
import time
from sqlalchemy import create_engine, text

url = os.environ["DATABASE_URL"]
for attempt in range(60):
    try:
        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("MySQL is ready")
        break
    except Exception as exc:
        print(f"MySQL not ready ({attempt + 1}/60): {exc}")
        time.sleep(2)
else:
    raise SystemExit("MySQL did not become ready in time")
PY

echo "Running migrations..."
alembic upgrade head

echo "Starting API..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
