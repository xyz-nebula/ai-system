# Текущие контракты Frontend, Admin Frontend и Audio Engine

Проверка исходников 2026-09-26. Это **описание текущего кода**, а не подтверждение развёртывания или сквозной работоспособности. Чужие исходники не изменялись, секреты не читались. Новая схема AI v2 в соседних документах — проект, а не реализованная интеграция.

## Зафиксированные версии

| Репозиторий | Основная проверенная ветка / commit | Default / commit |
|---|---|---|
| audio-engine (private) | dev / `c4d3907f64676613e0374daf96c1e500073824e5` | main / `ddfb6f093bf03aa7e88715dc8507e084079412f9` |
| front-end (private) | dev / `a62387b18d67038314fea05e2a6484b8e66caae9` | master / `220c1432b1c695a45247cd376454038fb98f1e0a` |
| admin-frontend (private) | dev / `9095bcd7f990ba4ae08b18f289af8fe9a246e3f5` | main / `1c04b0266e58afb5d64942b944706c18787e18c3` |

Доступные remote branches перечислены через Git: Audio — main, dev, calude/rewrite, feature/system_prompt; Admin — main, dev, case; FE — master, dev, new-design, connect-chat, connect-chat-broken, fix-repo, new-hero-design, feat-login, fix/proxy. Основной анализ — dev/default; для Audio feature/system_prompt и FE new-design отдельно проверены изменения интеграционных файлов. Не утверждается полноценный аудит каждой строки всех исторических feature-веток. Private permalinks ниже доступны только участникам организации.

## Ключевой вывод

Сквозная связка с AI-system ещё не реализована. Audio общается **напрямую с LocalAI Realtime**, а не с контролируемым AI-opponent; Frontend даже в real-клиенте возвращает демонстрационный результат при finish. Поэтому готовность схемы v2 не означает, что функциональные требования уже выполнены всем продуктом.

## Frontend → Backend: реально отправляемые запросы

Все запросы real negotiation-клиента используют Bearer access token, JSON, base URL по умолчанию `/api`, timeout 20 000 ms. Все перечисленные DTO-поля обязательные, если явно не указано иначе.

| Операция | Маршрут | Тело / ответ | Смысл и ограничение |
|---|---|---|---|
| Создание | POST /v1/chats/ | `{name:string}`; ответ ChatResponse | Отправляется caseName либо caseId как **имя**. case_id, роль, mode, preparation и clientCommandId не передаются |
| Активировать | PUT /v1/chats/active | `{uuid:string}` | UUID чата |
| Получить | GET /v1/chats/{sessionId} | ChatWithMessages | История |
| Список | GET /v1/chats/ | `[{uuid:string,name:string}]` | Затем отдельно загружается каждый чат |
| Текстовый ход | Нет реализованного запроса | featureUnavailable | Не работает в real adapter |
| Audio ticket | Нет реализованного запроса | featureUnavailable | TS-интерфейс не равен наличию endpoint |
| Завершение / итог | Нет реализованного запроса | Локальный demoResult | Не вызывает Backend finish, судей или Trainer |

Источники: [real adapter, строки 145–198](https://github.com/xyz-nebula/front-end/blob/a62387b18d67038314fea05e2a6484b8e66caae9/src/services/real/backendNegotiationClient.ts#L145-L198), [список, 201–228](https://github.com/xyz-nebula/front-end/blob/a62387b18d67038314fea05e2a6484b8e66caae9/src/services/real/backendNegotiationClient.ts#L201-L228), [timeout и transport](https://github.com/xyz-nebula/front-end/blob/a62387b18d67038314fea05e2a6484b8e66caae9/src/services/real/backendNegotiationClient.ts#L31-L34).

### Backend → Frontend DTO

| Объект | Поля | Хранение / преобразование |
|---|---|---|
| ChatResponse | uuid:string(UUID), name:string, status:`victory\|defeat\|ongoing`, created_at:string(date) | ongoing → active, прочее → finished |
| MessageResponse | uuid:string(UUID), sequence:number(positive integer), is_ai:boolean, text:string(nonempty), created_at:string(date) | is_ai → speaker ai/user; UUID → id; created_at → createdAt |
| ChatWithMessages | Все ChatResponse + messages:MessageResponse[] | Dedup по UUID, сортировка sequence |
| Ошибка ожидаемая клиентом | code:string, message:string, field?:string | Нужна синхронизация с фактическим error envelope Backend |

[DTO и runtime parsing](https://github.com/xyz-nebula/front-end/blob/a62387b18d67038314fea05e2a6484b8e66caae9/src/services/real/targetContract.ts#L5-L18), [валидация](https://github.com/xyz-nebula/front-end/blob/a62387b18d67038314fea05e2a6484b8e66caae9/src/services/real/targetContract.ts#L92-L134). Сейчас adapter назначает `caseId=chat.name`, а mode всегда voice: [mapping](https://github.com/xyz-nebula/front-end/blob/a62387b18d67038314fea05e2a6484b8e66caae9/src/services/real/backendNegotiationClient.ts#L36-L62). Имя кейса не заменяет стабильный case UUID.

### Внутренние TS-типы, НЕ готовый сетевой контракт

`createSession`: caseId:string, caseName?:string, mode:text|voice, clientCommandId:string.
`sendTextTurn`: sessionId:string, text:string, clientTurnId:string.
`finishSession`: sessionId:string, clientCommandId:string.
`AudioTicket`: ticket:string, expiresAt:string, protocol:audio-engine.v1.

`NegotiationResult`: sessionId:string, outcome:victory|defeat, score:number, summary:string, strengths:string[], improvements:string[], recommendations:string[].
`NegotiationResultState`: processing; ready+result; failed+message.
Это не моделирует четыре договорных исхода, три независимых судейских слота и Trainer slot. Real-клиент выдаёт фиксированные victory и score=74, с текстом «демонстрационный разбор». Нельзя показывать их как реальный результат переговоров.

Источники: [NegotiationClient](https://github.com/xyz-nebula/front-end/blob/a62387b18d67038314fea05e2a6484b8e66caae9/src/services/contracts/negotiationClient.ts#L10-L35), [тип результата](https://github.com/xyz-nebula/front-end/blob/a62387b18d67038314fea05e2a6484b8e66caae9/src/types/negotiation.ts#L25-L62).

Каталог Home/Arena берётся из `@/mocks/cases`, а не из Backend catalog: [Home](https://github.com/xyz-nebula/front-end/blob/a62387b18d67038314fea05e2a6484b8e66caae9/src/pages/HomePage.tsx#L12). В проверенной dev-поверхности нет сохранения подготовки пользователя одной строкой. В new-design подготовка также статическая: [mock data](https://github.com/xyz-nebula/front-end/blob/870787e718e917a2fd9abb9360956e5d9479d2b8/src/mocks/duelPreparation.ts#L1), [компонент прямо помечает подготовку demo](https://github.com/xyz-nebula/front-end/blob/870787e718e917a2fd9abb9360956e5d9479d2b8/src/components/arena/DuelPreparation.tsx#L27).

## Frontend ↔ Audio: реализованный WebSocket

FE открывает same-origin path по умолчанию `/audio/v1/audio-stream?token=<access-token>`; Audio route — `/v1/audio-stream`. Reverse proxy должен убрать prefix /audio. FE не передаёт session_id/chat_uuid, Audio сам получает active chat из Backend. Не включать token query в access logs. [FE URL](https://github.com/xyz-nebula/front-end/blob/a62387b18d67038314fea05e2a6484b8e66caae9/src/services/real/audioEngineClient.ts#L59-L70), [default path](https://github.com/xyz-nebula/front-end/blob/a62387b18d67038314fea05e2a6484b8e66caae9/src/services/config.ts#L47-L55), [Audio lookup](https://github.com/xyz-nebula/audio-engine/blob/c4d3907f64676613e0374daf96c1e500073824e5/app/api/routers/audio_stream.py#L21-L36).

| Направление | JSON поля | Обязательность / смысл |
|---|---|---|
| FE → Audio | type:audio, audio:string | Оба обязательны, base64 audio |
| FE → Audio | type:control, action:pause|resume|stop|close | Оба обязательны |
| Audio → FE | type:transcript, role:user|assistant, text:string | type имеет default transcript; role/text обязательны; нет utterance_id, turn_id, message_id, final flag |
| Audio → FE | type:audio_frame, sequence:int, timestamp:int, format:object, payload:string | type default audio_frame; прочие обязательны; timestamp epoch ms, payload base64 |
| format | codec:string, sample_rate:int, channels:int, bit_depth:int | Все обязательны; фактические константы pcm_s16le/24000/1/16 |
| Audio → FE | type:error или auth_error, code:string, message:string | type default, code/message обязательны |

[Модели Audio](https://github.com/xyz-nebula/audio-engine/blob/c4d3907f64676613e0374daf96c1e500073824e5/app/api/routers/models.py#L8-L54), [константы](https://github.com/xyz-nebula/audio-engine/blob/c4d3907f64676613e0374daf96c1e500073824e5/app/constants.py#L1-L9).

Audio принимает optional query `protocol`; единственное допустимое заданное значение audio-engine.v1, отсутствие разрешено. Frontend текущий URL этот query не добавляет. `pause/resume` парсятся, но сервер не меняет состояние: просто continue; stop/close заканчивают bridge. Это не подтверждение полноценной паузы обработки на сервере. [control handling](https://github.com/xyz-nebula/audio-engine/blob/c4d3907f64676613e0374daf96c1e500073824e5/app/services/audio_bridge_service.py#L138-L145).

На new-design wire type остаётся transcript, но frontend преобразует его в transcript_delta и применяет append-delta. Audio отправляет **completed** transcripts. Без согласованной семантики снапшота/дельты UI может неправильно склеивать реплики. [new-design parsing](https://github.com/xyz-nebula/front-end/blob/870787e718e917a2fd9abb9360956e5d9479d2b8/src/services/real/targetContract.ts#L141-L153), [Audio completed events](https://github.com/xyz-nebula/audio-engine/blob/c4d3907f64676613e0374daf96c1e500073824e5/app/services/audio_bridge_service.py#L153-L163).

## Audio → Backend / LocalAI: обход AI-контура

| Операция | Контракт |
|---|---|
| GET /v1/chats/active | Bearer пользовательского token. Response обязательные uuid:UUID,name:str,status:victory|defeat|ongoing,created_at:datetime; неизвестные поля игнорируются |
| POST /v1/chats/{chat_uuid}/message/ | Bearer того же token, body text:string,is_ai:boolean. Ответ лишь проверяется на успешный HTTP |
| LocalAI Realtime session | model из settings; output_modalities:[audio], audio.input.turn_detection.type:server_vad |
| Realtime → browser/backend | user completed transcription сохраняется is_ai=false; assistant completed transcription is_ai=true; аудио delta сразу отправляется браузеру |

[Backend calls](https://github.com/xyz-nebula/audio-engine/blob/c4d3907f64676613e0374daf96c1e500073824e5/app/services/chat_service.py#L18-L49), [session setup](https://github.com/xyz-nebula/audio-engine/blob/c4d3907f64676613e0374daf96c1e500073824e5/app/services/audio_bridge_service.py#L95-L105), [forward/persist](https://github.com/xyz-nebula/audio-engine/blob/c4d3907f64676613e0374daf96c1e500073824e5/app/services/audio_bridge_service.py#L153-L163).

Здесь нет AI-system turn/finish, case projection, snapshot, guards, контролируемых уступок, судей, Trainer, подтверждения сохранения с message UUID или idempotent utterance identity. Аудио может прозвучать **до** любого контроля AI-system, потому что это другая модельная цепочка.

В feature/system_prompt `c58b01cd5536f5a9096367570fc26b9e5efc920e` добавлено обязательное `ChatResponse.case`; обязательные поля nested CaseResponse: uuid:UUID,created_at:datetime,name:str,description:str,category:str,difficulty:str,time_limit:int,preparations:str,system_prompt:str. `case.system_prompt` передаётся как realtime instructions. Это всё ещё bypass, не AI-system integration. Кроме того, такой response требует сверки с реальным Backend contract, нельзя автоматически считать его существующим. [feature models](https://github.com/xyz-nebula/audio-engine/blob/c58b01cd5536f5a9096367570fc26b9e5efc920e/app/api/routers/models.py#L74-L95), [instructions](https://github.com/xyz-nebula/audio-engine/blob/c58b01cd5536f5a9096367570fc26b9e5efc920e/app/services/audio_bridge_service.py#L95-L105).
Default main отличается от dev старым singular `/v1/chat` вместо plural `/v1/chats`: развёртывание main вместо dev важно для совместимости.

## Admin Frontend ↔ Backend

Все create-поля ниже обязательные в TypeScript DTO; серверные ограничения проверяются отдельно Backend. Строки — содержимое авторского кейса, **не подготовка конкретного пользователя**.

| Поле create | Тип | Что хранится / что ещё нужно согласовать |
|---|---|---|
| name | string | Название |
| description | string | Описание; граница short/full не определена DTO |
| category | string | Категория |
| difficulty | easy|moderate|hard|insane | Уровень; AI behavior не вычисляется здесь |
| time_limit | number | В UI подпись s, min 1: секунды |
| preparations | string | Авторская подготовка кейса; нельзя смешивать с session preparation |
| system_prompt | string | Приватная AI-инструкция, admin-only |
| goal | string | Цель; единая строка не задаёт по-role private/public модель |
| synopsis | string | Фабула/вводные; публичность не определена DTO |
| first_role, second_role | string | Названия ролей, не стабильные role_id |

Response: все поля create, но difficulty:string, плюс uuid:string и created_at:string. PATCH допускает optional nullable name,description,time_limit,preparations,system_prompt,goal,synopsis,first_role,second_role; **category и difficulty в edit DTO отсутствуют**.

Маршруты: GET/POST /v1/cases/; PATCH /v1/cases/{caseUuid}. Auth: POST /v1/auth/login {email,password,totp_token?}; response {access_token,refresh_token}; refresh/logout {refresh_token}; setAdmin POST /v1/admin/ {code}. [DTO и запросы](https://github.com/xyz-nebula/admin-frontend/blob/9095bcd7f990ba4ae08b18f289af8fe9a246e3f5/src/api.ts#L148-L225), [login](https://github.com/xyz-nebula/admin-frontend/blob/9095bcd7f990ba4ae08b18f289af8fe9a246e3f5/src/api.ts#L82-L113), [time UI](https://github.com/xyz-nebula/admin-frontend/blob/9095bcd7f990ba4ae08b18f289af8fe9a246e3f5/src/pages/CasesPage.tsx#L218-L220).

Admin main ещё не содержит case CRUD этой версии: наличие в dev не доказывает наличие в опубликованном сайте.

## Минимальные обязательные доработки интеграции

### Дополнительные функциональные требования: время, повтор и транскрипт

В dev таймер ArenaHeader — **elapsed** от startedAt, обновляется раз в секунду; это не deadline/countdown и не автоматическое завершение по time_limit. [Код таймера](https://github.com/xyz-nebula/front-end/blob/a62387b18d67038314fea05e2a6484b8e66caae9/src/components/arena/ArenaHeader.tsx#L8-L28). Поэтому выполнение FR-TIME01..03 только этим компонентом не подтверждается.

Ручной finish вызывает audio.stop перед finishSession; audio.stop освобождает capture/playback. Это полезная реализованная часть остановки, но отсутствуют серверный expiry event, звуковой end signal и подтверждённое ожидание последней финальной STT перед finish. [Порядок](https://github.com/xyz-nebula/front-end/blob/a62387b18d67038314fea05e2a6484b8e66caae9/src/pages/ArenaPage.tsx#L73-L80), [очистка](https://github.com/xyz-nebula/front-end/blob/a62387b18d67038314fea05e2a6484b8e66caae9/src/features/arena/useArenaAudio.ts#L357-L380).

Повтор на ResultPage сохраняет caseId/mode/clientCommandId, но не case_config_version/selected_role_id/hidden configuration. Real adapter игнорирует command ID и передаёт лишь name. Следовательно FR-REPLAY о том же скрытом кейсе не обеспечено. [Repeat](https://github.com/xyz-nebula/front-end/blob/a62387b18d67038314fea05e2a6484b8e66caae9/src/pages/ResultPage.tsx#L64-L82).

MessageResponse.created_at — время сохранения записи; Audio timestamp — время аудиофрейма. Ни один не является согласованным start/end временем реплики относительно начала поединка. В wire TranscriptMessage нет timestamps вообще; FR-TRANS01/04 требует отдельной интеграционной договорённости. Источники — таблицы DTO и [TranscriptMessage](https://github.com/xyz-nebula/audio-engine/blob/c4d3907f64676613e0374daf96c1e500073824e5/app/api/routers/models.py#L51-L54).

Audio JWT проверяет signature/expiration через jwt.decode и обязательные sub/exp/iat моделью. Ownership текущего чата затем проверяется обращением в Backend с тем же token. Это не новый service token AI-system и не доказательство совпадения конфигурации реально развёрнутых сервисов. [Auth](https://github.com/xyz-nebula/audio-engine/blob/c4d3907f64676613e0374daf96c1e500073824e5/app/services/auth_service.py#L19-L40).

Прочитаны исходники mock-oriented Audio tests (не запускались): happy-path/auth/active-chat lookup и bridge persistence/stop. Они подтверждают тестируемую текущую цепочку, но не содержат проверки AI-system turn/finish. [Route tests](https://github.com/xyz-nebula/audio-engine/blob/c4d3907f64676613e0374daf96c1e500073824e5/tests/api/test_audio_stream_flow.py#L82-L133), [bridge tests](https://github.com/xyz-nebula/audio-engine/blob/c4d3907f64676613e0374daf96c1e500073824e5/tests/services/test_audio_bridge_service.py#L90-L202). FR-PREP02..04 (AI-проверка подготовки до дуэли) не реализуется показом static preparation; отдельного запроса проверки подготовки в перечисленных клиентах нет.

1. Backend/Frontend: стабильно case_id + version + selected role_id; не name-as-id. Реальный public catalog, role-specific вводные, серверный deadline.
2. Frontend/Backend: session preparation одной строкой с заголовками, отдельная от author `Case.preparations`; сохранение привязано к сессии/игровой роли, до finish. Точное имя нового поля — в согласуемой матрице, текущего endpoint нет.
3. Audio/Backend: финальный STT → тот же дедуплицируемый Backend turn command; session_id, utterance_id/client_request_id обязательны в новой цепочке. Не сохранять произвольного assistant как подтверждённый AI-system ход.
4. Backend/AI: AI-system единственный владелец opponent generation/guards/strategy; Backend атомарно сохраняет checked response+snapshot. Audio озвучивает только выданный checked text.
5. Frontend/Backend: реальный finish/getResult; договорный outcome отдельно от голосов 3 коллегий и Trainer; ready/failed слоты отображаются независимо, не fixed victory74.
6. Admin/Backend/AI: версия canonical case и приватные данные ролей/участников/универсальные условия торга. Не передавать public `system_prompt` браузеру и не считать произвольную строку готовым validated strategy.
7. Зафиксировать deployment branches, proxy route, JWT verification policy и async/dedupe envelope, затем проверить e2e на двух разных кейсах. Эта проверка исходников не заменяет live e2e.

Ни одно из этих предложений не объявляет уже существующий endpoint или выполненную доработку чужого репозитория.
