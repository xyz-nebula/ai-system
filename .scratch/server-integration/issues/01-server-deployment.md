# 01: Серверный запуск AI-сервиса

Status: ready-for-agent

- [x] Dockerfile с locked dependencies и непривилегированным процессом.
- [x] Отдельный compose project с приватным bind, read-only filesystem и healthcheck.
- [x] Защищённая серверная конфигурация и документация отката.
- [x] Образ собран и сервис запущен без изменений чужих контейнеров.
- [x] Публичные health/OpenAPI/auth проверены на сервере.

## Comments

- 2026-09-26: SSH работает, сервер `172.16.34.7`; LocalAI:8080, Qdrant и TEI доступны.
- 2026-09-26: пользователь подтвердил границы тестирования health/turn/finish/OpenAPI.
- 2026-09-26: `arena-ai-ai-1` healthy, user 10001, read-only rootfs; слушает
  `172.16.34.7:8000`. Первый серверный smoke прошёл все 8 проверок. Токен создан
  на сервере, shared mode 0700, env mode 0600; RAG и LocalAI не изменялись.
- 2026-09-26: текущий bundle `f4e50d251aae346be917f87a4093c12ea540413eba73e4586c1e94c012c70dbe`,
  image tag `arena-ai:f4e50d251aae`. Предыдущий `arena-ai:fcc42360cd9a` сохранён для отката.
