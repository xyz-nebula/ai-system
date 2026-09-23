# Инфраструктура retrieval

Status: ready-for-agent

## Problem Statement

AI-контур должен использовать общую Negotiation Knowledge Base, но сейчас у него нет доступного
векторного хранилища и embedding endpoint. Требования описывают Qdrant и отдельные retrieval-профили
для Coach, Opponent и Judge, однако отсутствует воспроизводимый способ поднять базовый runtime.

## Solution

Развернуть на модельном сервере отдельный Qdrant и Text Embeddings Inference с
`Qwen/Qwen3-Embedding-0.6B`. Оба HTTP endpoint публикуются только на loopback сервера и доступны
разработчику через SSH local forwarding. LocalAI на порту `8080` не изменяется.

## Implementation Decisions

- Qdrant и embedding runtime запускаются отдельным Docker Compose project `arena-rag`.
- Qdrant закреплён на `v1.19.1`, CPU-образ TEI — на ветке `1.9`.
- Начальная embedding-модель — публичная `Qwen/Qwen3-Embedding-0.6B`; образ и model ID допускают
  явную замену через окружение после проверки ресурсов сервера.
- Для приемлемого первого CPU-прогрева TEI ограничен batch в 2048 токенов; лимит допускает
  явную замену через окружение.
- REST Qdrant слушает `127.0.0.1:6333`, gRPC — `127.0.0.1:6334`, embeddings —
  `127.0.0.1:8081`; наружу эти порты не публикуются.
- Веса модели и данные Qdrant хранятся в отдельных Docker volumes.
- Smoke test создаёт уникальную временную коллекцию, проверяет embedding batch, запись и
  семантический поиск, затем удаляет только созданную им коллекцию.

## Testing Decisions

- `docker compose config` проверяет итоговую конфигурацию до работы с Docker daemon.
- После развёртывания HTTP smoke test должен подтвердить полный цикл
  `text → embedding → Qdrant → nearest-neighbor result`.
- Проверка выполняется через SSH-туннель и не обращается к существующему LocalAI `:8080`.

## Out of Scope

- Chunking и индексация полной базы знаний.
- Подключение retrieval к промптам Coach, Opponent и Judge.
- Reranker, hybrid search, production HA, внешняя публикация портов и TLS-терминация.
