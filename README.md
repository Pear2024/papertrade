# Paper Crypto Coach

Web app for practicing crypto trading with **simulated money only**.  
Starting paper balance: **$100.00 USD**.

> **Paper Trading Mode** — เงินทั้งหมดในระบบเป็นเงินจำลอง ไม่มีการซื้อขายเงินจริง  
> This is **not** financial advice. No live exchange orders, no deposits, no withdrawals.

---

## Overview

Paper Crypto Coach helps beginners build trading discipline:

- View crypto prices (public API, no secret keys)
- Buy / sell with paper cash
- Track positions, P&L, journals, and risk rules
- Reset account back to $10
- Future: mock AI Trading Coach (learning tips only)

**Version 1 is paper-only.** Real-money trading and API secrets for live trading are intentionally out of scope.

---

## Technology stack

| Layer | Stack |
|-------|--------|
| Frontend | Next.js, TypeScript, Tailwind CSS, (shadcn/ui in Phase 4+) |
| Backend | Python, FastAPI, SQLAlchemy, Alembic, Pydantic |
| Database | MySQL 8 |
| Dev | Docker Compose, ESLint, Prettier, Pytest |
| Shared | `packages/shared` (constants / types) |

---

## Requirements

- Docker Desktop (or Docker Engine + Compose v2)
- Git
- Optional for local (non-Docker) API/web: Node.js 22+, Python 3.12+

---

## Project structure

```
paper_crypto-coach/
├── apps/
│   ├── web/          # Next.js frontend
│   └── api/          # FastAPI backend
├── packages/
│   └── shared/       # Shared TypeScript constants/types
├── docker-compose.yml
├── .env.example
├── Makefile          # Convenience targets (Unix/macOS; Git Bash on Windows)
└── README.md
```

---

## Setup

### 1. Clone and configure environment

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and change passwords / `JWT_SECRET` before any shared or production use.  
**Never commit `.env` or real secrets.**

### 2. Start development (Docker Compose)

```bash
docker compose up --build
```

Detached:

```bash
docker compose up --build -d
```

Services:

| Service | URL |
|---------|-----|
| Web | http://localhost:3001 |
| API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |
| MySQL | localhost:3306 |

Stop:

```bash
docker compose down
```

Reset database volume (destructive):

```bash
docker compose down -v
docker compose up --build -d
```

### 3. Health checks

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

- `/health` — process is alive  
- `/ready` — MySQL is reachable  

Compose waits for MySQL **healthcheck** before starting the API.  
The web service waits until the API healthcheck passes.

### Hypothesis Lab free LLM parsing

The Lab always works without an LLM: it falls back to the built-in rules engine.
LLM credentials are read only by the API server—never put them in
`NEXT_PUBLIC_*` variables or browser code.

- **Local development (default):** install Ollama, run `ollama pull llama3.2`,
  and keep `OLLAMA_BASE_URL=http://127.0.0.1:11434` and
  `OLLAMA_MODEL=llama3.2` in `.env`. The API tries Ollama first and falls back
  automatically if it is stopped.
- **Deployed website:** set `ENVIRONMENT=production` and `GROQ_API_KEY` in the
  API host's `.env`. The production API tries Groq first, so every logged-in
  website user can generate structured rules without running Ollama locally.
  `GROQ_MODEL=llama-3.1-8b-instant` is the default.
- **API in Docker + host Ollama:** `127.0.0.1` points to the API container, not
  your host. Set `OLLAMA_BASE_URL=http://host.docker.internal:11434` on Docker
  Desktop, or use the reachable hostname of an Ollama service on the same
  network.

After changing API environment variables, restart the API:

```bash
docker compose up -d --build api
```

---

## Migrations

With Docker:

```bash
docker compose exec api alembic upgrade head
```

Locally (from `apps/api` with venv active):

```bash
alembic upgrade head
```

The API Docker entrypoint waits for MySQL, then runs `alembic upgrade head` automatically.

---

## Seed database

Development only (`ENVIRONMENT=development`):

```bash
docker compose exec api python -m app.db.seed
```

Locally:

```bash
python -m app.db.seed
```

Demo user (development only):

- Email: `demo@example.com`
- Password: `Demo1234!`
- Paper account starting balance: `$100.00`
- Seed assets: BTC, ETH, SOL (+ small sample trades/journals)

---

## Tests

```bash
docker compose exec api pytest -v
```

Or locally inside `apps/api` with a venv:

```bash
cd apps/api
python -m venv .venv
# Windows: .venv\Scripts\activate
# Unix: source .venv/bin/activate
pip install -r requirements.txt
pytest -v
```

---

## API documentation

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Service info |
| GET | `/health` | Liveness |
| GET | `/ready` | Readiness (DB) |
| GET | `/docs` | OpenAPI (Swagger) |
| POST | `/auth/register` | Create user + paper account ($10) |
| POST | `/auth/login` | JWT login |
| GET | `/auth/me` | Current user (Bearer token) |

| GET | `/assets` | List tradeable assets |
| GET | `/assets/{symbol}` | Asset detail |
| GET | `/prices` | Current prices (public API + snapshot fallback) |
| GET | `/prices/{symbol}` | Price for one symbol |
| GET | `/account` | Active paper account |
| GET | `/account/summary` | Portfolio summary + positions |
| POST | `/orders/buy` | Paper market buy |
| POST | `/orders/buy/preview` | Buy preview (fee, cash after, risk) |
| POST | `/orders/sell` | Paper market sell |
| GET | `/orders` | Order history |
| GET | `/orders/{id}` | Order detail |
| POST | `/orders/{id}/cancel` | Cancel pending order |
| GET | `/positions` | Open positions |
| GET | `/positions/{symbol}` | Position by symbol |
| GET | `/trades` | Trade history |
| GET | `/trades/{id}` | Trade detail |

| GET | `/account/settings` | Risk rules + fee info |
| PATCH | `/account/settings` | Update starting balance / risk rules |
| POST | `/account/reset` | Reset paper account (confirm required) |
| GET | `/account/reset-history` | Reset history |
| GET/POST | `/journal` | List / create journals |
| GET/PATCH/DELETE | `/journal/{id}` | Journal detail / update / delete |
| GET | `/analytics/overview` | Performance overview |
| GET | `/analytics/performance` | Alias of overview |
| GET | `/analytics/discipline` | Plan / stop-loss discipline |
| GET | `/analytics/by-asset` | P&L by symbol |
| GET | `/analytics/by-emotion` | Stats by emotional state |

Coach endpoints arrive in Phase 6.

---

## Makefile helpers (optional)

If you have `make` available:

```bash
make env      # copy .env.example → .env
make up       # docker compose up --build -d
make down
make logs
make health
make migrate
make seed
make test
make reset-db
```

---

## Paper trading limitations

- **No** real-money orders  
- **No** exchange API secrets for live trading  
- **No** deposit / withdraw  
- Fees are simulated at 0.80% of notional per fill by default (`PAPER_TRADING_FEE_PERCENT=0.80`), based on the confirmed Kraken Pro receipt; flat fee overrides are disabled (`PAPER_TRADING_FEE_USD=0`)
- Paper leverage (1x–50x) sizes notional as margin × leverage; no funding rate / liquidation engine yet 
- Prices come from a **public** market API; if it fails, the UI/API will surface a clear error (Phase 3+)  
- Monetary columns use **Decimal / Numeric** (not float)

---

## Roadmap

| Phase | Focus |
|-------|--------|
| 1 | Monorepo, Docker Compose, Next.js + FastAPI + MySQL, health checks, README |
| 2 | Models, Alembic, seed, JWT auth |
| 3 | Price service, buy/sell paper orders, positions, trades |
| 4 | Dashboard, market, trade form, portfolio, history |
| **5 (current)** | Journal, analytics, risk rules, account reset |
| 6 | Mock AI Coach, tests, security polish, responsive UI |

---

## Disclaimer

This application is for **education and practice only**.  
It is **not** investment, trading, or financial advice.  
Past simulated results do not predict future outcomes.

---

## Phase status

### Phase 1

- [x] Monorepo (`apps/web`, `apps/api`, `packages/shared`)
- [x] Docker Compose (`web`, `api`, `db`) with MySQL healthcheck
- [x] FastAPI `/health` and `/ready`
- [x] Next.js + Tailwind + dark mode landing page
- [x] `.env.example` and initial README

### Phase 2

- [x] SQLAlchemy models for all core tables
- [x] Alembic migration `0001_initial_schema`
- [x] Seed: BTC/ETH/SOL + demo user + sample activity
- [x] JWT auth: `POST /auth/register`, `POST /auth/login`, `GET /auth/me`
- [x] Register creates paper account ($10) + default risk rules
- [x] Auth pytest coverage

### Phase 3

- [x] Public price service (CoinGecko) + snapshot fallback + clear 503
- [x] Account + account summary
- [x] Paper market buy/sell with Decimal + DB transaction rollback
- [x] Fee, stop-loss requirement, daily trade/loss limits, risk % check
- [x] Positions + trades endpoints
- [x] Trading/money pytest coverage

### Phase 4

- [x] Login / Register (React Hook Form + Zod)
- [x] App shell with nav, dark mode, paper banner
- [x] Dashboard (summary stats, chart, positions, recent trades)
- [x] Market cards (BTC/ETH/SOL)
- [x] Trade panel with preview + confirmation dialog
- [x] Portfolio + Trade History with filters
- [x] TanStack Query + shadcn-style UI primitives

### Phase 5

- [x] Journal CRUD API + UI
- [x] Analytics overview / discipline / by-asset / by-emotion
- [x] Settings: risk rules + starting balance
- [x] Account reset with confirmation + history
- [x] Phase 5 pytest coverage
