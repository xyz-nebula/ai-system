# Как поднять AI-сервис v2

Гайд для команды, запускающей **новый экземпляр** на Linux-сервере.
AI вызывается только Backend. Audio и Frontend напрямую к AI не подключаются.
Для текущего экземпляра используйте [операционный гайд](staging-v2-checklist.md).

## Короткий вариант: один Compose-файл

Если LocalAI, Qdrant и заполненный индекс уже доступны, используйте
[compose.simple.yaml](../../deploy/ai/compose.simple.yaml).
Вся конфигурация AI находится в нём, отдельный `.env` и provision-скрипт не нужны.
После клонирования репозитория, из его корня:

```bash
export ARENA_BIND_IP=172.16.34.7 # приватный IP своего сервера, порт 8000 свободен
read -rsp 'Service token (тот же секрет передать Backend): ' ARENA_SERVICE_TOKEN
export ARENA_SERVICE_TOKEN
docker compose -f deploy/ai/compose.simple.yaml up -d --build
docker compose -f deploy/ai/compose.simple.yaml ps
curl --fail --max-time 10 "http://$ARENA_BIND_IP:8000/health/ready"
```

Вставьте заранее созданный длинный случайный секрет, не слово из примера.
Для обновления/перезапуска в новой shell снова задайте те же две переменные.
Если адреса зависимостей отличаются, исправьте их в Compose-файле.
На текущем сервере порт 8000 занят — этот пример **не команда замены** текущего AI.
Файл запускает только нашу часть: не переустанавливает чужой LocalAI и не создаёт
пустую БД поверх существующей. Для новой установки RAG см. раздел 3 ниже.

## 1. Что нужно заранее

- Docker Engine с Compose v2, Git и Python 3; право запускать Docker.
- Приватный IP, принадлежащий серверу, и свободный порт 8000.
- Доступ с этого сервера к LocalAI и указанной модели.
- Qdrant, embeddings и заполненная методическая коллекция для судей.

Текущие адреса: LocalAI — `172.16.34.6:8080`, AI — `172.16.34.7:8000`.
На текущем AI-сервере 8000 **уже занят** контейнером `arena-ai-v2-main`.
Не запускайте там вторую копию и не останавливайте существующую ради этого гайда.
При установке на другой сервер замените адреса; доступ по VPN сам по себе не
гарантирует, что новый сервер видит LocalAI.

Все следующие команды выполняются на целевом сервере, не на ноутбуке.

```bash
docker version
docker compose version
ip -brief address
ss -ltn 'sport = :8000'
git clone --branch dev https://github.com/xyz-nebula/ai-system.git ai-system
cd ai-system
git rev-parse HEAD
```

Для приватного репозитория нужна обычная Git-авторизация. Не вставляйте токен в URL.
Сборка выполняется из корня репозитория, где находятся Dockerfile и uv.lock.

## 2. Создать защищённый .env

Подставьте приватный IP **своего** сервера вместо `172.16.34.7`:

```bash
install -d -m 700 ../arena-ai-secrets
python3 scripts/provision_ai_env.py \
  --destination ../arena-ai-secrets/.env \
  --bind-ip 172.16.34.7
export ARENA_ENV_FILE="$(realpath ../arena-ai-secrets/.env)"
```

Скрипт использует [серверный шаблон](../../deploy/ai/.env.example), создаёт
случайный `ARENA_SERVICE_TOKEN`, выставляет права 0600 и не перезаписывает
существующий файл. При обновлении используйте прежний env, не меняйте токен.
Откройте файл в редакторе на сервере и проверьте:

| Переменная | Значение / назначение |
| --- | --- |
| `ARENA_BIND_IP` | Приватный IP этого сервера |
| `ARENA_V2_ENABLED` | `true`, иначе маршруты v2 не включатся |
| `ARENA_MODEL_MODE` | `qwen`, не `demo` |
| `ARENA_SERVICE_TOKEN` | Сгенерированный секрет, общий с Backend |
| `ARENA_QWEN_CHAT_URL` | `http://172.16.34.6:8080/v1/chat/completions`, если доступен |
| `ARENA_QWEN_MODEL` | `qwen3.8-9b-q4`, либо точный ID вашей доступной модели |
| `ARENA_QDRANT_URL` | `http://127.0.0.1:6333`, если Qdrant на этом сервере |
| `ARENA_EMBEDDINGS_URL` | `http://127.0.0.1:8081`, если TEI на этом сервере |
| `ARENA_JUDGE_COLLECTION` | `arena_judge_methodology_v1`, заполненная коллекция |

Остальные настройки берите из шаблона. `ARENA_QWEN_API_KEY` нужен только если
ваш LocalAI требует API key; это другой секрет, не service token Backend.
Не коммитьте `.env`, не отправляйте его в чат и не публикуйте полный
`docker inspect` или `docker compose config`: они могут раскрыть секреты.

## 3. Retrieval

Если Qdrant и embeddings уже работают, **не пересоздавайте** их.
Для отдельного нового сервера:

```bash
docker compose -f deploy/rag/compose.yaml up -d qdrant embeddings
docker compose -f deploy/rag/compose.yaml ps
```

Первый запуск TEI скачивает `Qwen/Qwen3-Embedding-0.6B`. Порты стека доступны
только на loopback. Данные находятся в Docker volumes; не выполняйте `down -v`.
Запуск контейнеров не наполняет базу: первичная индексация описана в
[гайде методического корпуса](../judge-corpus.md), исходные материалы предоставляются
отдельно. Без пригодного индекса судьи могут вернуть failed-слоты.

## 4. Собрать и запустить

```bash
git status --short
export ARENA_RELEASE_REVISION="$(git rev-parse HEAD)"
export ARENA_IMAGE="arena-ai:$ARENA_RELEASE_REVISION"
docker build --build-arg ARENA_SOURCE_REVISION="$ARENA_RELEASE_REVISION" \
  -t "$ARENA_IMAGE" .
docker compose --env-file "$ARENA_ENV_FILE" -f deploy/ai/compose.yaml config --quiet
docker compose --env-file "$ARENA_ENV_FILE" -f deploy/ai/compose.yaml up -d --no-deps ai
docker compose --env-file "$ARENA_ENV_FILE" -f deploy/ai/compose.yaml ps
```

Собирать нужно из чистого checkout согласованного commit. Для **сборки** `.env`
не нужен; он требуется для запуска. `ARENA_IMAGE` — tag собранного образа,
`ARENA_ENV_FILE` — абсолютный путь к защищённому файлу; Compose читает bind IP
из него. Используется Linux `network_mode: host`: localhost внутри AI означает
этот сервер. В обычной bridge-сети адреса и способ публикации портов будут другими.

Не запускайте image просто через `docker run IMAGE`: команда образа по умолчанию
слушает 127.0.0.1. Наш Compose явно задаёт приватный bind и порт 8000.

## 5. Проверить без генерации

В новом Compose-деплое контейнер называется `arena-ai-ai-1`:

```bash
docker exec arena-ai-ai-1 python scripts/check_ai_service.py \
  --api-url http://172.16.34.7:8000
curl --fail --max-time 10 http://172.16.34.7:8000/health/live
curl --fail --max-time 10 http://172.16.34.7:8000/health/ready
curl --fail --max-time 10 http://172.16.34.7:8000/openapi.json
```

Замените IP своим. Проверочный скрипт берёт service token из окружения контейнера,
проверяет health, контракт и защиту API, не генерируя диалог. Проверьте наличие
маршрутов `/v2/turn`, `/v2/finish`, `/v2/evaluate`, `/v2/preparation/review` в OpenAPI.
Повторите health-проверку из среды, где действительно работает Backend.
Docker health подтверждает процесс; readiness проверяет модельный gateway,
но не заменяет проверку RAG или полноценную приёмку качества судей.

Живые модельные проверки согласовываются отдельно: они занимают ресурсы LocalAI.
Известные ограничения описаны в [runtime v2](../api/v2/runtime.md).
Успешный запуск контейнера не означает завершённую приёмку всего проекта.

## 6. Передать Backend

Передайте приватный URL `http://<IP_AI>:8000`, версию контракта `2.0.0-rc.1`
и service token через защищённый канал. Backend передаёт
`Authorization: Bearer <ARENA_SERVICE_TOKEN>`; пользовательский JWT в AI не нужен.
Поля запросов/ответов и примеры: [гайд интеграции Backend](backend-ai-v2-guide.md).
Не отдавайте service token Frontend. LocalAI 8080 — не адрес нашего AI API.

## Ошибки и обновление

- `permission denied` при обращении к Docker: нет доступа к daemon; это не ошибка Dockerfile.
- Ошибка загрузки base image: проверьте доступ к Docker Hub/GHCR.
- Ошибка COPY: проверьте корень build context и checkout, не собирайте из `deploy/ai`.
- `address already in use`: порт занят; не останавливайте неизвестный контейнер.
- Нет v2 / ошибка при старте: проверьте `ARENA_V2_ENABLED=true`, qwen mode и непустой токен.
- Readiness не готов: проверьте сетевой доступ к LocalAI, URL и точный ID модели.
- Failed-судьи: возможны проблемы retrieval или проверки модельного ответа;
  не подменяйте результат demo-оценкой.

При ошибке сборки передайте commit, команду и лог без секретов.
Обновление: согласуйте окно без активных запросов, сохраните предыдущий image tag,
получите новый commit через `git pull --ff-only`, повторите разделы 4–5 с прежним env.
Откат — предыдущий image tag и соответствующий ему Compose-файл.
Это не требует удаления RAG volumes или изменения чужого LocalAI.
