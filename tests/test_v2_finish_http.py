import json
import os
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft202012Validator
from test_v2_http import configure

from arena_ai.app import create_configured_app


def finish_body():
    return json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs/api/v2/examples/finish-with-preparation.request.json"
        ).read_bytes()
    )


def unavailable_gateway(request):
    return httpx.Response(503, json={"error": "unavailable"})


@pytest.mark.anyio
async def test_finish_openapi_describes_complete_response(monkeypatch):
    configure(monkeypatch)
    async with httpx.AsyncClient(transport=httpx.MockTransport(unavailable_gateway)) as model:
        app = create_configured_app(model)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            schema = (await client.get("/openapi.json")).json()
            actual = await client.post(
                "/v2/finish",
                json=finish_body(),
                headers={
                    "Authorization": "Bearer test-token",
                    "X-Arena-Contract-Version": "2.0.0-rc.1",
                },
            )
    response = schema["paths"]["/v2/finish"]["post"]["responses"]["200"]
    assert response["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/V2FinishResponse"
    }
    definitions = schema["components"]["schemas"]
    finish = definitions["V2FinishResponse"]
    assert set(finish["required"]) == {
        "session_id",
        "outcome",
        "judge_verdicts",
        "trainer_feedback",
        "contract_version",
    }
    assert finish["additionalProperties"] is False
    slots = finish["properties"]["judge_verdicts"]
    assert slots["minItems"] == slots["maxItems"] == 3
    assert definitions["V2TrainerFeedback"]["properties"]["next_try"]["minItems"] == 2
    assert definitions["V2Outcome"]["properties"]["kind"]["enum"] == [
        "agreement",
        "partial_agreement",
        "deferred",
        "no_agreement",
    ]
    validator = Draft202012Validator(
        {"$ref": "#/components/schemas/V2FinishResponse", "components": schema["components"]}
    )
    examples = Path(__file__).resolve().parents[1] / "docs/api/v2/examples"
    assert actual.status_code == 200
    validator.validate(actual.json())
    canonical = json.loads((examples.parent / "contract.schema.json").read_bytes())
    Draft202012Validator({"$ref": "#/$defs/FinishResponse", "$defs": canonical["$defs"]}).validate(
        actual.json()
    )
    for name in (
        "empty-finish.response.json",
        "finish-with-preparation.response.json",
        "finish-partial.response.json",
    ):
        validator.validate(json.loads((examples / name).read_bytes()))


@pytest.mark.anyio
@pytest.mark.parametrize("mutation", ["extra", "slot_count", "trainer_steps", "criterion"])
async def test_finish_published_schema_rejects_incompatible_responses(monkeypatch, mutation):
    configure(monkeypatch)
    async with httpx.AsyncClient(transport=httpx.MockTransport(unavailable_gateway)) as model:
        app = create_configured_app(model)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            schema = (await client.get("/openapi.json")).json()
    example = (
        Path(__file__).resolve().parents[1]
        / "docs/api/v2/examples/finish-with-preparation.response.json"
    )
    payload = json.loads(example.read_bytes())
    if mutation == "extra":
        payload["private_context"] = "Unexpected field"
    elif mutation == "slot_count":
        payload["judge_verdicts"] = payload["judge_verdicts"][:2]
    elif mutation == "trainer_steps":
        payload["trainer_feedback"]["feedback"]["next_try"] = ["Один шаг"]
    else:
        payload["judge_verdicts"][0]["verdict"]["decisive_criterion"] = "Выдуманный критерий"
    validator = Draft202012Validator(
        {"$ref": "#/components/schemas/V2FinishResponse", "components": schema["components"]}
    )
    assert not validator.is_valid(payload)


@pytest.mark.anyio
async def test_finish_returns_grounded_cost_without_replacing_factual_outcome(monkeypatch):
    configure(monkeypatch)
    body = finish_body()
    entry = body["snapshot"]["transcript"][0]
    entry["text"] = "Обязуюсь предоставить отчёт завтра."
    evidence = {key: entry[key] for key in ("message_id", "turn_id", "speaker", "elapsed_ms")}
    evidence["quote"] = entry["text"]
    analysis = {
        "concessions": [],
        "costs": [
            {"role_id": "manager", "description": "Принято обязательство", "evidence": [evidence]}
        ],
        "consequences": [],
        "evidence": [evidence],
    }

    def gateway(request):
        messages = json.loads(request.content)["messages"]
        context = json.loads(messages[1]["content"])
        assert "preparation" not in context
        assert "opponent_brief" not in context
        if "[V2_OUTCOME_VERIFY]" in messages[0]["content"]:
            return httpx.Response(
                200, json={"choices": [{"message": {"content": '{"decision":"accept"}'}}]}
            )
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(analysis)}}]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as model:
        app = create_configured_app(model)
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
    outcome = response.json()["outcome"]
    assert outcome["kind"] == "no_agreement"
    assert outcome["agreement"] is None
    assert outcome["analysis_status"] == "ready"
    assert outcome["costs"] == analysis["costs"]


@pytest.mark.anyio
@pytest.mark.parametrize("decision", ["reject", "uncertain", "unavailable"])
async def test_true_quote_does_not_authorize_an_unsupported_cost(monkeypatch, decision):
    configure(monkeypatch)
    body = finish_body()
    entry = body["snapshot"]["transcript"][0]
    evidence = {key: entry[key] for key in ("message_id", "turn_id", "speaker", "elapsed_ms")}
    evidence["quote"] = entry["text"]
    analysis = {
        "concessions": [],
        "costs": [{"role_id": "manager", "description": "Принял KPI 130%", "evidence": [evidence]}],
        "consequences": [],
        "evidence": [evidence],
    }

    def gateway(request):
        messages = json.loads(request.content)["messages"]
        if "[V2_OUTCOME_VERIFY]" in messages[0]["content"]:
            context = json.loads(messages[1]["content"])
            assert context["analysis"]["costs"][0]["description"] == "Принял KPI 130%"
            if decision == "unavailable":
                return httpx.Response(503)
            reply = {"decision": decision}
        else:
            reply = analysis
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(reply)}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as model:
        app = create_configured_app(model)
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
    outcome = response.json()["outcome"]
    assert outcome["kind"] == "no_agreement"
    assert outcome["analysis_error_code"] == (
        "outcome_analysis_unavailable" if decision == "unavailable" else "invalid_outcome_analysis"
    )
    assert outcome["costs"] == []


@pytest.mark.anyio
@pytest.mark.parametrize("mutation", ["quote", "message_id", "speaker", "elapsed_ms", "role_id"])
async def test_finish_discards_analysis_with_false_evidence(monkeypatch, mutation):
    configure(monkeypatch)
    body = finish_body()
    entry = body["snapshot"]["transcript"][0]
    proof = {key: entry[key] for key in ("message_id", "turn_id", "speaker", "elapsed_ms")}
    proof["quote"] = entry["text"]
    action = {"role_id": "manager", "description": "Подтверждённое действие", "evidence": [proof]}
    if mutation == "role_id":
        action["role_id"] = "director"
    else:
        proof[mutation] = {
            "quote": "Я согласен на всё",
            "message_id": "nonexistent",
            "speaker": "opponent",
            "elapsed_ms": 999,
        }[mutation]
    analysis = {"concessions": [], "costs": [action], "consequences": [], "evidence": []}

    def gateway(request):
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(analysis)}}]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as model:
        app = create_configured_app(model)
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
    outcome = response.json()["outcome"]
    assert outcome["kind"] == "no_agreement"
    assert outcome["analysis_error_code"] == "invalid_outcome_analysis"
    assert outcome["costs"] == []


@pytest.mark.anyio
@pytest.mark.skipif(
    os.environ.get("ARENA_RUN_LIVE_V2") != "1", reason="Explicit live opt-in required"
)
async def test_live_finish_analyzes_public_dialogue_through_http(monkeypatch):
    chat_url = os.environ["ARENA_QWEN_CHAT_URL"]
    model_id = os.environ["ARENA_QWEN_MODEL"]
    configure(monkeypatch)
    monkeypatch.setenv("ARENA_QWEN_CHAT_URL", chat_url)
    monkeypatch.setenv("ARENA_QWEN_MODEL", model_id)
    async with (
        httpx.AsyncClient(timeout=60) as model,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_configured_app(model)), base_url="http://test"
        ) as client,
    ):
        response = await client.post(
            "/v2/finish",
            json=finish_body(),
            headers={
                "Authorization": "Bearer test-token",
                "X-Arena-Contract-Version": "2.0.0-rc.1",
            },
        )
    assert response.status_code == 200
    outcome = response.json()["outcome"]
    assert outcome["kind"] == "no_agreement"
    assert outcome["agreement"] is None
    assert outcome["analysis_status"] == "ready", outcome["analysis_error_code"]
    # In this example the player only asks about conditions and accepts no obligations.
    assert outcome["costs"] == []
    assert outcome["concessions"] == []


@pytest.mark.anyio
@pytest.mark.skipif(
    os.environ.get("ARENA_RUN_LIVE_V2") != "1", reason="Explicit live opt-in required"
)
async def test_live_verifier_rejects_cost_supported_only_by_a_question(monkeypatch):
    chat_url = os.environ["ARENA_QWEN_CHAT_URL"]
    model_id = os.environ["ARENA_QWEN_MODEL"]
    configure(monkeypatch)
    monkeypatch.setenv("ARENA_QWEN_CHAT_URL", chat_url)
    monkeypatch.setenv("ARENA_QWEN_MODEL", model_id)
    body = finish_body()
    entry = body["snapshot"]["transcript"][0]
    proof = {key: entry[key] for key in ("message_id", "turn_id", "speaker", "elapsed_ms")}
    proof["quote"] = entry["text"]
    candidate = {
        "concessions": [],
        "costs": [{"role_id": "manager", "description": "Принял KPI 130%", "evidence": [proof]}],
        "consequences": [],
        "evidence": [],
    }
    async with httpx.AsyncClient(timeout=60) as real_gateway:

        async def gateway(request):
            messages = json.loads(request.content)["messages"]
            if "[V2_OUTCOME_ANALYSIS]" in messages[0]["content"]:
                return httpx.Response(
                    200, json={"choices": [{"message": {"content": json.dumps(candidate)}}]}
                )
            response = await real_gateway.send(request)
            assert response.status_code == 200, response.status_code
            return response

        async with httpx.AsyncClient(transport=httpx.MockTransport(gateway), timeout=60) as model:
            app = create_configured_app(model)
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
    outcome = response.json()["outcome"]
    assert outcome["kind"] == "no_agreement"
    assert outcome["analysis_status"] == "failed"
    assert outcome["analysis_error_code"] == "invalid_outcome_analysis"
    assert outcome["costs"] == []


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_empty_frozen_round_has_no_invented_agreement_or_analytics(monkeypatch):
    configure(monkeypatch)
    examples = Path(__file__).resolve().parents[1] / "docs/api/v2/examples"

    def gateway(request):
        raise AssertionError("An empty conversation must not be sent to a model")

    async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as model:
        app = create_configured_app(model)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v2/finish",
                content=(examples / "empty-finish.request.json").read_bytes(),
                headers={
                    "Authorization": "Bearer test-token",
                    "X-Arena-Contract-Version": "2.0.0-rc.1",
                },
            )
    assert response.status_code == 200
    assert response.json() == json.loads((examples / "empty-finish.response.json").read_bytes())


@pytest.mark.anyio
async def test_nonempty_finish_does_not_claim_analysis_is_ready(monkeypatch):
    configure(monkeypatch)
    examples = Path(__file__).resolve().parents[1] / "docs/api/v2/examples"
    async with httpx.AsyncClient(transport=httpx.MockTransport(unavailable_gateway)) as model:
        app = create_configured_app(model)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v2/finish",
                content=(examples / "finish-with-preparation.request.json").read_bytes(),
                headers={
                    "Authorization": "Bearer test-token",
                    "X-Arena-Contract-Version": "2.0.0-rc.1",
                },
            )
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"]["kind"] == "no_agreement"
    assert body["outcome"]["analysis_status"] == "failed"
    assert body["outcome"]["analysis_error_code"] == "outcome_analysis_unavailable"
    assert [slot["college"] for slot in body["judge_verdicts"]] == [
        "hiring",
        "negotiation",
        "ownership",
    ]
    assert all(slot["verdict"] is None for slot in body["judge_verdicts"])
    assert body["trainer_feedback"]["feedback"] is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("change", "status", "code"),
    [
        ("token", 401, "unauthorized"),
        ("version", 409, "contract_version_mismatch"),
        ("open", 409, "round_not_closed"),
        ("blank", 422, "invalid_request"),
    ],
)
async def test_finish_rejects_invalid_boundary_requests(monkeypatch, change, status, code):
    configure(monkeypatch)
    examples = Path(__file__).resolve().parents[1] / "docs/api/v2/examples"
    body = json.loads((examples / "empty-finish.request.json").read_bytes())
    headers = {
        "Authorization": "Bearer test-token",
        "X-Arena-Contract-Version": "2.0.0-rc.1",
    }
    if change == "token":
        headers["Authorization"] = "Bearer wrong"
    elif change == "version":
        headers["X-Arena-Contract-Version"] = "1"
    elif change == "open":
        body["snapshot"]["round"].update(status="open", finished_at=None, end_reason=None)
    else:
        body["preparation"] = "   "
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(unavailable_gateway)) as model,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_configured_app(model)), base_url="http://test"
        ) as client,
    ):
        response = await client.post("/v2/finish", json=body, headers=headers)
    assert response.status_code == status
    assert response.json() == {
        "code": code,
        "message": {
            "unauthorized": "Unauthorized",
            "contract_version_mismatch": "Unsupported contract version",
            "round_not_closed": "Round is not frozen",
            "invalid_request": "Invalid finish request",
        }[code],
        "retryable": False,
    }


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["agreement", "partial_agreement", "deferred"])
async def test_finish_preserves_confirmed_result_instead_of_rejudging_it(monkeypatch, kind):
    configure(monkeypatch)
    examples = Path(__file__).resolve().parents[1] / "docs/api/v2/examples"
    body = json.loads((examples / "finish-with-preparation.request.json").read_bytes())
    state = body["snapshot"]["state"]
    if kind == "agreement":
        state.update(
            stage="agreed", agreement=body["case"]["opponent_strategy"]["steps"][0]["terms"]
        )
    elif kind == "partial_agreement":
        state.update(
            stage=kind,
            decision={
                "kind": kind,
                "commitments": [{"role_id": "manager", "text": "Предоставить отчёт завтра"}],
                "open_points": ["Условия повышения"],
            },
        )
    else:
        state.update(
            stage=kind,
            decision={"kind": kind, "reason": "Нужен отчёт", "next_step": "Обсудить отчёт завтра"},
        )
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(unavailable_gateway)) as model,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_configured_app(model)), base_url="http://test"
        ) as client,
    ):
        response = await client.post(
            "/v2/finish",
            json=body,
            headers={
                "Authorization": "Bearer test-token",
                "X-Arena-Contract-Version": "2.0.0-rc.1",
            },
        )
    assert response.status_code == 200
    outcome = response.json()["outcome"]
    assert outcome["kind"] == kind
    if kind == "agreement":
        assert outcome["agreement"] == state["agreement"]
    elif kind == "partial_agreement":
        assert outcome["open_points"] == ["Условия повышения"]
        assert outcome["commitments"] == [
            {"role_id": "manager", "text": "Предоставить отчёт завтра"}
        ]
    else:
        assert outcome["reason"] == "Нужен отчёт"
        assert outcome["next_step"] == "Обсудить отчёт завтра"
