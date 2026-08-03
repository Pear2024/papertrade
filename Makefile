.PHONY: help env up down logs ps migrate seed test reset-db health api-shell web-shell

help:
	@echo "Paper Crypto Coach — common commands"
	@echo ""
	@echo "  make env        Copy .env.example to .env (if missing)"
	@echo "  make up         Start development stack (Docker Compose)"
	@echo "  make down       Stop services"
	@echo "  make logs       Tail service logs"
	@echo "  make ps         Show running containers"
	@echo "  make health     Hit API /health and /ready"
	@echo "  make migrate    Run Alembic migrations (Phase 2+)"
	@echo "  make seed       Seed database (Phase 2+)"
	@echo "  make test       Run API tests (Phase 6)"
	@echo "  make reset-db   Reset MySQL volume and restart"
	@echo "  make api-shell  Open shell in API container"
	@echo "  make web-shell  Open shell in web container"

env:
	@if [ ! -f .env ]; then cp .env.example .env; echo "Created .env from .env.example"; else echo ".env already exists"; fi

up: env
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f

ps:
	docker compose ps

health:
	@curl -sf http://localhost:8000/health && echo ""
	@curl -sf http://localhost:8000/ready && echo ""

migrate:
	docker compose exec api alembic upgrade head

seed:
	docker compose exec api python -m app.db.seed

test:
	docker compose exec api pytest -v

reset-db:
	docker compose down -v
	docker compose up --build -d

api-shell:
	docker compose exec api /bin/sh

web-shell:
	docker compose exec web /bin/sh
