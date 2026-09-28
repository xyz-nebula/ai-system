# ai-system

AI-сервис «Арены переговоров»: управляемый ход AI-оппонента (Guard → Opponent → Validator),
оценка завершённого диалога (исход, три судьи, тренер) и проверка блока подготовки.
Вызывается только Backend; модель — внешний LocalAI, методология судей — в Qdrant.

## Запуск

Нужны Docker с Compose и доступный LocalAI с моделью `qwen3.8-9b-q4`.

```bash
cp .env.example .env        # задать ARENA_SERVICE_TOKEN и ARENA_BIND_IP
docker compose up -d        # AI + Qdrant + эмбеддинги
curl http://<ARENA_BIND_IP>:8000/health/ready
```

`docker compose up -d` берёт образ `ghcr.io/xyz-nebula/ai-system:dev` (собирается CI из
ветки `dev`; для приватного пакета — `docker login ghcr.io`). Собрать локально:
`docker compose up -d --build`. Другая ветка или коммит: `ARENA_IMAGE_TAG=main`.

Qdrant и эмбеддинги доступны только с сервера (`127.0.0.1:6333`, `127.0.0.1:8081`).
Тома называются `arena-rag_*`, поэтому существующий индекс судей переиспользуется.
Для пустого Qdrant проиндексируйте методологию (исходные материалы не хранятся в репозитории):

```bash
uv run python scripts/index_judge_corpus.py --source-root <папка-с-материалами>
uv run python scripts/index_judge_corpus.py --check-index
```

Без индекса судьи возвращают `judge_retrieval_unavailable`, остальные слоты работают.

## Настройки (`.env`)

| Переменная | Назначение |
| --- | --- |
| `ARENA_SERVICE_TOKEN` | Общий с Backend секрет, обязателен |
| `ARENA_BIND_IP` | IP, на котором слушает порт 8000; для Backend — приватный IP сервера |
| `ARENA_QWEN_CHAT_URL`, `ARENA_QWEN_MODEL` | Chat Completions LocalAI и модель |
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
