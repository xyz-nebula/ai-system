# Серверный интеграционный стенд AI

Это тестовый стенд, не подтверждение полной приёмки приложения. Известный отказ
`opponent_unearned_concession` на конструктивном ходе полного adversarial-сценария
остаётся открытым. Изменяются только `ai-system` и его контейнер; чужие сервисы не меняются.

26 сентября 2026 минимальный живой smoke прошёл: принятый ход, настоящий retrieval,
три ready судьи и ready Trainer. [Безопасный отчёт](../../.scratch/server-integration/reports/2026-09-26-live-smoke.json).
Релиз: `arena-ai:f4e50d251aae`; источники/compose на сервере:
`/home/farrahovd234/arena-ai/releases/f4e50d251aae`, защищённый env в `shared/.env`.

## Адреса и границы

- SSH: `farrahovd234@2.26.27.230`, порт `8022`, среда `pyxis-lynx`.
- AI: **`http://172.16.34.7:8000`**, только приватная сеть/VPN, не публичный интернет.
- Модель: `http://172.16.34.6:8080/v1/chat/completions`, `qwen3.8-9b-q4`.
- Qdrant/TEI: `127.0.0.1:6333` / `127.0.0.1:8081` на AI-сервере.
- `/v1/turn` и `/v1/finish` требуют отдельный `ARENA_SERVICE_TOKEN`.
  Это не пользовательский JWT. Токен передавать Backend через защищённое хранилище,
  никогда не Frontend, query string, репозиторий или чат.

Backend вызывает AI внутри приватной сети; браузер вызывает Backend, а не AI напрямую.
Кейсы и снимки с приватными полями должны оставаться на межсервисной границе.
Audio Engine передаёт STT через Backend в AI и озвучивает только проверенный ответ.
Прямой LocalAI realtime разговор не является интеграцией этого контура.

Compose использует Linux `network_mode: host`, чтобы читать существующие loopback
Qdrant/TEI без их перенастройки. Uvicorn связывается с конкретным приватным IP, не
`0.0.0.0`; bridge-контейнер Backend должен использовать адрес `172.16.34.7`, не свой
`localhost`. `ARENA_BIND_IP` должен быть назначен сетевому интерфейсу этой среды.
Контейнер непривилегированный, root filesystem read-only, capabilities сняты.
Host networking не даёт сетевой изоляции: применять только в этой доверенной тестовой
среде. HTTP модельного и AI endpoint допустим только внутри неё; публичный доступ
потребует TLS и отдельного согласования сетевых правил.

## Первый запуск

Создать отдельный каталог `/home/farrahovd234/arena-ai`, `shared/` и
`releases/<release-id>/`. Передавать туда только выбранные файлы исходников,
Dockerfile, lockfile и deployment scripts, без `.git`, `.venv`, `.env`, transcript
и полного knowledge-base. `.dockerignore` дополнительно ограничивает build context.
Не использовать `git archive HEAD` для ещё не закоммиченных изменений.

Из каталога конкретного релиза:

```bash
python3 scripts/provision_ai_env.py \
  --destination /home/farrahovd234/arena-ai/shared/.env \
  --bind-ip 172.16.34.7
docker build --build-arg ARENA_SOURCE_REVISION=<commit-and-bundle-id> \
  -t arena-ai:<release-id> .
```

Provision создаёт env атомарно с mode `0600` и случайным токеном. Повторный запуск
отказывается перезаписывать файл: при обновлении этот шаг пропустить. Родительский
`shared/` должен принадлежать оператору и иметь mode `0700`.
Перед стартом проверить `ss -ltn 'sport = :8000'`; чужой listener не останавливать.

```bash
export ARENA_IMAGE=arena-ai:<release-id>
export ARENA_ENV_FILE=/home/farrahovd234/arena-ai/shared/.env
docker compose --env-file "$ARENA_ENV_FILE" -f deploy/ai/compose.yaml config --quiet
docker compose --env-file "$ARENA_ENV_FILE" -f deploy/ai/compose.yaml up -d --no-deps ai
```

Не печатать полный `compose config`, `.env` или `docker inspect`: они содержат секреты.
Не выполнять `down` для `arena-rag` и не удалять volumes. Dockerfile использует
locked Python dependencies; сохранить построенный image ID и bundle checksum для отката.

## Проверки

```bash
docker exec arena-ai-ai-1 python scripts/check_ai_service.py \
  --api-url http://172.16.34.7:8000
docker exec arena-ai-ai-1 python scripts/check_ai_service.py \
  --api-url http://172.16.34.7:8000 --live-duel --timeout 900
```

Первая команда не генерирует диалог: проверяет liveness, модельную readiness,
OpenAPI, обязательную авторизацию, валидацию тела и отказ finish без принятых ходов.
Вторая явно вызывает модель: один нейтральный ход и finish с частичной подготовкой.
Она проверяет доставку настоящего ответа и готовность трёх судей/Trainer, не требует
соглашения и не заменяет полный adversarial acceptance. Отчёт содержит только
булевы проверки, статусы и типизированные коды; реплики/методики/токены не печатаются.
Exit `0`: все выбранные проверки прошли, `1`: нарушен инвариант, `2`: ошибка подключения
или конфигурации. Не делать автоматический повтор хода после timeout.

Healthcheck Docker проверяет только HTTP-процесс; модельная readiness не проверяет
retrieval. До приёмки отдельно проверять настоящий индекс и поиск либо успешные
живые судейские слоты. Готовность mock/process тестов не означает готовность живого Qwen.

## Обновление и откат

Сохранить предыдущий image и release directory. Для нового релиза повторить build и
`up -d --no-deps ai`, используя тот же защищённый env. Если smoke не прошёл, из каталога
предыдущего релиза повторить compose с предыдущим `ARENA_IMAGE`. При первом неудачном
деплое остановить только `ai` командой `docker compose ... stop ai`.
Не удалять ни существующие RAG volumes, ни секреты при откате.

## Задачи остальных команд

**Backend:** добавить серверный AI client с base URL выше и секретом; вызывать turn/finish,
сохранять `SessionSnapshot` целиком, исключить приватные поля из ответа браузеру,
обеспечить порядок ходов и внешний таймер. Не превращать `model_error` в сохранённый ход.

**Frontend:** подключить текстовый ход и настоящий finish/result вместо демо-результата;
показать три независимых судейских слота и Trainer, сохранить ready при частичных failed.
Не считать соглашение завершением раунда и не показывать методические источники.

**Audio Engine:** использовать STT/TTS, отправлять распознанный текст в управляемый ход
через Backend; не генерировать игровой ответ альтернативно в LocalAI и не озвучивать
его до проверки. Согласовать подтверждение последней реплики перед finish.

**Admin/кейсы:** админка не должна вызывать AI с пользовательским токеном напрямую;
конфигурацию кейса Backend преобразует в `CaseConfig`. Судейский критерий не равен
общему `score` или победе по условиям сделки; UI-агрегацию согласовывают владельцы продукта.

Полный контракт: [API](../api/README.md), [качество поединка](../api/duel-quality-handoff.md).
Адреса живых Backend/Frontend/Audio Engine не обнаружены в проверенных dev-конфигурациях:
там localhost-примеры. GitHub deployments пусты, workflows только публикуют images.
На доступной серверной среде изначально работали только наши два retrieval контейнера;
пути `/api/openapi.json` и `/audio/openapi.json` на HTTPS модельного gateway возвращают 404.
Это не доказывает отсутствие сервисов на других средах или адресах.

## Проверка с рабочей машины

Прямой маршрут через `nebula_wg0` существует, но на проверке 26 сентября соединение
с `172.16.34.7:8000` с рабочей машины истекло по timeout. Внутри серверной сети endpoint
работает. Не считать это ошибкой AI-контейнера и не менять WireGuard без диагностики.
Альтернативный проверенный доступ — отдельный loopback SSH-туннель:

```bash
ssh -N -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:18000:172.16.34.7:8000 \
  -p 8022 farrahovd234@2.26.27.230
curl http://127.0.0.1:18000/health/live
curl http://127.0.0.1:18000/health/ready
```

Не закрывать существующие клиентские туннели и не занимать чужой локальный порт.
Токен для turn/finish остаётся обязательным; health не является обходом авторизации.
