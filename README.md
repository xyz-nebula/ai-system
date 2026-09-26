# Арена переговоров — AI-сервис

Серверный AI-контур тренажёра переговоров: управляемый ход с Guard и Validator,
AI-оппонент, три независимых судьи и отдельный Trainer. Backend хранит кейс и снимок
поединка; Audio Engine отвечает за STT/TTS.

README описывает деплой на Linux-сервере. Локальный demo и тесты вынесены в
[отдельный гайд](docs/local-development.md).

Для новой разработки подготовлен
[единый контракт 2.0.0-rc.1](docs/api/v2/README.md): ответственность команд,
полные поля, REST/Audio схемы, примеры и правила таймера/границ/replay. Это target
реализации, одобренный командами по сообщению пользователя. Начата реализация
v2-моделей, проверок и модельного negotiating-хода; действующий HTTP API и деплой пока остаются v1.
Полнота требований и фактические стыки проверены отдельно в
[аудите всех доступных репозиториев](docs/integration/project-requirements-and-fields-audit.md).

## Серверная схема

| Компонент | Адрес в текущей среде |
| --- | --- |
| AI API | `http://172.16.34.7:8000` |
| LocalAI Chat Completions | `http://172.16.34.6:8080/v1/chat/completions` |
| Модель | `qwen3.8-9b-q4` |
| Qdrant | `http://127.0.0.1:6333` на AI-сервере |
| Qwen3 Embeddings / TEI | `http://127.0.0.1:8081` на AI-сервере |

AI работает в Docker внутри выделенной серверной среды. Backend обращается к нему
по приватной сети; браузер — только к Backend. Публиковать AI или RAG в интернет не нужно.
На другом сервере замените пользователя, каталоги и приватные адреса.

## 1. Подготовка сервера

Нужны Linux, Git, Python 3 для provision-скрипта, Docker с Compose и право оператора
запускать Docker. Python-зависимости приложения устанавливаются внутри image.
Приватный bind IP должен принадлежать интерфейсу сервера, порт 8000 — быть свободен.

```bash
ssh -p 8022 farrahovd234@2.26.27.230
docker version
docker compose version
ip -brief address
ss -ltn 'sport = :8000'
```

Если AI уже развёрнут, не создавайте второй экземпляр: используйте
[операционный гайд](docs/integration/server-deployment.md) для текущих release-каталогов.
Не останавливайте чужой listener ради освобождения порта.

Ниже — **новая установка**. Все дальнейшие команды выполняются на сервере.
Выберите утверждённую ветку или tag; пример использует `dev`.

```bash
mkdir -p /home/farrahovd234/arena-ai
install -d -m 700 /home/farrahovd234/arena-ai/shared
git clone --branch dev https://github.com/xyz-nebula/ai-system.git \
  /home/farrahovd234/arena-ai/source
cd /home/farrahovd234/arena-ai/source
git rev-parse HEAD
```

Для закрытого репозитория используйте штатную Git-авторизацию, не токен в URL.

## 2. Модель и retrieval

LocalAI должен быть доступен с AI-сервера, модель — загружена. Этот репозиторий
не разворачивает и не перенастраивает чужой LocalAI.

Если retrieval-стек уже работает, используйте его без пересоздания. Для новой установки:

```bash
docker compose -f deploy/rag/compose.yaml up -d qdrant embeddings
docker compose -f deploy/rag/compose.yaml ps
```

Qdrant и TEI слушают только loopback. Первый запуск TEI скачивает
`Qwen/Qwen3-Embedding-0.6B`; данные сохраняются в Docker volumes.
Не выполняйте `down -v` и не запускайте второй стек на тех же портах.

Судьям нужен заполненный проверенный индекс `arena_judge_methodology_v1`.
Первичная индексация описана в [гайде корпуса](docs/judge-corpus.md):
исходные методические страницы предоставляются отдельно и не входят в image.
Существующий актуальный индекс повторно загружать не нужно.
Без retrieval судьи возвращают failed-слоты, а не demo-вердикты.

## 3. Защищённая конфигурация

```bash
python3 scripts/provision_ai_env.py \
  --destination /home/farrahovd234/arena-ai/shared/.env \
  --bind-ip 172.16.34.7
```

Скрипт создаёт env с правами `0600`, режимом `qwen` и случайным service token.
Существующий файл не перезаписывает: при обновлении пропустите этот шаг.
Проверьте конфигурацию в редакторе на сервере по
[deploy/ai/.env.example](deploy/ai/.env.example).

Основные параметры: `ARENA_BIND_IP`, `ARENA_QWEN_CHAT_URL`, `ARENA_QWEN_MODEL`,
`ARENA_QDRANT_URL`, `ARENA_EMBEDDINGS_URL`, `ARENA_JUDGE_COLLECTION`.
В host-network контейнере loopback относится к этой серверной среде.
Сохраняйте `ARENA_MODEL_MODE=qwen` и сгенерированный `ARENA_SERVICE_TOKEN`.

Service token передавайте только Backend через защищённое хранилище.
Не публикуйте env, полный `docker inspect` или `compose config`: они содержат секреты.
Токен не должен попасть в Git, image, чат или браузер; это не пользовательский JWT.

## 4. Сборка и запуск

Из серверного checkout без незакоммиченных изменений:

```bash
git status --short
export ARENA_RELEASE_REVISION="$(git rev-parse HEAD)"
export ARENA_IMAGE="arena-ai:$ARENA_RELEASE_REVISION"
export ARENA_ENV_FILE=/home/farrahovd234/arena-ai/shared/.env
docker build --build-arg ARENA_SOURCE_REVISION="$ARENA_RELEASE_REVISION" \
  -t "$ARENA_IMAGE" .
docker compose --env-file "$ARENA_ENV_FILE" -f deploy/ai/compose.yaml config --quiet
docker compose --env-file "$ARENA_ENV_FILE" -f deploy/ai/compose.yaml up -d --no-deps ai
docker compose --env-file "$ARENA_ENV_FILE" -f deploy/ai/compose.yaml ps
```

Если `git status` показывает изменения, сначала определите точный состав релиза:
один commit ID не описывает изменённые исходники.
Compose запускает только AI, не трогает LocalAI и RAG. Контейнер работает без root,
с read-only filesystem, лимитами ресурсов и `restart: unless-stopped`.
Используется Linux host networking и bind только на выбранный приватный IP.

## 5. Проверка деплоя

Подставьте свой bind IP, если он отличается:

```bash
docker exec arena-ai-ai-1 python scripts/check_ai_service.py \
  --api-url http://172.16.34.7:8000
docker exec arena-ai-ai-1 python scripts/check_ai_service.py \
  --api-url http://172.16.34.7:8000 --live-duel --timeout 900
```

Первая команда проверяет health, OpenAPI, авторизацию и валидацию без генерации диалога.
Вторая вызывает настоящую модель: один управляемый ход и finish с тремя судьями и Trainer.
Токен берётся из окружения контейнера; отчёт не содержит секретов.
Exit `0` означает успешное прохождение выбранных проверок.

Docker health проверяет процесс; `/health/ready` — gateway и модель, **не RAG**.
Retrieval подтверждайте проверкой индекса и готовыми живыми судейскими слотами.
Также проверьте health из контейнера Backend: его `localhost` — не AI-сервер.
Не повторяйте модельный запрос автоматически после неоднозначного timeout.

## 6. Обновление и откат

Для текущего деплоя с каталогами `releases/` используйте
[операционный гайд](docs/integration/server-deployment.md), не создавайте параллельный деплой.
Для новой установки из разделов выше:

1. Запишите предыдущий commit и image tag, сохраните предыдущий image.
2. В серверном checkout выполните `git pull --ff-only` для выбранной ветки.
3. Повторите сборку и запуск из раздела 4 с **тем же** защищённым env.
4. Выполните проверки из раздела 5.

Для отката задайте `ARENA_IMAGE` предыдущим сохранённым tag и повторите
`up -d --no-deps ai`; при изменениях Compose используйте и предыдущий deployment-файл.
Обновление может прервать запросы: согласуйте окно без активных поединков.
Не удаляйте RAG volumes или секреты при обновлении и откате.

Остановка только AI при заданных переменных из раздела 4:

```bash
docker compose --env-file "$ARENA_ENV_FILE" -f deploy/ai/compose.yaml stop ai
```

## Интеграция и документация

Turn/finish требуют `Authorization: Bearer <AI service token>`.
Backend хранит снимок целиком, управляет ходами и таймером, не отдаёт закрытые поля браузеру.
Audio Engine озвучивает только проверенный ответ.

26 сентября 2026 минимальный серверный turn/finish проверен на реальных Qwen и RAG.
Это не полная приёмка: стыковка остальных компонентов, экспертная проверка и нагрузка
шести пользователей — отдельные этапы. Последние локальные исправления v1 прошли
шесть модельных ходов и отдельный повтор finish с готовыми тремя судьями и Trainer;
это не свежий полный прогон после последней правки и не подтверждение их деплоя.

- [Единый документ интеграции v2 для всех команд: задачи, маршруты и все поля](docs/integration/unified-integration-guide.md)
- [Подключение существующего v1](docs/integration/team-integration.md)
- [API-контракт и примеры](docs/api/README.md)
- [Сценарий вызовов: CaseConfig → turn → snapshot → finish](docs/api/usage-flow.md)
- [Серверная эксплуатация и SSH-туннель](docs/integration/server-deployment.md)
- [Корпус судей и индексация](docs/judge-corpus.md)
- [Локальная разработка и тесты](docs/local-development.md)
- [Словарь проекта](CONTEXT.md) и [архитектурные решения](docs/adr/)
- [База знаний команды](https://github.com/xyz-nebula/knowledge-base)

Локальные задачи, черновики и отчёты в `.scratch/` не публикуются в Git.
