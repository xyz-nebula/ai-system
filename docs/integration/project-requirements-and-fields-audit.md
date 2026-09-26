# Соответствие требованиям и обмен данными между командами

**Срез аудита текущего кода и первого draft.** Найденные проектные пробелы затем
учтены в [целевом контракте 2.0.0-rc.1](../api/v2/README.md). Наличие новой
спецификации не меняет выводы о неполной реализации. Словарь draft в приложении A
исторический; актуальные target-поля находятся в [новом словаре](../api/v2/fields.md).

Дата: 2026-09-26. Проверка исходников, **не проверка запущенного приложения**.

## Короткий ответ

**Нет: все функциональные требования ещё не выполнены, и замечания не исправлены
полностью в работающем коде.** Универсальный v2 — проект схемы, а не реализация.
В v1 остаются KPI/недели/повышение и структурированная PreparationCard; текстовую
подготовку v1 не принимает. Согласование формата не равно готовности интеграции.

Даже проект v2 пока недостаточен для полного FR v0.3: нет интерфейса поэтапной
проверки подготовки, временных отметок в AI-транскрипте, полного описания цены
результата/последствий, авторских доступных ролевых сочетаний и согласованной
семантики немедленного прерывания голосового ответа. Ниже эти пробелы не скрыты
под формулировкой «всё готово».

## 1. Что именно проверено

GitHub вернул 6 доступных репозиториев организации, включая 3 приватных. Это все
репозитории, видимые текущей авторизации; наличие недоступных ей репозиториев
исключить нельзя. Перечень веток просмотрен; основная оценка — текущие dev либо
master и фактические исходники, не только README. Старые feature-ветки не считаются
актуальной интеграцией автоматически. Ветка запуска на сервере из Git не следует.

| Репозиторий | Проверенная основная версия | Что является источником истины |
| --- | --- | --- |
| ai-system | dev `e669c42c9b891fee0dafe45286a06be90decee2c` + локальный проект документов v2 | Реализованные Python-модели и маршруты v1; draft отдельно |
| backend | dev `412fb983ae3e2b365ceaceab13876b3699f6e50e` | Pydantic DTO, routers, ORM; main `887752c…` старее |
| knowledge-base | master `72887a9d2389ad0ab2ada291a62de288c9fe5c63` | Бизнес-документы, особенно FR v0.3 |
| front-end (private) | dev `a62387b18d67038314fea05e2a6484b8e66caae9` | Реальный клиент + его локальные заглушки |
| audio-engine (private) | dev `c4d3907f64676613e0374daf96c1e500073824e5` | Realtime-путь, STT/TTS, запись сообщений |
| admin-frontend (private) | dev `9095bcd7f990ba4ae08b18f289af8fe9a246e3f5` | Форма кейса и HTTP payload |

Детальный разбор остальных клиентов, типов и веток:
[Frontend, Admin и Audio: фактические контракты](frontend-audio-current-contracts.md).

Основные первичные источники:

- [FR v0.3 — зафиксированная версия](https://github.com/xyz-nebula/knowledge-base/blob/72887a9d2389ad0ab2ada291a62de288c9fe5c63/business/Функциональные%20требования%20v0.3.md).
- [Структура кейса](https://github.com/xyz-nebula/knowledge-base/blob/72887a9d2389ad0ab2ada291a62de288c9fe5c63/business/Структура%20кейса.md).
- [Подготовка к роли](https://github.com/xyz-nebula/knowledge-base/blob/72887a9d2389ad0ab2ada291a62de288c9fe5c63/business/Подготовка%20к%20роли.md).
- [Структура аналитики](https://github.com/xyz-nebula/knowledge-base/blob/72887a9d2389ad0ab2ada291a62de288c9fe5c63/business/Структура%20аналитики%20поединка.md).
- [Backend DTO](https://github.com/xyz-nebula/backend/blob/412fb983ae3e2b365ceaceab13876b3699f6e50e/app/api/v1/routers/models.py),
  [ORM](https://github.com/xyz-nebula/backend/blob/412fb983ae3e2b365ceaceab13876b3699f6e50e/app/database/models.py),
  [chat routes](https://github.com/xyz-nebula/backend/blob/412fb983ae3e2b365ceaceab13876b3699f6e50e/app/api/v1/routers/chat.py).
- [AI-модели v1](https://github.com/xyz-nebula/ai-system/blob/e669c42c9b891fee0dafe45286a06be90decee2c/src/arena_ai/contracts.py),
  [AI routes](https://github.com/xyz-nebula/ai-system/blob/e669c42c9b891fee0dafe45286a06be90decee2c/src/arena_ai/app.py),
  [OpenAPI v1](../api/openapi.json), [проект v2](../api/drafts/case-contract-v2-proposal.md).

## 2. Проверка функциональных требований

Статусы ниже не означают экспертную приёмку качества LLM.
«Есть в AI» означает реализацию нашей части, но не готовность пользовательского пути.
Номера требований — из FR v0.3 по ссылке выше.

| Требования | Фактическое состояние | Что осталось / владелец |
| --- | --- | --- |
| AUTH-01,02 | Backend имеет JWT и проверки владельца чата | Проверить весь пользовательский путь и голосовой доступ; Backend/Frontend/Audio |
| AUTH-03 | Чаты/сообщения сохраняются, пользовательская подготовка отдельной сессии не представлена DTO | Хранение подготовки, версий и snapshot; Backend |
| CASE-01,02 | Backend каталог и описания есть | Действительный каталог на Frontend, однозначный mapping краткого/полного описания |
| CASE-03,04 | first_role/second_role — две строки, не каталог участников/разрешённых сочетаний | Все участники, stable role IDs, разрешённые пары, выбор роли; Backend/Admin/Frontend |
| CASE-05 | system_prompt и текст preparations не выражают полностью ролевую методическую конфигурацию | Авторские вводные/границы/возможные исходы и последствия; Backend/Admin/AI |
| PREP-01 | V1 AI знает только часть подготовки; FE не имеет полноценного сервиса подготовки | Все необязательные элементы UI; Frontend; хранение текста Backend; Trainer v2 AI |
| PREP-02,03,04 | Ни v1 turn/finish, ни draft v2 не являются AI-помощником проверки блока | Отдельный интерфейс проверки выбранного блока и его версия, отдельная реализация AI |
| PREP-05 | Уточнение команды: сохранить одним текстом; это ещё не реализованная связь | Склейка с подписями, привязка к роли, возврат прошлой подготовки; Backend/Frontend |
| GAME-01 | Выбор UI-роли не гарантирует изменение реальных вводных AI | Backend фиксирует пару и выбирает авторскую проекцию; AI убрать hardcode |
| GAME-02 | Наш turn начинается с пользователя | Голосовой прототип не должен сам начинать/отвечать вне этого пути |
| VOICE-01,02,03 | Есть Realtime-аудиопрототип | Перенаправить финальный STT через Backend → AI; TTS только проверенного текста |
| VOICE-04 | AI v1 учитывает переданный snapshot | Audio сейчас использует другой путь; единая история и последовательность |
| AI-01 | Ролевые вводные и стратегия есть для первого кейса | Универсальные роли/интересы/отношения/ограничения ещё не реализованы |
| AI-02,03,04 | Есть Validator, лестница уступок, сохраняемое состояние для первого кейса | Обобщить проверку границ и последовательности; экспертные проверки разных кейсов |
| AI-05,06 | В коде есть сопротивление, реакция на давление, запрет преждевременного окончания | Не гарантировано в обходном аудиопути; сквозные конфликтные сценарии |
| TIME-01,02 | Backend time_limit есть; длительность сама не равна серверному deadline | ≤300 секунд от «Начать», authoritative deadline; UI таймер; Backend/Frontend |
| TIME-03,04 | Draft описывает finish, но не реализует прерывание звука/сигнал | При 00:00 или кнопке отменить воспроизведение/генерацию, зафиксировать последний допустимый ход; все три команды |
| TRANS-01,02,03,04 | Backend сообщения с created_at; AI история/цитаты по turn_id без временной отметки | Связь роли/turn_id/message_id/времени и отображение mm:ss; Backend/Audio/AI/Frontend |
| OUT-01 | AI v1 возвращает 4 типа исхода отдельно от голосов | Передать реальный finish на FE вместо demo |
| OUT-02,03 | Условия/обязательства есть, но универсальные уступки/последствия/цена не покрыты гарантированными полями | Дополнить модель и анализ исхода, только по наблюдаемым данным; AI/Backend/Frontend |
| JUDGE-01…07 | Три отдельных последовательных вызова, выбор/критерий/цитата/наблюдение/эффект/сравнение; внутренний RAG | Экспертная приёмка, разные роли/кейсы и UI реальных слотов; независимость не требует 3 моделей |
| COACH-01,03…06 | Отдельный Trainer, эпизоды, последствия, next_try | Универсальность, полноценные пропущенные возможности/позиции и экспертная приёмка |
| COACH-02 | V1 сопоставляет лишь структурированную урезанную PreparationCard | Новый Trainer для одной строки, всех явно заполненных блоков; без выдумывания плана |
| RESULT-01 | Наш finish отдаёт отдельные блоки | FE finish сейчас демонстрационный; показать реальные исход/слоты/Trainer/replay |
| REPLAY-01,02,03 | Контракт допускает новый снимок, но полного пути нет | Новый session_id, те же case version/roles/закрытые настройки, возврат к подготовке; Backend/Frontend |
| ADMIN-01,02 | CRUD Backend и административная форма есть | Согласовать полноту формы и сохранение ролевой конфигурации |
| ADMIN-03,04,05 | CRUD ещё не связан с нашими реальными вызовами | Проекция из сохранённого кейса, неизменяемые версии, экспертно утверждённые кейсы |

Раздел 15 допускает дополнительные методологии позднее; не считаем всё перечисленное
там обязательными отдельными агентами MVP.

### Содержательные расхождения требований

`Структура аналитики` описывает сильный и слабый эпизоды каждого судьи и содержит
пример с названием методики. Позднее пользователь передал прямое уточнение владельца:
судья объясняет один решающий голос и **не упоминает методички вообще**. Наш код следует
этому уточнению и FR-JUDGE-07. Не объявляем документы полностью согласованными:
владельцу knowledge-base нужно обновить устаревший пример/формат.

Подготовка одной строкой подходит для finish/Trainer, но не отменяет PREP-02:
до поединка должен быть отдельный optional вызов проверки конкретного блока,
не проверка всей склеенной карточки. Отсутствующий помощник нельзя скрыть этим решением.
Для REPLAY-02 одна строка без подписей/границ не позволяет надёжно восстановить
отдельные редактируемые поля; Frontend/Backend должны согласовать сохранение разделителей
или возврат к редактированию всего текста, либо явно изменить требование UI.

### Замечания о прежнем контракте: что исправлено, а что только спроектировано

| Замечание | Сейчас |
| --- | --- |
| Универсальный CaseConfig привязан к KPI/неделям/зарплате | Убрано только в draft v2; runtime v1 не переделан |
| Потеря фонового HR/других участников | Participants предусмотрены draft; Backend/AI v1 пока две роли строками |
| Смешение public/private, интересов, BATNA и позиции | RoleBrief/Interest/Strategy разведены в draft; нужны авторские данные и реализация |
| Короткое/полное описание, категория, время отсутствуют в AI | Не обязаны быть в AI; Backend уже имеет поля, но mapping текстов/единицы/лимит требует соглашения |
| Сложность не влияет на AI | Метаданные есть Backend; бизнес-правила поведенческого влияния не заданы — нельзя выдумать их |
| PreparationCard урезана | Решение команды — одна строка в v2; runtime v1 и FE ещё не адаптированы |
| Судейство пересказывает диалог/ссылается на методички | Формат/фильтры в AI v1 изменены, экспертная и сквозная приёмка остаются |
| Оппонент выходит из роли под давлением / уступает без основания | В AI v1 есть проверки и исправления; обходной Audio-путь их не использует |
| Все FR можно считать закрытыми после схемы | Нет: schema — только дизайн; дополнительные пробелы перечислены отдельно |

Основные реальные блокеры стыковки: Frontend POST chat не передаёт обязательный
Backend `case_uuid` (такой payload не проходит DTO), Audio обходит AI, Frontend
finish — demo, у Backend нет turn/finish адаптера и хранения per-session preparation.
Доказательства клиентских вызовов — в приложении Frontend/Audio.

## 3. Что изменилось с прошлого Backend-аудита

Dev обновился с `79dc4bf…` до `412fb983…`: добавлены Aerich, начальная миграция,
команды и запуск `aerich upgrade` перед процессом. Поэтому «миграций нет» теперь
устарело. Не проверено применение этой initial-миграции к существующей серверной БД:
наличие файла не доказывает безопасный upgrade без backup/baseline.
[Docker startup](https://github.com/xyz-nebula/backend/blob/412fb983ae3e2b365ceaceab13876b3699f6e50e/Dockerfile#L24).

DTO и переговорный путь не изменились: браузер всё ещё может передать `is_ai`,
sequence вычисляется last+1, нет AI-клиента/канонического snapshot/finish.
[DTO](https://github.com/xyz-nebula/backend/blob/412fb983ae3e2b365ceaceab13876b3699f6e50e/app/api/v1/routers/models.py#L139),
[insert](https://github.com/xyz-nebula/backend/blob/412fb983ae3e2b365ceaceab13876b3699f6e50e/app/database/actions/message.py#L9).
Предыдущие 67 тестов относятся к прежнему срезу; в этом исследовании новый Backend
не запускался. Не переносим старую цифру на новый код без проверки.

## 4. Реальные поля текущего Backend (не проект v2)

Все поля ответа обязательны в DTO, если явно не указано иное. Ссылки — models.py
и chat routes из раздела 1. Внешний префикс из конфигурации reverse proxy не угадывается.

### Browser/Admin → Backend: авторизация

| Операция | Поля и типы | Содержание |
| --- | --- | --- |
| register | email:string(email), first_name:string(1…64), last_name:string(1…64), password:string(8…128) | Пользовательские данные; password не передавать AI/Audio |
| login | email, password обязательны; totp_token:string из 6 цифр, optional/null | Пользовательский доступ |
| activate | code:UUID | Код активации |
| refresh/logout | refresh_token:string | Только Backend auth |
| register response | user_id:UUID, status:pending_activation по умолчанию | Не session_id переговоров |
| tokens response | access_token:string, refresh_token:string | Не наш сервисный токен |
| TOTP enroll response | secret:string, otpauth_url:string | Не раскрывать в логах/AI |
| TOTP confirm | totp_token:string(6 цифр) | Подтверждение |
| TOTP disable | password:string(8…128) | Отключение |
| admin bootstrap | code:string | Защищённая операция, не переговорное поле |

### Admin → Backend: создание/изменение кейса

Create требует все поля следующей таблицы. Edit принимает optional/null для name,
description, time_limit, preparations, system_prompt, goal, synopsis, first_role,
second_role; **category/difficulty редактированием текущий DTO не принимает**.

| Поле | Тип/ограничение | Что хранится сейчас / неоднозначность |
| --- | --- | --- |
| name | string 1…100 | Название, не стабильный ID |
| description | string ≥1 | Описание; соответствие short/full надо утвердить |
| category | string 1…100 | Тип ситуации |
| difficulty | easy/moderate/hard/insane | Метаданные, не настроенная уступчивость AI |
| time_limit | int >0 | Лимит; единицу в контракте уточнить, ограничение ≤300 добавить |
| preparations | string | **Поле кейса**, не собственная подготовка отдельного пользователя |
| system_prompt | string ≥1 | Админский текст; недостаточен вместо машинной конфигурации; не выдаётся в CaseResponse |
| goal | string ≥1 | Авторская цель; не подменяет личную цель пользователя автоматически |
| synopsis | string ≥1 | Ещё один текст; нужен явный mapping описаний |
| first_role | string ≥1 | Имя/описание первой роли, не stable role_id |
| second_role | string ≥1 | Имя/описание второй роли, не список разрешённых пар |

Backend → Browser `CaseResponse`: все эти поля кроме system_prompt, плюс
`uuid:UUID`, `created_at:datetime`; difficulty в ответе string.
Backend → Admin `AdminCaseResponse`: тот же ответ **с** system_prompt.
Если preparations содержит закрытую подготовку оппонента, текущая публичная выдача
этого поля опасна. Содержание БД не проверялось; это условный риск, не утверждение утечки.

### Frontend/Audio → Backend: существующие чаты

| Направление / операция | Точный DTO | Содержание |
| --- | --- | --- |
| → POST /v1/chats/ | name:string(1…100), case_uuid:UUID — оба обязательны | Создать чат по реальному UUID кейса |
| → PUT /v1/chats/active | uuid:UUID | Активировать свой чат |
| → POST /v1/chats/{chat_uuid}/message/ | text:string≥1; is_ai:boolean default false | Сейчас generic CRUD; для управляемого поединка клиент не должен задавать is_ai |
| ← ChatResponse | uuid:UUID,name:string,status:victory/defeat/ongoing,created_at:datetime | Не исход соглашения и не статус асинхронной команды |
| ← ChatListItem[] | uuid:UUID,name:string | Список чатов |
| ← ChatWithCaseResponse | ChatResponse + case:CaseResponse | Активный чат с кейсом |
| ← ChatWithMessagesResponse | предыдущий + messages:MessageResponse[] | История |
| ← MessageResponse | uuid:UUID,sequence:int,is_ai:boolean,text:string,created_at:datetime | Нет turn_id/status/ролевой привязки/времени от начала раунда |

В текущем Backend **нет** отдельного DTO сохранения пользовательского preparation,
выбора role pair, старта таймера, управляемого turn, finish или полного AI result.
Точные реальные payload клиентов и их несовпадения см. приложение Frontend/Audio.

## 5. Что кто должен передавать после согласования

**Следующие поля — предложение, не существующий Browser API.** Команды должны
утвердить имена/маршруты и дополнить draft; неизвестные поля запрещены текущими AI
схемами. Не копировать новые поля в v1 или в текущий draft без его обновления.

### Полный кейс: Admin → Backend → публичный Frontend

| Предлагаемое поле | Тип | Владелец/видимость/значение |
| --- | --- | --- |
| id | string | Backend UUID кейса; mapping из нынешнего uuid |
| config_version | string | Backend неизменяемая версия содержимого |
| title | string | Автор/админ; нынешний name |
| short_description | string | Автор; только карточка каталога |
| full_description | string | Автор; полный разрешённый общий сюжет, не private role notes |
| category | string | Автор/админ; публично |
| difficulty | enum текущего Backend | Метаданные, отдельные поведенческие параметры не выдумывать |
| duration_seconds | int 1…300 | Автор/Backend; max 5 минут по FR-TIME01 |
| participants | Participant[] | Все участники с id/name/public_context/public_interests |
| allowed_role_pairs | {player_role_id:string,opponent_role_id:string}[] | Только авторски допустимые разные роли, не случайный выбор двух участников |
| role_configs | RoleConfig[] | Закрытое серверное хранение вводных/интересов/BATNA/стратегии каждой доступной AI-роли |
| possible_outcomes | Авторская конфигурация, формат ещё не утверждён | Возможные исходы/последствия, не заполненный результат пользователя |

RoleConfig предлагается хранить как role_id, private_context, interests,
batna, opponent_strategy плюс утверждённые параметры роли. Нужна отдельная схема
канонического кейса Backend: AI CaseConfig — лишь проекция выбранной пары.
Frontend получает только публичную часть и свои доступные вводные после выбора.
Нынешние description/synopsis/preparations/system_prompt нельзя механически и
без автора раскидать между этими полями.

### Сессия / подготовка / команда: Frontend → Backend

| Операция | Предлагаемые поля | Что означает / где хранится |
| --- | --- | --- |
| Создать прохождение | case_id:string,player_role_id:string,opponent_role_id:string,client_request_id:string | Backend проверяет допустимую пару, закрепляет версии; не стартует таймер раньше кнопки |
| Сохранить подготовку | session_id:string,preparation:string|null | Один текст ответов пользователя; принадлежность/роль берутся из сессии |
| Начать раунд | session_id:string,client_request_id:string | Backend фиксирует started_at/deadline_at; первый ход всё равно пользовательский |
| Текстовый ход | session_id:string,client_request_id:string,text:string≥1 | Backend создаёт turn_id, очередь; браузер не присылает snapshot/is_ai |
| Finish | session_id:string,client_request_id:string | Закрыть приём ходов, отменить звук/запись по согласованному порядку, вызвать AI finish |
| Replay | source_session_id:string,client_request_id:string | Новый session_id; та же версия и ролевые условия; изменённая подготовка допустима |

Строка preparation склеивается Frontend с подписями, например:
`Цель: ...; Желаемая позиция: ...; Красная черта: ...; BATNA: ...; Вопросы: ...`.
Один текст в поле БД **не** означает одну неразмеченную фразу: переносы/разделители
допустимы. Backend сохраняет исходный текст и возвращает его владельцу. Не путать
с Case.preparations; не отправлять оппоненту/судьям, только Trainer в finish.

### Backend → Frontend: жизненный цикл и команды

| Предлагаемое поле | Тип | Значение |
| --- | --- | --- |
| session_id | string | ID конкретной попытки, не ID кейса |
| case_id,case_config_version | string | Закреплённые вводные |
| contract_version | string | v1/v2; без смены в середине попытки |
| player_role_id,opponent_role_id | string | Согласованная пара |
| preparation | string|null | Свой сохранённый текст |
| round_status | open/finishing/finished | Жизненный цикл; до старта нужно отдельно согласовать ready-состояние |
| started_at,deadline_at,finished_at | ISO8601 UTC string|null | Backend timestamps; UI вычисляет оставшееся время, не задаёт deadline |
| command_id | string | Устойчивая операция, одинаковая при повторной доставке |
| command_status | queued/running/completed/failed/unknown | Не AI status и не outcome |
| result | публичный TurnResult/FinishResponse или null | Не raw snapshot/закрытая стратегия |
| error | публичный code/message или null | Техническая ошибка; без provider payload/секретов |

Frontend предлагает свои названия DTO? Это допустимо, но mapping должен быть явным.
Утверждённого Browser JSON Schema пока нет. Дедупликация client_request_id scoped
к пользователю/сессии/операции; иной payload с тем же ID — конфликт. Один изменяющий
вызов на сессию; ambiguous timeout не повод повторить модель вслепую.

### Audio ↔ Backend: требуемый новый путь

| Направление | Предлагаемые поля | Содержание |
| --- | --- | --- |
| Audio → Backend, финальный STT | session_id:string,utterance_id:string,text:string,started_at/ended_at:UTC timestamps | Одна завершённая реплика, не VAD partial; авторизация пользователя отдельно |
| Backend → Audio, TTS | session_id,turn_id,opponent_text,playback_id | Только checked accepted/blocked; технический model_error не озвучивать как персонажа |
| Backend/Frontend → Audio, stop | session_id,playback_id,reason:deadline/user_finish | Немедленная остановка речи; финальный порядок ещё надо реализовать |
| Audio → Backend, playback event | session_id,playback_id,status:started/completed/cancelled/failed,time | Согласование запрета overlap и timer cutoff |

Это требования к новому адаптеру, не текущий Audio WebSocket протокол.
До согласования события/поля не считаются поддержанными. Сервисный AI токен и
закрытый CaseConfig Audio не нужны. Проверка пользовательского доступа не заменяется
наличием одного session_id.

### Backend ↔ AI: существующее и проектное

| Операция | Уже реализованный v1 | Предлагаемый v2 |
| --- | --- | --- |
| turn request | case:CaseConfig,snapshot:SessionSnapshot,turn_id:string,user_text:string | Та же внешняя форма, универсальные вложенные объекты и версии |
| turn response | session_id,turn_id,status,opponent_text,snapshot,error_code | Та же форма; snapshot хранится только Backend |
| finish request | case,snapshot,preparation:PreparationCard|null optional | preparation:string|null optional; **v1 это не принимает** |
| finish response | session_id,outcome,judge_verdicts[],trainer_feedback | Та же верхняя форма, универсальные terms и текстовое сопоставление |
| auth | Authorization: Bearer service token | Backend-only; не пользовательский JWT |

Все вложенные поля **текущего проекта v2** перечислены в приложении ниже без
пропусков. Поля для закрытия FR-пробелов не добавлены туда автоматически: это
отдельные решения/доработки следующего раздела.

### Вложенные модели реально работающего AI v1

Источник — contracts.py/OpenAPI из раздела 1. Значения по умолчанию здесь действуют
только в v1, не в строгом проекте v2. Избегать преобразования свободного текста
в эти объекты с придумыванием отсутствующих полей.

| Объект | Поля / обязательность | Содержание |
| --- | --- | --- |
| CaseConfig | id,title,shared_context,player_role,opponent_role,player_private_context,opponent_private_context:string обязательны | Кейс и две роли без role IDs/версии; контексты не пользовательская подготовка |
| CaseConfig optional | agreement_rules:AgreementRules default; opponent_private_phrases:string[] default []; opponent_strategy:OpponentStrategy|null default null | Дополнительные ограничения первого кейса |
| AgreementRules | min_control_weeks:int≥0 default1; max_control_weeks:int≥0 default4; min_kpi_percent:int≥0 default100; max_kpi_percent:int≥0 default130; require_automatic_raise:boolean defaulttrue | Специализированные границы |
| DealTerms | control_weeks:int≥0,kpi_percent:int≥0,automatic_raise:boolean,employee_commitments:string[] min1,director_commitments:string[] min1 — всё обязательно | Условия первого кейса; не цена/поставка универсального кейса |
| ConcessionRequirement | id,description:string≥1; direct_commitment_markers:string[] min1 обязательны; evidence_groups:string[][] default[] | Основание уступки |
| OpponentPositionStep | id:string≥1,kind:declared/intermediate/target/red_line,terms:DealTerms обязательны; requires:ConcessionRequirement[] default[] | Одна ступень |
| OpponentStrategy | steps:OpponentPositionStep[] min3 обязательно | Лестница с проверками уникальности/порядка и невозрастания недель/KPI |
| OpponentPositionProgress | current_step_id:string≥1 обязательно; satisfied_requirement_ids:string[] default[]; last_transition:AppliedPositionTransition|null defaultnull; restored_from_agreement:true|null defaultnull | Закрытая история уступок; флаг восстановления v1 |
| AppliedPositionTransition | from_step_id,to_step_id,evidence_turn_id,evidence_quote:string≥1; requirement_ids:string[] min1 — обязательно | Подтверждённый переход |
| SessionState | turn_count:int≥0 обязательно; stage:negotiating/agreed/partial_agreement/deferred defaultnegotiating; agreement:DealTerms|null,decision:PartialDecision/DeferredDecision|null,opponent_progress:OpponentPositionProgress|null defaultnull | Состояние, не таймер |
| PartialDecision | kind:partial_agreement,commitments:string[] min1,open_points:string[] min1 — обязательно | Частичная сделка без явного commitment role_id |
| DeferredDecision | kind:deferred,reason:string≥1,next_step:string≥1 — обязательно | Отложенное решение |
| TranscriptEntry | turn_id:string,speaker:player/opponent,status:accepted/blocked/safe_reaction,text:string обязательны; blocked_reason:GuardReason|null defaultnull | Времени/role_id в записи нет |
| SessionSnapshot | session_id:string,state:SessionState,transcript:TranscriptEntry[] — обязательно | Без schema_version/case version/закреплённых role IDs |
| PreparationCard | situation_analysis,strategic_goal,negotiation_goal:string≥1|null defaultnull; planned_questions,possible_solutions,arguments:string[] default[] | Все необязательны; **не одна строка** |
| OutcomeResult | kind:agreement/partial_agreement/deferred/no_agreement,summary:string обязательны; agreement:DealTerms|null,next_step/reason:string|null defaultnull; commitments/open_points:string[] default[] | Исход отдельно от skill assessment |
| JudgeVerdict | college:hiring/negotiation/ownership,choice:player/opponent,decisive_criterion:string enum15,evidence_turn_id/evidence_quote/observation/effect/comparison:string — обязательно | Один объяснённый выбор, цитата и эпизод |
| JudgeSlot | college,status:ready/failed обязательно; verdict:JudgeVerdict|null,error_code:JudgeError|null defaultnull | Готовность каждого судьи |
| CoachingPoint | evidence_turn_id,evidence_quote,action,situation_change,consequence:string — обязательно | Наблюдаемый эпизод пользователя |
| PreparationComparisonItem | preparation_kind:situation_analysis/strategic_goal/negotiation_goal/planned_question/possible_solution/argument,preparation_text:string,status:followed/adapted/not_observed,observation:string обязательны; evidence_turn_id/evidence_quote:string|null defaultnull | В отличие от draft имеется структурный kind; null evidence сериализация может пропускать |
| PreparationDuelComparison | summary:string,items:PreparationComparisonItem[] min1 — обязательно | Сравнение заполненных элементов |
| TrainerFeedback | summary:string,next_try:string[] min1 обязательно; strengths/mistakes:CoachingPoint[] default[]; plan_vs_reality:PreparationDuelComparison|null defaultnull | Хотя бы один наблюдаемый эпизод; null plan может отсутствовать в JSON |
| TrainerSlot | status:ready/failed обязательно; feedback:TrainerFeedback|null,error_code:TrainerError|null defaultnull | Разбор отдельного вызова |

TurnResponse в v1 требует session_id,turn_id,status,opponent_text,snapshot;
error_code optional/null. FinishRequest requires case/snapshot, optional PreparationCard.
FinishResponse requires session_id,outcome,judge_verdicts,trainer_feedback.
Коды/критерии и точные minLength/семантические проверки доступны в OpenAPI/исходнике;
это межсервисные DTO, внутренние model context/proposal не нужно отправлять Backend.

GuardReason: prompt_override/private_data_request/hidden_position_request/
physical_harm_threat. ModelErrorCode: invalid_opponent_output/opponent_unavailable/
guard_unavailable/invalid_guard_output/guard_uncertain/validator_unavailable/
invalid_validator_output/validator_uncertain/opponent_role_break/
opponent_premature_ending/opponent_unearned_concession.
JudgeError: judge_unavailable/invalid_judge_output/judge_retrieval_unavailable/
invalid_judge_retrieval. TrainerError: trainer_unavailable/invalid_trainer_output.
Ready требует payload без error; failed требует error без payload. Не превращать
failed в положительный вердикт или score по умолчанию.

## 6. Что нужно добавить, прежде чем объявлять контракт полным

1. **Проверка блока подготовки:** отдельная optional операция с session_id,
   section_id, block_text, revision_id; ответ — сильные/слабые стороны, вопросы,
   направления улучшения. Проверка не заполняет карточку за игрока и не обязательна
   для старта. Названия/маршрут/объекты ещё согласовать; ни в1, ни draft этого нет.
2. **Время транскрипта:** серверные timestamp и elapsed_ms для каждой реплики,
   stable message_id и role_id либо однозначный mapping speaker→session role.
   При цитировании нужны turn_id **и** speaker/message_id: в паре две реплики
   с одним turn_id. В draft сейчас нет времени и evidence speaker, надо дополнить.
3. **Outcome:** отдельные данные о взаимных уступках, цене результата и вероятных
   последствиях, включая последствия невыполнения только если обсуждались.
   Предложить evidence-grounded concessions/cost/consequences; формат пока не
   утверждён. Не додумывать правовые санкции/будущее. Личная цель — отдельный анализ
   Trainer, исход сделки сам по себе не означает её достижение.
4. **Универсальные границы:** определить как проверять произвольное предложение
   по каждому параметру (допустимые ranges/choices/пакеты/зависимости). Сам список
   declared/target/red_line не гарантирует универсальную математическую проверку
   многомерной красной черты. Не согласовывать draft как уже универсальный решатель.
5. **Роль/кейс:** каноническая Backend-схема разрешённых пар, версии, private
   permissions, возможные последствия, настройки Admin и отображение своего role brief.
6. **Таймер/голос/replay:** ready→open→finishing→finished, отмена воспроизведения и
   принятие последней реплики, стабильный replay, показ прошлой подготовки. Адреса
   тестовых сервисов, версии и ответственности подтвердить командами.

Ничего из этого не требует передавать категории/короткие описания AI на каждый ход.
Напротив, UI-метаданные остаются Backend; важные вводные/время/evidence/границы
должны быть отражены там, где реально используются.

## 7. Порядок работы

Передать команде этот аудит и [handoff](contract-v2-handoff.md), получить ответы по
пробелам, затем дополнить схему и зафиксировать согласованную версию. После этого
AI реализует свой v2; команды отдельно адаптируют свои репозитории. Сквозная проверка
двух кейсов/обеих ролей, текста/голоса/таймера/replay/частичных ошибок — до rollout.

Этот документ основан на research по исходникам. Репозитории команд не изменены,
серверы не проверялись и не перенастраивались. Нет нового обещания деплоя или
заявления о полной функциональной приёмке.

## Приложение A. Полный словарь полей текущего draft AI v2

Источник: [case-contract-v2.schema.json](../api/drafts/case-contract-v2.schema.json).
Это точный перечень **предлагаемых** полей на дату аудита, не реализованный OpenAPI.
Требуемые дополнения из раздела 6 сюда ещё не включены. Все объекты запрещают
неизвестные поля. «Обязательно / null допустим» не равно отсутствующему полю.
Backend сохраняет case/snapshot/результат; AI постоянное хранилище не ведёт.

### Outcome

Направление: AI → Backend → публичный Frontend, кроме закрытых данных.

| Поле | Тип | Обязательность | Содержание |
| --- | --- | --- | --- |
| `kind` | agreement / partial_agreement / deferred / no_agreement | Обязательно | Фактический исход, не качество игры |
| `summary` | string (непустая) | Обязательно | Краткое описание исхода |
| `agreement` | DealTerms / null | Обязательно | Полные согласованные условия либо null |
| `commitments` | Commitment[] | Обязательно | Принятые обязательства сторон |
| `open_points` | string (непустая)[] | Обязательно | Открытые вопросы |
| `next_step` | string (непустая) / null | Обязательно | Зафиксированный следующий шаг либо null |
| `reason` | string (непустая) / null | Обязательно | Причина отложения/исхода либо null |

### JudgeVerdict

Направление: AI → Backend → публичный Frontend, кроме закрытых данных.

| Поле | Тип | Обязательность | Содержание |
| --- | --- | --- | --- |
| `college` | hiring / negotiation / ownership | Обязательно | Судейская коллегия |
| `choice` | player / opponent | Обязательно | Кого выбрал судья |
| `decisive_criterion` | Надёжность / Отношение к людям / Управленческая твёрдость / Забота о команде / Долгосрочные последствия управления / Движение к цели / Управление другой стороной / Работа с картиной мира / Управление ролями / Сохранение отношений / Качество решений / Компетентность / Ответственность / Управление рисками / Последствия для ресурсов | Обязательно | Один критерий своей коллегии |
| `evidence_turn_id` | string (непустая) | Обязательно | ID хода с доказательством |
| `evidence_quote` | string (непустая) | Обязательно | Дословный непрерывный фрагмент реплики |
| `observation` | string (непустая) | Обязательно | Наблюдаемое действие |
| `effect` | string (непустая) | Обязательно | Что изменилось в разговоре |
| `comparison` | string (непустая) | Обязательно | Чем отличалась другая сторона |

### JudgeSlot

Направление: AI → Backend → публичный Frontend, кроме закрытых данных.

| Поле | Тип | Обязательность | Содержание |
| --- | --- | --- | --- |
| `college` | hiring / negotiation / ownership | Обязательно | Коллегия этого слота |
| `status` | ready / failed | Обязательно | Готов результат или произошла ошибка |
| `verdict` | JudgeVerdict / null | Обязательно | Вердикт только при ready |
| `error_code` | judge_unavailable / invalid_judge_output / judge_retrieval_unavailable / invalid_judge_retrieval / null | Обязательно | Код ошибки только при failed |

### CoachingPoint

Направление: AI → Backend → публичный Frontend, кроме закрытых данных.

| Поле | Тип | Обязательность | Содержание |
| --- | --- | --- | --- |
| `evidence_turn_id` | string (непустая) | Обязательно | ID пользовательского хода |
| `evidence_quote` | string (непустая) | Обязательно | Дословная цитата пользователя |
| `action` | string (непустая) | Обязательно | Что сделал пользователь |
| `situation_change` | string (непустая) | Обязательно | Как изменил ситуацию |
| `consequence` | string (непустая) | Обязательно | Последствие действия |

### PreparationComparisonItem

Направление: AI → Backend → публичный Frontend, кроме закрытых данных.

| Поле | Тип | Обязательность | Содержание |
| --- | --- | --- | --- |
| `preparation_text` | string (непустая) | Обязательно | Точный непрерывный фрагмент исходной строки подготовки |
| `status` | followed / adapted / not_observed | Обязательно | Следовал плану / адаптировал / не наблюдалось |
| `evidence_turn_id` | string (непустая) / null | Обязательно | ID принятого пользовательского хода; null для not_observed |
| `evidence_quote` | string (непустая) / null | Обязательно | Цитата этого хода; null для not_observed |
| `observation` | string (непустая) | Обязательно | Обоснованное сопоставление намерения и поведения |

### PreparationComparison

Направление: AI → Backend → публичный Frontend, кроме закрытых данных.

| Поле | Тип | Обязательность | Содержание |
| --- | --- | --- | --- |
| `summary` | string (непустая) | Обязательно | Итог сравнения плана с диалогом |
| `items` | PreparationComparisonItem[] (min 1) | Обязательно | Сопоставления явно записанных намерений |

### TrainerFeedback

Направление: AI → Backend → публичный Frontend, кроме закрытых данных.

| Поле | Тип | Обязательность | Содержание |
| --- | --- | --- | --- |
| `summary` | string (непустая) | Обязательно | Общий разбор пользователя |
| `strengths` | CoachingPoint[] | Обязательно | Подтверждённые сильные эпизоды |
| `mistakes` | CoachingPoint[] | Обязательно | Подтверждённые ошибки |
| `next_try` | string (непустая)[] (min 1) | Обязательно | Конкретные действия для следующей попытки |
| `plan_vs_reality` | PreparationComparison / null | Обязательно | Сопоставление с подготовкой; null без подготовки |

### TrainerSlot

Направление: AI → Backend → публичный Frontend, кроме закрытых данных.

| Поле | Тип | Обязательность | Содержание |
| --- | --- | --- | --- |
| `status` | ready / failed | Обязательно | Готовность отдельного Trainer |
| `feedback` | TrainerFeedback / null | Обязательно | Разбор только при ready |
| `error_code` | trainer_unavailable / invalid_trainer_output / null | Обязательно | Ошибка только при failed |

### FinishResponse

Направление: AI → Backend → публичный Frontend, кроме закрытых данных.

| Поле | Тип | Обязательность | Содержание |
| --- | --- | --- | --- |
| `session_id` | string (непустая) | Обязательно | Сессия запроса |
| `outcome` | Outcome | Обязательно | Фактический исход |
| `judge_verdicts` | JudgeSlot[] (min 3) (max 3) | Обязательно | Ровно три независимых слота |
| `trainer_feedback` | TrainerSlot | Обязательно | Отдельный слот Trainer |

### Interest

Направление: Backend → AI (вложенные авторские данные при необходимости).

| Поле | Тип | Обязательность | Содержание |
| --- | --- | --- | --- |
| `text` | string (непустая) | Обязательно | Содержимое интереса роли |
| `visibility` | public / private | Обязательно | Разрешено публиковать либо private |

### Participant

Направление: Backend → AI (вложенные авторские данные при необходимости).

| Поле | Тип | Обязательность | Содержание |
| --- | --- | --- | --- |
| `id` | string (непустая) | Обязательно | Стабильный ID участника |
| `name` | string (непустая) | Обязательно | Имя/название роли |
| `public_context` | string | Обязательно | Разрешённые общие сведения |
| `public_interests` | string (непустая)[] | Обязательно | Только публичные интересы |

### RoleBrief

Направление: Backend → AI (вложенные авторские данные при необходимости).

| Поле | Тип | Обязательность | Содержание |
| --- | --- | --- | --- |
| `role_id` | string (непустая) | Обязательно | ID из participants |
| `private_context` | string | Обязательно | Закрытые вводные выбранной роли |
| `interests` | Interest[] | Обязательно | Авторские интересы с признаками видимости |
| `batna` | string (непустая) / null | Обязательно | Авторская альтернатива роли либо null |

### Negotiable

Направление: Backend → AI (вложенные авторские данные при необходимости).

| Поле | Тип | Обязательность | Содержание |
| --- | --- | --- | --- |
| `id` | string (непустая) | Обязательно | ID предмета торга |
| `label` | string (непустая) | Обязательно | Человекочитаемое название |
| `value_type` | number / text / boolean / choice / date | Обязательно | Тип значения |
| `unit` | string (непустая) / null | Обязательно | Единица измерения либо null |
| `choices` | string (непустая)[] | Обязательно | Разрешённые значения choice; иначе [] |

### TermValue

Направление: Backend → AI (вложенные авторские данные при необходимости).

| Поле | Тип | Обязательность | Содержание |
| --- | --- | --- | --- |
| `term_id` | string (непустая) | Обязательно | Ссылка на Negotiable.id |
| `value` | number / string / boolean | Обязательно | Значение соответствующего типа |

### Commitment

Направление: Backend → AI (вложенные авторские данные при необходимости).

| Поле | Тип | Обязательность | Содержание |
| --- | --- | --- | --- |
| `role_id` | string (непустая) | Обязательно | Одна из двух активных ролей |
| `text` | string (непустая) | Обязательно | Конкретное обязательство этой стороны |

### DealTerms

Направление: Backend → AI (вложенные авторские данные при необходимости).

| Поле | Тип | Обязательность | Содержание |
| --- | --- | --- | --- |
| `values` | TermValue[] | Обязательно | Типизированные условия сделки |
| `commitments` | Commitment[] | Обязательно | Обязательства сторон |

### ConcessionRequirement

Направление: Backend → AI (вложенные авторские данные при необходимости).

| Поле | Тип | Обязательность | Содержание |
| --- | --- | --- | --- |
| `id` | string (непустая) | Обязательно | Уникальный ID основания уступки |
| `description` | string (непустая) | Обязательно | Авторское условие перехода |
| `direct_commitment_markers` | string (непустая)[] (min 1) | Обязательно | Маркеры прямого обязательства |
| `evidence_groups` | string (непустая)[] (min 1)[] | Обязательно | Группы дополнительных маркеров проверки; не NLP-гарантия |

### PositionStep

Направление: Backend → AI (вложенные авторские данные при необходимости).

| Поле | Тип | Обязательность | Содержание |
| --- | --- | --- | --- |
| `id` | string (непустая) | Обязательно | Уникальный ID ступени |
| `kind` | declared / intermediate / target / red_line | Обязательно | Место в лестнице |
| `terms` | DealTerms | Обязательно | Полный пакет условий |
| `requires` | ConcessionRequirement[] | Обязательно | Основания перехода; declared — [] |

### OpponentStrategy

Направление: Backend → AI (вложенные авторские данные при необходимости).

| Поле | Тип | Обязательность | Содержание |
| --- | --- | --- | --- |
| `steps` | PositionStep[] (min 3) | Обязательно | Авторская лестница уступок в порядке движения |

### CaseConfig

Направление: Backend → AI (вложенные авторские данные при необходимости).

| Поле | Тип | Обязательность | Содержание |
| --- | --- | --- | --- |
| `id` | string (непустая) | Обязательно | Backend ID кейса |
| `config_version` | string (непустая) | Обязательно | Закреплённая версия вводных |
| `title` | string (непустая) | Обязательно | Название |
| `shared_context` | string (непустая) | Обязательно | Вся значимая фабула, доступная обеим выбранным ролям |
| `participants` | Participant[] (min 2) | Обязательно | Публичные сведения всех участников |
| `player` | RoleBrief | Обязательно | Вводные пользовательской роли; не передавать оппоненту |
| `opponent` | RoleBrief | Обязательно | Вводные AI-роли; не передавать браузеру |
| `negotiables` | Negotiable[] | Обязательно | Каталог параметров сделки |
| `opponent_strategy` | OpponentStrategy / null | Обязательно | Закрытая авторская стратегия выбранной AI-роли |
| `opponent_private_phrases` | string (непустая)[] | Обязательно | Известные закрытые фразы для дополнительной проверки утечек |

### PartialDecision

Направление: Backend ↔ AI внутри snapshot.

| Поле | Тип | Обязательность | Содержание |
| --- | --- | --- | --- |
| `kind` | "partial_agreement" | Обязательно | partial_agreement |
| `commitments` | Commitment[] (min 1) | Обязательно | Частично согласованные обязательства |
| `open_points` | string (непустая)[] (min 1) | Обязательно | Оставшиеся вопросы |

### DeferredDecision

Направление: Backend ↔ AI внутри snapshot.

| Поле | Тип | Обязательность | Содержание |
| --- | --- | --- | --- |
| `kind` | "deferred" | Обязательно | deferred |
| `reason` | string (непустая) | Обязательно | Причина отложения |
| `next_step` | string (непустая) | Обязательно | Согласованный следующий шаг |

### AppliedTransition

Направление: Backend ↔ AI внутри snapshot.

| Поле | Тип | Обязательность | Содержание |
| --- | --- | --- | --- |
| `from_step_id` | string (непустая) | Обязательно | Исходная ступень |
| `to_step_id` | string (непустая) | Обязательно | Подтверждённая новая ступень |
| `requirement_ids` | string (непустая)[] (min 1) | Обязательно | Проверенные основания уступки |
| `evidence_turn_id` | string (непустая) | Обязательно | ID хода-основания |
| `evidence_quote` | string (непустая) | Обязательно | Полный текущий пользовательский текст-основание |

### Progress

Направление: Backend ↔ AI внутри snapshot.

| Поле | Тип | Обязательность | Содержание |
| --- | --- | --- | --- |
| `current_step_id` | string (непустая) | Обязательно | Текущая ступень оппонента |
| `satisfied_requirement_ids` | string (непустая)[] | Обязательно | Подтверждённые основания |
| `last_transition` | AppliedTransition / null | Обязательно | Последний подтверждённый переход либо null |

### SessionState

Направление: Backend ↔ AI внутри snapshot.

| Поле | Тип | Обязательность | Содержание |
| --- | --- | --- | --- |
| `turn_count` | integer ≥0 | Обязательно | Количество сохранённых управляемых ходов |
| `stage` | negotiating / agreed / partial_agreement / deferred | Обязательно | Состояние переговорного решения, не закрытия раунда |
| `agreement` | DealTerms / null | Обязательно | Договорённость при agreed; иначе null |
| `decision` | PartialDecision / DeferredDecision / null | Обязательно | Частичное/отложенное решение; иначе null |
| `opponent_progress` | Progress / null | Обязательно | Закрытое состояние уступок; не выдавать браузеру/судьям/Trainer |

### TranscriptEntry

Направление: Backend ↔ AI внутри snapshot.

| Поле | Тип | Обязательность | Содержание |
| --- | --- | --- | --- |
| `turn_id` | string (непустая) | Обязательно | Backend ID управляемого хода |
| `speaker` | player / opponent | Обязательно | Сторона выбранной пары |
| `status` | accepted / blocked / safe_reaction | Обязательно | Принятая реплика / блокировка / безопасная реакция |
| `text` | string (непустая) | Обязательно | Текст записи |
| `blocked_reason` | prompt_override / private_data_request / hidden_position_request / physical_harm_threat / null | Обязательно | Основание блокировки либо null |

### SessionSnapshot

Направление: Backend ↔ AI внутри snapshot.

| Поле | Тип | Обязательность | Содержание |
| --- | --- | --- | --- |
| `schema_version` | "2.0" | Обязательно | Версия схемы снимка |
| `session_id` | string (непустая) | Обязательно | ID попытки |
| `case_id` | string (непустая) | Обязательно | ID закреплённого кейса |
| `case_config_version` | string (непустая) | Обязательно | Закреплённая версия содержимого |
| `player_role_id` | string (непустая) | Обязательно | Выбранная роль пользователя |
| `opponent_role_id` | string (непустая) | Обязательно | Выбранная AI-роль |
| `state` | SessionState | Обязательно | Каноническое состояние |
| `transcript` | TranscriptEntry[] | Обязательно | Проверенная история |

### TurnRequest

Направление: Backend → AI (вложенные авторские данные при необходимости).

| Поле | Тип | Обязательность | Содержание |
| --- | --- | --- | --- |
| `case` | CaseConfig | Обязательно | Разрешённая AI-проекция кейса |
| `snapshot` | SessionSnapshot | Обязательно | Последний канонический снимок Backend |
| `turn_id` | string (непустая) | Обязательно | Новый стабильный ID команды хода |
| `user_text` | string (непустая) | Обязательно | Текущая реплика пользователя |

### FinishRequest

Направление: Backend → AI (вложенные авторские данные при необходимости).

| Поле | Тип | Обязательность | Содержание |
| --- | --- | --- | --- |
| `case` | CaseConfig | Обязательно | Та же закреплённая проекция |
| `snapshot` | SessionSnapshot | Обязательно | Последний сохранённый снимок |
| `preparation` | string (непустая) / null | Необязательно | Одна исходная строка подготовки; только Trainer; optional/null |

### TurnResponse

Направление: AI → Backend → публичный Frontend, кроме закрытых данных.

| Поле | Тип | Обязательность | Содержание |
| --- | --- | --- | --- |
| `session_id` | string (непустая) | Обязательно | ID сессии запроса |
| `turn_id` | string (непустая) | Обязательно | ID хода запроса |
| `status` | accepted / blocked / model_error | Обязательно | accepted/blocked/model_error |
| `opponent_text` | string (непустая) | Обязательно | Проверенная реплика либо технический безопасный ответ |
| `snapshot` | SessionSnapshot | Обязательно | Новый снимок accepted/blocked; прежний при model_error |
| `error_code` | string (непустая) / null | Обязательно | Код технической причины либо null |

Всего: 30 объектов, 128 именованных полей. Семантические
ограничения (связь IDs, роли, тип value, точность evidence, ready/failed) проверяются
не только JSON Schema; их реализация и тесты ещё необходимы.
