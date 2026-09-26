# Локальная разработка и тесты

Серверный деплой описан в [README](../README.md). Этот документ — для рабочей машины.
Нужны Python `>=3.13` и [uv](https://docs.astral.sh/uv/). Команды выполняются из корня репозитория.

## Demo без модели

```bash
uv sync --locked
cp .env.example .env
uv run --env-file .env uvicorn arena_ai.app:app --host 127.0.0.1 --port 8000 --reload
```

Копирование env — только для первого запуска, не перезаписывайте существующий файл.
По умолчанию включён demo: модель и RAG не нужны. В другом терминале:

```bash
uv run arena-ai --api-url http://127.0.0.1:8000
```

Команды клиента: `:history`, `:finish`, `:quit`. Карточку подготовки можно задать
через `--preparation-file docs/api/examples/preparation-card.json`.
Клиент предназначен для локального API без service token, не для защищённого сервера.

## Реальный режим

В `.env` задайте `ARENA_MODEL_MODE=qwen`, фактические `ARENA_QWEN_CHAT_URL`,
`ARENA_QWEN_MODEL`, `ARENA_QDRANT_URL` и `ARENA_EMBEDDINGS_URL`.
Приложение не читает env само: используйте `uv run --env-file .env`.
Судьям нужен [проверенный индекс](judge-corpus.md); удалённый loopback доступен
через [SSH-туннель](integration/server-deployment.md#проверка-с-рабочей-машины).

## Проверки кода

```bash
uv run pytest
uv run ruff check src tests scripts
uv run ty check
uv run python scripts/export_openapi.py --check
```

Обычные тесты не требуют живой модели. Проверка методических страниц пропускается,
если отдельно предоставленные исходники отсутствуют.

Полный конфликтный сценарий против локального API в реальном режиме:

```bash
uv run --env-file .env arena-ai-eval --api-url http://127.0.0.1:8000 \
  --scenario adversarial --runs 1 --timeout 900 --progress \
  --output /tmp/arena-adversarial.json
```

Команда вызывает модель; отчёт содержит безопасные статусы, не реплики и секреты.
Минимальный smoke не заменяет полный сценарий.
