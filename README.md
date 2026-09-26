# Арена переговоров — AI-сервис

AI-контур тренажёра переговоров на Python и FastAPI: управляемый ход с Guard и
Validator, AI-оппонент, три независимых судьи и отдельный тренерский разбор.
Backend хранит кейс и состояние поединка; STT/TTS принадлежат Audio Engine.

## Запуск

Требуются Python `>=3.13` и [uv](https://docs.astral.sh/uv/).
Команды выполняются из корня репозитория.

```bash
uv sync --locked
cp .env.example .env
uv run --env-file .env uvicorn arena_ai.app:app --host 127.0.0.1 --port 8000 --reload
```

По умолчанию включён `demo`: модель и RAG не нужны, ответы демонстрационные.
В другом терминале запустите текстовый клиент:

```bash
uv run arena-ai --api-url http://127.0.0.1:8000
```

Команды клиента: `:history`, `:finish`, `:quit`. Необязательная карточка подготовки:

```bash
uv run arena-ai --preparation-file docs/api/examples/preparation-card.json
```

Интерактивный клиент предназначен для локального запуска без service token.
Защищённый сервер проверяйте через API или smoke-команды ниже.

## Модель и RAG

Для реальных ответов измените `.env`:

```dotenv
ARENA_MODEL_MODE=qwen
ARENA_QWEN_CHAT_URL=http://localhost:8080/v1/chat/completions
ARENA_QWEN_MODEL=qwen3.8-9b-q4
ARENA_QDRANT_URL=http://127.0.0.1:6333
ARENA_EMBEDDINGS_URL=http://127.0.0.1:8081
```

Нужен OpenAI-compatible Chat Completions gateway. Адрес и model ID должны
соответствовать вашей среде; `localhost` означает машину, где работает AI-сервис.
`.env` загружается через `uv run --env-file`, не самим приложением.

Судьи требуют Qdrant, Qwen3 embeddings и загруженный проверенный корпус:

```bash
docker compose -f deploy/rag/compose.yaml up -d
uv run --env-file .env python scripts/check_rag_stack.py
```

Qdrant и TEI слушают только loopback. Первый запуск TEI скачивает веса модели.
Для первичного индексирования нужны согласованные исходные страницы методик в
`knowledge-base/methodology/`; они предоставляются отдельно и не входят в этот репозиторий:

```bash
uv run --env-file .env python scripts/index_judge_corpus.py --verify-only
uv run --env-file .env python scripts/index_judge_corpus.py
uv run --env-file .env python scripts/index_judge_corpus.py --check-index
```

Если используете уже заполненный серверный индекс, повторно загружать корпус не нужно.
Подробности: [корпус и retrieval](docs/judge-corpus.md).
Readiness проверяет только модель, не готовность RAG. Ошибка retrieval даёт failed-слот
судьи, а не демонстрационный вердикт. Методики не выводятся в итоговой аналитике.

## Docker

Для нового серверного запуска требуются Linux, Docker Compose, доступ к gateway и готовому RAG.
Подставьте приватный IP своей среды; команды ниже выполняются из checkout:

```bash
mkdir -m 700 .secrets
python3 scripts/provision_ai_env.py \
  --destination .secrets/.env --bind-ip 172.16.34.7
docker build -t arena-ai:local .
export ARENA_IMAGE=arena-ai:local
export ARENA_ENV_FILE="$PWD/.secrets/.env"
docker compose --env-file "$ARENA_ENV_FILE" -f deploy/ai/compose.yaml up -d --no-deps ai
```

Проверьте gateway/RAG URLs в созданном env и убедитесь, что порт 8000 свободен.
`.secrets/` исключён из Git и build context; не добавляйте его принудительно.
Provision генерирует service token и отказывается перезаписывать существующие секреты.
Compose использует host networking, непривилегированный процесс и read-only filesystem;
он не запускает и не меняет LocalAI или RAG. Публичный интернет-доступ не настроен.
Обновление, откат и подключение команд: [серверный запуск](docs/integration/server-deployment.md).

## API

| Endpoint | Назначение |
| --- | --- |
| `GET /health/live` | Проверка HTTP-процесса |
| `GET /health/ready` | Проверка gateway и наличия модели |
| `GET /v1/info` | Режим и model ID |
| `POST /v1/turn` | Проверенный ход и обновлённый снимок |
| `POST /v1/finish` | Фактический исход, три судьи и Trainer |
| `GET /openapi.json` | Схема API |

При заданном `ARENA_SERVICE_TOKEN` turn/finish требуют `Authorization: Bearer <token>`.
Токен предназначен только для Backend, не для браузера. В deployment он обязателен;
не публикуйте `.env`, полные снимки и закрытые вводные.

`accepted` и `blocked` возвращают следующий снимок; `model_error` не продвигает поединок.
Backend управляет порядком ходов и повторной доставкой. Не повторяйте публичный запрос
автоматически после неоднозначного timeout. Соглашение не завершает раунд: таймер и
вызов finish принадлежат Backend. Failed-слот судьи/Trainer не отменяет готовые слоты.

[Контракт и примеры](docs/api/README.md) · [Интеграция команд](docs/api/duel-quality-handoff.md)

## Проверки

```bash
uv run pytest
uv run ruff check src tests scripts
uv run ty check
uv run python scripts/export_openapi.py --check
```

Обычные тесты не требуют живых моделей. Проверка настоящих методических страниц
пропускается, если отдельно предоставленные исходники отсутствуют.

Серверный smoke использует токен из окружения контейнера:

```bash
docker exec arena-ai-ai-1 python scripts/check_ai_service.py \
  --api-url http://172.16.34.7:8000
docker exec arena-ai-ai-1 python scripts/check_ai_service.py \
  --api-url http://172.16.34.7:8000 --live-duel --timeout 900
```

Вторая команда вызывает модель: один ход и finish. Это не полная приёмка.
Для конфликтного сценария с продолжением после соглашения:

```bash
uv run --env-file .env arena-ai-eval --api-url http://127.0.0.1:8000 \
  --scenario adversarial --runs 1 --timeout 900 --progress \
  --output /tmp/arena-adversarial.json
```

Отчёты содержат безопасные статусы, не реплики и секреты.
Полная adversarial-приёмка пока не пройдена: известен отказ конструктивного хода
`opponent_unearned_concession`. Минимальный серверный turn/finish проверен на живом
Qwen, но сквозная интеграция Backend/Frontend/Audio Engine остаётся отдельным этапом.

## Документация

- [Корпус судей](docs/judge-corpus.md)
- [Словарь проекта](CONTEXT.md) и [архитектурные решения](docs/adr/)
- [База знаний команды](https://github.com/xyz-nebula/knowledge-base)

Локальные задачи, черновики и отчёты в `.scratch/` не публикуются в Git.
