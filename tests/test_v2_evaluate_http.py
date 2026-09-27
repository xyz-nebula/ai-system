import json
import os
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft202012Validator
from test_judge_retrieval_api import RetrievalGateway
from test_v2_http import configure

from arena_ai.app import create_configured_app


@pytest.fixture
def anyio_backend():
    return "asyncio"


HEADERS = {
    "Authorization": "Bearer test-token",
    "X-Arena-Contract-Version": "2.0.0-rc.1",
}


def validate_contract(kind, value):
    path = Path(__file__).resolve().parents[1] / "docs/api/v2/evaluation.schema.json"
    schema = json.loads(path.read_bytes())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator({**schema, "$ref": f"#/$defs/{kind}"}).validate(value)


def evaluate_body():
    return {
        "role": "Покупатель",
        "opponent_role": "Поставщик",
        "case_description": "Обсуждение цены и срока поставки.",
        "messages": [
            {"text": "Предлагаю цену 100 рублей и поставку в пятницу.", "is_ai": False},
            {"text": "Согласен на 100 рублей и поставку в пятницу.", "is_ai": True},
        ],
        "preparations": "Моя цель — согласовать цену и срок.",
    }


@pytest.mark.anyio
async def test_unavailable_dependencies_return_failed_slots_without_invented_outcome(monkeypatch):
    configure(monkeypatch)
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(503))) as model,
        httpx.AsyncClient(
            transport=httpx.MockTransport(lambda req: httpx.Response(503))
        ) as retrieval,
    ):
        app = create_configured_app(model, retrieval)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/v2/evaluate", json=evaluate_body(), headers=HEADERS)
    assert response.status_code == 200
    result = response.json()
    validate_contract("EvaluationRequest", evaluate_body())
    validate_contract("EvaluationResponse", result)
    assert result["outcome"] == {
        "basis": "dialogue_inference",
        "status": "failed",
        "assessment": None,
        "error_code": "outcome_analysis_unavailable",
    }
    assert [slot["college"] for slot in result["judge_verdicts"]] == [
        "hiring",
        "negotiation",
        "ownership",
    ]
    assert all(slot["status"] == "failed" for slot in result["judge_verdicts"])
    assert result["trainer_feedback"]["status"] == "failed"
    assert "elapsed_ms" not in response.text
    assert "session_id" not in result


def outcome_example():
    return {
        "kind": "agreement",
        "summary": "Стороны согласовали цену 100 рублей и поставку в пятницу.",
        "agreed_terms": ["Цена 100 рублей", "Поставка в пятницу"],
        "open_points": [],
        "next_step": None,
        "evidence": [
            {
                "message_index": 0,
                "is_ai": False,
                "quote": "Предлагаю цену 100 рублей и поставку в пятницу.",
            },
            {
                "message_index": 1,
                "is_ai": True,
                "quote": "Согласен на 100 рублей и поставку в пятницу.",
            },
        ],
    }


def trainer_example():
    return {
        "summary": "Пользователь предложил конкретные условия и получил согласие.",
        "strengths": [
            {
                "evidence": outcome_example()["evidence"][0],
                "action": "Предложил цену и срок",
                "situation_change": "Появилось конкретное предложение",
                "consequence": "Оппонент согласился с условиями",
            }
        ],
        "mistakes": [],
        "missed_opportunities": [],
        "next_try": ["Уточнить порядок оплаты.", "Обсудить способ подтверждения поставки."],
        "plan_vs_reality": {
            "summary": "Записанная цель реализована в разговоре.",
            "items": [
                {
                    "preparation_text": "согласовать цену и срок",
                    "status": "followed",
                    "evidence": outcome_example()["evidence"][0],
                    "observation": "Пользователь предложил оба условия.",
                }
            ],
        },
        "goal_assessment": {
            "status": "achieved",
            "goal_text": "согласовать цену и срок",
            "explanation": "Предложенные условия приняты второй стороной.",
            "evidence": outcome_example()["evidence"],
        },
    }


def judge_example(college):
    return {
        "college": college,
        "choice": "player",
        "decisive_criterion": {
            "hiring": "Надёжность",
            "negotiation": "Движение к цели",
            "ownership": "Качество решений",
        }[college],
        "evidence": outcome_example()["evidence"][0],
        "observation": "Пользователь предложил конкретные цену и срок.",
        "effect": "Поставщик согласился с обоими условиями.",
        "comparison": "Покупатель сформулировал предложение, поставщик подтвердил его.",
    }


async def send_evaluation(monkeypatch, gateway, body=None, retrieval_fault=None):
    configure(monkeypatch)
    monkeypatch.setenv("ARENA_RETRIEVAL_TIMEOUT_SECONDS", "2")
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as model,
        httpx.AsyncClient(
            transport=httpx.MockTransport(RetrievalGateway(retrieval_fault))
        ) as retrieval,
    ):
        app = create_configured_app(model, retrieval)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(
                "/v2/evaluate", json=body if body is not None else evaluate_body(), headers=HEADERS
            )


def reply_json(reply):
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(reply)}}]})


@pytest.mark.anyio
async def test_unilateral_deferral_is_not_published_as_agreed_next_step(monkeypatch):
    candidate = outcome_example()
    candidate.update(
        kind="deferred",
        agreed_terms=[],
        summary="Обсуждение перенесено.",
        next_step="Вернуться к обсуждению завтра.",
        evidence=[{"message_index": 0, "is_ai": False, "quote": "Вернёмся завтра?"}],
    )
    body = evaluate_body()
    body["messages"] = [
        {"text": "Вернёмся завтра?", "is_ai": False},
        {"text": "Нет, обсуждаем сегодня.", "is_ai": True},
    ]

    def gateway(req):
        system = json.loads(req.content)["messages"][0]["content"]
        if "[V2_EVALUATE_OUTCOME_VERIFY]" in system:
            return reply_json({"decision": "accept"})
        if "[V2_EVALUATE_OUTCOME]" in system:
            return reply_json(candidate)
        return httpx.Response(503)

    response = await send_evaluation(monkeypatch, gateway, body)
    assert response.json()["outcome"] == {
        "basis": "dialogue_inference",
        "status": "failed",
        "assessment": None,
        "error_code": "invalid_outcome_analysis",
    }


@pytest.mark.anyio
async def test_evaluate_returns_inferred_outcome_three_judges_and_personal_trainer(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setenv("ARENA_RETRIEVAL_TIMEOUT_SECONDS", "2")
    body = evaluate_body()

    def gateway(req):
        messages = json.loads(req.content)["messages"]
        system = messages[0]["content"]
        context = json.loads(messages[1]["content"])
        assert "elapsed_ms" not in messages[1]["content"]
        assert "state" not in messages[1]["content"]
        assert "snapshot" not in messages[1]["content"]
        if "TRAINER" not in system:
            assert body["preparations"] not in messages[1]["content"]
        if "VERIFY]" in system:
            reply = {"decision": "accept"}
        elif "[V2_EVALUATE_OUTCOME]" in system:
            reply = outcome_example()
        elif "[V2_EVALUATE_JUDGE]" in system:
            reply = judge_example(context["college"])
        elif "[V2_EVALUATE_TRAINER]" in system:
            assert context["preparation"] == body["preparations"]
            reply = trainer_example()
        else:
            raise AssertionError("Unexpected model request")
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(reply)}}]})

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as model,
        httpx.AsyncClient(transport=httpx.MockTransport(RetrievalGateway())) as retrieval,
    ):
        app = create_configured_app(model, retrieval)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/v2/evaluate", json=body, headers=HEADERS)
    assert response.status_code == 200
    result = response.json()
    assert result["outcome"] == {
        "basis": "dialogue_inference",
        "status": "ready",
        "assessment": outcome_example(),
        "error_code": None,
    }
    assert result["judge_verdicts"] == [
        {
            "college": college,
            "status": "ready",
            "verdict": judge_example(college),
            "error_code": None,
        }
        for college in ("hiring", "negotiation", "ownership")
    ]
    assert result["trainer_feedback"] == {
        "status": "ready",
        "feedback": trainer_example(),
        "error_code": None,
    }
    validate_contract("EvaluationRequest", body)
    validate_contract("EvaluationResponse", result)


@pytest.mark.anyio
async def test_openapi_describes_the_approved_request_and_actual_response(monkeypatch):
    configure(monkeypatch)
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(503))) as model,
        httpx.AsyncClient(
            transport=httpx.MockTransport(lambda req: httpx.Response(503))
        ) as retrieval,
    ):
        app = create_configured_app(model, retrieval)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            schema = (await client.get("/openapi.json")).json()
            response = await client.post("/v2/evaluate", json=evaluate_body(), headers=HEADERS)
    operation = schema["paths"]["/v2/evaluate"]["post"]
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert request_schema == {"$ref": "#/components/schemas/V2EvaluationRequest"}
    assert response_schema == {"$ref": "#/components/schemas/V2EvaluationResponse"}
    Draft202012Validator({**request_schema, "components": schema["components"]}).validate(
        evaluate_body()
    )
    Draft202012Validator({**response_schema, "components": schema["components"]}).validate(
        response.json()
    )
    for code in (401, 409, 422):
        assert str(code) in operation["responses"]
    assert operation["parameters"][0]["required"] is True


@pytest.mark.anyio
@pytest.mark.parametrize("stage", ["OUTCOME", "JUDGE", "TRAINER"])
@pytest.mark.parametrize(
    "fault", ["index", "author", "quote", "reject", "uncertain", "unavailable", "format"]
)
async def test_invalid_or_unverified_slot_is_not_published_and_other_slots_survive(
    monkeypatch, stage, fault
):
    def gateway(req):
        messages = json.loads(req.content)["messages"]
        system = messages[0]["content"]
        context = json.loads(messages[1]["content"])
        targeted = f"[V2_EVALUATE_{stage}" in system
        if stage == "JUDGE":
            college = context.get("college", context.get("verdict", {}).get("college"))
            targeted = targeted and college == "hiring"
        if "VERIFY]" in system:
            if targeted and fault == "unavailable":
                return httpx.Response(503, text="private-gateway-error")
            return reply_json(
                {"decision": fault if targeted and fault in ("reject", "uncertain") else "accept"}
            )
        if "[V2_EVALUATE_OUTCOME]" in system:
            candidate = outcome_example()
            proof = candidate["evidence"][0]
        elif "[V2_EVALUATE_JUDGE]" in system:
            candidate = judge_example(context["college"])
            proof = candidate["evidence"]
        else:
            candidate = trainer_example()
            proof = candidate["strengths"][0]["evidence"]
        if targeted:
            if fault == "index":
                proof["message_index"] = 999
            elif fault == "author":
                proof["is_ai"] = True
            elif fault == "quote":
                proof["quote"] = "Получил деньги и товар"
            elif fault == "format":
                candidate = {}
        return reply_json(candidate)

    response = await send_evaluation(monkeypatch, gateway)
    assert response.status_code == 200
    result = response.json()
    slots = {
        "OUTCOME": result["outcome"],
        "JUDGE": result["judge_verdicts"][0],
        "TRAINER": result["trainer_feedback"],
    }
    failed = slots[stage]
    assert failed["status"] == "failed"
    payload_field = {"OUTCOME": "assessment", "JUDGE": "verdict", "TRAINER": "feedback"}[stage]
    assert failed[payload_field] is None
    assert (
        failed["error_code"]
        == {
            "OUTCOME": "outcome_analysis_unavailable"
            if fault == "unavailable"
            else "invalid_outcome_analysis",
            "JUDGE": "judge_unavailable" if fault == "unavailable" else "invalid_judge_output",
            "TRAINER": "trainer_unavailable"
            if fault == "unavailable"
            else "invalid_trainer_output",
        }[stage]
    )
    assert all(slot["status"] == "ready" for name, slot in slots.items() if name != stage)
    assert all(slot["status"] == "ready" for slot in result["judge_verdicts"][1:])
    assert "private-gateway-error" not in response.text


@pytest.mark.anyio
async def test_trainer_without_preparation_does_not_invent_a_personal_plan(monkeypatch):
    body = evaluate_body()
    del body["preparations"]
    feedback = trainer_example()
    feedback["plan_vs_reality"] = None
    feedback["goal_assessment"] = {
        "status": "not_assessable",
        "goal_text": None,
        "explanation": "Пользователь не записал личную цель.",
        "evidence": [],
    }

    def gateway(req):
        messages = json.loads(req.content)["messages"]
        system = messages[0]["content"]
        if "[V2_EVALUATE_TRAINER_VERIFY]" in system:
            return reply_json({"decision": "accept"})
        if "[V2_EVALUATE_TRAINER]" in system:
            assert json.loads(messages[1]["content"])["preparation"] is None
            return reply_json(feedback)
        return httpx.Response(503)

    result = (await send_evaluation(monkeypatch, gateway, body)).json()
    assert result["trainer_feedback"] == {
        "status": "ready",
        "feedback": feedback,
        "error_code": None,
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    "fault", ["opponent_action", "goal", "preparation", "source", "criterion", "length"]
)
async def test_content_rules_reject_fabricated_plans_and_invalid_judge_comments(monkeypatch, fault):
    def gateway(req):
        messages = json.loads(req.content)["messages"]
        system = messages[0]["content"]
        context = json.loads(messages[1]["content"])
        if "VERIFY]" in system:
            return reply_json({"decision": "accept"})
        if "[V2_EVALUATE_TRAINER]" in system:
            candidate = trainer_example()
            if fault == "opponent_action":
                candidate["strengths"][0]["evidence"] = outcome_example()["evidence"][1]
            elif fault == "goal":
                candidate["goal_assessment"]["goal_text"] = "Получить миллион рублей"
            elif fault == "preparation":
                candidate["plan_vs_reality"]["items"][0]["preparation_text"] = "Несуществующий план"
        elif "[V2_EVALUATE_JUDGE]" in system:
            candidate = judge_example(context["college"])
            if context["college"] == "hiring":
                if fault == "source":
                    candidate["observation"] = (
                        "Согласно методичке пользователь действовал правильно."
                    )
                elif fault == "criterion":
                    candidate["decisive_criterion"] = "Движение к цели"
                elif fault == "length":
                    candidate["comparison"] = "Сравнение " * 130
        else:
            return reply_json(outcome_example())
        return reply_json(candidate)

    result = (await send_evaluation(monkeypatch, gateway)).json()
    if fault in ("opponent_action", "goal", "preparation"):
        assert result["trainer_feedback"]["status"] == "failed"
        assert result["trainer_feedback"]["feedback"] is None
        assert all(slot["status"] == "ready" for slot in result["judge_verdicts"])
    else:
        assert result["judge_verdicts"][0]["status"] == "failed"
        assert result["judge_verdicts"][0]["verdict"] is None
        assert result["trainer_feedback"]["status"] == "ready"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("headers", "body", "status", "code"),
    [
        ({}, evaluate_body(), 401, "unauthorized"),
        ({**HEADERS, "Authorization": "Bearer wrong"}, evaluate_body(), 401, "unauthorized"),
        ({"Authorization": "Bearer test-token"}, evaluate_body(), 409, "contract_version_mismatch"),
        (
            {**HEADERS, "X-Arena-Contract-Version": "wrong"},
            evaluate_body(),
            409,
            "contract_version_mismatch",
        ),
        (HEADERS, {}, 422, "invalid_request"),
        (HEADERS, {**evaluate_body(), "messages": []}, 422, "invalid_request"),
        (HEADERS, {**evaluate_body(), "role": " \n"}, 422, "invalid_request"),
        (HEADERS, {**evaluate_body(), "snapshot": {}}, 422, "invalid_request"),
        (
            HEADERS,
            {**evaluate_body(), "messages": [{"text": "X", "is_ai": "true"}]},
            422,
            "invalid_request",
        ),
    ],
)
async def test_bad_transport_is_rejected_before_external_calls(
    monkeypatch, headers, body, status, code
):
    configure(monkeypatch)

    def external(req):
        raise AssertionError("Rejected input must not reach an external dependency")

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(external)) as model,
        httpx.AsyncClient(transport=httpx.MockTransport(external)) as retrieval,
    ):
        app = create_configured_app(model, retrieval)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/v2/evaluate", json=body, headers=headers)
    assert response.status_code == status
    assert response.json() == {
        "code": code,
        "message": {
            401: "Unauthorized",
            409: "Unsupported contract version",
            422: "Invalid evaluation request",
        }[status],
        "retryable": False,
    }


@pytest.mark.anyio
async def test_invalid_retrieval_fails_only_the_affected_college(monkeypatch):
    def gateway(req):
        messages = json.loads(req.content)["messages"]
        system = messages[0]["content"]
        if "VERIFY]" in system:
            return reply_json({"decision": "accept"})
        if "[V2_EVALUATE_JUDGE]" in system:
            return reply_json(judge_example(json.loads(messages[1]["content"])["college"]))
        return httpx.Response(503)

    result = (await send_evaluation(monkeypatch, gateway, retrieval_fault="missing_core")).json()
    assert result["judge_verdicts"][0] == {
        "college": "hiring",
        "status": "failed",
        "verdict": None,
        "error_code": "invalid_judge_retrieval",
    }
    assert all(slot["status"] == "ready" for slot in result["judge_verdicts"][1:])


@pytest.mark.anyio
async def test_opponent_only_dialogue_does_not_invent_a_comparison_or_user_action(monkeypatch):
    configure(monkeypatch)
    body = evaluate_body()
    body["messages"] = [{"text": "Здравствуйте.", "is_ai": True}]
    assessment = {
        "kind": "not_assessable",
        "summary": "Есть только приветствие оппонента.",
        "agreed_terms": [],
        "open_points": [],
        "next_step": None,
        "evidence": [{"message_index": 0, "is_ai": True, "quote": "Здравствуйте."}],
    }

    def gateway(req):
        system = json.loads(req.content)["messages"][0]["content"]
        if "[V2_EVALUATE_OUTCOME_VERIFY]" in system:
            return reply_json({"decision": "accept"})
        assert "[V2_EVALUATE_OUTCOME]" in system
        return reply_json(assessment)

    def retrieval(req):
        raise AssertionError("A one-sided greeting does not require judge retrieval")

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as model,
        httpx.AsyncClient(transport=httpx.MockTransport(retrieval)) as external,
    ):
        app = create_configured_app(model, external)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            result = (await client.post("/v2/evaluate", json=body, headers=HEADERS)).json()
    assert result["outcome"]["assessment"] == assessment
    assert all(slot["error_code"] == "insufficient_evidence" for slot in result["judge_verdicts"])
    assert result["trainer_feedback"] == {
        "status": "failed",
        "feedback": None,
        "error_code": "insufficient_evidence",
    }


@pytest.mark.anyio
async def test_evaluate_is_absent_when_v2_is_disabled():
    from arena_ai.app import create_app

    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.post("/v2/evaluate", json=evaluate_body())).status_code == 404
        assert "/v2/evaluate" not in (await client.get("/openapi.json")).json()["paths"]


@pytest.mark.anyio
@pytest.mark.parametrize("scope", ["full", "trainer"])
@pytest.mark.skipif(
    os.environ.get("ARENA_RUN_LIVE_V2") != "1", reason="Explicit live opt-in required"
)
async def test_live_evaluate_short_dialogue_returns_verified_assessment(monkeypatch, scope):
    url, model_id = os.environ["ARENA_QWEN_CHAT_URL"], os.environ["ARENA_QWEN_MODEL"]
    configure(monkeypatch)
    monkeypatch.setenv("ARENA_QWEN_CHAT_URL", url)
    monkeypatch.setenv("ARENA_QWEN_MODEL", model_id)
    monkeypatch.setenv("ARENA_RETRIEVAL_TIMEOUT_SECONDS", "2")
    async with httpx.AsyncClient(timeout=60) as real:

        async def gateway(req):
            system = json.loads(req.content)["messages"][0]["content"]
            if scope == "full" or "[V2_EVALUATE_TRAINER" in system:
                return await real.send(req)
            return httpx.Response(503)

        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(gateway), timeout=60) as model,
            httpx.AsyncClient(
                transport=httpx.MockTransport(
                    RetrievalGateway() if scope == "full" else lambda req: httpx.Response(503)
                )
            ) as retrieval,
        ):
            app = create_configured_app(model, retrieval)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post("/v2/evaluate", json=evaluate_body(), headers=HEADERS)
    assert response.status_code == 200
    result = response.json()
    # Only synthetic public dialogue is used; do not print gateway headers or credentials.
    diagnostic = {
        "outcome": {key: result["outcome"][key] for key in ("status", "error_code")},
        "judges": [
            {key: slot[key] for key in ("college", "status", "error_code")}
            for slot in result["judge_verdicts"]
        ],
        "trainer": {key: result["trainer_feedback"][key] for key in ("status", "error_code")},
    }
    if scope == "full":
        assert result["outcome"]["status"] == "ready", diagnostic
        assert result["outcome"]["assessment"]["kind"] == "agreement", diagnostic
        assert all(slot["status"] == "ready" for slot in result["judge_verdicts"]), diagnostic
    assert result["trainer_feedback"]["status"] == "ready", result["trainer_feedback"]
    assert result["trainer_feedback"]["feedback"]["goal_assessment"]["status"] == "achieved"
