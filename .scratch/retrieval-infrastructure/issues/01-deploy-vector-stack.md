# 01: Развернуть Qdrant и Qwen3 Embeddings

**What to build:** воспроизводимый серверный runtime Qdrant и embedding endpoint, доступный только
через SSH port forwarding.

Status: ready-for-agent

- [x] Compose фиксирует отдельные сервисы, версии, persistent volumes и loopback-порты.
- [x] Smoke test проверяет embedding, временную коллекцию и semantic search.
- [x] Документация содержит команды серверного запуска и SSH-туннеля.
- [x] Получен рабочий SSH shell с доступом к Docker на модельном сервере.
- [x] На сервере проверены GPU, RAM, диск и конфликты портов без обращения к LocalAI `:8080`.
- [x] Compose запущен на сервере, оба endpoint прошли readiness и smoke test через туннель.

## Comments

- 2026-09-24: WireGuard-маршрут и SSH transport доступны, но известный ключ пользователя
  `farrahovd234` отклоняется на `172.16.34.6:22` и `2.26.27.230:8022` с
  `Permission denied (publickey)`. Для продолжения нужен разрешённый SSH key/account и Docker.
- 2026-09-24: причина отказа — зашифрованный ключ не был загружен в `ssh-agent`. После загрузки
  ключа подтверждён вход как `farrahovd234` через `2.26.27.230:8022`.
- 2026-09-24: на сервере запущены `qdrant/qdrant:v1.19.1` на loopback-портах 6333/6334 и
  `Qwen/Qwen3-Embedding-0.6B` через CPU TEI 1.9 на loopback-порту 8081. Порт 8080 не изменялся.
  Оба контейнера прошли readiness без рестартов. Smoke test через SSH-туннель получил векторы
  размерности 1024, записал их в Qdrant, поставил BATNA на первое место и удалил временную
  коллекцию.
