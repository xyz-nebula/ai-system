# Запуск всего стека (AI + Qdrant + эмбеддинги); нужен заполненный .env.
up:
    docker compose up -d --build

down:
    docker compose down

logs:
    docker compose logs -f ai

# Локальный запуск без Docker, с переменными из .env.
run-dev: sync
    ARENA_MODEL_MODE=qwen ARENA_V2_ENABLED=true uv run --env-file .env uvicorn arena_ai.app:app --reload --port 8000

build-docker:
    docker build -t ai-system .

sync:
    uv sync --dev

lint: sync
    uv run ruff check .

fmt: sync
    uv run ruff format .

fmt-check: sync
    uv run ruff format --check .

typecheck: sync
    uv run ty check

test: sync
    uv run pytest -q

check: lint fmt-check typecheck test
