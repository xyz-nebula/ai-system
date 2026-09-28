# ai-system

[![CI](https://github.com/xyz-nebula/ai-system/actions/workflows/ci.yml/badge.svg)](https://github.com/xyz-nebula/ai-system/actions/workflows/ci.yml)
[![Docker](https://github.com/xyz-nebula/ai-system/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/xyz-nebula/ai-system/actions/workflows/docker-publish.yml)

AI-сервис тренажёра «Арена переговоров»: AI-оппонент в переговорах, а после разговора —
исход, голоса трёх судей и разбор тренера.

## Запуск

Нужны Docker с Compose и OpenAI-совместимый сервер модели (LocalAI, vLLM и т. п.)
с Qwen3 8–9B; проверено на LocalAI с `qwen3.8-9b-q4`.

```bash
git clone https://github.com/xyz-nebula/ai-system.git && cd ai-system
cp .env.example .env    # задать ARENA_SERVICE_TOKEN и ARENA_QWEN_CHAT_URL
docker compose up -d
curl http://127.0.0.1:8000/health/ready
```

Первый запуск дольше: собирается образ и скачивается модель эмбеддингов (~1 ГБ).
Индекс для судей заполняется сам; готово, когда `docker compose logs indexer`
показывает `Indexed 18 judge excerpts`.

## Настройки (`.env`)

| Переменная | Назначение |
| --- | --- |
| `ARENA_SERVICE_TOKEN` | Секрет для вызовов API, обязателен |
| `ARENA_QWEN_CHAT_URL` | Адрес Chat Completions сервера модели (`host.docker.internal` — эта же машина) |
| `ARENA_QWEN_MODEL` | Имя модели на сервере |
| `ARENA_BIND_IP`, `ARENA_PORT` | Где слушает сервис, по умолчанию `127.0.0.1:8000` |
| `ARENA_EVALUATE_VALIDATION` | `soft` — оценка быстрее и без отказов; `strict` — с перепроверкой второй моделью |

Остальные параметры — в `.env.example` с комментариями.

## API

Все POST-запросы требуют заголовки `Authorization: Bearer <ARENA_SERVICE_TOKEN>` и
`X-Arena-Contract-Version: 2.0.0-rc.1`. Полные схемы — `/docs`.

| Маршрут | Что делает |
| --- | --- |
| `GET /health/ready` | Сервис и модель доступны |
| `POST /v2/evaluate` | Оценка диалога: исход, три судьи, тренер |
| `POST /v2/turn` | Ход AI-оппонента |
| `POST /v2/finish` | Итог поединка |
| `POST /v2/preparation/review` | Отзыв на блок подготовки |

Пример: `role` — роль модели (реплики `is_ai: true`), `opponent_role` — роль пользователя.

```bash
curl -X POST http://127.0.0.1:8000/v2/evaluate \
  -H "Authorization: Bearer $ARENA_SERVICE_TOKEN" \
  -H "X-Arena-Contract-Version: 2.0.0-rc.1" \
  -H "Content-Type: application/json" \
  --max-time 360 \
  -d '{
    "role": "Генеральный директор",
    "opponent_role": "Менеджер",
    "case_description": "Переговоры о повышении после пропущенного рабочего дня.",
    "messages": [
      {"text": "Предлагаю две недели контроля и KPI 120%.", "is_ai": false},
      {"text": "Согласен: две недели контроля и KPI 120%.", "is_ai": true}
    ],
    "preparations": "Моя цель — согласовать измеримые условия повышения."
  }'
```

Ответ приходит за 30–60 с. Каждый блок (`outcome`, `judge_verdicts`, `trainer_feedback`)
отдельно `ready` или `failed`; `failed` — «оценка недоступна», а не проигрыш.

## Если не работает

- `/health/ready` отвечает 503 — сервис не видит сервер модели или модель с таким именем.
- Судьи возвращают `judge_retrieval_unavailable` — смотрите `docker compose logs indexer`.
- 401 — неверный токен, 409 — нет заголовка `X-Arena-Contract-Version`, 422 — тело запроса не по схеме.

## Разработка

```bash
uv sync --dev
uv run pytest -q
uv run ruff check . && uv run ty check
```

## Лицензия

[GNU GPL v3](LICENSE).
