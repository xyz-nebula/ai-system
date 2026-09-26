# Полный словарь контракта 2.0.0-rc.1

Источник формы — [contract.schema.json](contract.schema.json), семантики —
[README](README.md). Это цель реализации, не работающий API. Объекты strict,
required/null/optional различаются. Видимость вложенного объекта зависит от родителя.
Auth v1 остаётся прежним, его поля описаны в аудите.

## Маршруты

| Владелец | Метод/путь | Request | Ответ | HTTP |
| --- | --- | --- | --- | --- |
| backend | `GET /v2/cases` | Без тела | PublicCase[] | 200 |
| backend | `GET /v2/cases/{case_id}` | Без тела | PublicCase | 200 |
| backend | `POST /v2/sessions` | CreateSessionRequest | SessionView | 201 |
| backend | `GET /v2/sessions/{session_id}` | Без тела | SessionView | 200 |
| backend | `POST /v2/sessions/{session_id}/start` | CommandRequest | SessionView | 200 |
| backend | `PUT /v2/sessions/{session_id}/preparation` | SavePreparationRequest | SessionView | 200 |
| backend | `POST /v2/sessions/{session_id}/preparation/review` | CheckPreparationRequest | CommandEnvelope | 202 |
| backend | `POST /v2/sessions/{session_id}/turn` | TextTurnCommand | CommandEnvelope | 202 |
| backend | `POST /v2/sessions/{session_id}/finish` | CommandRequest | CommandEnvelope | 202 |
| backend | `GET /v2/sessions/{session_id}/commands/{command_id}` | Без тела | CommandEnvelope | 200 |
| backend | `GET /v2/sessions/{session_id}/result` | Без тела | FinishResponse | 200 |
| backend | `GET /v2/sessions/{session_id}/events` | Без тела | SessionEvent | 200 |
| backend | `POST /v2/sessions/{session_id}/replay` | ReplayRequest | SessionView | 201 |
| backend | `POST /v2/sessions/{session_id}/audio-ticket` | Без тела | AudioTicket | 200 |
| backend | `POST /v2/internal/audio/utterances` | FinalUtterance | CommandEnvelope | 202 |
| backend | `POST /v2/internal/audio/playback-events` | PlaybackState | Без тела | 204 |
| backend | `GET /v2/admin/cases` | Без тела | CanonicalCase[] | 200 |
| backend | `POST /v2/admin/cases` | CanonicalCase | CanonicalCase | 201 |
| backend | `PUT /v2/admin/cases/{case_id}` | CanonicalCase | CanonicalCase | 200 |
| ai | `GET /v2/info` | Без тела | ServiceInfo | 200 |
| ai | `POST /v2/turn` | TurnRequest | TurnResponse | 200 |
| ai | `POST /v2/finish` | FinishRequest | FinishResponse | 200 |
| ai | `POST /v2/preparation/review` | PreparationReviewRequest | PreparationReviewResponse | 200 |
| audio | `POST /v2/internal/playbacks` | PlaybackRequest | PlaybackState | 202 |
| audio | `POST /v2/internal/playbacks/stop` | StopPlaybackRequest | Без тела | 204 |

WS `/v2/audio-stream`: AudioInput/AudioOutput, ticket и protocol по README.

## Поля

### Outcome

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `kind` | agreement / partial_agreement / deferred / no_agreement | Required | Фактический исход, не качество игры |
| `summary` | string minLength=1 | Required | Краткое описание исхода |
| `agreement` | DealTerms / null | Required | Полные согласованные условия либо null |
| `commitments` | Commitment[] | Required | Принятые обязательства сторон |
| `open_points` | string minLength=1[] | Required | Открытые вопросы |
| `next_step` | string minLength=1 / null | Required | Зафиксированный следующий шаг либо null |
| `reason` | string minLength=1 / null | Required | Причина отложения/исхода либо null |
| `analysis_status` | ready / partial / failed | Required | Готовность дополнительного разбора цены/последствий |
| `analysis_error_code` | outcome_analysis_unavailable / invalid_outcome_analysis / null | Required | Ошибка этого разбора; не фактический kind исхода |
| `concessions` | SourcedAction[] min=0 | Required | Подтверждённые уступки сторон |
| `costs` | SourcedAction[] min=0 | Required | Цена результата по сторонам |
| `consequences` | Consequence[] min=0 | Required | Наблюдаемые/возможные последствия |
| `evidence` | Evidence[] | Required | Однозначная привязка к принятой реплике, не к методичке |

### JudgeVerdict

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `college` | hiring / negotiation / ownership | Required | Судейская коллегия |
| `choice` | player / opponent | Required | Кого выбрал судья |
| `decisive_criterion` | Надёжность / Отношение к людям / Управленческая твёрдость / Забота о команде / Долгосрочные последствия управления / Движение к цели / Управление другой стороной / Работа с картиной мира / Управление ролями / Сохранение отношений / Качество решений / Компетентность / Ответственность / Управление рисками / Последствия для ресурсов | Required | Один критерий своей коллегии |
| `evidence` | Evidence | Required | Однозначная привязка к принятой реплике, не к методичке |
| `observation` | string minLength=1 | Required | Наблюдаемое действие |
| `effect` | string minLength=1 | Required | Что изменилось в разговоре |
| `comparison` | string minLength=1 | Required | Чем отличалась другая сторона |

### JudgeSlot

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `college` | hiring / negotiation / ownership | Required | Коллегия этого слота |
| `status` | ready / failed | Required | Готов результат или произошла ошибка |
| `verdict` | JudgeVerdict / null | Required | Вердикт только при ready |
| `error_code` | judge_unavailable / invalid_judge_output / judge_retrieval_unavailable / invalid_judge_retrieval / insufficient_evidence / null | Required | Код ошибки только при failed |

### CoachingPoint

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `evidence` | Evidence | Required | Однозначная привязка к принятой реплике, не к методичке |
| `action` | string minLength=1 | Required | Что сделал пользователь |
| `situation_change` | string minLength=1 | Required | Как изменил ситуацию |
| `consequence` | string minLength=1 | Required | Последствие действия |

### PreparationComparisonItem

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `preparation_text` | string minLength=1 | Required | Точный непрерывный фрагмент исходной строки подготовки |
| `status` | followed / adapted / not_observed | Required | Следовал плану / адаптировал / не наблюдалось |
| `evidence` | Evidence / null | Required | Однозначная привязка к принятой реплике, не к методичке |
| `observation` | string minLength=1 | Required | Обоснованное сопоставление намерения и поведения |

### PreparationComparison

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `summary` | string minLength=1 | Required | Итог сравнения плана с диалогом |
| `items` | PreparationComparisonItem[] min=1 | Required | Сопоставления явно записанных намерений |

### TrainerFeedback

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `summary` | string minLength=1 | Required | Общий разбор пользователя |
| `strengths` | CoachingPoint[] | Required | Подтверждённые сильные эпизоды |
| `mistakes` | CoachingPoint[] | Required | Подтверждённые ошибки |
| `next_try` | string minLength=1[] min=2 max=3 | Required | Конкретные действия для следующей попытки |
| `plan_vs_reality` | PreparationComparison / null | Required | Сопоставление с подготовкой; null без подготовки |
| `missed_opportunities` | CoachingPoint[] min=0 | Required | Подтверждённые эпизоды упущенных возможностей |
| `goal_assessment` | GoalAssessment | Required | Оценка явно записанной личной цели |

### TrainerSlot

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `status` | ready / failed | Required | Готовность отдельного Trainer |
| `feedback` | TrainerFeedback / null | Required | Разбор только при ready |
| `error_code` | trainer_unavailable / invalid_trainer_output / insufficient_evidence / null | Required | Ошибка только при failed |

### FinishResponse

Направление: AI → Backend → Frontend.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `session_id` | string minLength=1 | Required | Сессия запроса |
| `outcome` | Outcome | Required | Фактический исход |
| `judge_verdicts` | JudgeSlot[] min=3 max=3 | Required | Ровно три независимых слота |
| `trainer_feedback` | TrainerSlot | Required | Отдельный слот Trainer |
| `contract_version` | "2.0.0-rc.1" | Required | Версия wire-контракта |

### Interest

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `text` | string minLength=1 | Required | Содержимое интереса роли |
| `visibility` | public / private | Required | Разрешено публиковать либо private |

### Participant

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `id` | string minLength=1 | Required | Стабильный ID участника |
| `name` | string minLength=1 | Required | Имя/название роли |
| `public_context` | string | Required | Разрешённые общие сведения |
| `public_interests` | string minLength=1[] | Required | Только публичные интересы |

### RoleBrief

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `role_id` | string minLength=1 | Required | ID из participants |
| `private_context` | string | Required | Закрытые вводные выбранной роли |
| `interests` | Interest[] | Required | Авторские интересы с признаками видимости |
| `batna` | string minLength=1 / null | Required | Авторская альтернатива роли либо null |
| `negotiation_goal` | string minLength=1 / null | Required | Авторская цель роли; не собственный план игрока |
| `declared_position` | string minLength=1 / null | Required | Авторская ЗП выбранной роли |
| `desired_position` | string minLength=1 / null | Required | Авторская ЖП выбранной роли |
| `red_line` | string minLength=1 / null | Required | Авторское описание красной черты |
| `role_preparation` | string minLength=1 / null | Required | Авторские методические вводные, не заполненная карточка пользователя |

### Negotiable

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `id` | string minLength=1 | Required | ID предмета торга |
| `label` | string minLength=1 | Required | Человекочитаемое название |
| `value_type` | number / text / boolean / choice / date | Required | Тип значения |
| `unit` | string minLength=1 / null | Required | Единица измерения либо null |
| `choices` | string minLength=1[] | Required | Разрешённые значения choice; иначе [] |

### TermValue

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `term_id` | string minLength=1 | Required | Ссылка на Negotiable.id |
| `value` | number / string / boolean | Required | Значение соответствующего типа |

### Commitment

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `role_id` | string minLength=1 | Required | Одна из двух активных ролей |
| `text` | string minLength=1 | Required | Конкретное обязательство этой стороны |

### DealTerms

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `values` | TermValue[] | Required | Типизированные условия сделки |
| `commitments` | Commitment[] | Required | Обязательства сторон |

### ConcessionRequirement

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `id` | string minLength=1 | Required | Уникальный ID основания уступки |
| `description` | string minLength=1 | Required | Авторское условие перехода |
| `direct_commitment_markers` | string minLength=1[] min=1 | Required | Маркеры прямого обязательства |
| `evidence_groups` | string minLength=1[] min=1[] | Required | Группы дополнительных маркеров проверки; не NLP-гарантия |

### PositionStep

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `id` | string minLength=1 | Required | Уникальный ID ступени |
| `kind` | declared / intermediate / target / red_line | Required | Место в лестнице |
| `terms` | DealTerms | Required | Полный пакет условий |
| `requires` | ConcessionRequirement[] | Required | Основания перехода; declared — [] |
| `constraint_ids` | string minLength=1[] min=0 | Required | ID ограничений окна этой ступени |

### OpponentStrategy

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `steps` | PositionStep[] min=3 | Required | Авторская лестница уступок в порядке движения |

### CaseConfig

Направление: Backend → AI; не браузер и не Audio.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `id` | string minLength=1 | Required | Backend ID кейса |
| `config_version` | string minLength=1 | Required | Закреплённая версия вводных |
| `title` | string minLength=1 | Required | Название |
| `shared_context` | string minLength=1 | Required | Вся значимая фабула, доступная обеим выбранным ролям |
| `participants` | Participant[] min=2 | Required | Публичные сведения всех участников |
| `player` | RoleBrief | Required | Вводные пользовательской роли; не передавать оппоненту |
| `opponent` | RoleBrief | Required | Вводные AI-роли; не передавать браузеру |
| `negotiables` | Negotiable[] | Required | Каталог параметров сделки |
| `opponent_strategy` | OpponentStrategy | Required | Закрытая авторская стратегия выбранной AI-роли |
| `opponent_private_phrases` | string minLength=1[] | Required | Известные закрытые фразы для дополнительной проверки утечек |
| `agreement_policy` | AgreementPolicy | Required | Проверяемые границы и обязательства |
| `contract_version` | "2.0.0-rc.1" | Required | Версия wire-контракта |
| `possible_outcomes` | PossibleOutcome[] | Required | Авторские возможные развязки с признаками видимости |

### PartialDecision

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `kind` | "partial_agreement" | Required | partial_agreement |
| `commitments` | Commitment[] min=1 | Required | Частично согласованные обязательства |
| `open_points` | string minLength=1[] min=1 | Required | Оставшиеся вопросы |

### DeferredDecision

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `kind` | "deferred" | Required | deferred |
| `reason` | string minLength=1 | Required | Причина отложения |
| `next_step` | string minLength=1 | Required | Согласованный следующий шаг |

### AppliedTransition

Направление: Backend ↔ AI; закрыто.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `from_step_id` | string minLength=1 | Required | Исходная ступень |
| `to_step_id` | string minLength=1 | Required | Подтверждённая новая ступень |
| `requirement_ids` | string minLength=1[] min=1 | Required | Проверенные основания уступки |
| `evidence` | Evidence | Required | Полный текст текущей принятой пользовательской реплики-основания |

### Progress

Направление: Backend ↔ AI; закрыто.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `current_step_id` | string minLength=1 | Required | Текущая ступень оппонента |
| `satisfied_requirement_ids` | string minLength=1[] | Required | Подтверждённые основания |
| `last_transition` | AppliedTransition / null | Required | Последний подтверждённый переход либо null |

### SessionState

Направление: Backend ↔ AI; внутри snapshot.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `turn_count` | integer min=0 | Required | Количество сохранённых управляемых ходов |
| `stage` | negotiating / agreed / partial_agreement / deferred | Required | Состояние переговорного решения, не закрытия раунда |
| `agreement` | DealTerms / null | Required | Договорённость при agreed; иначе null |
| `decision` | PartialDecision / DeferredDecision / null | Required | Частичное/отложенное решение; иначе null |
| `opponent_progress` | Progress / null | Required | Закрытое состояние уступок; не выдавать браузеру/судьям/Trainer |

### TranscriptEntry

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `message_id` | string minLength=1 | Required | ID конкретной реплики в истории |
| `turn_id` | string minLength=1 | Required | Backend ID управляемого хода |
| `speaker` | player / opponent | Required | Сторона выбранной пары |
| `status` | accepted / blocked / safe_reaction / interrupted | Required | Принятая реплика / блокировка / безопасная реакция |
| `text` | string minLength=1 | Required | Текст записи |
| `created_at` | string (date-time) | Required | UTC время серверной записи |
| `elapsed_ms` | integer min=0 | Required | Миллисекунды от started_at |
| `blocked_reason` | prompt_override / private_data_request / hidden_position_request / physical_harm_threat / null | Required | Основание блокировки либо null |

### SessionSnapshot

Направление: Backend ↔ AI; закрытый канонический снимок.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `schema_version` | "2.0.0-rc.1" | Required | Версия схемы снимка |
| `session_id` | string minLength=1 | Required | ID попытки |
| `case_id` | string minLength=1 | Required | ID закреплённого кейса |
| `case_config_version` | string minLength=1 | Required | Закреплённая версия содержимого |
| `player_role_id` | string minLength=1 | Required | Выбранная роль пользователя |
| `opponent_role_id` | string minLength=1 | Required | Выбранная AI-роль |
| `state` | SessionState | Required | Каноническое состояние |
| `transcript` | TranscriptEntry[] | Required | Проверенная история |
| `revision` | integer min=0 | Required | Счётчик изменений snapshot |
| `round` | Round | Required | Жизненный цикл и времена Backend |

### TurnRequest

Направление: Backend → AI.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `contract_version` | "2.0.0-rc.1" | Required | Версия wire-контракта |
| `case` | CaseConfig | Required | Разрешённая AI-проекция кейса |
| `snapshot` | SessionSnapshot | Required | Последний канонический снимок Backend |
| `turn_id` | string minLength=1 | Required | Новый стабильный ID команды хода |
| `user_text` | string minLength=1 | Required | Текущая реплика пользователя |
| `user_message_id` | string minLength=1 | Required | Backend ID будущей пользовательской записи |
| `opponent_message_id` | string minLength=1 | Required | Backend ID будущей записи AI |
| `user_created_at` | string (date-time) | Required | Backend UTC время приёма текущей реплики |
| `user_elapsed_ms` | integer min=0 | Required | Время приёма текущей реплики от начала раунда |

### FinishRequest

Направление: Backend → AI; preparation только Trainer.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `contract_version` | "2.0.0-rc.1" | Required | Версия wire-контракта |
| `case` | CaseConfig | Required | Та же закреплённая проекция |
| `snapshot` | SessionSnapshot | Required | Последний сохранённый снимок |
| `preparation` | string minLength=1 / null | Optional | Одна исходная строка подготовки; только Trainer; optional/null |

### TurnResponse

Направление: AI → Backend; для UI строится PublicTurnResult.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `session_id` | string minLength=1 | Required | ID сессии запроса |
| `turn_id` | string minLength=1 | Required | ID хода запроса |
| `status` | accepted / blocked / model_error | Required | accepted/blocked/model_error |
| `opponent_text` | string minLength=1 | Required | Проверенная реплика либо технический безопасный ответ |
| `snapshot` | SessionSnapshot | Required | Новый снимок accepted/blocked; прежний при model_error |
| `error_code` | string minLength=1 / null | Required | Код технической причины либо null |
| `contract_version` | "2.0.0-rc.1" | Required | Версия wire-контракта |

### Evidence

Направление: Вложено в публичные результаты либо закрытый Progress; видимость по родителю.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `message_id` | string minLength=1 | Required | ID конкретной реплики в истории |
| `turn_id` | string minLength=1 | Required | Backend ID управляемого хода |
| `speaker` | player / opponent | Required | Сторона выбранной пары |
| `elapsed_ms` | integer min=0 | Required | Миллисекунды от started_at |
| `quote` | string minLength=1 | Required | Дословный непрерывный фрагмент конкретного сообщения |

### NumericConstraint

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `id` | string minLength=1 | Required | Уникальный ID ограничения |
| `kind` | "numeric_range" | Required | Дискриминатор варианта объекта |
| `term_id` | string minLength=1 | Required | Ссылка на Negotiable.id |
| `minimum` | number / null | Required | Нижняя включительная граница; null — отсутствует |
| `maximum` | number / null | Required | Верхняя включительная граница; null — отсутствует |

### DateConstraint

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `id` | string minLength=1 | Required | Уникальный ID ограничения |
| `kind` | "date_range" | Required | Дискриминатор варианта объекта |
| `term_id` | string minLength=1 | Required | Ссылка на Negotiable.id |
| `minimum` | string (date) / null | Required | Нижняя включительная граница; null — отсутствует |
| `maximum` | string (date) / null | Required | Верхняя включительная граница; null — отсутствует |

### ValueConstraint

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `id` | string minLength=1 | Required | Стабильный ID данного объекта в его реестре |
| `kind` | "allowed_values" | Required | Дискриминатор варианта объекта |
| `term_id` | string minLength=1 | Required | Ссылка на Negotiable.id |
| `values` | number / string / boolean[] min=1 | Required | Точно разрешённые значения указанного term_id |

### LinearCoefficient

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `term_id` | string minLength=1 | Required | Ссылка на Negotiable.id |
| `coefficient` | number | Required | Десятичный коэффициент numeric терма |

### LinearConstraint

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `id` | string minLength=1 | Required | Уникальный ID ограничения |
| `kind` | "linear" | Required | Дискриминатор варианта объекта |
| `coefficients` | LinearCoefficient[] min=1 | Required | Слагаемые нормализованной линейной комбинации |
| `relation` | le / ge / eq | Required | le ≤; ge ≥; eq точное десятичное равенство |
| `bound` | number | Required | Правая часть линейной проверки |

### Constraint

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

Варианты: NumericConstraint / DateConstraint / ValueConstraint / LinearConstraint.

### CommitmentRule

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `id` | string minLength=1 | Required | Уникальный ID обязательства |
| `role_id` | string minLength=1 | Required | Ссылка на стабильную игровую роль |
| `description` | string minLength=1 | Required | Смысл обязательства, проверяемый Validator |

### AgreementPolicy

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `constraints` | Constraint[] min=0 | Required | Реестр типизированных ограничений |
| `hard_constraint_ids` | string minLength=1[] min=0 | Required | Обязательные для каждого полного предложения границы |
| `commitment_rules` | CommitmentRule[] min=0 | Required | Авторские смысловые обязательства с ID и ролью |
| `required_commitment_ids` | string minLength=1[] min=0 | Required | Обязательства, необходимые для полной сделки |

### RolePair

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `player_role_id` | string minLength=1 | Required | Выбранная роль пользователя |
| `opponent_role_id` | string minLength=1 | Required | Выбранная AI-роль |

### RoleAuthorConfig

Направление: Admin → Backend; закрыто.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `role_id` | string minLength=1 | Required | Ссылка на стабильную игровую роль |
| `brief` | RoleBrief | Required | Авторские сведения конкретной роли |
| `negotiables` | Negotiable[] min=0 | Required | Каталог параметров сделки |
| `opponent_strategy` | OpponentStrategy / null | Required | Закрытая авторская стратегия выбранной AI-роли |
| `agreement_policy` | AgreementPolicy | Required | Проверяемые границы и обязательства |
| `private_phrases` | string minLength=1[] min=0 | Required | Дополнительные закрытые формулировки для контроля утечек |

### PossibleOutcome

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `id` | string minLength=1 | Required | ID авторской возможной развязки |
| `kind` | agreement / partial_agreement / deferred / no_agreement | Required | Дискриминатор варианта объекта |
| `description` | string minLength=1 | Required | Описание авторской развязки |
| `possible_consequences` | string minLength=1[] min=0 | Required | Авторские возможные последствия этой развязки |
| `visibility` | public / private | Required | Разрешено публиковать либо private |
| `known_to_role_ids` | string minLength=1[] min=0 | Required | Роли, которым разрешена закрытая информация |

### CanonicalCase

Направление: Admin → Backend; закрытое хранение.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `contract_version` | "2.0.0-rc.1" | Required | Версия wire-контракта |
| `id` | string minLength=1 | Required | ID кейса |
| `config_version` | string minLength=1 | Required | Закреплённая версия вводных |
| `title` | string minLength=1 | Required | Название |
| `short_description` | string minLength=1 | Required | Краткое описание в каталоге |
| `shared_context` | string minLength=1 | Required | Полная общая фабула; закрытые роли отдельно |
| `category` | string minLength=1 | Required | Категория ситуации |
| `difficulty` | easy / moderate / hard / insane | Required | Метаданные; поведенческое правило не выдумывается |
| `duration_seconds` | integer min=1 max=300 | Required | Лимит в секундах, максимум 300 |
| `participants` | Participant[] min=2 | Required | Публичные сведения всех участников |
| `allowed_role_pairs` | RolePair[] min=1 | Required | Авторски разрешённые направленные пары пользователя и AI |
| `role_configs` | RoleAuthorConfig[] min=2 | Required | Закрытое версионированное содержимое ролей |
| `possible_outcomes` | PossibleOutcome[] min=0 | Required | Авторские возможные развязки с признаками видимости |
| `publication_status` | draft / published / archived | Required | draft/published/archived, не статус сессии |
| `full_description` | string minLength=1 | Required | Полный авторский исходник; Admin-only, не автоматически публичная фабула |

### PublicCase

Направление: Backend → Frontend; публично.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `id` | string minLength=1 | Required | ID кейса |
| `config_version` | string minLength=1 | Required | Закреплённая версия вводных |
| `title` | string minLength=1 | Required | Название |
| `short_description` | string minLength=1 | Required | Краткое описание в каталоге |
| `shared_context` | string minLength=1 | Required | Вся значимая фабула, доступная обеим выбранным ролям |
| `category` | string minLength=1 | Required | Категория ситуации |
| `difficulty` | easy / moderate / hard / insane | Required | Метаданные; поведенческое правило не выдумывается |
| `duration_seconds` | integer min=1 max=300 | Required | Лимит в секундах, максимум 300 |
| `participants` | Participant[] min=2 | Required | Публичные сведения всех участников |
| `allowed_role_pairs` | RolePair[] min=1 | Required | Авторски разрешённые направленные пары пользователя и AI |
| `possible_outcomes` | PossibleOutcome[] | Required | Только visibility=public |

### Round

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `status` | ready / open / finishing / finished | Required | ready → open → finishing → finished, владелец Backend |
| `started_at` | string (date-time) / null | Required | UTC начало раунда/высказывания по месту вложения |
| `deadline_at` | string (date-time) / null | Required | Авторитетный UTC дедлайн Backend |
| `finished_at` | string (date-time) / null | Required | UTC прекращение разговора, не завершение анализа |
| `end_reason` | deadline / user_finish / null | Required | deadline либо user_finish |

### SourcedAction

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `role_id` | string minLength=1 | Required | Ссылка на стабильную игровую роль |
| `description` | string minLength=1 | Required | Подтверждённая уступка/цена по указанной роли |
| `evidence` | Evidence[] min=1 | Required | Однозначная привязка к принятой реплике, не к методичке |

### Consequence

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `description` | string minLength=1 | Required | Подтверждённое наблюдение или обоснованный возможный эффект |
| `certainty` | observed / possible | Required | observed — наблюдаемое; possible — прогноз |
| `evidence` | Evidence[] min=1 | Required | Однозначная привязка к принятой реплике, не к методичке |

### GoalAssessment

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `status` | achieved / partially_achieved / not_achieved / not_assessable | Required | Оценка достижения личной цели, не голоса/исход сделки |
| `goal_text` | string minLength=1 / null | Required | Дословный фрагмент личной цели из подготовки либо null |
| `explanation` | string minLength=1 | Required | Обоснование оценки цели |
| `evidence` | Evidence[] min=0 | Required | Однозначная привязка к принятой реплике, не к методичке |

### PreparationContext

Направление: Backend → AI helper; без private opponent.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `case_id` | string minLength=1 | Required | ID закреплённого кейса |
| `case_config_version` | string minLength=1 | Required | Закреплённая версия содержимого |
| `title` | string minLength=1 | Required | Название |
| `shared_context` | string minLength=1 | Required | Вся значимая фабула, доступная обеим выбранным ролям |
| `participants` | Participant[] min=2 | Required | Публичные сведения всех участников |
| `player` | RoleBrief | Required | Вводные пользовательской роли; не передавать оппоненту |
| `opponent_role_id` | string minLength=1 | Required | Выбранная AI-роль |

### PreparationReviewRequest

Направление: Backend → AI.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `contract_version` | "2.0.0-rc.1" | Required | Версия wire-контракта |
| `context` | PreparationContext | Required | Разрешённая информация для проверки собственного блока подготовки |
| `section_id` | root_conflict / strategic_goal / conflict_solutions / layers / swot / negotiation_goal / declared_position / desired_position / red_line / batna / scenario / opening_statement | Required | ID выбранного логического блока |
| `block_text` | string minLength=1 | Required | Только выбранный текст для optional проверки |
| `revision_id` | string minLength=1 | Required | ID редакции блока для защиты от устаревшего ответа |

### PreparationFeedback

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `summary` | string minLength=1 | Required | Разбор одного блока |
| `strengths` | string minLength=1[] min=0 | Required | Сильные стороны выбранного ответа |
| `weaknesses` | string minLength=1[] min=0 | Required | Недостатки выбранного ответа |
| `questions` | string minLength=1[] min=0 | Required | Уточняющие вопросы, не заполнение карточки вместо игрока |
| `improvement_directions` | string minLength=1[] min=0 | Required | Направления самостоятельной доработки |

### PreparationReviewResponse

Направление: AI → Backend → Frontend.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `contract_version` | "2.0.0-rc.1" | Required | Версия wire-контракта |
| `section_id` | root_conflict / strategic_goal / conflict_solutions / layers / swot / negotiation_goal / declared_position / desired_position / red_line / batna / scenario / opening_statement | Required | ID выбранного логического блока |
| `revision_id` | string minLength=1 | Required | ID редакции блока для защиты от устаревшего ответа |
| `status` | ready / failed | Required | Состояние именно данного объекта; значения указаны в типе |
| `feedback` | PreparationFeedback / null | Required | Разбор только при ready |
| `error_code` | preparation_review_unavailable / invalid_preparation_review / null | Required | Код технической ошибки либо null |

### CreateSessionRequest

Направление: Frontend → Backend.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `case_id` | string minLength=1 | Required | ID закреплённого кейса |
| `case_config_version` | string minLength=1 | Required | Закреплённая версия содержимого |
| `player_role_id` | string minLength=1 | Required | Выбранная роль пользователя |
| `opponent_role_id` | string minLength=1 | Required | Выбранная AI-роль |
| `mode` | text / voice | Required | text/voice, закреплено на попытку |
| `client_request_id` | string minLength=1 | Required | Ключ идемпотентности команды |

### SavePreparationRequest

Направление: Frontend → Backend.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `preparation` | string / null | Required | Одна исходная строка пользовательского плана либо null |
| `preparation_revision` | integer min=0 | Required | Ожидаемая текущая версия при записи; фактическая в ответе |

### CheckPreparationRequest

Направление: Frontend → Backend.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `section_id` | root_conflict / strategic_goal / conflict_solutions / layers / swot / negotiation_goal / declared_position / desired_position / red_line / batna / scenario / opening_statement | Required | ID выбранного логического блока |
| `block_text` | string minLength=1 | Required | Только выбранный текст для optional проверки |
| `revision_id` | string minLength=1 | Required | ID редакции блока для защиты от устаревшего ответа |
| `client_request_id` | string minLength=1 | Required | Ключ идемпотентности команды |

### CommandRequest

Направление: Frontend → Backend start/finish.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `client_request_id` | string minLength=1 | Required | Ключ идемпотентности команды |

### TextTurnCommand

Направление: Frontend → Backend.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `client_request_id` | string minLength=1 | Required | Ключ идемпотентности команды |
| `text` | string minLength=1 | Required | Исходный текст данного элемента |

### PublicMessage

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `message_id` | string minLength=1 | Required | ID конкретной реплики в истории |
| `turn_id` | string minLength=1 | Required | Backend ID управляемого хода |
| `speaker` | player / opponent | Required | Сторона выбранной пары |
| `status` | pending / accepted / blocked / safe_reaction / interrupted / model_error | Required | Состояние именно данного объекта; значения указаны в типе |
| `text` | string minLength=1 | Required | Исходный текст данного элемента |
| `created_at` | string (date-time) | Required | UTC время серверной записи |
| `elapsed_ms` | integer min=0 | Required | Миллисекунды от started_at |
| `blocked_reason` | prompt_override / private_data_request / hidden_position_request / physical_harm_threat / null | Required | Основание блокировки либо null |

### PublicTurnResult

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `turn_id` | string minLength=1 | Required | Backend ID управляемого хода |
| `status` | accepted / blocked / model_error / interrupted | Required | Состояние именно данного объекта; значения указаны в типе |
| `messages` | PublicMessage[] min=0 | Required | Публичные записи UI, не закрытый снимок |
| `error_code` | string minLength=1 / null | Required | Код технической ошибки либо null |

### ServiceError

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `code` | string minLength=1 | Required | Стабильный публичный код ошибки |
| `message` | string minLength=1 | Required | Безопасное описание без provider payload |
| `retryable` | boolean | Required | Допустим безопасный повтор; false при неоднозначном модельном выполнении |

### CommandEnvelope

Направление: Backend → Frontend; для STT также Audio.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `contract_version` | "2.0.0-rc.1" | Required | Версия wire-контракта |
| `command_id` | string minLength=1 | Required | Стабильный ID серверной команды |
| `session_id` | string minLength=1 | Required | Сессия запроса |
| `operation` | turn / finish / preparation_review | Required | Тип команды определяет тип result |
| `status` | queued / running / completed / failed / unknown | Required | Доставка/выполнение команды, не результат игры |
| `result` | PublicTurnResult или FinishResponse или PreparationReviewResponse / null | Required | Завершённый публичный результат либо null |
| `error` | ServiceError / null | Required | Публичная техническая ошибка либо null |

### SessionView

Направление: Backend → Frontend владельцу.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `contract_version` | "2.0.0-rc.1" | Required | Версия wire-контракта |
| `session_id` | string minLength=1 | Required | Сессия запроса |
| `case_id` | string minLength=1 | Required | ID закреплённого кейса |
| `case_config_version` | string minLength=1 | Required | Закреплённая версия содержимого |
| `player_role_id` | string minLength=1 | Required | Выбранная роль пользователя |
| `opponent_role_id` | string minLength=1 | Required | Выбранная AI-роль |
| `player_brief` | RoleBrief | Required | Только собственные разрешённые вводные игрока |
| `mode` | text / voice | Required | text/voice, закреплено на попытку |
| `round` | Round | Required | Жизненный цикл и времена Backend |
| `server_time` | string (date-time) | Required | UTC часы Backend для коррекции countdown |
| `preparation` | string / null | Required | Одна исходная строка пользовательского плана либо null |
| `preparation_revision` | integer min=0 | Required | Ожидаемая текущая версия при записи; фактическая в ответе |
| `messages` | PublicMessage[] min=0 | Required | Публичные записи UI, не закрытый снимок |
| `result` | FinishResponse / null | Required | Завершённый публичный результат либо null |
| `case` | PublicCase | Required | Проекция кейса строго соответствующего типа |

### AudioTicket

Направление: Backend → Frontend → Audio.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `ticket` | string minLength=1 | Required | Подписанный краткоживущий Audio ticket |
| `expires_at` | string (date-time) | Required | Срок установления WS-соединения |
| `ws_url` | string minLength=1 | Required | Audio URL с внешним proxy prefix |
| `protocol` | "arena.audio.v2" | Required | Версия Audio wire |

### AudioFormat

Направление: Вложенный объект: направление и видимость определяются родительским DTO.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `codec` | "pcm_s16le" | Required | PCM16 little-endian |
| `sample_rate` | 24000 | Required | 24000 Hz |
| `channels` | 1 | Required | Mono, один канал |
| `bit_depth` | 16 | Required | 16 бит |

### AudioInput

Направление: Frontend → Audio WS.

Варианты: object / object.

### AudioInput — вариант 1

Направление: Frontend → Audio WS.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `type` | "audio" | Required | Дискриминатор WS сообщения/события |
| `sequence` | integer min=0 | Required | Порядок фрейма/пакета, не turn ID |
| `payload` | string minLength=1 | Required | Base64 PCM либо объект события по типу |

### AudioInput — вариант 2

Направление: Frontend → Audio WS.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `type` | "control" | Required | Дискриминатор WS сообщения/события |
| `action` | stop / close | Required | Что сделал пользователь |

### AudioOutput

Направление: Audio → Frontend WS.

Варианты: object / object / object / object.

### AudioOutput — вариант 1

Направление: Audio → Frontend WS.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `type` | "transcript" | Required | Дискриминатор WS сообщения/события |
| `utterance_id` | string minLength=1 | Required | Стабильный ID финального STT высказывания |
| `text` | string minLength=1 | Required | Исходный текст данного элемента |
| `final` | true | Required | Целый завершённый текст, не delta |
| `started_at` | string (date-time) | Required | UTC начало раунда/высказывания по месту вложения |
| `ended_at` | string (date-time) | Required | UTC конец высказывания |

### AudioOutput — вариант 2

Направление: Audio → Frontend WS.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `type` | "audio_frame" | Required | Дискриминатор WS сообщения/события |
| `playback_id` | string minLength=1 | Required | Стабильный ID озвучивания checked текста |
| `sequence` | integer min=0 | Required | Порядок фрейма/пакета, не turn ID |
| `timestamp` | string (date-time) | Required | UTC время аудиофрейма |
| `format` | AudioFormat | Required | Фиксированный формат Audio |
| `payload` | string minLength=1 | Required | Base64 PCM либо объект события по типу |

### AudioOutput — вариант 3

Направление: Audio → Frontend WS.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `type` | "state" | Required | Дискриминатор WS сообщения/события |
| `state` | listening / transcribing / waiting / playing / stopped | Required | Фаза Audio либо каноническое состояние поединка по месту вложения |

### AudioOutput — вариант 4

Направление: Audio → Frontend WS.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `type` | "error" | Required | Дискриминатор WS сообщения/события |
| `code` | string minLength=1 | Required | Стабильный публичный код ошибки |
| `message` | string minLength=1 | Required | Безопасное описание без provider payload |

### FinalUtterance

Направление: Audio → Backend internal.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `audio_ticket` | string minLength=1 | Required | Ticket этой сессии/пользователя для повторной проверки Backend |
| `utterance_id` | string minLength=1 | Required | Стабильный ID финального STT высказывания |
| `text` | string minLength=1 | Required | Исходный текст данного элемента |
| `started_at` | string (date-time) | Required | UTC начало раунда/высказывания по месту вложения |
| `ended_at` | string (date-time) | Required | UTC конец высказывания |

### PlaybackRequest

Направление: Backend → Audio internal.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `session_id` | string minLength=1 | Required | Сессия запроса |
| `turn_id` | string minLength=1 | Required | Backend ID управляемого хода |
| `message_id` | string minLength=1 | Required | ID конкретной реплики в истории |
| `playback_id` | string minLength=1 | Required | Стабильный ID озвучивания checked текста |
| `text` | string minLength=1 | Required | Исходный текст данного элемента |
| `deadline_at` | string (date-time) | Required | Авторитетный UTC дедлайн Backend |

### StopPlaybackRequest

Направление: Backend → Audio internal.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `session_id` | string minLength=1 | Required | Сессия запроса |
| `reason` | deadline / user_finish | Required | deadline/user_finish |

### PlaybackState

Направление: Audio ↔ Backend internal.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `session_id` | string minLength=1 | Required | Сессия запроса |
| `playback_id` | string minLength=1 | Required | Стабильный ID озвучивания checked текста |
| `status` | queued / playing / completed / cancelled / failed | Required | Состояние именно данного объекта; значения указаны в типе |
| `at` | string (date-time) | Required | UTC время события playback |
| `error_code` | string minLength=1 / null | Required | Код технической ошибки либо null |

### ReplayRequest

Направление: Frontend → Backend.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `client_request_id` | string minLength=1 | Required | Ключ идемпотентности команды |

### SessionEvent

Направление: Backend → Frontend SSE.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `event_id` | string minLength=1 | Required | Устойчивый SSE cursor для Last-Event-ID |
| `session_id` | string minLength=1 | Required | Сессия запроса |
| `type` | session / command / message / round_ended | Required | Дискриминатор WS сообщения/события |
| `payload` | SessionView или CommandEnvelope или PublicMessage или Round | Required | Объект, соответствующий type |

### ServiceInfo

Направление: AI → Backend discovery.

| Поле | Тип / ограничения | Обязательность | Что хранится / передаётся |
| --- | --- | --- | --- |
| `contract_version` | "2.0.0-rc.1" | Required | Версия wire-контракта |
| `mode` | demo / qwen | Required | Режим AI-сервиса: демонстрационный или с реальной моделью; не режим ввода сессии |
| `model` | string minLength=1 / null | Required | Runtime модель либо null для demo |
| `supported_routes` | string minLength=1[] min=0 | Required | Поддержанные AI маршруты версии |

Всего 73 именованных типа, 374 полей с учётом inline вариантов WS.
JSON Schema не заменяет проверки ссылок/приватности/Evidence/идемпотентности и
экспертную приёмку. Nullable required поля передаются явно даже при null.
