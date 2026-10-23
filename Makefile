.PHONY: db seed test lint eval api web corpus

db:          ## Postgres 16 + pgvector on localhost:5433
	docker compose up -d --wait db

seed: db     ## schema, row-level security, users and the 31-document corpus
	cd api && uv run python -m app.cli seed

test: db     ## 197 API tests with the offline providers (no keys needed)
	cd api && uv run pytest -q

lint:
	cd api && uv run ruff check . ../eval ../seed && uv run ruff format --check . && uv run mypy app
	cd web && pnpm exec tsc --noEmit && pnpm lint

eval:        ## golden sets; uses the providers configured in .env
	cd api && uv run python ../eval/run_eval.py --throttle 7

api:
	cd api && uv run uvicorn app.main:app --port 8000 --reload

web:
	cd web && pnpm dev

corpus:      ## regenerate seed/corpus (needs WeasyPrint and pango; the files are committed)
	cd api && uv run --group corpus python ../seed/generate_corpus.py
