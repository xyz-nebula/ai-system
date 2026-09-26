# Живая проверка текущего среза v2

Это вызовы Qwen через LocalAI, не проверка развёрнутого `/v2/turn`:
публичный HTTP runtime пока v1. Используйте только синтетические примеры из
`docs/api/v2/examples`, не пользовательские снимки и не реальные закрытые вводные.
Проверка не изменяет серверные контейнеры, данные Backend или настройки LocalAI.

## Запуск

Из корня репозитория, при уже работающем SSH-доступе к серверу, откройте отдельный
loopback-туннель на свободном локальном порту:

```bash
ssh -N -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:18086:172.16.34.6:8080 \
  -p 8022 farrahovd234@2.26.27.230
```

В другом терминале:

```bash
export ARENA_QWEN_CHAT_URL=http://127.0.0.1:18086/v1/chat/completions
export ARENA_QWEN_MODEL=qwen3.8-9b-q4
export ARENA_QWEN_JSON_MODE=prompt
export ARENA_QWEN_TIMEOUT_SECONDS=60
export ARENA_QWEN_FAST_EXTRA_BODY='{"chat_template_kwargs":{"enable_thinking":false},"temperature":0,"max_tokens":1800}'
export ARENA_QWEN_REASONED_EXTRA_BODY="$ARENA_QWEN_FAST_EXTRA_BODY"

uv run python -m arena_ai.v2.live_eval docs/api/v2/examples/supply-turn.request.json
uv run python -m arena_ai.v2.live_eval --mode turn docs/api/v2/examples/supply-turn.request.json
uv run python -m arena_ai.v2.live_eval --mode turn docs/api/v2/examples/next-day-turn.request.json
uv run python -m arena_ai.v2.live_eval --mode agreement docs/api/v2/examples/supply-turn.request.json
uv run python -m arena_ai.v2.live_eval --scenario repeat docs/api/v2/examples/supply-turn.request.json
```

Если gateway требует API key, передайте его через защищённое окружение
`ARENA_QWEN_API_KEY`; не вставляйте в команды, отчёты или Git.
Не запускайте большое количество параллельных прогонов на общей модели.
Завершите только собственный туннель Ctrl+C, не чужие SSH-процессы.

## Что проверяется

Validator probe проверяет прямое обязательство, отрицание, условное обещание,
чужую цитату, давление, повтор обещания и числовое предложение без структурированных
terms. Вывод содержит только сценарий, решение и passed; тексты модели, private context,
снимки и ключи не выводятся. Ошибка модели не считается успешным отказом.

Validator включает консервативный veto для явных RU/EN условных формулировок,
непосредственного отрицания и авторских маркеров внутри кавычек. Он может отказаться
от неоднозначной реплики, содержащей одновременно условный контекст и настоящее
обещание. Veto не доказывает понимание языка: отсутствие этих признаков не разрешает
уступку без модельной проверки и grounded Evidence.

Turn probe проверяет один ожидаемо accepted negotiating-ход через три модельные
роли и проверенный кандидат снимка с revision+1. При model_error снимок не меняется.
Agreement probe проверяет полный кандидат сделки с доказательствами текущей пары,
всех обязательств и mandatory rules. Один accepted без stage=agreed не считается
успехом этой проверки. Сделка не закрывает round. В живом прогоне найдена путаница
индексов обязательств; модель получает явный catalogue с индексом, role_id и speaker,
но неверные доказательства не исправляются автоматически.
Это не полная сессия: partial/deferred, finish, три судьи и Trainer
v2 ещё не включены. Backend commit/CAS/deadline и интеграция с другими сервисами
также не проверяются этой командой.

## Ограничения приёмки

Проверка 26 сентября обнаружила Markdown-обёртку ответа, путаницу текста предложения
со словами пользователя, неверный переход declared→declared и нестабильную
классификацию условного обещания. Добавлены строгая обработка целого JSON fence,
уточнения инструкций и детерминированный veto с регрессионными тестами.
Отдельный удачный прогон не является экспертной NLP-приёмкой или гарантией поведения
модели на всех кейсах. Перед включением v2 в runtime нужны повторные прогоны и
проверка оставшихся операций; не заменяйте ими работающий v1.

Финальный прогон этого среза 26 сентября: Validator probe — 7/7, negotiating-ходы
`demo-supply-v2` и `demo-next-day-v2` — accepted, локальный набор — 514 passed.
Три синтаксически явных отрицательных сценария отклоняются до вызова LLM;
7/7 — результат Validator с защитным шлюзом, не оценка одной модели без защиты.

Следующий срез полной сделки: отдельный Agreement Validator прошёл проверку,
полный живой ход вернул accepted + stage=agreed. Также обнаружено смешение правила
полной сделки с доказательством уступки: эти правила исключены из контекста Offer
Validator и проверяются отдельно. Неверные proof IDs/роли по-прежнему отклоняются.
Локальный набор этого среза — 548 passed. Регрессия повтора сначала дала model_error:
модель одновременно прислала accept и is_new_direct_commitment=false со старой
Evidence. Gate не разрешил уступку. После уточнения инструкции отдельный повтор
сценария вернул reject. Это подтверждает исправление конкретного сбоя, не гарантирует
стабильность всех ответов модели; полную live/expert приёмку ещё предстоит выполнить.
После этого уточнения полный повтор Validator probe также прошёл 7/7.
