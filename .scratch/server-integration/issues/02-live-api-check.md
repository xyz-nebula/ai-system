# 02: Проверка серверного публичного API

Status: ready-for-agent

Blocked by: 01

- [x] Воспроизводимая безопасная проверка HTTP-контракта.
- [x] Настоящий управляемый ход через серверный контейнер.
- [x] Finish с настоящим retrieval, тремя судьями и Trainer; failed-слоты честно отражены.
- [x] Локальные тесты, lint, type-check и OpenAPI не регрессировали.

## Comments

- 2026-09-26: полный adversarial acceptance остаётся отдельной незакрытой проверкой.
- 2026-09-26: 348 локальных тестов, lint, ty, OpenAPI и source verification успешны.
  Процессный тест проверяет также минимальный turn/finish через независимый gateway,
  но не выдаётся за доказательство качества живого Qwen.
- 2026-09-26: минимальный живой smoke на `arena-ai:f4e50d251aae` прошёл 13 проверок:
  реальный turn accepted, finish получен, все три судьи и Trainer ready. Отчёт:
  `../reports/2026-09-26-live-smoke.json`. Это НЕ полный adversarial acceptance,
  не экспертная оценка судей и не проверка интеграции с реальным Backend/Frontend/Audio.
- 2026-09-26: рабочая машина получает health/ready через отдельный SSH tunnel
  `127.0.0.1:18000 → 172.16.34.7:8000`; прямой VPN HTTP истёк по timeout.
- 2026-09-26: финальные проверки — 350 passed, Ruff lint, формат изменённых Python-файлов,
  ty, OpenAPI и diff check успешны. Добавлены негативные process проверки partial finish
  и отсутствующего service token; они не вызывают настоящий gateway.
