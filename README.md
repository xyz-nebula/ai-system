# ai-system

[![CI](https://github.com/xyz-nebula/ai-system/actions/workflows/ci.yml/badge.svg)](https://github.com/xyz-nebula/ai-system/actions/workflows/ci.yml)
[![Docker](https://github.com/xyz-nebula/ai-system/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/xyz-nebula/ai-system/actions/workflows/docker-publish.yml)

AI-сервис «Арены переговоров»: управляемый ход AI-оппонента (Guard → Opponent → Validator),
оценка завершённого диалога (исход, три судьи, тренер) и проверка блока подготовки.
Вызывается только Backend; модель — внешний LocalAI, методология судей — в Qdrant.

## Запуск

Нужны Docker с Compose и OpenAI-совместимый сервер модели (LocalAI, vLLM и т. п.)
с Qwen3 8–9B; проверено на LocalAI с `qwen3.8-9b-q4`.

```bash
git clone https://github.com/xyz-nebula/ai-system.git && cd ai-system
cp .env.example .env        # задать ARENA_SERVICE_TOKEN и ARENA_QWEN_CHAT_URL
docker compose up -d        # AI + Qdrant + эмбеддинги + индекс судей
curl http://127.0.0.1:8000/health/ready
```

Образ `ghcr.io/xyz-nebula/ai-system` собирает CI; если скачать его нельзя, `docker compose`
соберёт его из исходников (`docker compose up -d --build` — всегда из исходников).

Индекс судей заполняется сам: сервис `indexer` загружает в Qdrant фрагменты методологии
из [`judge_corpus.py`](src/arena_ai/judge_corpus.py) и завершается. При первом старте
эмбеддинги скачивают модель, индексатор дождётся их. Проверка:
`docker compose run --rm indexer arena-ai-index --check-index`.
Сами методические пособия в репозиторий не входят; `arena-ai-index --source-root <папка>`
сверяет фрагменты с их постраничным переносом, если он у вас есть.

Для доступа из Backend задайте `ARENA_BIND_IP` — приватный IP сервера. Qdrant и эмбеддинги
слушают только `127.0.0.1`. Тома называются `arena-rag_*`: существующий индекс сохраняется.

## Настройки (`.env`)

| Переменная | Назначение |
| --- | --- |
| `ARENA_SERVICE_TOKEN` | Общий с Backend секрет, обязателен |
| `ARENA_BIND_IP` | IP, на котором слушает порт 8000; для Backend — приватный IP сервера |
| `ARENA_QWEN_CHAT_URL`, `ARENA_QWEN_MODEL` | Chat Completions сервера модели и имя модели |
| `ARENA_QWEN_*_EXTRA_BODY` | Параметры вызова: генератор судьи без thinking (`metadata`), проверяющие — с thinking |
| `ARENA_EVALUATE_VALIDATION` | `soft` — без модельных проверок `/v2/evaluate`, `strict` — все проверки |
| `ARENA_QWEN_API_KEY` | Ключ LocalAI, если нужен |

## API

POST-запросы требуют `Authorization: Bearer <ARENA_SERVICE_TOKEN>` и
`X-Arena-Contract-Version: 2.0.0-rc.1`. Полные схемы: `/docs` и `/openapi.json`.

| Маршрут | Что делает |
| --- | --- |
| `GET /health/live`, `GET /health/ready` | Процесс жив; LocalAI и модель доступны |
| `POST /v2/evaluate` | Оценка сохранённого диалога: исход, судьи `hiring`/`negotiation`/`ownership`, тренер |
| `POST /v2/turn` | Управляемый ход оппонента по снимку поединка |
| `POST /v2/finish` | Итог поединка по замороженному снимку |
| `POST /v2/preparation/review` | Обратная связь по одному блоку подготовки |

Пример `/v2/evaluate`. `role` — роль **модели** (реплики `is_ai: true`), `opponent_role` —
роль пользователя:

```json
{
  "role": "Генеральный директор",
  "opponent_role": "Менеджер",
  "case_description": "Переговоры о повышении после пропущенного рабочего дня.",
  "messages": [
    {"text": "Предлагаю две недели контроля и KPI 120%.", "is_ai": false},
    {"text": "Согласен: две недели контроля и KPI 120%.", "is_ai": true}
  ],
  "preparations": "Моя цель — согласовать измеримые условия повышения."
}
```

Ответ всегда HTTP 200 при валидном запросе; каждый слот отдельно `ready` или `failed`
с `error_code`. `failed` — «оценка недоступна», не проигрыш. Один запрос идёт 30–60 с,
при нескольких одновременных — дольше: таймаут на стороне Backend не меньше 300 с.

## Разработка

```bash
uv sync --dev
just check      # ruff, format, ty, pytest
just run-dev    # локально без Docker, с переменными из .env
```

Живые тесты с LocalAI включаются явно:
`ARENA_RUN_LIVE_V2=1 uv run pytest tests/test_v2_evaluate_http.py -k live` (нужны
`ARENA_QWEN_CHAT_URL` и `ARENA_QWEN_MODEL`).

CI (`.github/workflows`): `ci.yml` — lint, format, typecheck, тесты; `docker-publish.yml` —
образ `ghcr.io/xyz-nebula/ai-system` с тегами ветки, `sha-…`, semver и `latest`.

Словарь предметной области — [CONTEXT.md](CONTEXT.md), решения — [docs/adr](docs/adr).

## Авторы

Команда [xyz-nebula](https://github.com/xyz-nebula) при участии ИИ-агентов
[Codex](https://github.com/codex) (OpenAI) и [Claude](https://github.com/claude) (Anthropic).

## Лицензия

[GNU GPL v3](LICENSE).
