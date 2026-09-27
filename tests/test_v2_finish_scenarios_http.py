"""Synthetic cross-case acceptance at the public finish boundary."""

import json
import os
from pathlib import Path

import httpx
import pytest
from test_judge_retrieval_api import RetrievalGateway
from test_v2_http import configure

from arena_ai.app import create_configured_app


@pytest.fixture
def anyio_backend():
    return "asyncio"


def scenario_body(scenario):
    base = json.loads(
        (
            Path(__file__).resolve().parents[1] / "docs/api/v2/examples/supply-turn.request.json"
        ).read_bytes()
    )
    case, snapshot = base["case"], base["snapshot"]
    if scenario == "supply":
        dialogue = [
            "Для производства нужна поставка не позднее 12 дней. Какие условия вы предлагаете?",
            "Предлагаю 5000 рублей за единицу и поставку за 14 дней.",
            "Обязуюсь заказать 500 единиц. В обмен предлагаю 4800 рублей за единицу и поставку за 12 дней.",
            "Согласен на 4800 рублей за единицу и 12 дней при заказе 500 единиц. Обязуюсь поставить в этот срок.",
            "Согласен: заказываю 500 единиц, обязуюсь оплатить по 4800 рублей за единицу, поставка за 12 дней.",
            "Подтверждаю заказ 500 единиц по 4800 рублей и обязательство поставить за 12 дней.",
        ]
        snapshot["state"].update(
            stage="agreed", agreement=case["opponent_strategy"]["steps"][1]["terms"]
        )
    else:
        case.update(
            id="synthetic-deadline",
            title="Учебный пример: перенос дедлайна",
            shared_context="Студент и преподаватель обсуждают перенос срока проекта. Все данные вымышлены.",
            participants=[
                {
                    "id": "student",
                    "name": "Студент",
                    "public_context": "Готовит проект",
                    "public_interests": ["Завершить проект"],
                },
                {
                    "id": "teacher",
                    "name": "Преподаватель",
                    "public_context": "Принимает проект",
                    "public_interests": ["Проверить результат вовремя"],
                },
            ],
            negotiables=[
                {
                    "id": "submission_date",
                    "label": "Дата сдачи",
                    "value_type": "date",
                    "unit": None,
                    "choices": [],
                }
            ],
        )
        for side, role in (("player", "student"), ("opponent", "teacher")):
            case[side].update(
                role_id=role,
                private_context=f"Закрытые учебные вводные {role}.",
                interests=[],
                batna=None,
            )
        case["opponent_private_phrases"] = ["Закрытые учебные вводные teacher"]
        steps, constraints = [], []
        for kind, date in (
            ("declared", "2026-09-28"),
            ("target", "2026-09-30"),
            ("red_line", "2026-10-02"),
        ):
            constraints.append(
                {
                    "id": kind,
                    "kind": "date_range",
                    "term_id": "submission_date",
                    "minimum": date,
                    "maximum": date,
                }
            )
            steps.append(
                {
                    "id": kind,
                    "kind": kind,
                    "terms": {
                        "values": [{"term_id": "submission_date", "value": date}],
                        "commitments": [{"role_id": "student", "text": f"Сдать проект {date}"}],
                    },
                    "requires": []
                    if kind == "declared"
                    else [
                        {
                            "id": f"preview-{kind}",
                            "description": "Показать промежуточный результат",
                            "direct_commitment_markers": ["обязуюсь"],
                            "evidence_groups": [["черновик"]],
                        }
                    ],
                    "constraint_ids": [kind],
                }
            )
        case["opponent_strategy"] = {"steps": steps}
        case["agreement_policy"] = {
            "constraints": constraints,
            "hard_constraint_ids": [],
            "commitment_rules": [],
            "required_commitment_ids": [],
        }
        snapshot.update(case_id=case["id"], player_role_id="student", opponent_role_id="teacher")
        dialogue = [
            "Прошу перенести сдачу проекта с 28 сентября на 2 октября.",
            "Важно оставить время на проверку. Почему нужен перенос?",
            "Не завершил расчёты. Могу показать черновик 28 сентября и предлагаю сдачу 30 сентября.",
            "Готов обсудить 30 сентября после просмотра черновика; пока перенос не подтверждаю.",
            "Тогда сначала покажу черновик. Сегодня окончательную дату не согласовали.",
            "Да, решение о переносе примем после просмотра черновика. Сейчас срок не меняем.",
        ]
    snapshot["transcript"] = [
        {
            "turn_id": f"{scenario}-turn-{index // 2 + 1}",
            "speaker": "player" if index % 2 == 0 else "opponent",
            "status": "accepted",
            "text": text,
            "blocked_reason": None,
            "message_id": f"{scenario}-message-{index + 1}",
            "created_at": f"2026-09-26T10:00:{(index + 1) * 10:02d}Z"
            if index < 5
            else "2026-09-26T10:01:00Z",
            "elapsed_ms": (index + 1) * 10000,
        }
        for index, text in enumerate(dialogue)
    ]
    snapshot["state"]["turn_count"] = 3
    if scenario == "supply":
        entry = snapshot["transcript"][2]
        proof = {key: entry[key] for key in ("message_id", "turn_id", "speaker", "elapsed_ms")}
        proof["quote"] = entry["text"]
        snapshot["state"]["opponent_progress"] = {
            "current_step_id": "target",
            "satisfied_requirement_ids": ["order-volume"],
            "last_transition": {
                "from_step_id": "declared",
                "to_step_id": "target",
                "requirement_ids": ["order-volume"],
                "evidence": proof,
            },
        }
    snapshot["revision"] = 3
    snapshot["round"].update(
        status="finishing", finished_at="2026-09-26T10:03:00Z", end_reason="user_finish"
    )
    return {
        "contract_version": "2.0.0-rc.1",
        "case": case,
        "snapshot": snapshot,
        "preparation": None,
    }


@pytest.mark.anyio
@pytest.mark.parametrize("scenario", ["supply", "deadline"])
async def test_finish_preserves_case_outcome_when_models_are_unavailable(monkeypatch, scenario):
    configure(monkeypatch)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503))
    ) as model:
        app = create_configured_app(model)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v2/finish",
                json=scenario_body(scenario),
                headers={
                    "Authorization": "Bearer test-token",
                    "X-Arena-Contract-Version": "2.0.0-rc.1",
                },
            )
    assert response.status_code == 200
    outcome = response.json()["outcome"]
    if scenario == "supply":
        assert outcome["kind"] == "agreement"
        assert outcome["agreement"]["values"] == [
            {"term_id": "price_per_unit", "value": 4800},
            {"term_id": "delivery_days", "value": 12},
        ]
    else:
        assert outcome["kind"] == "no_agreement"
        assert outcome["agreement"] is None


@pytest.mark.anyio
@pytest.mark.parametrize("scenario", ["supply", "deadline"])
@pytest.mark.skipif(
    os.environ.get("ARENA_RUN_LIVE_V2") != "1", reason="Explicit live opt-in required"
)
async def test_live_judges_evaluate_complete_dialogues_across_cases(monkeypatch, scenario):
    url, model_id = os.environ["ARENA_QWEN_CHAT_URL"], os.environ["ARENA_QWEN_MODEL"]
    configure(monkeypatch)
    monkeypatch.setenv("ARENA_QWEN_CHAT_URL", url)
    monkeypatch.setenv("ARENA_QWEN_MODEL", model_id)
    monkeypatch.setenv("ARENA_RETRIEVAL_TIMEOUT_SECONDS", "2")
    body = scenario_body(scenario)
    async with (
        httpx.AsyncClient(timeout=60) as model,
        httpx.AsyncClient(transport=httpx.MockTransport(RetrievalGateway())) as retrieval,
    ):
        app = create_configured_app(model, retrieval)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v2/finish",
                json=body,
                headers={
                    "Authorization": "Bearer test-token",
                    "X-Arena-Contract-Version": "2.0.0-rc.1",
                },
            )
    assert response.status_code == 200
    result = response.json()
    assert result["outcome"]["kind"] == ("agreement" if scenario == "supply" else "no_agreement")
    assert result["outcome"]["agreement"] == body["snapshot"]["state"]["agreement"]
    assert [slot["college"] for slot in result["judge_verdicts"]] == [
        "hiring",
        "negotiation",
        "ownership",
    ]
    assert all(slot["status"] == "ready" for slot in result["judge_verdicts"]), result[
        "judge_verdicts"
    ]


@pytest.mark.anyio
@pytest.mark.skipif(
    os.environ.get("ARENA_RUN_LIVE_V2") != "1", reason="Explicit live opt-in required"
)
async def test_live_deadline_offer_cannot_be_reported_as_confirmed_agreement(monkeypatch):
    url, model_id = os.environ["ARENA_QWEN_CHAT_URL"], os.environ["ARENA_QWEN_MODEL"]
    configure(monkeypatch)
    monkeypatch.setenv("ARENA_QWEN_CHAT_URL", url)
    monkeypatch.setenv("ARENA_QWEN_MODEL", model_id)
    monkeypatch.setenv("ARENA_RETRIEVAL_TIMEOUT_SECONDS", "2")
    body = scenario_body("deadline")
    entry = body["snapshot"]["transcript"][2]
    proof = {key: entry[key] for key in ("message_id", "turn_id", "speaker", "elapsed_ms")}
    proof["quote"] = entry["text"]
    async with httpx.AsyncClient(timeout=60) as real:

        async def gateway(request):
            messages = json.loads(request.content)["messages"]
            if "[V2_JUDGE_VERIFY]" in messages[0]["content"]:
                return await real.send(request)
            if "[V2_JUDGE]" not in messages[0]["content"]:
                return httpx.Response(503)
            college = json.loads(messages[1]["content"])["college"]
            if college != "negotiation":
                return httpx.Response(503)
            verdict = {
                "college": college,
                "choice": "player",
                "decisive_criterion": "Движение к цели",
                "evidence": proof,
                "observation": "Студент согласовал перенос сдачи на 30 сентября.",
                "effect": "Преподаватель подтвердил новую дату, перенос вступил в силу.",
                "comparison": "Студент добился согласия, преподаватель принял предложенный срок.",
            }
            return httpx.Response(
                200, json={"choices": [{"message": {"content": json.dumps(verdict)}}]}
            )

        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(gateway), timeout=60) as model,
            httpx.AsyncClient(transport=httpx.MockTransport(RetrievalGateway())) as retrieval,
        ):
            app = create_configured_app(model, retrieval)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/v2/finish",
                    json=body,
                    headers={
                        "Authorization": "Bearer test-token",
                        "X-Arena-Contract-Version": "2.0.0-rc.1",
                    },
                )
    assert response.status_code == 200
    result = response.json()
    assert result["outcome"]["kind"] == "no_agreement"
    slot = result["judge_verdicts"][1]
    assert slot["status"] == "failed"
    assert slot["verdict"] is None
    assert slot["error_code"] == "invalid_judge_output"
