# Backend: аудит готовности к AI-интеграции

Дата: 2026-09-26. Проверен `xyz-nebula/backend`, `dev`:
`79dc4bf3b8e79ff413a4a016cd24a074a555a408`. Удалённая ветка перепроверена после аудита.
`main`: `887752c236494d0e94e9249de16a2ebd65e47683`, значительно старее.

Это оценка текущего кода, не ревью одного PR и не проверка живого серверного деплоя.
Backend и другие сервисы не изменялись. Проверки выполнены во временной копии
с изолированной тестовой SQLite; серверные данные не затрагивались.

## Вывод

Есть рабочая основа авторизации, каталога кейсов, админки и хранения чатов.
Нет реализации управляемого AI-хода и завершения поединка. Одной настройки URL
недостаточно: отсутствуют клиент AI, канонический снимок, сериализация ходов,
команды/дедупликация, хранение итоговой аналитики и жизненный цикл раунда.

## Что уже сделано правильно

- JWT проверяется на защищённых маршрутах; доступ к чату ограничен владельцем
  через `get_chat_by_uuid_for_user` и `_require_chat`. Чужой чат не раскрывается.
  [ChatService](https://github.com/xyz-nebula/backend/blob/79dc4bf3b8e79ff413a4a016cd24a074a555a408/app/services/ChatService.py#L109).
- Каталог кейсов доступен авторизованным пользователям; создание/редактирование
  кейсов защищено `get_current_admin`.
  [Маршруты админки](https://github.com/xyz-nebula/backend/blob/79dc4bf3b8e79ff413a4a016cd24a074a555a408/app/api/v1/routers/admin.py#L23).
- `system_prompt` отделён от пользовательского `CaseResponse` и появляется только
  в `AdminCaseResponse`; тесты проверяют отсутствие этого поля в пользовательской выдаче.
  [Схемы](https://github.com/xyz-nebula/backend/blob/79dc4bf3b8e79ff413a4a016cd24a074a555a408/app/api/v1/routers/models.py#L70).
- Чат связан с пользователем и кейсом, сообщения сохраняются, есть публичные роли,
  описание, цель и `time_limit`. Это можно переиспользовать, переписывать весь backend не нужно.
- 67 существующих тестов проходят; Ruff check, format-check и ty проходят.
  Это проверка текущего CRUD/auth, не доказательство готовности AI-интеграции.

## Подтверждённые проблемы

### 1. Пользователь может подделать AI-сообщение — исправить до интеграции

`MessageCreateRequest.is_ai` принимается из браузера и без изменения передаётся
в `ChatService.post_message` → `create_message`. Пользователь может записать любые
условия от имени директора, минуя AI/Guard/Validator. Существующий API-тест
`test_get_chat_assembles_messages_in_sequence` прямо подтверждает HTTP 200 для `is_ai=true`.

[Схема](https://github.com/xyz-nebula/backend/blob/79dc4bf3b8e79ff413a4a016cd24a074a555a408/app/api/v1/routers/models.py#L139),
[сервис](https://github.com/xyz-nebula/backend/blob/79dc4bf3b8e79ff413a4a016cd24a074a555a408/app/services/ChatService.py#L71).

Для поединков браузер передаёт только пользовательскую команду. AI-сообщение создаёт
backend только из проверенного ответа AI. Старый CRUD не должен менять канонический
транскрипт, обходя эту операцию. Удаление отдельных сообщений поединка также нельзя
использовать для незаметного изменения доказательств уже состоявшихся ходов.

### 2. Порядок сообщений не защищён от гонки — воспроизведено

`create_message` читает последний `sequence`, затем отдельно делает INSERT.
Нет блокировки/атомарного счётчика и уникальности `(chat, sequence)`.
В локальном опыте десять конкурентных вызовов получили один `sequence=1`.

[Действие БД](https://github.com/xyz-nebula/backend/blob/79dc4bf3b8e79ff413a4a016cd24a074a555a408/app/database/actions/message.py#L9).
Проверка: десять параллельных вызовов `create_message` через `asyncio.gather` в отдельной временной SQLite.
Это не нагрузочный тест production Postgres, но подтверждение небезопасного алгоритма.

Нужны межпроцессная сериализация по сессии, атомарная фиксация snapshot/сообщений/
результата команды и ограничение уникальности. Одна asyncio.Lock не решает проблему
нескольких backend workers. Не удерживать долгую DB-транзакцию на время вызова модели
без продуманного механизма резервирования команды и восстановления после сбоя.

### 3. Обновление схемы БД не предусмотрено

В Case добавлены обязательные поля, а приложение использует `generate_schemas=True`.
Это создаёт таблицы, но не является миграцией существующих таблиц. Коммит `966aa18`
прямо отмечает необходимость reset существующей БД. Для сервера с данными reset —
не приемлемая процедура обновления без отдельного согласования.

[Запуск ORM](https://github.com/xyz-nebula/backend/blob/79dc4bf3b8e79ff413a4a016cd24a074a555a408/app/app.py#L25).
Нужна миграция с заполнением новых полей и backup/rollback. Свежая тестовая SQLite
не проверяет обновление существующей серверной БД.

### 4. Небезопасный fallback выдачи admin — условный риск деплоя

При отсутствии `ADMIN_CODE` используется публичный default `change-me`; приложение
лишь пишет warning. Авторизованный пользователь может стать admin с этим кодом.
Проверка роли на остальных admin-маршрутах правильная, но bootstrap должен быть безопасным.

[Настройки](https://github.com/xyz-nebula/backend/blob/79dc4bf3b8e79ff413a4a016cd24a074a555a408/app/config/config.py#L11),
[проверка кода](https://github.com/xyz-nebula/backend/blob/79dc4bf3b8e79ff413a4a016cd24a074a555a408/app/services/AdminService.py#L80).
Не установлено, какой ADMIN_CODE в настоящем деплое. Перед общим запуском задать
секрет, запретить default в серверном режиме или отключить публичный bootstrap.
Dev Compose содержит также тестовый JWT secret и опубликованные порты БД/Valkey:
это dev-конфигурация, не безопасный production-шаблон.

## Чего не хватает по контракту интеграции

| Компонент | Текущее состояние | Требуемое дополнение |
| --- | --- | --- |
| AI client | В app нет вызовов AI, настроек URL/token; HTTPX только dev-зависимость | Серверный клиент `/v1/turn`, `/v1/finish`, token, timeouts, проверка ответов |
| CaseConfig | Case содержит общие строки и один system_prompt | Валидируемая серверная конфигурация с отдельными private contexts, rules, strategy и выбранными ролями |
| SessionSnapshot | Chat хранит владельца, кейс и enum статуса; Message — отдельный текст | Полный snapshot с state/transcript/opponent_progress, версия и атомарное обновление |
| Команды | Нет turn_id, дедупликации и записи неопределённого результата | Командные записи, одна активная операция на сессию, без слепого retry после timeout |
| Раунд | time_limit есть только у Case | Единицы времени, started_at/deadline/finished_at, start/finish, защита от ходов после завершения |
| Подготовка | Case.preparations — строка кейса | Отдельная пользовательская PreparationCard на сессию для Trainer |
| Итоги | Feedback/Judgement — текст и UUID без FK; нет finish/result API | Полный FinishResponse: outcome, три judge slots, TrainerSlot; связать с владельцем, хранить и повторно выдавать |
| Статусы | victory/defeat/ongoing | Разделить жизненный цикл раунда и исход: agreement/partial_agreement/deferred/no_agreement, не превращать голос судьи в victory |

Источники: [модели БД](https://github.com/xyz-nebula/backend/blob/79dc4bf3b8e79ff413a4a016cd24a074a555a408/app/database/models.py),
[ChatService](https://github.com/xyz-nebula/backend/blob/79dc4bf3b8e79ff413a4a016cd24a074a555a408/app/services/ChatService.py),
[настройки](https://github.com/xyz-nebula/backend/blob/79dc4bf3b8e79ff413a4a016cd24a074a555a408/app/config/config.py).

Наличие первого/второго имени роли ещё не фиксирует выбор роли для конкретного поединка.
Нельзя автоматически считать любой `system_prompt` готовым CaseConfig: нужен явный
mapper/серверный реестр конфигураций или валидируемый JSON. Правила и лестница уступок
не должны теряться в переводе из админки. Конфигурацию кейса нужно версионировать или
фиксировать на старте, чтобы редактирование админом не меняло текущий поединок.

AI статусы обрабатывать отдельно: accepted/blocked сохраняют возвращённый snapshot;
model_error не продвигает его. В браузер — публичная проекция, не raw snapshot и не
service token. Agreement не завершает раунд автоматически. Failed judge slots
сохранять как failed, без demo-подмены.

## Порядок работы для команды backend

1. Закрыть подделку AI-сообщений; определить внешний API управляемого хода/result с frontend.
2. Добавить хранилище серверного CaseConfig, версию кейса, snapshot/команды/раунд/подготовку
   и безопасные миграции. Устранить гонку sequence.
3. Добавить AI client и text-turn orchestration с сериализацией, статусами, публичной
   проекцией и обработкой неопределённого timeout без blind retry.
4. Добавить finish/result и сохранение полного ответа, исключить гонку с активным turn.
5. Проверить из контейнера backend приватную сеть и service token; затем один настоящий
   сквозной text-session. Только после него подключать голосовой путь через тот же backend.

Приёмка: чужая сессия запрещена; is_ai нельзя подделать; повтор команды не вызывает
второй AI-ход; конкурентные turn/finish не расходят snapshot; blocked/model_error
не превращаются в accepted; приватные поля не появляются в браузере; частичный finish
сохраняется и повторно открывается; agreed не завершает раунд; обновление БД сохраняет данные.

Основа требований: [гайд интеграции](https://github.com/xyz-nebula/ai-system/blob/dev/docs/integration/team-integration.md),
[OpenAPI AI-сервиса](https://github.com/xyz-nebula/ai-system/blob/dev/docs/api/openapi.json),
[контракт поединка](https://github.com/xyz-nebula/ai-system/blob/dev/docs/adr/0002-duel-contract.md) и
[порядок доставки ходов](https://github.com/xyz-nebula/ai-system/blob/dev/docs/adr/0004-backend-owns-turn-delivery.md). Состояние живого backend, его deployed commit, секреты
и доступность AI из backend-контейнера этим аудитом не проверялись.
