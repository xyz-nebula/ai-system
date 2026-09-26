# Итоговая спецификация интеграции: Arena 2.0.0-rc.1

**Контракт одобрен командами по сообщению пользователя.** Дата: 2026-09-26.
Начата реализация моделей и детерминированных проверок в `arena_ai.v2.contracts`.
HTTP v2 и полный модельный контур **ещё не реализованы и не развёрнуты**;
работающий [OpenAPI v1](../openapi.json) не изменён. Этот документ заменяет прежний
неполный [draft](../drafts/case-contract-v2-proposal.md) как цель новой разработки.

Текущий срез кода — строгие модели AI-кейса/снимка, TurnRequest/FinishRequest,
детерминированные проверки и отдельные контексты Guard/Opponent/Judge/Trainer,
а не готовые v2 endpoints или подключённый модельный контур.
В `arena_ai.v2.turn.QwenTurnPipeline` реализован кандидат negotiating-хода:
Guard → Opponent → Validator, пара сообщений и revision+1 только после проверки,
неизменный snapshot при model_error. Candidate opponent time равен времени user
до перезаписи Backend при commit. Новая полная сделка фиксируется через отдельный
Agreement Validator: подтверждение текущей пары, доказательства каждого обязательства
и всех required_commitment_ids, проверенные по роли/сообщению/цитате/времени.
Agreement не закрывает round; сохранённая сделка не меняется на следующем ходе.
Частичное решение и перенос фиксируются отдельным Decision Validator: текущая пара
подтверждает одно и то же решение, каждое частичное обязательство имеет grounded
доказательство своей роли. Нерешённые вопросы, причина и следующий шаг должны
соответствовать обсуждению, а не быть выдуманными моделью. Обязательные правила
полной сделки не навязываются частичному решению. Partial/deferred не закрывают
round и не стирают уже согласованные обязательства. Без нового claim решение
сохраняется. Снятие/переформулирование прежних обязательств пока не поддерживается:
сохранение проверяется по точной паре role_id/text, не по сходству формулировок.
Числовые условия требуют полного проверяемого предложения terms даже при partial;
оно не означает взаимного принятия всего пакета. Этот срез не является полной реализацией
`/v2/turn` и не включён в HTTP runtime. Claim/assessment — внутренние DTO модели,
публичный контракт 2.0.0-rc.1 не расширяется.
При проверяемой уступке после accepted истории игрока Offer Validator дополнительно
вызывает узкую Novelty-проверку: только требования текущего перехода, текущая
реплика и принятая история игрока, без скрытых вводных/подготовки/цены предложения.
Свежий message_id не доказывает новую ценность. Accept со ссылкой на старый
эквивалент противоречив; каждая историческая Evidence проверяется по источнику,
роли, статусу, времени и цитате. Reject/uncertain/error не продвигают снимок.
При отсутствии перехода или accepted истории дополнительный вызов не нужен.
В `arena_ai.v2.offers` добавлена read-only проверка полного предложения и соседней
уступки по входному результату Validator: literal текущая Evidence, новое прямое
обязательство, окна/границы и сохранение сделки. Она не фиксирует agreement,
не изменяет snapshot. В `arena_ai.v2.validator` реализован HTTP-адаптер Qwen:
изолированный контекст, строгий JSON, проверка каждого accept через этот gate,
ошибка без публикации предложения при сбое модели. Адаптер проверен через HTTP
MockTransport и отдельными вызовами живой модели; ещё не включён в runtime.
Эти тесты не доказывают реальное распознавание отрицаний/блефа моделью.
Инструкция запуска и границы [живых проверок текущего среза](live-validation.md).
Numeric DTO используют int/Decimal. `model_validate_json(raw_body)` сохраняет
исходные decimal-значения, `model_dump_json()` выводит их числовыми JSON-токенами.
Для v2 wire нельзя использовать предварительный `json.loads` с float,
`model_dump(mode="json")` (стандартное Decimal-as-string поведение Pydantic)
или автоматическое преобразование Decimal в float через JSONResponse/encoder.
Будущий HTTP/модельный адаптер должен использовать точные методы выше;
кодек не восстанавливает точность, уже потерянную на стороне отправителя.

Нельзя объявлять результат этого документа «100% работающим продуктом»:
спецификация, согласование, реализация, сквозная приёмка и деплой — разные этапы.
После подтверждения teams ACK идентификатор rc.1 замораживается; несовместимая
правка получает новый идентификатор. Ни один потребитель не угадывает mapping полей.

## 1. Что передать команде

- Этот файл: ответственность, семантика, ошибки, порядок работы и приёмка.
- [Все DTO: JSON Schema 2020-12](contract.schema.json). Выбирать именованный `$defs`,
  корень является реестром типов, а не схемой произвольного запроса.
- [Backend REST](backend.openapi.json), [AI REST](ai.openapi.json),
  [Audio internal REST](audio.openapi.json): OpenAPI 3.1 **проектных** маршрутов.
- [Полный словарь полей](fields.md), [учебные fixtures](examples/),
  [проверка схем/маршрутов/примеров](check_contract.py).
- [Обоснование и текущие расхождения реализаций](../../integration/project-requirements-and-fields-audit.md).

В реальном релизе каждой команды OpenAPI экспортируется из приложения и проверяется
на соответствие этим схемам/маршрутам. Эти JSON-файлы не являются таким экспортом.

Локальная проверка артефактов (не обращается к серверу или модели):

```bash
uv run --no-project --with jsonschema --with openapi-spec-validator \
  python docs/api/v2/check_contract.py
```

Fixtures вымышленные, tickets — невалидные placeholders. Их нельзя использовать
как авторские production-настройки или действительные учётные данные.

## 2. Ответственность

| Владелец | Хранит / делает | Не делает |
| --- | --- | --- |
| Backend | Версии кейса, допустимые пары, пользовательские сессии и подготовку, канонический snapshot, очередь/дедупликацию, таймер, результаты, доступ | Не генерирует оппонента напрямую через LocalAI и не превращает голоса в исход |
| Frontend | Реальный каталог, выбор пары, необязательную карточку, текст/голос, countdown, реальные результаты и replay | Не отправляет is_ai/raw snapshot, не хранит сервисные токены и не показывает demo как итог |
| Admin + автор кейса | Утверждённые фабулу/роли/публичность/позиции/границы/исходы; UI настройки и сохранение новой версии | Не публикует system_prompt/закрытые интересы игрокам и не придумывает значения из примеров |
| AI | Проверку блока подготовки; Guard, оппонента, Validator и условия уступок; исход, 3 судейских вызова, отдельный Trainer | Не хранит сессии, не проверяет пользовательский JWT и не владеет таймером |
| Audio | VAD, STT, идентификаторы высказываний, TTS проверенного текста и остановку воспроизведения | Не вызывает свободного разговорного оппонента, не создаёт подтверждённые assistant-реплики сам |

```text
Подготовка: Frontend → Backend → AI preparation/review → Backend → Frontend
Текст:     Frontend → Backend command → AI turn → Backend commit → Frontend
Голос:     Frontend → Audio STT → Backend command → AI turn → Backend commit
           → Frontend (проверенный текст) + Audio TTS (тот же текст)
Итог:      Backend freeze → AI finish → Backend save → Frontend
Повтор:    Backend новый session_id, прежние case version и роли → подготовка
```

## 3. Формат и версии

В JSON строго snake_case. Неизвестные поля запрещены. ID — непустые непрозрачные
строки; Backend может использовать UUID как строку. Не путать case_id, session_id,
turn_id, message_id, command_id, client_request_id, utterance_id и playback_id.
Любая ссылка должна указывать на объект той же сессии/версии/пары.

`contract_version` / `schema_version` = `2.0.0-rc.1`.
`config_version` — независимая неизменяемая версия **содержимого кейса**.
Backend закрепляет обе при создании попытки, не меняет их посреди поединка.
revision снимка — счётчик изменений канонической истории/состояния; подготовка имеет
отдельный preparation_revision. Все UTC timestamps — ISO8601 с Z, elapsed_ms —
целые миллисекунды от started_at, не часы компьютера пользователя.

На всех REST v2 запросах кроме discovery `/v2/info` обязателен заголовок
`X-Arena-Contract-Version: 2.0.0-rc.1`. Несовпадение — 409 contract_version_mismatch.
В WS версия закреплена подписанным ticket и протоколом arena.audio.v2.

Required с nullable-типом: поле присутствует, значение null допустимо. Optional
только там, где это отмечено в схеме: например FinishRequest.preparation.
В списках неизвестное не заменять выдуманным элементом; нет подтверждённых
уступок/последствий — пустые массивы. Пробельная подготовка нормализуется в null.

## 4. Кейс, роль и приватность

### Admin → Backend: CanonicalCase

Хранит title, short_description, авторский full_description и полную **общую
разрешённую** фабулу shared_context,
category, difficulty, duration_seconds 1…300, всех participants, allowed_role_pairs,
role_configs и possible_outcomes. Publication_status: draft/published/archived.
Схема не является генератором авторских данных. В examples только вымышленные кейсы.

PublicCase — явная белая проекция: без role_configs, strategies и private facts.
Full_description сохраняет оригинальное полное описание для автора/админа, но
не выдаётся публично автоматически. Shared_context — полный общий текст для
игроков, не краткая карточка. Если вся фабула публична, автор задаёт одинаковые
full_description/shared_context; иначе разрешённые факты распределяет явно между
shared_context и private role brief. Так три текста не смешиваются и исходник не теряется.
Каждый Participant имеет стабильный id, name, public_context, public_interests.
Участников может быть больше двух; активный диалог всегда 1×1. RolePair задаёт
player_role_id и opponent_role_id — разные участники из разрешённой автором пары.
Backend отклоняет произвольную комбинацию участников, которой нет в allowed_role_pairs.

RoleAuthorConfig содержит role_id, brief, negotiables, opponent_strategy,
agreement_policy и private_phrases. Brief включает авторские интересы/вводные,
BATNA, цель/ЗП/ЖП/КЧ и role_preparation: это информация роли, **не** собственный
план пользователя. Неизвестные авторские текстовые позиции могут быть null;
для каждой роли, доступной в качестве AI-оппонента, машинная стратегия и её
условия обязательны. У фонового участника стратегия может быть null.

PossibleOutcome: авторская возможная развязка, описание и возможные последствия,
visibility и known_to_role_ids. Это не результат уже сыгранной попытки. Публичная
выдача включает только visibility=public; закрытые данные доступны только разрешённым
ролям. Backend сохраняет исходную версию целиком, не выводит закрытое поле публично
потому, что оно находилось в исходной методичке или старом preparations.

### Backend → AI: CaseConfig

Проекция выбранной пары: id/version/title/shared_context/participants,
player/opponent RoleBrief, negotiables, opponent_strategy, agreement_policy,
opponent_private_phrases и разрешённые для этой пары possible_outcomes.
Категория/short_description/difficulty/duration не нужны в prompt каждого хода.
Deadline передаётся в snapshot.round отдельно; метаданные difficulty не означают
неописанной «автоматической агрессивности» или случайно изменённых границ.

Мат, оскорбления, жёсткий торг и сценарное давление сами по себе не являются
prompt override. Оппонент держит роль, не отвечает встречными оскорблениями,
не переходит к общему нравоучению и не объявляет раунд оконченным. Попытки сменить
системные инструкции/раскрыть закрытые данные блокируются безопасной реакцией,
но не дают оппоненту самостоятельно закончить раунд до внешнего cutoff.

Внутри AI используются отдельные белые проекции:

| Получатель | Может видеть |
| --- | --- |
| Opponent | Общий контекст, публичные участники, свои private вводные/интересы/позиции/исходы, состояние и историю; не подготовку и не private player brief |
| Guard | Публичный контекст и текущую реплику |
| Validator | Данные, необходимые для контроля ответа/границ/утечек; не публикует их |
| Preparation helper | Общий контекст + собственный brief игрока + выбранный блок; без private opponent данных |
| Судьи | Общий контекст, названия выбранных ролей, публичное состояние/исход и транскрипт; без подготовки, private interests и progress |
| Trainer | Публичный контекст, исход и транскрипт + сохранённая пользовательская строка подготовки; без private opponent вводных/progress |

Frontend видит только PublicCase, собственный player_brief и публичные сообщения/
результаты. CaseConfig/snapshot не выдаются браузеру или Audio целиком. Exact phrase
фильтр — дополнительная мера, не достаточная защита от перефразированных утечек.

## 5. Универсальные условия и границы

Negotiable: id/label/value_type (number/text/boolean/choice/date)/unit/choices.
TermValue: term_id/value. DealTerms: values + commitments `{role_id,text}`.
Никаких обязательных KPI, недель, employee/director или salary полей.
Дата — YYYY-MM-DD; число конечно; boolean не number; choice только из choices.
Все значения авторских единиц фиксированы в версии, автоматическое преобразование
валют/дней/процентов моделью запрещено.

AgreementPolicy содержит реестр constraints, hard_constraint_ids,
commitment_rules и required_commitment_ids. Все ID уникальны; ссылки существуют.
Детерминированные ограничения этой версии:

| kind | Проверка |
| --- | --- |
| numeric_range | minimum ≤ value ≤ maximum; null означает отсутствие данной границы; хотя бы одна граница задана |
| date_range | Та же включительная проверка валидной даты YYYY-MM-DD |
| allowed_values | Точное типизированное равенство одному значению; false не равно 0 |
| linear | sum(coefficient × numeric term value) relation bound, relation le/ge/eq; коэффициенты и bound конечны |

Hard constraints применяются ко всем предложениям/полным сделкам. PositionStep
дополнительно содержит constraint_ids — допустимое окно предложений на этой ступени.
Все указанные условия соединяются AND. Окно может включать любую поддержанную
числовую/дата/choice/линейную комбинацию, не только точное exemplar terms ступени.
Eq для numeric/linear реализовать decimal-арифметикой по исходным JSON-десятичным
значениям, не float epsilon. Date-границы относятся только к date, linear — к number.
Allowed_values проверяется по объявленному типу. Коэффициенты нормализации единиц
задаёт автор; значения не интерпретируются как рубли/дни по имени поля.

Exemplar каждой ступени проходит её окно и hard constraints. Перед публикацией
конфигурации проверить типы, ссылки, границы, роли, уникальность и обязательства.
Окно каждой ступени должно явно покрывать все negotiables (включая компоненты
linear); материальные условия нельзя прятать только в расплывчатом тексте.
Неописанный предмет торга можно обсуждать, но нельзя молча добавить как новое
подтверждённое условие полной сделки. Значимые условия/санкции заранее моделирует автор.
Любой предложенный полный пакет в runtime проходит hard + текущее окно, даже если
авторское окно ошибочно выходит за hard границу. Не поддержанное этой DSL правило
не переводить молча в свободный prompt: публикация запрещена до явной новой версии
контракта. Свободный text-терм с жёсткой границей задаётся allowed_values; не объявлять
детерминированной границей расплывчатое «выгодно для бизнеса».

Стратегия: declared first → intermediate* → target → red_line last. Ровно по одному
declared/target/red_line, минимум 3 ступени. На declared requires=[], остальные
ступени требуют авторских ConcessionRequirement; переход только на следующую ступень.
Никакого универсального «меньше число = уступка»: направление задают окна автора.
Давление, повтор требования, гипотетическое обещание и цитирование чужих слов
не подтверждают уступку. Прямое новое обязательство пользователя должно иметь
Evidence из его текущей принятой реплики. Требования перехода сохраняются между ходами.

CommitmentRule задаёт id/role_id/description. Required_commitment_ids проверяются
по смыслу и доказательствам в диалоге Validator; маркеры сами по себе недостаточны
(отрицания/условность/чужая речь). Неопределённость = запрет подтверждать полную
сделку/переход, а не угадывание. Частичная сделка возможна без всех обязательных
условий, но не считается agreement. Эта проверка требует экспертных NLP-тестов.

## 6. Подготовка: одна строка и отдельная проверка блока

Frontend склеивает **все заполненные** ответы пользователя в одну строку preparation;
Backend хранит этот текст в сессии и передаёт только Trainer в finish. Не путать
с author role_preparation или прежним Case.preparations. Все элементы необязательны;
можно стартовать без подготовки/без её проверки. Чужая роль не может изменить этот текст.

Карточка UI поддерживает корневой конфликт, стратегическую цель, решения, 8 слоёв,
SWOT (4 части), цель на переговоры, ЗП/ЖП/КЧ/BATNA, сценарий (вопросы, темы, варианты,
аргументы, фиксация) и загрузку. Для склейки/восстановления фиксируем формат:

```text
[negotiation_goal]
Согласовать проверяемые условия.
[desired_position]
Две недели контроля.
[scenario]
Вопросы: как проверяем результат?
Фиксация: сроки и обязательства.
```

Заголовки — section_id из схемы, по одному на блок, отсутствующие блоки пропущены.
В содержимом Frontend экранирует обратную косую черту как двойную; строку, которая
начинается с `[`, как `\[`. При восстановлении сначала выделяет неэкранированные
заголовки, потом снимает экранирование. UTF-8 текст сохраняется без потерь;
порядок заголовков фиксирован порядком section_id в схеме. Внутри layers/SWOT/scenario
сохраняются человекочитаемые подписи всех заполненных подпунктов. Старый текст без
этого формата не парсить эвристически: показать редактируемым текстом как legacy plan.

SavePreparationRequest: preparation + preparation_revision (ожидаемая текущая
версия). Backend atomically compare-and-set, увеличивает revision на 1; stale — 409.
Тот же текст повторной доставки с уже обновлённым revision возвращается без нового
изменения; иной текст со старой версией отклоняется. Сохранение только пока round=ready.
При start текст фиксируется для этой попытки; изменение стратегии — через replay.

Review блока — optional POST Backend `/preparation/review`, затем AI
`/v2/preparation/review`. Пользователь выбирает section_id и block_text одной
логической части; revision_id позволяет отбросить устаревший ответ после редактирования.
AI получает только PreparationContext и этот блок, не всю подготовку. Ответ:
summary, strengths, weaknesses, questions, improvement_directions. Не подставляет
готовый полный ответ вместо пользователя. После ответа можно редактировать/проверять
снова. Review не перезаписывает сохранённый plan и не начинает таймер.
Start не ждёт review: queued проверки отменяются, уже выполняющаяся проверка не
получает права менять закреплённую подготовку или блокировать игровой жизненный цикл.

В finish preparation можно omit/null; пустой текст Backend нормализует в null.
Plan_vs_reality=null без плана. Каждый item цитирует непрерывный preparation_text
из **исходной** строки, не выдуманный JSON Pointer. Followed/adapted требуют Evidence
принятой пользовательской реплики; not_observed — evidence=null. Адаптация не равна
ошибке. Содержательная интерпретация блоков проверяется экспертно, не только substring.

## 7. Маршруты и авторизация

Полные пути и тела в трёх OpenAPI рядом. Base URL берётся из deployment manifest;
reverse proxy prefix (например /api) не является частью этих путей.

| Направление | Основные операции |
| --- | --- |
| Frontend → Backend | /v2/cases; /v2/sessions; session start/preparation/review/turn/finish/result/events/commands/replay/audio-ticket |
| Admin → Backend | /v2/admin/cases, полный create или новая версия через PUT; обязательная admin role |
| Backend → AI | /v2/info, /v2/preparation/review, /v2/turn, /v2/finish |
| Audio → Backend | /v2/internal/audio/utterances, /v2/internal/audio/playback-events |
| Backend → Audio | /v2/internal/playbacks, /v2/internal/playbacks/stop |
| Frontend ↔ Audio | WebSocket /v2/audio-stream; внешний proxy может добавлять /audio |

Пользовательские Backend routes: Bearer access JWT + проверка owner сессии.
Admin: тот же JWT + admin. Auth v1 login/refresh/logout не переименовывается.
Backend → AI: отдельный AI service bearer. Audio ↔ Backend: отдельные bearer tokens
для конкретного направления/назначения; они не дают Audio читать private CaseConfig.
Не переиспользовать пользовательский token как сервисный и не публиковать их в UI.
AI/RAG/internal Audio routes не выставлять в публичный интернет. Межсервисные вызовы
идут в доверенной приватной сети/VPN; внешние пользовательские соединения — через
TLS с валидным сертификатом. В production не отключать проверку TLS. Тексты сообщений
в UI рендерить как текст, не как непроверенный HTML; token и полные private payload
не писать в access/application logs.

Audio ticket выдаёт Backend владельцу открытой voice-сессии: signed short-lived
token (sub, session_id, contract_version, aud=arena-audio, exp, connect_by, jti,
scopes=stt/tts). JWT exp не позже deadline; connect_by не позже now+60 секунд.
Ticket.expires_at = connect_by — срок установления соединения; существующий stream всё равно
ограничен серверным deadline и событием окончания. WS принимает ticket query;
query нужно исключить из access logs. Audio проверяет подпись/audience/срок и
передаёт ticket вместе с final utterance Backend, который повторно проверяет owner/
сессию/назначение. Сервисный bearer одного Audio недостаточен для подмены пользователя.
Audio проверяет connect_by только при WS handshake и атомарно потребляет jti.
Backend для STT проверяет JWT exp/назначение/owner/актуальный jti, не истёкший
handshake connect_by: иначе 5-минутный stream сломался бы после первой минуты.
В одной сессии активен один voice stream; новый ticket инвалидирует предыдущий jti,
старый stream останавливается. Отзыв сессии останавливает stream.

Публичные ошибки: ServiceError `{code,message,retryable}`; без provider payload,
stacktrace, секретов или закрытых вводных. Основные HTTP:
401 missing/invalid auth; 403 owner/admin/scope denied; 404 объект не найден;
409 stale revision / закрытый раунд / конфликт request ID / недопустимая операция;
422 форма/ссылки/типы/границы конфигурации; 429 очередь заполнена;
503 недоступность инфраструктуры. AI обработанный model_error/failed slot может
возвращаться в HTTP 200: читать поле status, не только HTTP.

## 8. Команды, снимок и транскрипт

Create session закрепляет config/version/roles, round=ready, empty transcript,
state.turn_count=0, state.stage=negotiating, nullable decisions/progress=null.
Возвращается SessionView (PublicCase + собственный brief), не raw snapshot.
Start с client_request_id фиксирует started_at и deadline_at=started_at+duration.
Повтор start возвращает прежний срок, не перезапускает таймер.

Turn/finish/review принимаются Backend асинхронно: HTTP 202 CommandEnvelope.
Frontend получает состояние через GET command и SSE events (Last-Event-ID),
а при пропуске событий перечитывает SessionView. Состояния команды:
queued/running/completed/failed/unknown; result только при completed, error только
при failed/unknown. Тип result соответствует operation. Техническая ошибка AI-хода
может быть completed + PublicTurnResult.model_error: transport завершён, игра не продвинулась.

Client_request_id scoped к owner+session+operation (для create — owner+operation).
Backend резервирует устойчивую запись до внешнего вызова; одинаковый payload
возвращает ту же операцию, другой payload с тем же ID — 409. Turn_id/два message_id
назначает Backend, а не браузер/Audio. Очередь и сериализация межпроцессные; один
активный изменяющий модельный вызов на сессию. Не держать DB-транзакцию всё время модели.
Текстовый `/turn` разрешён для mode=text; internal final utterance — для mode=voice.
Неподходящий источник — 409 input_mode_mismatch. В voice следующий input запрещён
во время waiting/playing; режим не меняется внутри попытки. Replay сохраняет mode.

TurnRequest содержит прежний snapshot, user_text, turn_id, оба будущих message_id,
user_created_at/user_elapsed_ms. AI candidate snapshot добавляет пару player/opponent,
увеличивает turn_count и revision на 1 при accepted/blocked. Model_error возвращает
тот же snapshot. Старые сообщения/IDs/state не меняются незаметно. AI не дедуплицирует.

Backend commit делает CAS revision и проверяет, что round всё ещё open и текущее
время меньше deadline. AI timestamp последней opponent записи — кандидат;
Backend устанавливает created_at/elapsed_ms по времени фактического commit до
публикации ответа. Прежние времена/цитаты неизменны. Text/Evidence финального
снимка должны ссылаться на уже committed сообщения, не на кандидата/diagnostic.

При timeout после отправки AI command=unknown: не запускать тот же или новый turn
вслепую. Worker lease/generation fencing не позволяет запоздалому ответу изменить
уже закрытую сессию. Worker сохраняет найденный результат той же операции либо
оператор завершает неопределённость без принятия неподтверждённого AI ответа.
При deadline freeze всё равно немедленный: analysis не ждёт бесконечно unknown turn.
Unknown finish допускает явный повтор **только анализа того же frozen snapshot** с
audit attempt ID оператором; исходные успешные слоты не подменяются автоматически.

TranscriptEntry: message_id, turn_id, speaker, status, text, created_at, elapsed_ms,
blocked_reason. Speaker отображается через закреплённые role IDs. Evidence:
message_id+turn_id+speaker+elapsed_ms+quote — точная непрерывная цитата сообщения.
Судьи/Trainer не используют blocked/interrupted/technical input как успешный
переговорный эпизод. Перевод elapsed_ms в mm:ss выполняет UI.

## 9. Таймер и голос: определённое поведение при границе

Backend — источник deadline; Frontend корректирует countdown по server_time,
Audio также получает deadline. Round: ready → open → finishing → finished.
Finishing означает закрытый приём ходов и обработку итоговой аналитики, не продолжение
разговора. После таймера или кнопки прекращение диалога происходит **немедленно**,
даже если LLM finish выполняется ещё долго.

На cutoff Backend атомарно фиксирует finished_at/end_reason, запрещает commit новых
ответов, отменяет queued/running turn и посылает round_ended. Frontend немедленно
останавливает захват/воспроизведение и проигрывает короткий локальный сигнал окончания;
Audio прекращает приём/генерацию/TTS и не отправляет поздние фреймы. Cancellation
после deadline — управление инфраструктурой, а не отказ персонажа продолжать раунд.

Последний ход: final text должен поступить в Backend до cutoff. Приём после cutoff
не становится новым игровым ходом. Незавершённая STT/реплика сохраняется отдельно
как interrupted diagnostic; недоставленный ответ модели не попадает в договорённость.
Если turn был принят до cutoff, но ответ не committed, Backend может сохранить
последний пользовательский текст в snapshot как одиночный interrupted tail:
revision+1, turn_count/state/progress не меняются. Этот tail не используется как
Evidence успешного переговорного эпизода. Полный текст попытки остаётся доступен UI.
Это явная семантика пограничного случая, не обещание ждать STT после остановки раунда.

Accepted opponent text показывается в чате целиком при commit **до** запуска TTS;
поэтому он уже доступен пользователю до cutoff. Audio status отдельно показывает
cancelled при обрыве речи, не переписывает текстовую договорённость. Результат анализирует
проверенную **текстовую** историю; аудиообрыв не означает, что весь текст был услышан.
UI не выдаёт отменённую озвучку за завершённую. Если продукт требует судить только
фактически озвученные фрагменты, это отдельный несовместимый контракт доставки,
не молчаливая правка этого release candidate.

Voice: server VAD → одна финальная STT → FinalUtterance(utterance_id/text/times/ticket)
→ Backend (utterance ID дедуплицируется) → общий turn. Никакого автоматического
Realtime conversation response. TTS стартует только по Backend PlaybackRequest
с checked текстом и message_id/turn_id. Audio проверяет deadline. Пока AI/TTS не закончил,
следующий input не допускается: listening → transcribing → waiting → playing → listening.
После stopped возобновление в той же закрытой сессии запрещено.

WS wire: фиксированный PCM16 LE 24 kHz mono; input audio(sequence,payload base64)
или control stop/close. Output final transcript с utterance_id и times, audio_frame
с playback_id/sequence/UTC timestamp/format/payload, state или error. Transcript —
**целый завершённый текст, не delta**; UI заменяет временное отображение по utterance_id.
Каноническое сообщение UI приходит от Backend; не добавлять тот же STT второй раз.
Playback events идут в Backend для состояния и диагностики, не определяют исход.

## 10. Finish и отображение результата

Backend замораживает snapshot/plan при cutoff, формирует FinishRequest и сохраняет
FinishResponse целиком. Дедуплицирует finish: повторные команды возвращают одну
анализируемую версию снимка, не платят за новый полный анализ. Agreement во время
раунда не заканчивает раунд сам и не отменяет дальнейшие пользовательские ходы.

Outcome.kind: agreement / partial_agreement / deferred / no_agreement. Условия,
обязательства, open_points, next_step/reason отражают только фактический диалог.
Agreement требует явного взаимного согласия и Evidence обеих сторон плюс прохождения
границ/обязательств; полная сделка не выводится из одной стороны или учебного exemplar.
Partial/deferred имеют доказательства соответствующего решения; no_agreement может
иметь [] evidence при отсутствии материала. Игровое «все договорились» не равно
победе или хорошему навыку.

Concessions/costs — SourcedAction по role_id, description и точным evidence;
consequences — description, observed/possible и evidence. Последствия невыполнения
не выдумывать, если они не обсуждались. Прогноз помечать possible, не выдавать за факт.
Analysis_status ready/partial/failed относится к дополнительному разбору цены и
последствий, не стирает уже извлечённый фактический kind. Partial/failed содержит
analysis_error_code; failed возвращает пустые дополнительные массивы, без demo.

Три судейских слота — по одному hiring/negotiation/ownership. Ready: verdict, error=null;
failed: verdict=null, error. Каждый вызов независим и использует собственную коллегию;
вызовы последовательны на одной модели, предыдущие вердикты не передаются следующему.
Choice player/opponent; один decisive_criterion своей коллегии, Evidence и
observation → effect → comparison. Видимый комментарий ≤120 слов, включая критерий
и цитату. Без ссылок/названий методичек/внутреннего RAG/тренерских советов.

Trainer — отдельный вызов/slot. Summary, strengths/mistakes/missed_opportunities,
next_try (ровно 2–3 конкретные задачи), goal_assessment и plan_vs_reality.
Goal status achieved/partially_achieved/not_achieved/not_assessable. Goal_text — явная
цель из подготовки; её нет/неоднозначна — null/not_assessable, не «пользователь проиграл».
Вывод о цели и все эпизоды обосновываются принятыми пользовательскими Evidence.
Отсутствующий элемент подготовки не является ошибкой. Авторская цель кейса может
объяснять ситуацию, но не подменяет личный план.

Finish открыт даже после пустого/прерванного раунда: no_agreement, пустые условия;
судьи/Trainer при недостатке материала failed/insufficient_evidence. Не принуждать
модель выбрать игрока на пустом транскрипте. Частичный результат сохраняется и
показывается; технические ошибки не заменяются mock victory/score.
Экран: исход/условия/цена/последствия; 3 отдельных выбора; Trainer; 2–3 replay задачи.

## 11. Replay и Admin

Replay после finished создаёт новый session_id с прежними case_config_version,
ролевой парой и **теми же** private AI вводными/стратегией, а не текущей «доброй»
случайной версией. Старый snapshot/result не меняются; новая история пустая,
progress на declared, таймер ready. Строка прошлой подготовки копируется в editable
карточку новой попытки; её можно изменить до start. Подготовка не участвует в
opponent prompt ни при первом, ни при повторном поединке.

Admin POST создаёт новую авторскую конфигурацию; PUT всегда сохраняет новую
config_version, никогда не перезаписывает уже использованную. Published-кейс
проходит схемы, ссылки, проверку стратегии/границ и экспертное подтверждение автора.
Archived скрывается из каталога, но сохранённые версии доступны владельцу старых
попыток/replay. Полноценный произвольный визуальный конструктор не нужен: достаточно
формы разрешённых параметров/импорта валидного CanonicalCase и сохранения версии.
Изменения параметров действительно попадают в Backend → AI projection, не только UI.

## 12. Покрытие требований и приёмка

Источник: FR v0.3 knowledge-base/master `72887a9d…`, структура кейса/подготовки;
ссылки и конфликт старого формата судьи — в аудите. Таблица означает **покрытие
в спецификации**, не реализованность/экспертную приёмку.

| Требования | Разделы / интерфейс |
| --- | --- |
| AUTH-01…03 | 2/7/8: JWT owner, persisted snapshot/preparation |
| CASE-01…05 | 4/5/11: CanonicalCase/PublicCase/pairs/role brief/outcomes |
| PREP-01…05 | 6: optional card/string/review/revision/replay |
| GAME-01,02 | 4/8: закреплённая пара, первый ход пользователя |
| VOICE-01…04 | 8/9: VAD STT/checked TTS/полный snapshot/очерёдность |
| AI-01…06 | 4/5/8/9: авторская роль, окна/границы/earned уступки/роль до cutoff |
| TIME-01…04 | 8/9: ≤300 секунд, start/deadline, остановка/сигнал/кнопка |
| TRANS-01…04 | 8/9: message/role/time/text/evidence, Backend UI feed |
| OUT-01…03 | 5/10: kind/terms/evidence/concessions/costs/consequences |
| JUDGE-01…07 | 10: независимые 3 slots/обязательный выбор при достаточном материале/критерий/цитата/формула |
| COACH-01…06 | 6/10: отдельный Trainer, план/цель/эпизоды/последствия/replay задачи |
| RESULT-01 | 10: независимые блоки реальных результатов |
| REPLAY-01…03 | 6/11: новая попытка, editable plan, неизменные условия |
| ADMIN-01…05 | 4/5/11: отдельный UI, versioned configuration, реальная projection, экспертные кейсы |

Нормальные сценарии: 2 разных кейса (не только KPI), обе ориентации ролей, пустая/
частичная/полная подготовка, review/редактирование, текст и голос, договорённость/
partial/deferred/no_agreement, продолжение после сделки, replay с прежней версией.
Негативные: private prompt injection/утечки, давление/мат без выхода из роли и
бесплатных уступок, отрицания/чужая речь, выход за каждую границу/линейную комбинацию,
неверные IDs/версии/evidence, двойная команда/сбой/late result, blocked/model_error,
failed judge/Trainer/outcome analysis, cutoff во время STT/LLM/TTS, пустой finish,
stale preparation revision, чужая сессия/role pair, отсутствие admin.

Нагрузка: 6 одновременных сессий на реальном сервере, измерить очередь/turn/finish/
ошибки и определить приемлемую задержку с командой; не обещать её из схемы.
Схема/fixtures не проверяют педагогическую точность или качество реального STT/TTS.

## 13. Реализация и безопасный rollout

1. Команды отвечают ACK `2.0.0-rc.1` по checklist ниже либо перечисляют конкретные
   несовместимые замечания. Не вводим вторую расходящуюся «почти такую же» схему.
2. После фиксации AI делает свой v2; Backend — projection/queues/storage/таймер;
   Frontend/Admin/Audio — свои адаптеры. Работать можно параллельно по fixtures.
3. Получить runtime OpenAPI, прогнать контрактные тесты и реальные сценарии из 12.
4. Release manifest фиксирует commit/image каждого модуля, contract version, case
   version, приватные base URLs/proxy paths, владельца deploy, порядок/окно и backup.
   Секреты только в secret storage; в manifest — имена переменных/ссылки, не значения.
5. Деплой candidate рядом со старым AI на свободном приватном порту после проверки;
   не останавливать чужой 8080 и не менять LocalAI. Затем совместимый rollout
   Backend/Audio/Frontend, smoke text/voice/finish/replay и контроль логов/ошибок.
6. Старые v1-сессии продолжают v1 по закреплённой версии; v2 создаёт только новые.
   При rollback не направлять сохранённые v2 snapshots в v1. Можно остановить создание
   v2 и оставить соответствующий v2 worker для начатых попыток либо явно завершить
   их технической ошибкой; никакого удаления БД/volumes/reset ради отката.

AI_URL — адрес **нашего** AI HTTP, LOCALAI_BASE_URL — модельный gateway; их не путать.
Qdrant/Embeddings остаются внутренними зависимостями AI, Frontend к ним не обращается.
Deployment manifest заполняют по реальным сервисам, адресам и image IDs; этот файл
не утверждает, какие ветки сейчас работают на сервере.
Используйте [шаблон release manifest](release-manifest.example.json), заменив null
реальными значениями. Это не исполняемая конфигурация и не файл с секретами.

### Единственное оставшееся внешнее согласование

```text
Команда: Backend / Frontend / Admin / Audio
Владелец:
Контракт: ACK 2.0.0-rc.1 либо перечень несовместимых пунктов
Реализация интерфейсов своей команды: задачи и срок
Тестовая среда: base URL / proxy path / branch+commit (без секретов)
Два авторски утверждённых кейса и разрешённые пары: ID/version/ответственный
Деплой: ответственный, окно, manifest и rollback
```

Это запрос подтверждения, не уже полученные ответы. Наша спецификация готова как
единая цель разработки; межкомандная совместимость подтверждается ACK и тестами,
а готовность продакшн-релиза — приёмкой, не названием «итоговый контракт».
