# Интеграционный контракт AI-сервиса

- `openapi.json` — зафиксированная схема работающего AI-сервиса.
- `examples/managed-turn.json` — безопасные примеры `accepted`, `blocked`, `model_error`, 409 и 401. Значения закрытых вводных и service token заменены placeholders.

Проверить, что схема не разошлась с приложением:

```bash
uv run python scripts/export_openapi.py --check
```

После намеренного изменения публичного API обновить схему:

```bash
uv run python scripts/export_openapi.py
```

Воспроизвести интеграционный сценарий без живого Qwen:

```bash
uv run pytest tests/black_box/test_managed_turn_process.py -q
```

Тест запускает на loopback-портах два независимых процесса: управляемый OpenAI-compatible gateway и `arena_ai.app:app`. Он проверяет readiness, Bearer auth, `accepted`, `blocked`, `model_error`, неизменность снимка при ошибке, 409 завершённого поединка и совпадение live OpenAPI с committed-схемой.
