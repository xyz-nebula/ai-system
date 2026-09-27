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


def verifier_reply(system, decision="accept"):
    if "[V2_EVALUATE_COMMENT_GROUNDING]" in system:
        return {"counterexamples": [], "decision": decision}
    if "[V2_EVALUATE_JUDGE_VERIFY]" in system:
        return {
            "unsupported_claims": [],
            "facts": decision,
            "criterion_link": decision,
            "comparison": decision,
        }
    return {"decision": decision}


@pytest.mark.anyio
@pytest.mark.parametrize(
    "grounding",
    [
        {"counterexamples": [], "decision": "uncertain"},
        {"counterexamples": [], "decision": "reject"},
        {"counterexamples": ["Согласие не доказывает исполнение."], "decision": "accept"},
    ],
)
async def test_unconfirmed_comment_is_not_published_even_when_college_check_accepts(
    monkeypatch, grounding
):
    def gateway(req):
        messages = json.loads(req.content)["messages"]
        system = messages[0]["content"]
        context = json.loads(messages[1]["content"])
        if "[V2_EVALUATE_COMMENT_GROUNDING]" in system:
            assert set(context) == {"dialogue", "observation", "effect", "comparison"}
            return reply_json(grounding)
        if "[V2_EVALUATE_JUDGE_VERIFY]" in system:
            return reply_json(verifier_reply(system))
        if "[V2_EVALUATE_JUDGE]" in system:
            return reply_json(judge_example(context["college"]))
        return httpx.Response(503)

    result = (await send_evaluation(monkeypatch, gateway)).json()
    assert all(
        slot["status"] == "failed" and slot["verdict"] is None for slot in result["judge_verdicts"]
    )
    assert all(slot["error_code"] == "invalid_judge_output" for slot in result["judge_verdicts"])


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["unavailable", "format"])
async def test_comment_check_failure_does_not_discard_other_assessments(monkeypatch, fault):
    replies = iter(
        [
            httpx.Response(503) if fault == "unavailable" else reply_json({"decision": "accept"}),
            reply_json({"counterexamples": [], "decision": "accept"}),
            reply_json({"counterexamples": [], "decision": "accept"}),
        ]
    )

    def gateway(req):
        messages = json.loads(req.content)["messages"]
        system = messages[0]["content"]
        context = json.loads(messages[1]["content"])
        if "[V2_EVALUATE_COMMENT_GROUNDING]" in system:
            return next(replies)
        if "VERIFY]" in system:
            return reply_json(verifier_reply(system))
        if "[V2_EVALUATE_JUDGE]" in system:
            return reply_json(judge_example(context["college"]))
        if "[V2_EVALUATE_TRAINER]" in system:
            return reply_json(trainer_example())
        return reply_json(outcome_example())

    result = (await send_evaluation(monkeypatch, gateway)).json()
    assert result["judge_verdicts"][0] == {
        "college": "hiring",
        "status": "failed",
        "verdict": None,
        "error_code": "judge_unavailable" if fault == "unavailable" else "invalid_judge_output",
    }
    assert all(slot["status"] == "ready" for slot in result["judge_verdicts"][1:])
    assert result["outcome"]["status"] == result["trainer_feedback"]["status"] == "ready"
    validate_contract("EvaluationResponse", result)


@pytest.mark.anyio
@pytest.mark.parametrize("effect_index", [1, 999])
async def test_effect_support_is_validated_without_changing_public_verdict(
    monkeypatch, effect_index
):
    def gateway(req):
        messages = json.loads(req.content)["messages"]
        system = messages[0]["content"]
        context = json.loads(messages[1]["content"])
        if "[V2_EVALUATE_COMMENT_GROUNDING]" in system:
            return reply_json(verifier_reply(system))
        if "[V2_EVALUATE_JUDGE_VERIFY]" in system:
            return reply_json(verifier_reply(system))
        if "[V2_EVALUATE_JUDGE]" in system:
            draft = judge_example(context["college"])
            draft["effect_evidence"] = {
                "message_index": effect_index,
                "is_ai": True,
                "quote": "Согласен на 100 рублей и поставку в пятницу.",
            }
            return reply_json(draft)
        return httpx.Response(503)

    response = await send_evaluation(monkeypatch, gateway)
    validate_contract("EvaluationResponse", response.json())
    for slot in response.json()["judge_verdicts"]:
        assert slot["status"] == ("ready" if effect_index == 1 else "failed")
        if effect_index == 1:
            assert "effect_evidence" not in slot["verdict"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "failed_gate", [None, "facts", "criterion_link", "comparison", "unsupported_claims"]
)
async def test_judge_requires_every_independent_check_to_accept(monkeypatch, failed_gate):
    def gateway(req):
        messages = json.loads(req.content)["messages"]
        system = messages[0]["content"]
        context = json.loads(messages[1]["content"])
        if "[V2_EVALUATE_COMMENT_GROUNDING]" in system:
            return reply_json(verifier_reply(system))
        if "[V2_EVALUATE_JUDGE_VERIFY]" in system:
            checks = verifier_reply(system)
            if failed_gate == "unsupported_claims":
                checks[failed_gate] = [context["verdict"]["comparison"]]
            elif failed_gate:
                checks[failed_gate] = "uncertain"
            return reply_json(checks)
        if "[V2_EVALUATE_JUDGE]" in system:
            return reply_json(judge_example(context["college"]))
        return httpx.Response(503)

    response = await send_evaluation(monkeypatch, gateway)
    for slot in response.json()["judge_verdicts"]:
        assert slot["status"] == ("failed" if failed_gate else "ready")
        if failed_gate:
            assert slot["verdict"] is None


@pytest.mark.anyio
@pytest.mark.parametrize("proof_case", ["player", "opponent", "array"])
async def test_plan_action_uses_user_evidence_while_goal_can_use_both_sides(
    monkeypatch, proof_case
):
    candidate = trainer_example()
    if proof_case == "opponent":
        candidate["plan_vs_reality"]["items"][0].update(
            evidence=outcome_example()["evidence"][1],
            observation="Поставщик подтвердил условия из предложения покупателя.",
        )
    elif proof_case == "array":
        candidate["plan_vs_reality"]["items"][0]["evidence"] = [outcome_example()["evidence"][0]]

    def gateway(req):
        system = json.loads(req.content)["messages"][0]["content"]
        if "[V2_EVALUATE_TRAINER_VERIFY]" in system:
            return reply_json({"decision": "accept"})
        if "[V2_EVALUATE_TRAINER]" in system:
            return reply_json(candidate)
        return httpx.Response(503)

    result = (await send_evaluation(monkeypatch, gateway)).json()["trainer_feedback"]
    assert result["status"] == ("ready" if proof_case == "player" else "failed")
    if proof_case != "player":
        assert result["feedback"] is None
        assert result["error_code"] == "invalid_trainer_output"
    else:
        assert result["feedback"]["goal_assessment"]["evidence"] == outcome_example()["evidence"]


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
        if "VERIFY]" in system or "[V2_EVALUATE_COMMENT_GROUNDING]" in system:
            reply = verifier_reply(system)
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
        if "[V2_EVALUATE_COMMENT_GROUNDING]" in system:
            return reply_json(verifier_reply(system))
        targeted = f"[V2_EVALUATE_{stage}" in system
        if stage == "JUDGE":
            college = context.get("college", context.get("verdict", {}).get("college"))
            targeted = targeted and college == "hiring"
        if "VERIFY]" in system:
            if targeted and fault == "unavailable":
                return httpx.Response(503, text="private-gateway-error")
            return reply_json(
                verifier_reply(
                    system, fault if targeted and fault in ("reject", "uncertain") else "accept"
                )
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
        if "VERIFY]" in system or "[V2_EVALUATE_COMMENT_GROUNDING]" in system:
            return reply_json(verifier_reply(system))
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
        if "VERIFY]" in system or "[V2_EVALUATE_COMMENT_GROUNDING]" in system:
            return reply_json(verifier_reply(system))
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
@pytest.mark.parametrize("scope", ["full", "trainer", "trainer_without_preparation"])
@pytest.mark.skipif(
    os.environ.get("ARENA_RUN_LIVE_V2") != "1", reason="Explicit live opt-in required"
)
async def test_live_evaluate_short_dialogue_returns_verified_assessment(monkeypatch, scope):
    url, model_id = os.environ["ARENA_QWEN_CHAT_URL"], os.environ["ARENA_QWEN_MODEL"]
    configure(monkeypatch)
    monkeypatch.setenv("ARENA_QWEN_CHAT_URL", url)
    monkeypatch.setenv("ARENA_QWEN_MODEL", model_id)
    monkeypatch.setenv("ARENA_RETRIEVAL_TIMEOUT_SECONDS", "2")
    body = evaluate_body()
    if scope == "trainer_without_preparation":
        body["preparations"] = None
    trainer_replies = []
    async with httpx.AsyncClient(timeout=60) as real:

        async def gateway(req):
            system = json.loads(req.content)["messages"][0]["content"]
            if scope == "full" or "[V2_EVALUATE_TRAINER" in system:
                response = await real.send(req)
                if "[V2_EVALUATE_TRAINER" in system and response.status_code == 200:
                    trainer_replies.append(
                        {
                            "stage": "verify" if "VERIFY]" in system else "generate",
                            "content": response.json()["choices"][0]["message"]["content"],
                        }
                    )
                return response
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
                response = await client.post("/v2/evaluate", json=body, headers=HEADERS)
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
        assert all(slot["status"] == "ready" for slot in result["judge_verdicts"]), json.dumps(
            {**diagnostic, "trainer_replies": trainer_replies}, ensure_ascii=False, indent=2
        )
    assert result["trainer_feedback"]["status"] == "ready", json.dumps(
        {"slot": result["trainer_feedback"], "replies": trainer_replies},
        ensure_ascii=False,
        indent=2,
    )
    feedback = result["trainer_feedback"]["feedback"]
    if scope == "trainer_without_preparation":
        assert feedback["plan_vs_reality"] is None
        assert feedback["goal_assessment"]["goal_text"] is None
        assert feedback["goal_assessment"]["status"] == "not_assessable"
    else:
        assert feedback["goal_assessment"]["status"] == "achieved"
        assert feedback["plan_vs_reality"] is not None
        for item in feedback["plan_vs_reality"]["items"]:
            if item["evidence"] is not None:
                assert item["evidence"]["is_ai"] is False


def grounded_hiring_example():
    return {
        "college": "hiring",
        "choice": "opponent",
        "decisive_criterion": "Надёжность",
        "evidence": outcome_example()["evidence"][1],
        "observation": "Поставщик явно подтвердил цену и срок поставки.",
        "effect": "Обсуждение перешло от предложения к явному согласию.",
        "comparison": "Покупатель предложил условия, поставщик прямо подтвердил свою сторону договорённости.",
    }


def unsupported_hiring_example():
    return {
        "college": "hiring",
        "choice": "player",
        "decisive_criterion": "Надёжность",
        "evidence": outcome_example()["evidence"][0],
        "observation": "Инициатива по определению условий сделки принадлежит игроку, а не оппоненту.",
        "effect": "Игрок задаёт рамки взаимодействия, демонстрируя готовность брать на себя ответственность за результат.",
        "comparison": "Оппонент лишь пассивно согласился на предложенные условия, не проявив самостоятельности в формировании договорённости.",
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    "candidate",
    [
        "generated",
        "grounded",
        "unsupported",
        "bounded",
        "generated_bounded",
        "generated_deadline",
        "unsupported_bounded",
        "unsupported_with_effect",
        "unsupported_after_extraction",
        "deadline_bounded",
        "deadline_potential",
        "unsupported_deadline",
        "unsupported_deadline_risk",
    ],
)
@pytest.mark.skipif(
    os.environ.get("ARENA_RUN_LIVE_V2") != "1", reason="Explicit live opt-in required"
)
async def test_live_evaluate_hiring_returns_a_grounded_verdict(monkeypatch, candidate):
    url, model_id = os.environ["ARENA_QWEN_CHAT_URL"], os.environ["ARENA_QWEN_MODEL"]
    configure(monkeypatch)
    monkeypatch.setenv("ARENA_QWEN_CHAT_URL", url)
    monkeypatch.setenv("ARENA_QWEN_MODEL", model_id)
    monkeypatch.setenv("ARENA_RETRIEVAL_TIMEOUT_SECONDS", "2")
    body = evaluate_body()
    bounded = {
        "college": "hiring",
        "choice": "opponent",
        "decisive_criterion": "Надёжность",
        "evidence": {
            "message_index": 1,
            "is_ai": True,
            "quote": "Пятницу гарантировать не могу. Подтверждённый срок — понедельник.",
        },
        "observation": "Поставщик отделил желаемый срок от подтверждённого и отказался гарантировать пятницу.",
        "effect": "Покупатель принял понедельник вместо первоначально требуемой пятницы.",
        "comparison": "Покупатель сначала запросил неподтверждённый срок, затем принял понедельник; поставщик сразу ограничил обещание подтверждённым сроком. По надёжности предпочту управление поставщика.",
    }
    captured_bounded = {
        **bounded,
        "observation": "Поставщик сразу обозначил реальные границы, отказавшись от фиктивного обещания.",
        "effect": "Это создало прозрачную картину реальности, где сроки привязаны к фактическим возможностям.",
        "comparison": "Покупатель предложил фиктивную дату, игнорируя риски, тогда как Поставщик выбрал честность, что снижает вероятность срыва обязательств.",
    }
    captured_with_effect = {
        **bounded,
        "observation": "Поставщик отказался от неопределённого обещания, предложив конкретную дату с оговоркой о подтверждении.",
        "effect_evidence": {
            "message_index": 2,
            "is_ai": False,
            "quote": "Тогда принимаю поставку в понедельник.",
        },
        "effect": "Покупатель принял предложение поставщика, что свидетельствует о его честности и прозрачности.",
        "comparison": "Покупатель сразу предложил фиксированную дату без оговорок, что создало давление на поставщика. Поставщик честно признал ограничения, не вводя в заблуждение, что демонстрирует профессиональную надёжность.",
    }
    captured_after_extraction = {
        **bounded,
        "evidence": {
            "message_index": 0,
            "is_ai": False,
            "quote": "Обещайте пятницу, даже если срок пока не подтверждён.",
        },
        "effect_evidence": bounded["evidence"],
        "observation": "Игрок просит дать фиксированную дату без подтверждения фактов.",
        "effect": "Оппонент отказывается от фиктивного обещания, называя реальный срок.",
        "comparison": "Игрок пытается получить фиксацию без фактов, игнорируя риски. Оппонент честно называет реальный срок, не давая ложных обещаний. В управлении важнее честность, чем красивая дата.",
    }
    if candidate in (
        "bounded",
        "generated_bounded",
        "unsupported_bounded",
        "unsupported_with_effect",
        "unsupported_after_extraction",
    ):
        body["messages"] = [
            {"text": "Обещайте пятницу, даже если срок пока не подтверждён.", "is_ai": False},
            {"text": bounded["evidence"]["quote"], "is_ai": True},
            {"text": "Тогда принимаю поставку в понедельник.", "is_ai": False},
            {"text": "Согласен, фиксируем понедельник.", "is_ai": True},
        ]
    deadline = {
        "college": "hiring",
        "choice": "opponent",
        "decisive_criterion": "Надёжность",
        "evidence": {
            "message_index": 1,
            "is_ai": True,
            "quote": "Готов продлить до среды, если пришлёте черновик во вторник.",
        },
        "effect_evidence": {
            "message_index": 2,
            "is_ai": False,
            "quote": "Согласен, пришлю черновик во вторник.",
        },
        "observation": "Преподаватель связал перенос срока с обязательством прислать черновик.",
        "effect": "Студент согласился прислать черновик во вторник.",
        "comparison": "Студент попросил перенос срока, преподаватель назвал условие переноса. Я предпочёл бы работать под управлением преподавателя, потому что он явно сформулировал обязательство в обмен на уступку.",
    }
    if candidate in (
        "deadline_bounded",
        "deadline_potential",
        "unsupported_deadline",
        "generated_deadline",
        "unsupported_deadline_risk",
    ):
        body.update(
            role="Студент",
            opponent_role="Преподаватель",
            case_description="Обсуждение переноса срока сдачи учебной работы.",
            preparations=None,
            messages=[
                {"text": "Прошу продлить срок до среды.", "is_ai": False},
                {"text": deadline["evidence"]["quote"], "is_ai": True},
                {"text": deadline["effect_evidence"]["quote"], "is_ai": False},
                {
                    "text": "Договорились: черновик во вторник, итоговая работа в среду.",
                    "is_ai": True,
                },
            ],
        )
    unsupported_deadline = {
        **deadline,
        "effect": "Студент прислал черновик во вторник и заслужил доверие преподавателя.",
    }
    deadline_potential = {
        **deadline,
        "effect": "Студент принял условие о черновике. Оно потенциально позволяет раньше заметить отставание; это возможный эффект, не наблюдавшееся событие.",
    }
    unsupported_deadline_risk = {
        **deadline,
        "observation": "Оппонент сразу предложил конкретный промежуточный контрольный пункт (черновик во вторник), а не просто согласился на финальный срок.",
        "effect": "Игрок подтвердил готовность выполнить промежуточное условие, что снижает риск срыва финального дедлайна.",
        "comparison": "Я предпочёл бы оппонента, потому что он сразу предложил механизм контроля (черновик), а не просто согласился на результат, что снижает риск срыва сроков.",
    }
    public_replies = []
    grounding_calls = 0
    async with httpx.AsyncClient(timeout=60) as real:

        async def gateway(req):
            nonlocal grounding_calls
            messages = json.loads(req.content)["messages"]
            system = messages[0]["content"]
            context = json.loads(messages[1]["content"])
            college = context.get("college", context.get("verdict", {}).get("college"))
            grounding = "[V2_EVALUATE_COMMENT_GROUNDING]" in system
            if grounding:
                grounding_calls += 1
            if grounding and grounding_calls > 1:
                return httpx.Response(503)
            if not grounding and ("[V2_EVALUATE_JUDGE" not in system or college != "hiring"):
                return httpx.Response(503)
            if not grounding and "VERIFY]" not in system and not candidate.startswith("generated"):
                return reply_json(
                    unsupported_deadline_risk
                    if candidate == "unsupported_deadline_risk"
                    else unsupported_deadline
                    if candidate == "unsupported_deadline"
                    else deadline
                    if candidate == "deadline_bounded"
                    else deadline_potential
                    if candidate == "deadline_potential"
                    else captured_after_extraction
                    if candidate == "unsupported_after_extraction"
                    else captured_with_effect
                    if candidate == "unsupported_with_effect"
                    else captured_bounded
                    if candidate == "unsupported_bounded"
                    else bounded
                    if candidate == "bounded"
                    else grounded_hiring_example()
                    if candidate == "grounded"
                    else unsupported_hiring_example()
                )
            response = await real.send(req)
            if response.status_code == 200:
                public_replies.append(
                    {
                        "stage": "grounding"
                        if grounding
                        else "verify"
                        if "VERIFY]" in system
                        else "generate",
                        "content": response.json()["choices"][0]["message"]["content"],
                    }
                )
            else:
                public_replies.append(
                    {
                        "stage": "grounding"
                        if grounding
                        else "verify"
                        if "VERIFY]" in system
                        else "generate",
                        "http_status": response.status_code,
                    }
                )
            return response

        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(gateway), timeout=60) as model,
            httpx.AsyncClient(transport=httpx.MockTransport(RetrievalGateway())) as retrieval,
        ):
            app = create_configured_app(model, retrieval)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post("/v2/evaluate", json=body, headers=HEADERS)
    assert response.status_code == 200
    slot = response.json()["judge_verdicts"][0]
    if candidate.startswith("unsupported"):
        assert slot == {
            "college": "hiring",
            "status": "failed",
            "verdict": None,
            "error_code": "invalid_judge_output",
        }, public_replies
        grounding = [reply for reply in public_replies if reply["stage"] == "grounding"]
        assert len(grounding) == 1 and "content" in grounding[0], public_replies
        check = json.loads(
            grounding[0]["content"].strip().removeprefix("```json").removesuffix("```").strip()
        )
        assert check["counterexamples"] or check["decision"] != "accept", public_replies
    else:
        assert slot["status"] == "ready", json.dumps(
            {"slot": slot, "public_replies": public_replies}, ensure_ascii=False, indent=2
        )
