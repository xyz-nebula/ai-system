# Проверка ролей и подготовки — 27 сентября 2026

Проверка исходников GitHub, включая приватные репозитории. Это не проверка запущенных контейнеров и не сквозной тест. Другие репозитории не изменялись.

## Согласованная модель

Case содержит две авторские подготовки для двух активных ролей. Chat содержит одну личную подготовку пользователя — текст, собранный фронтендом. Это разные сущности.

Пользователь выбирает роль. Backend сохраняет этот выбор и назначает противоположную роль AI: первая → вторая, вторая → первая. LLM не выбирает роль случайно и не меняет её между ходами. Остальные участники ситуации могут оставаться в контексте кейса, не становясь активными собеседниками.

| Данные | Владелец | Передача в AI |
| --- | --- | --- |
| `first_role`, `first_role_preparations` | Case, автор/админ | В `player` или `opponent` согласно выбранной паре |
| `second_role`, `second_role_preparations` | Case, автор/админ | Аналогично; текст подготовки в `RoleBrief.role_preparation` |
| Выбранная роль пользователя | Backend, конкретный Chat | Стабильный `player_role_id` и противоположный `opponent_role_id` |
| `Chat.preparations` | Пользователь, конкретный Chat | Одна строка `FinishRequest.preparation`, только тренеру |
| Приватные вводные AI-роли | Case | Только оппоненту, не пользователю и не публичным судьям |

В нашем v2 это разделение уже заложено: [контракты](https://github.com/xyz-nebula/ai-system/blob/bb6e082fc85de6c16f19c392ba27abd294f9651c/src/arena_ai/v2/contracts.py), [проекции контекстов](https://github.com/xyz-nebula/ai-system/blob/bb6e082fc85de6c16f19c392ba27abd294f9651c/src/arena_ai/v2/contexts.py). Но v2 `/finish`, судьи и тренер ещё не реализованы как рабочий HTTP-поток; DTO не означает готовую интеграцию.

## Что обнаружено в остальных репозиториях

### Backend — dev `c78e6e5`

Две подготовки Case и одна строка Chat уже существуют в [ORM](https://github.com/xyz-nebula/backend/blob/c78e6e5589d6589fccd2db2d16c66326b9a56faa/app/database/models.py).

Однако [ChatCreateRequest](https://github.com/xyz-nebula/backend/blob/c78e6e5589d6589fccd2db2d16c66326b9a56faa/app/api/v1/routers/models.py) принимает только `name`, `case_uuid`: нет выбранной роли и пользовательской подготовки. В [маршрутах](https://github.com/xyz-nebula/backend/blob/c78e6e5589d6589fccd2db2d16c66326b9a56faa/app/api/v1/routers/chat.py) нет сохранения подготовки или AI turn/finish; сообщения только сохраняются. Клиентское `is_ai` нельзя использовать как доверенную историю модели.

CaseResponse выдаёт обе авторские подготовки. Если там скрытые интересы, BATNA или красные черты, их необходимо убрать из публичного каталога и выдавать только разрешённые вводные выбранной роли. Скрытие на фронтенде не защищает HTTP-ответ.

[Миграция](https://github.com/xyz-nebula/backend/blob/c78e6e5589d6589fccd2db2d16c66326b9a56faa/migrations/models/1_20260926213927_case_role_preparations.py) удаляет старую Case.preparations без переноса текста: перед применением к заполненной базе нужен план сохранения данных.

### Admin frontend — dev `3b21ca9`

В [форме](https://github.com/xyz-nebula/admin-frontend/blob/3b21ca91ad453c3a88858927544618e74b4e80a4/src/pages/CasesPage.tsx) уже две авторские подготовки. Это соответствует решению. Но этих строк недостаточно для полного v2-кейса: нужны типизированные предметы торга, ограничения и стратегия уступок либо явно утверждённый автором и валидированный способ их заполнения. Нельзя молча угадывать жёсткие ограничения из свободного текста.

### Frontend — dev `5dff36e`

[Запуск переговоров](https://github.com/xyz-nebula/front-end/blob/5dff36eb3099715512f9a8a4413980c17b460ef7/src/features/preparation/useStartNegotiation.ts) знает `roleIndex`, но не передаёт его в `createSession`: роли сохраняются лишь локально. [DTO](https://github.com/xyz-nebula/front-end/blob/5dff36eb3099715512f9a8a4413980c17b460ef7/src/services/real/targetContract.ts) отправляет `name`, `case_uuid`, `preparations`, причём последнее поле отсутствует в Backend ChatCreateRequest.

Парсер намеренно не раскрывает обе авторские подготовки в UI, но они всё равно приходят в сетевом ответе. В [клиенте](https://github.com/xyz-nebula/front-end/blob/5dff36eb3099715512f9a8a4413980c17b460ef7/src/services/real/backendNegotiationClient.ts) описания ролей берутся из локальных примеров; итог переговоров пока демонстрационный, не ответ наших судей. [Сериализация личной подготовки](https://github.com/xyz-nebula/front-end/blob/5dff36eb3099715512f9a8a4413980c17b460ef7/src/features/preparation/preparation.ts) уже собирает одну строку; для пустой карточки нужен согласованный маркер отсутствия, а не оценка служебного текста как плана пользователя.

### Audio engine — dev `1dc0c2c`

[CaseResponse](https://github.com/xyz-nebula/audio-engine/blob/1dc0c2cb89a046059bc75241ea68d6387286cac3/app/api/routers/models.py) по-прежнему требует старое `case.preparations`, которое Backend уже удалил. Это конкретная несовместимость десериализации.

[Chat service](https://github.com/xyz-nebula/audio-engine/blob/1dc0c2cb89a046059bc75241ea68d6387286cac3/app/services/chat_service.py) берёт единый `case.system_prompt`. [Audio bridge](https://github.com/xyz-nebula/audio-engine/blob/1dc0c2cb89a046059bc75241ea68d6387286cac3/app/services/audio_bridge_service.py) напрямую генерирует ответы через LocalAI Realtime, обходя наш Guard/Opponent/Validator. Для согласованной архитектуры текст пользователя должен идти через Backend в ai-system, а озвучиваться должен принятый ответ. Прямой отдельный AI-диалог не обеспечивает наши гарантии.

### Knowledge base — master `5f7a99d`

[Структура кейса](https://github.com/xyz-nebula/knowledge-base/blob/5f7a99d0eeb66e76b0646c19349c534490c27309/business/Структура%20кейса.md) предусматривает подготовку к каждой роли. Это не подмена личной карточки пользователя. Согласованное разделение не требует возвращать две пользовательские подготовки или смешивать их с вводными оппонента.

## Что передать команде

1. Backend: добавить стабильный выбранный role ID в создание/хранение Chat, назначать противоположную роль; принимать и сохранять личную строку подготовки; строить v2-проекцию Case и канонический snapshot; реализовать AI bridge и защитить приватные вводные.
2. Frontend: отправлять выбранную роль, согласовать сохранение одной подготовки с реальным DTO Backend, получать разрешённые вводные выбранной роли и настоящий итог вместо demo.
3. Admin/Backend: обеспечить полный валидируемый AI-конфиг кейса, а не только два текста.
4. Audio: обновить DTO после изменения Case и перейти на согласованный поток через Backend, без независимого AI-оппонента.
5. AI-system: сохранять нынешнее разделение контекстов, завершить v2 finish/судей/тренера и затем проверить интеграцию на реальных сервисах.

Итог: бизнес-решение подходит нашему v2, но сквозная интеграция ещё не готова. Проверены актуальные dev-линии и основные ветки; для Backend/Admin дополнительно сопоставлены все remote branch tips. Проверка исходников не доказывает, какая версия сейчас развёрнута на сервере.
