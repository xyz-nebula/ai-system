# Интеграция Backend ↔ ai-system

Проверено 27 сентября 2026. Для команды Backend; прямых стыков AI с Audio,
Frontend и Admin нет. Этот документ не требует менять чужие сервисы силами AI-команды.

## 1. Адрес и доступ

```text
AI_BASE_URL=http://172.16.34.7:8000
AI_CONTRACT_VERSION=2.0.0-rc.1
```

Это предлагаемые имена Backend-настроек: сейчас их нет в Backend Settings.
Добавить также серверный секрет `AI_SERVICE_TOKEN` и таймаут операции.
Токен соответствует существующему ARENA_SERVICE_TOKEN у AI; получить его от оператора
через защищённый канал. Не передавать пользовательский JWT вместо сервисного токена.
Не публиковать секрет в чате, Git, браузере, query string или логах HTTP-заголовков.

AI доступен только в приватной сети/VPN. Из Backend-контейнера localhost означает
сам Backend, а не AI. Нельзя направлять этот клиент на LocalAI :8080. На :8000 теперь основной AI с v2.
Сервисный AI-клиент запускается на Backend, пользовательский JWT и доступ к Chat
проверяет Backend до межсервисного вызова.

Из среды **самого Backend** проверить без модели:

```bash
curl --connect-timeout 3 --max-time 15 "$AI_BASE_URL/health/live"
curl --connect-timeout 3 --max-time 15 "$AI_BASE_URL/health/ready"
curl --connect-timeout 3 --max-time 15 "$AI_BASE_URL/openapi.json"
```

Проверка этих адресов из SSH-сеанса на AI-сервере уже прошла; доступ из Backend
ещё надо подтвердить. Маршруты с телом требуют заголовки:

```text
Authorization: Bearer <AI_SERVICE_TOKEN>
X-Arena-Contract-Version: 2.0.0-rc.1
Content-Type: application/json
```

## 2. Первый стык: оценка сохранённого разговора

`POST /v2/evaluate` не требует CaseConfig/SessionSnapshot и не генерирует оппонента.

```json
{
  "role": "Поставщик",
  "opponent_role": "Заказчик",
  "case_description": "Стороны согласуют срок поставки и подтверждение заказа.",
  "messages": [
    {"text": "Предлагаю доставку в пятницу при подтверждении заказа сегодня.", "is_ai": false},
    {"text": "Согласен. Подтверждаю заказ сегодня.", "is_ai": true}
  ],
  "preparations": "Моя цель — зафиксировать срок поставки и подтверждение заказа."
}
```

| Поле | Тип и источник |
| --- | --- |
| role | Непустая строка: Case.first_role при Chat.selected_role=0, иначе Case.second_role |
| opponent_role | Непустая строка: другая из двух ролей |
| case_description | Непустая общая фабула Case.description; без system_prompt/закрытых вводных |
| messages | Непустой список сохранённых реплик по Message.sequence |
| messages[].text | Непустой Message.text, не системный промпт/ошибка |
| messages[].is_ai | Строго JSON boolean, доверенное серверное авторство |
| preparations | Chat.preparations одной строкой; отсутствующая/пустая → null, поле можно опустить |

Неизвестные поля запрещены. is_ai не число и не строка. Не обрезать/переписывать
реплики: цитаты проверяются буквально. Чередование авторов не обязательно.
Авторские Case.first_role_preparations/second_role_preparations не подставляются
в preparations: тренер сравнивает **собственный план пользователя** с его действиями.

### Имя пользователя из аккаунта

Backend получает имя из проверенной записи аккаунта (например, User.firstname),
а не из произвольного текста Frontend. Имя можно использовать для отображения результата.
Это **не игровая роль**: role остаётся «Менеджер»/«Поставщик» и т. п., а is_ai
определяет авторство независимо от имени. Не добавлять имя в текст реплик задним числом.

В действующем EvaluationRequest нет user_name/display_name, неизвестное поле вызовет
422. Для текущей оценки имя AI не требуется. Если нужно, чтобы оппонент обращался
по имени, потребуется отдельно согласованное поле контракта управляемого хода;
эта персонализация сейчас не реализована. Email/токены и другие данные аккаунта
AI не передавать. Сам факт получения имени Backend не означает его передачи AI.

### Исправление текущего Backend до вызова

В проверенном Backend dev `4af14ed` Frontend уже отправляет preparations, но
ChatCreateRequest его не описывает. Router → ChatService.create_chat также не
передают его в DB action; последний умеет сохранить поле, но получает default="".
Добавить поле в DTO, провести его сквозь service и проверить сохранение/чтение строки.
Не менять смысл двух авторских подготовок Case ради личного плана Chat.

### Вызов

Сохранить пример в evaluation-request.json; переменные секретов задаёт оператор:

```bash
curl --request POST "$AI_BASE_URL/v2/evaluate" \
  --header "Authorization: Bearer $AI_SERVICE_TOKEN" \
  --header "X-Arena-Contract-Version: $AI_CONTRACT_VERSION" \
  --header 'Content-Type: application/json' \
  --data-binary @evaluation-request.json \
  --connect-timeout 5 --max-time 330
```

Не применять curl --verbose и не логировать секреты. Не повторять модельный запрос
автоматически после таймаута: сервер мог уже его обработать.

Pydantic 2 [EvaluationRequest](../../src/arena_ai/v2/evaluation_request.py) можно
скопировать отдельно в Backend. [EvaluationResponse](../../src/arena_ai/v2/evaluation_response.py)
имеет зависимости от типов arena_ai; для независимого клиента использовать
[evaluation.schema.json](../api/v2/evaluation.schema.json), `$defs.EvaluationRequest`
и `$defs.EvaluationResponse`, либо серверный runtime OpenAPI.

## 3. Что возвращается и что сохранять

Корневые поля ответа: `contract_version`, `outcome`, `judge_verdicts`, `trainer_feedback`.

| Блок | Поля |
| --- | --- |
| outcome | basis=dialogue_inference, status, assessment/null, error_code/null |
| outcome.assessment | kind, summary, agreed_terms[], open_points[], next_step/null, evidence[] |
| judge_verdicts | Ровно три независимых слота: hiring, negotiation, ownership |
| Судейский слот | college, status, verdict/null, error_code/null |
| verdict | college, choice=player/opponent, decisive_criterion, evidence, observation, effect, comparison |
| trainer_feedback | status, feedback/null, error_code/null |
| feedback | summary, strengths[], mistakes[], missed_opportunities[], next_try[], plan_vs_reality/null, goal_assessment |
| Coaching point | evidence, action, situation_change, consequence |
| plan_vs_reality | summary, items[] с preparation_text/status/evidence-null/observation |
| goal_assessment | status, goal_text/null, explanation, evidence[] |
| Evidence | message_index с нуля, is_ai, quote — дословный фрагмент соответствующей входной реплики |

outcome.kind: agreement/partial_agreement/deferred/no_agreement/not_assessable.
goal_assessment.status: achieved/partially_achieved/not_achieved/not_assessable.
Статусы подготовки: followed/adapted/not_observed; next_try содержит 2–3 задачи.

Backend сохраняет весь валидированный ответ вместе с Chat и **неизменяемым оценённым
транскриптом**. Не терять null/status/error_code и не сводить всё к тексту или
Chat.status=victory/defeat. Исход сделки, три голоса и тренер — разные сущности.
По тексту нельзя доказать исполнение обещаний: basis=dialogue_inference не является
канонической подтверждённой сделкой Backend.

HTTP 200 может содержать отдельные failed-слоты. Сохранить готовые части, отдать
Frontend статусы; failed не означает проигрыш, ноль или no_agreement.
Методические источники не добавлять в судейскую аналитику.

## 4. Ожидание, ошибки и повторная доставка

- 401 unauthorized: исправить внутренний токен, не запускать модельный retry.
- 409 contract_version_mismatch: согласовать версию; для turn/finish также возможны
  round_closed/round_not_closed.
- 422 invalid_request: исправить DTO/данные; не отправлять тот же запрос снова.
- HTTP 200 + failed: отдельная модельная/проверочная ошибка слота, не транспортный сбой.
- Обрыв/timeout: результат неизвестен; AI stateless и не дедуплицирует вызовы.

Полный evaluate может занимать около 300 секунд. Текущий 20-секундный UI timeout
не подходит для синхронного ожидания. Рекомендуется задача Backend с сохранённым
processing/result и отдельным чтением результата. У AI нет готового job/poll API:
этот слой и маршруты для Frontend реализует Backend и согласует с ним.
Не держать DB-транзакцию заблокированной весь модельный вызов; использовать короткие
транзакции/состояния обработки и защиту от параллельного запуска одной оценки.

## 5. Второй стык: управляемый диалог

Чтобы подключить не только оценку, но и оппонента, Backend вызывает `/v2/turn`.
Нельзя заменить его прямым вызовом LocalAI: тогда обходятся Guard и проверка уступок.

Backend хранит версионированный CaseConfig и SessionSnapshot; AI не загружает кейс по ID.
CaseConfig содержит публичную фабулу/участников, две RoleBrief, универсальные negotiables,
opponent_strategy, agreement_policy и possible_outcomes. Автор задаёт границы/уступки:
свободный system_prompt не конвертируется в эти структуры автоматически.
Правильная пара: selected_role=0 → player=first, opponent=second; 1 → наоборот.

TurnRequest содержит:

```text
contract_version, case, snapshot, turn_id, user_text,
user_message_id, opponent_message_id, user_created_at, user_elapsed_ms
```

Снимок содержит:

```text
schema_version, session_id, case_id, case_config_version,
player_role_id, opponent_role_id, state, transcript[], revision, round
```

Backend назначает ID и времена, допускает один активный ход на сессию и проверяет
revision до сохранения. В TurnResponse возвращаются session_id, turn_id, status,
opponent_text, snapshot, error_code, contract_version.
Обработка accepted/blocked следует возвращённому снимку; model_error не добавляет
принятый ход и не продвигает историю. Сохранять снимок атомарно и передавать только
разрешённый публичный ответ клиентам. Не отдавать private role data браузеру.

Backend владеет таймером. Round.started_at — начало активного поединка, не дата
создания Chat. Текущий код допускает раунд до 300 секунд, не произвольный лимит.

Для завершения заморозить round и transcript, затем `POST /v2/finish`:
`contract_version`, `case`, `snapshot`, `preparation` (личная строка или null).
FinishResponse включает session_id, outcome, judge_verdicts, trainer_feedback,
contract_version; outcome также имеет concessions/costs/consequences и analysis_status.
Не выдумывать снимок из готового текстового диалога и не вызывать evaluate и finish
автоматически для одной оценки: это разные режимы, двойной вызов увеличит нагрузку.

Точные вложенные DTO/ограничения: [runtime](../api/v2/runtime.md),
[fields](../api/v2/fields.md), [контракт](unified-integration-guide.md), серверный OpenAPI.
Fixtures — примеры, не утверждённые параметры реальных кейсов.

## 6. Необязательная проверка подготовки до диалога

`POST /v2/preparation/review` принимает contract_version, context, section_id,
block_text, revision_id. context: case_id, case_config_version, title, shared_context,
participants, player (свои RoleBrief), opponent_role_id. Закрытую подготовку
оппонента туда не включать.

section_id: root_conflict/strategic_goal/conflict_solutions/layers/swot/
negotiation_goal/declared_position/desired_position/red_line/batna/scenario/opening_statement.
block_text — один выбранный непустой блок, revision_id связывает ответ с версией текста.
Ответ: contract_version, section_id, revision_id, status, feedback/null, error_code/null;
feedback: summary/strengths/weaknesses/questions/improvement_directions.
Эта операция не заменяет preparations в evaluate или preparation в finish.

## 7. Обязательные исправления и приёмка Backend

- [ ] DTO → Router → ChatService → DB сохраняют личную подготовку, чтение возвращает её.
- [ ] Пользовательский Case DTO не содержит system_prompt/закрытые вводные другой роли;
  admin/internal/public схемы разделены. Сейчас CaseResponse включает обе подготовки.
- [ ] Авторство определяется доверенным потоком, браузер не может записать AI-реплику.
- [ ] sequence/revision защищены от параллельных записей; freeze не допускает изменение
  уже оценённой истории и потерю последней принятой реплики.
- [ ] Backend-среда видит health/OpenAPI на 8000 и корректно обрабатывает 401/409/422.
- [ ] Один завершённый Chat → AI evaluate → валидированный сохранённый ответ →
  реальная выдача результата клиенту, без demo и без преобразования failed в defeat.
- [ ] Для полного контура подключены turn/finish, таймер, снимок и preparation review;
  Audio получает только ответ, уже подтверждённый Backend/AI, без прямого стыка с AI.

Сейчас в проверенном Backend dev `4af14ed` нет AI client и готовых публичных
finish/result маршрутов. Их имена определяет Backend совместно с Frontend:
описание проектного маршрута в старой схеме не означает его реализации.
Перед совместным тестом передать AI-команде URL Backend и commit развёрнутой версии.

Наша инфраструктура доступна, но судейство ещё не полностью принято:
[подтверждённое текущее состояние](ai-current-state.md). Подключение Backend возможно
до завершения этих внутренних исправлений, если частичные ошибки обрабатываются честно.
