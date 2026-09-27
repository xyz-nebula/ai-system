# Подключение всего проекта: проверенный план

Дата проверки: 27 сентября 2026. Контракт AI: `2.0.0-rc.1`.

Прямой интеграционный партнёр AI — только Backend. Для него отдельно подготовлены
[Backend ↔ AI гайд](backend-ai-v2-guide.md) и [состояние нашей части](ai-current-state.md).
Задачи остальных компонентов ниже адресованы их владельцам, не AI-команде.

**Начать интеграцию можно. Полностью интегрированным приложение пока не является.**
AI доступен; в Backend, Frontend и Audio остаются конкретные изменения ниже.
Проверка репозиториев не заменяет сквозной прогон развёрнутого приложения.

## 1. Что проверено

GitHub показывает шесть доступных репозиториев организации, включая три приватных.
Проверены рабочие `dev` у сервисов и `master` у knowledge-base, перечни веток,
конфигурации, маршруты, клиенты и GitHub deployments. Не проверялся каждый исторический
коммит/feature branch; неизвестно, какие ветки реально запущены у других команд.

| Репозиторий | Проверенный снимок | Результат |
| --- | --- | --- |
| ai-system | dev `31527e6` | V2 маршруты реализованы, отдельный серверный стенд |
| backend | dev `4af14ed` | Case/Chat/Message есть; вызова AI и выдачи результата нет |
| front-end (private) | dev `d30e066` | Каталог/создание/история есть; текст недоступен, результат демонстрационный |
| audio-engine (private) | dev `5e01ec2` | Realtime LocalAI + сохранение транскрипта, не управляемый AI-ход |
| admin-frontend (private) | dev `3b21ca9` | CRUD кейсов с двумя ролями и двумя авторскими подготовками |
| knowledge-base | master `5f7a99d` | Кейсы, подготовка, три коллегии, отдельный тренер и replay описаны |

На доступной машине `pyxis-lynx` теперь запущены основной AI с v2 и Qdrant/TEI; старый v1 и стенд 8002 остановлены.
Это **не доказывает**, что другие компоненты нигде не развёрнуты. GitHub deployments
сервисных репозиториев пусты; workflow публикации image не сообщает адрес приложения.

## 2. Реальные адреса и проверенные границы

| Компонент | Адрес | Статус |
| --- | --- | --- |
| AI v2 | `http://172.16.34.7:8000` | health/live и health/ready HTTP 200 |
| Старый AI v1 | Не слушает порт | Остановлен по просьбе пользователя; сохранён для отката |
| LocalAI | `http://172.16.34.6:8080/v1/chat/completions` | Модельная readiness AI прошла; сервис не перенастраивался |
| Qdrant на AI-машине | `http://127.0.0.1:6333` | healthz HTTP 200 |
| Embeddings на AI-машине | `http://127.0.0.1:8081` | health HTTP 200 |
| Backend / Frontend / Admin / Audio | Адреса живых экземпляров не установлены | Нужны от владельцев |

Из Backend-контейнера обращаться к IP AI, **не к localhost**.
AI приватный HTTP; не публиковать его в интернет и не проксировать браузеру токен.
Health не доказывает готовность всех судей или сетевую доступность из другого хоста.

Проверенные AI маршруты: `/v2/turn`, `/v2/finish`, `/v2/preparation/review`,
`/v2/evaluate`. Точные runtime-схемы: `GET /openapi.json` на порту 8000.
Проектные `/v2/info` и маршруты Backend/Audio из старых схем не считать существующими.

Последний серверный модельный smoke **из предыдущего этапа**, не новый повтор:
evaluate HTTP 200 за 68.63 с, исход agreement ready, Trainer ready, negotiation ready,
hiring/ownership failed с invalid_judge_output. Сейчас повторены только безопасные
health/OpenAPI и 401/409/422 проверки, без генерации диалога.

## 3. Кто с кем соединяется

```text
Admin ──> Backend: Case, две авторские подготовки игровых ролей
Frontend ──> Backend: выбранная роль + собственная подготовка пользователя
Текст: Frontend ──> Backend ──> AI turn ──> Backend сохранение ──> Frontend
Голос: Frontend ──> Audio STT ──> Backend ──> AI turn
       Backend подтверждённый текст ──> Audio TTS ──> Frontend
Итог: Backend фиксирует историю ──> AI evaluate или finish
      AI исход + три судьи + тренер ──> Backend хранение ──> Frontend
```

AI не обращается к Audio, не хранит пользовательские сессии, не проверяет JWT
пользователя. Пользовательский доступ проверяет Backend; его внутренний клиент
использует сервисный токен AI. При текущей Audio v1 JWT проверяет также Audio.

## 4. Первый срез: подключить оценку готового диалога

Не требует сложного CaseConfig или snapshot. **Не заменяет интеграцию оппонента.**

### Backend → AI

`POST http://172.16.34.7:8000/v2/evaluate`

Заголовки:

```text
Authorization: Bearer <существующий внутренний AI-токен>
X-Arena-Contract-Version: 2.0.0-rc.1
Content-Type: application/json
```

Токен передаёт оператор через защищённое хранилище. Не брать пользовательский JWT,
не помещать секрет в VITE_* или коммит. AI использует существующий ARENA_SERVICE_TOKEN.
Для Backend предлагаются новые настройки `AI_BASE_URL`, `AI_SERVICE_TOKEN`,
`AI_CONTRACT_VERSION`, `AI_TIMEOUT_SECONDS`; **их ещё нет в Backend Settings**.
Просто записать env без реализации клиента недостаточно.

| Поле AI | Тип / содержание | Источник Backend |
| --- | --- | --- |
| role | Непустая строка, роль пользователя | first_role при selected_role=0, second_role при 1 |
| opponent_role | Непустая строка, роль AI | Противоположная роль Case |
| case_description | Общая фабула, без скрытой подготовки/промпта | Case.description, полноту проверяет автор |
| messages | Непустой список в сохранённом порядке | Message по sequence |
| messages[].text | Непустая реплика | Message.text |
| messages[].is_ai | Строго boolean | Доверенное авторство сохранённого сообщения |
| preparations | Непустая строка или null; можно опустить | Chat.preparations, пустую строку нормализовать в null |

Собственную подготовку Chat не заменять Case.first_role_preparations/second_role_preparations.
В сообщения не включать системные промпты, ошибки и отклонённые попытки.
Индекс доказательства соответствует позиции в этом списке; хранить именно оценённую
версию транскрипта и не менять порядок после оценки.

Пример серверного клиента; сохранение, очередь и авторизация пользователя остаются
в Backend, а не в этом фрагменте:

```python
async with httpx.AsyncClient(timeout=330.0) as client:
    response = await client.post(
        f"{ai_base_url.rstrip('/')}/v2/evaluate",
        headers={
            "Authorization": f"Bearer {ai_service_token}",
            "X-Arena-Contract-Version": "2.0.0-rc.1",
        },
        json=evaluation_request,
    )
    response.raise_for_status()
    result = response.json()  # затем проверить по EvaluationResponse
```

Готовая [Pydantic-модель запроса](../../src/arena_ai/v2/evaluation_request.py),
[модель ответа](../../src/arena_ai/v2/evaluation_response.py),
[самостоятельный JSON Schema реестр](../api/v2/evaluation.schema.json).
Request можно копировать отдельно; response-файл использует типы пакета AI:
для независимого Backend генерировать модели из схемы/runtime OpenAPI, не копировать
его без связанных типов.

### AI → Backend → Frontend

Корень ответа: `contract_version`, `outcome`, `judge_verdicts`, `trainer_feedback`.

- outcome: `basis=dialogue_inference`, `status`, `assessment|null`, `error_code|null`.
  Assessment: `kind`, `summary`, `agreed_terms[]`, `open_points[]`, `next_step|null`,
  `evidence[]`. kind: agreement/partial_agreement/deferred/no_agreement/not_assessable.
- judge_verdicts: ровно три слота hiring/negotiation/ownership; каждый содержит
  `college`, `status`, `verdict|null`, `error_code|null`. Verdict: `college`,
  `choice=player|opponent`, `decisive_criterion`, `evidence`, `observation`, `effect`, `comparison`.
- trainer_feedback: `status`, `feedback|null`, `error_code|null`. Feedback: `summary`,
  `strengths[]`, `mistakes[]`, `missed_opportunities[]`, `next_try[]` (2–3 задачи),
  `plan_vs_reality|null`, `goal_assessment`.
- Coaching point: `evidence`, `action`, `situation_change`, `consequence`.
  Plan comparison: `summary`, `items[]`; item: `preparation_text`,
  `status=followed|adapted|not_observed`, `evidence|null`, `observation`.
  Goal assessment: `status`, `goal_text|null`, `explanation`, `evidence[]`.
- Любое indexed evidence: `message_index` (с нуля), `is_ai`, `quote` — точный фрагмент
  соответствующей реплики. Условие обещано ≠ условие исполнено.

HTTP 200 может содержать failed-слоты. Frontend сохраняет успешные части и показывает
«Оценка недоступна» для failed. Нельзя превращать failed в defeat/0/no_agreement.
ready означает прохождение внутренних проверок, не гарантию истинности вывода модели.
401 — токен, 409 — версия, 422 — входные данные; они проверены без модельного вызова.

AI синхронный, возможны около 300 с на полную оценку. Для обычного UI рекомендуется
фоновая задача Backend + сохранённый статус обработки; AI job/poll API отсутствует.
Имена публичных finish/result/job маршрутов определяет Backend с Frontend:
таких реализованных маршрутов в проверенном Backend пока нет. Не объявлять их рабочими.
Не повторять модельный POST автоматически после неоднозначного таймаута.

## 5. Блокеры и конкретные задачи владельцев

### Backend

1. **Подготовка теряется:** ChatCreateRequest содержит name/case_uuid/selected_role,
   но не preparations. Router и ChatService также её не передают. DB action умеет
   сохранить preparations, однако сейчас получает пустое значение по умолчанию.
   Добавить поле и передать сквозь весь путь; проверить запись и чтение.
2. Создать AI client, завершение Chat, freeze транскрипта, сохранение полного
   структурированного результата, endpoint его чтения и защиту от повторного запуска.
   create_feedback/create_judgement сейчас только сохраняют текст, не вызывают AI.
3. **Закрытые вводные:** CaseResponse включает system_prompt и обе role_preparations,
   эта схема используется в пользовательских case/active-chat/chat ответах.
   Разделить admin/internal DTO и public DTO; отдавать только разрешённые выбранной
   роли вводные. Frontend-фильтрация не является защитой.
4. Не принимать is_ai=true как доказательство авторства от произвольного браузера.
   При сохранении доверенного ответа проставлять авторство на сервере.
5. Сериализовать сообщения по Chat: текущий sequence вычисляется через last+1,
   параллельные записи требуют транзакции/блокировки/ограничения уникальности.
6. Для полного диалога добавить канонические CaseConfig/SessionSnapshot, управляемый
   turn, таймер и сохранение результата по разделу 6. Chat.created_at не равен
   автоматически started_at активного раунда; victory/defeat не заменяет исход и голоса.

### Frontend

1. Уже отправляет preparations и selected_role: дождаться исправления Backend,
   проверить roundtrip подготовки. Не хранить единственную копию только в браузере.
2. sendTextTurn сейчас featureUnavailable; finishSession/getResult вызывают demoResult
   с victory и score=74. Заменить реальными Backend endpoint/адаптером ответа.
3. В .env.example negotiation/audio mock. Переключать на real после внедрения стыков,
   не считать смену флага реализацией отсутствующих маршрутов.
4. UI должен отображать outcome, три независимых judge slots, Trainer и loading/failed.
   Нельзя свести ответ AI к текущему демонстрационному score.
5. Проверить proxy: Vite удаляет /api, но Caddy на 8080 ожидает /api/*.
   Для текущего dev выбрать direct Backend target :3000 с rewrite или Caddy :8080
   с сохранением /api. Не направлять Backend proxy на LocalAI.
6. Нынешний timeout 20 с не подходит для синхронного finish до 300 с; лучше Backend job,
   без автоматического повтора оценки. Production reverse proxy настраивается отдельно:
   Vite dev proxy не входит в статический production build.

### Audio Engine

1. Сейчас подключается к LocalAI realtime и сразу отправляет upstream audio в браузер,
   а user/assistant transcripts затем пишет в Backend. Это обход AI Guard/Validator.
   Выделить STT → Backend managed turn → подтверждённый текст → TTS.
   Не запускать второго свободного оппонента параллельно ai-system.
2. **Роль перепутана:** ChatService.get_active_chat выбирает selected role как system_role
   и её авторскую preparation как «Твоя подготовка». AI должен получить противоположную
   роль, её вводные; собеседник — выбранная пользователем роль. Проверить оба значения 0/1.
3. Не выдавать последнее аудио за сохранённую реплику до подтверждения Backend;
   завершение должно дождаться последней принятой реплики и остановить генерацию.
4. Нынешние pause/resume допускаются DTO, но bridge не реализует их семантику:
   обрабатываются только stop/close. Это отдельный блокер полноценного голосового UX.
5. Согласовать Backend/Audio авторизацию и привязку Chat, WS proxy и порт.
   default Audio port 8000/host network конфликтует с AI v1 на этой машине;
   пример Frontend Audio proxy :8081 здесь указывает на embeddings, не Audio.
   Реальный отдельный порт назначает оператор. AI-токен Audio не нужен.

### Admin и авторы кейсов

CRUD двух ролей и двух авторских подготовок уже есть. Хранить их раздельно с личной
подготовкой Chat. Для выбора 0 пользователь first, AI second; для 1 наоборот.
Для managed turn нужна утверждённая структурированная AI-проекция: нельзя автоматически
превратить свободный system_prompt в ограничения и лестницу уступок.
Admin/Backend должны хранить её версию и параметры из раздела 6; значения задаёт автор,
не AI-команда из тестовых fixtures. Не менять закреплённый кейс посреди попытки.

### AI

Сохранять внешний контракт. Исправлять качество hiring/ownership и ложные
семантические accept/reject; не маскировать failed. Проверить живые managed turn,
finish и preparation на утверждённых кейсах. Наличие маршрута не доказывает качество.

## 6. Полный управляемый контур (после первого среза)

Точные вложенные поля и ограничения: [единый контракт](unified-integration-guide.md),
[словарь](../api/v2/fields.md), [runtime-срез](../api/v2/runtime.md) и серверный OpenAPI.
Здесь необходимые группы, которые отсутствуют в простой текущей DB-модели Backend:

- CaseConfig: contract_version, id, config_version, title, shared_context,
  participants[], player, opponent, negotiables[], opponent_strategy,
  opponent_private_phrases[], agreement_policy, possible_outcomes[].
- participant: id/name/public_context/public_interests[]; RoleBrief: role_id,
  private_context/interests[]/batna/negotiation_goal/declared_position/desired_position/
  red_line/role_preparation (nullable согласно схеме).
- opponent_strategy.steps[]: id/kind/terms/requires[]/constraint_ids[];
  agreement_policy: constraints[]/hard_constraint_ids[]/commitment_rules[]/
  required_commitment_ids[]. Это параметры произвольного кейса, не KPI-хардкод.
- SessionSnapshot: schema_version/session_id/case_id/case_config_version/
  player_role_id/opponent_role_id/state/transcript[]/revision/round.
- TurnRequest: contract_version/case/snapshot/turn_id/user_text/user_message_id/
  opponent_message_id/user_created_at/user_elapsed_ms.
  TurnResponse: session_id/turn_id/status/opponent_text/snapshot/error_code/contract_version.
  Backend сохраняет допустимый следующий снимок; model_error не продвигает историю.
- FinishRequest: contract_version/case/snapshot/preparation (личная строка или null).
  Финализировать раунд с настоящими Backend-временами, не выдумывать snapshot из
  текста готовой истории. Finish использует состояние, evaluate — только текстовый вывод.
- PreparationReviewRequest: contract_version/context/section_id/block_text/revision_id.
  context: case_id/case_config_version/title/shared_context/participants/player/
  opponent_role_id; только доступные пользователю вводные, без private brief оппонента.
  Response: contract_version/section_id/revision_id/status/feedback/error_code.
  feedback: summary/strengths[]/weaknesses[]/questions[]/improvement_directions[].

Оценка одного блока до диалога не равна разбору всей preparations после диалога.
Бизнес-аналитика также описывает цену результата и возможные последствия:
simple evaluate не имеет отдельного поля costs/consequences. Для полной аналитики
managed finish имеет эти структуры; нельзя утверждать 100% покрытие требований
одним упрощённым endpoint или дорисовывать отсутствующие поля на Frontend.

## 7. Порядок совместной приёмки

1. Владельцы сообщают реальные URL, ветки/коммиты Backend/Frontend/Admin/Audio и
   private-сетевой доступ. Не устанавливать их сервисы на AI-машине без согласования.
2. Из Backend-среды проверить AI live/ready/OpenAPI на 8000; передать токен безопасно.
3. Исправить подготовку/DTO, создать Chat с каждой ролью и убедиться в сохранении
   строки. Убедиться, что пользователь не получает закрытые вводные другой роли.
4. Один фиксированный Chat → Backend evaluate → сохранённый EvaluationResponse → UI.
   Проверить ready и частичные failed, индексы/авторов цитат, отсутствие demo/авторетрай.
5. Добавить текстовый managed turn: accepted/blocked/model_error, revision/order,
   таймер и финализацию. Повторный запрос не должен создавать второй принятый ход.
6. Голос: законченная STT реплика → тот же managed turn → TTS точно возвращённого
   текста; проверить завершение при незаконченной записи и обрыве соединения.
7. Preparation review и replay: правильная роль, неизменные скрытые вводные кейса,
   новый Chat/сессия, персональные 2–3 задачи. Только затем полная живая приёмка судей.

## 8. Источники проверки

- [Backend Chat/хранение](https://github.com/xyz-nebula/backend/blob/4af14edb38f0126695105f9004634e311d81b338/app/services/ChatService.py),
  [DTO](https://github.com/xyz-nebula/backend/blob/4af14edb38f0126695105f9004634e311d81b338/app/api/v1/routers/models.py).
- [Frontend реальные и demo-операции](https://github.com/xyz-nebula/front-end/blob/d30e066775e4c513d5e264c78098130efc8f4677/src/services/real/backendNegotiationClient.ts),
  [proxy](https://github.com/xyz-nebula/front-end/blob/d30e066775e4c513d5e264c78098130efc8f4677/vite.config.ts).
- [Audio выбор роли](https://github.com/xyz-nebula/audio-engine/blob/5e01ec25271ac1cd7f425bc467fbbedf33da4137/app/services/chat_service.py),
  [realtime bridge](https://github.com/xyz-nebula/audio-engine/blob/5e01ec25271ac1cd7f425bc467fbbedf33da4137/app/services/audio_bridge_service.py).
- [Admin контракт](https://github.com/xyz-nebula/admin-frontend/blob/3b21ca91ad453c3a88858927544618e74b4e80a4/src/api.ts).
- [Бизнес-документы зафиксированной версии](https://github.com/xyz-nebula/knowledge-base/tree/5f7a99d0eeb66e76b0646c19349c534490c27309/business).

Приватные ссылки требуют доступа организации. Никакие чужие файлы, контейнеры,
данные пользователей или конфигурации этой проверкой не изменялись.
