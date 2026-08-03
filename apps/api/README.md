# Paper Crypto Coach API

FastAPI backend for paper (simulated) crypto trading.

## Phase 1

- App factory in `app/main.py`
- Settings via `pydantic-settings`
- SQLAlchemy engine stub (models in Phase 2)
- `GET /health`, `GET /ready`

## Local run (without Docker)

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Point `DATABASE_URL` at `localhost` instead of `db` when MySQL runs in Compose and the API runs on the host.
