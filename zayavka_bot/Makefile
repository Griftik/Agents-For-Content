.PHONY: install run test migrate docker-up docker-logs

install:
	python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

run:
	.venv/bin/python -m bot.main

test:
	.venv/bin/python -m pytest -q

migrate:
	.venv/bin/alembic upgrade head

docker-up:
	docker compose up -d --build

docker-logs:
	docker compose logs -f --tail=100
