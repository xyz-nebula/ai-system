# Сохранённый серверный AI с v2: остановка и откат

Обновлено 28 сентября 2026. `arena-ai-v2-main` остановлен для передачи запуска
команде; restart policy — `no`, порт 8000 освобождён. LocalAI и RAG не остановлены.
Новый запуск: [короткий гайд](launch-ai-service.md),
[один Compose-файл](../../deploy/ai/compose.simple.yaml).
Целевой адрес — **http://172.16.34.7:8000**, сейчас старый API недоступен.

## Сохранённый остановленный экземпляр

- Контейнер: `arena-ai-v2-main`.
- Image: `arena-ai:integration-v2-20260927-01`, собран из рабочего дерева перед 31527e6.
- Используется защищённый `/home/farrahovd234/arena-ai/shared/.env`.
- V2 явно включён через `ARENA_V2_ENABLED=true`; токен не изменялся.
- Старый `arena-ai-ai-1` (v1) и `arena-ai-v2-integration` (8002) остановлены,
  но не удалены. Их images и данные сохранены для отката.
- LocalAI, Qdrant и embeddings не менялись.

Приложение основного контейнера пока сохраняет совместимые v1-маршруты.
Отдельный старый v1-процесс больше не работает; новые клиенты используют только v2.

## Исторические проверки 27 сентября после переноса

На основном 8000: live/ready HTTP 200, все четыре v2 POST в OpenAPI,
без токена 401, неверная версия 409, пустое тело с правильными заголовками 422.
После переноса не запускалась новая модельная оценка: этот же image ранее дал
evaluate HTTP 200 за 68.63 с — исход/Trainer/negotiation ready,
hiring/ownership invalid_judge_output. Перенос порта не исправляет эти AI-баги.

Из Backend обращаться к приватному IP, не к localhost.
Нужны внутренний токен и `X-Arena-Contract-Version: 2.0.0-rc.1`.
[Гайд Backend](backend-ai-v2-guide.md), [состояние AI](ai-current-state.md),
[общекомандный аудит](full-stack-connection-guide.md).

## Воспроизводимый запуск основного экземпляра

Команда ниже описывает текущий отдельный запуск, не предназначена для повторного
создания уже существующего контейнера. Сначала проверить, кто занимает 8000;
не останавливать чужой listener.

```bash
docker run -d --name arena-ai-v2-main --network host \
  --env-file /home/farrahovd234/arena-ai/shared/.env \
  -e ARENA_V2_ENABLED=true --user 10001:10001 --read-only \
  --tmpfs /tmp:size=16m,mode=1777 --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 128 --memory 1g --cpus 2 \
  --restart unless-stopped --log-opt max-size=10m --log-opt max-file=3 \
  --health-cmd "python -c 'import urllib.request; urllib.request.urlopen(\"http://172.16.34.7:8000/health/live\", timeout=3)'" \
  --health-interval 15s --health-timeout 5s --health-start-period 15s --health-retries 3 \
  arena-ai:integration-v2-20260927-01 \
  uvicorn arena_ai.app:app --host 172.16.34.7 --port 8000 \
  --no-access-log --log-level warning
```

Команда docker run выше описывает прежний запуск, не новый рекомендуемый деплой.
Не выполняйте её при запуске через compose.simple.yaml. Старый production-compose не
запускать параллельно: он создаст arena-ai-ai-1 на том же порту, а v2 по умолчанию
выключен. Перевод основного релиза под Compose потребует согласованного переключения
с явным ARENA_V2_ENABLED=true и тем же токеном.

## Остановка и откат

Остановить основной AI: `docker stop arena-ai-v2-main`.
Запустить его обратно для согласованного отката: `docker start arena-ai-v2-main`.
Сначала остановите новый AI и убедитесь, что 8000 свободен. Чтобы восстановить
автозапуск старого контейнера после отката:
`docker update --restart=unless-stopped arena-ai-v2-main`.

Если нужен откат к старому v1, сначала остановить main, затем
`docker start arena-ai-ai-1`. Это вернёт v1 на 8000; Backend v2 при таком откате
не будет работать. Не запускать оба одновременно. Не удалять секреты/images/RAG volumes.

Откат к сохранённому стенду 8002: `docker start arena-ai-v2-integration`;
при этом основной адрес клиентов надо согласовать отдельно.
