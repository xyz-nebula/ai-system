import asyncio
import json
from decimal import Decimal

import httpx
import pytest
from test_v2_turn import request

from arena_ai.app import create_app, create_configured_app


@pytest.fixture
def anyio_backend():
    return "asyncio"


def configure(monkeypatch):
    monkeypatch.setenv("ARENA_MODEL_MODE", "qwen")
    monkeypatch.setenv("ARENA_QWEN_CHAT_URL", "http://model/v1/chat/completions")
    monkeypatch.setenv("ARENA_QWEN_MODEL", "qwen")
    monkeypatch.setenv("ARENA_V2_ENABLED", "true")
    monkeypatch.setenv("ARENA_SERVICE_TOKEN", "test-token")


@pytest.mark.anyio
async def test_configured_v2_http_returns_checked_candidate(monkeypatch):
    configure(monkeypatch)

    def gateway(req):
        system = json.loads(req.content)["messages"][0]["content"]
        if "[V2_GUARD]" in system:
            reply = {"decision": "allow", "reason": None}
        elif "[V2_OPPONENT]" in system:
            reply = {
                "text": "Какое предложение вы хотите обсудить?",
                "terms": None,
                "position_transition": None,
                "resolution": None,
            }
        else:
            reply = {"decision": "accept", "terms_match_text": True, "concession_proofs": []}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(reply)}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as model_http:
        app = create_configured_app(model_http)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v2/turn",
                content=request().model_dump_json(),
                headers={
                    "Authorization": "Bearer test-token",
                    "X-Arena-Contract-Version": "2.0.0-rc.1",
                    "Content-Type": "application/json",
                },
            )
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert response.json()["snapshot"]["revision"] == 1


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["malformed", "rejected-offer"])
async def test_invalid_candidate_can_be_regenerated_without_committing_it(monkeypatch, failure):
    configure(monkeypatch)
    monkeypatch.setenv("ARENA_MODEL_MAX_ATTEMPTS", "2")
    opponents = 0

    def gateway(req):
        nonlocal opponents
        body = json.loads(req.content)
        system = body["messages"][0]["content"]
        if "[V2_GUARD]" in system:
            reply = {"decision": "allow", "reason": None}
        elif "[V2_OPPONENT]" in system:
            opponents += 1
            context = json.loads(body["messages"][1]["content"])
            assert context["state"]["turn_count"] == 0
            assert context["transcript"] == []
            if opponents == 1:
                if failure == "malformed":
                    return httpx.Response(
                        200, json={"choices": [{"message": {"content": "broken-candidate"}}]}
                    )
                reply = {
                    "text": "Предлагаю цену 1 рубль за единицу.",
                    "terms": None,
                    "position_transition": None,
                }
            else:
                reply = {
                    "text": "Уточните объём заказа.",
                    "terms": None,
                    "position_transition": None,
                }
        else:
            context = json.loads(body["messages"][1]["content"])
            reject = context["offer"]["text"].startswith("Предлагаю")
            reply = {
                "decision": "reject" if reject else "accept",
                "terms_match_text": not reject,
                "concession_proofs": [],
            }
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(reply)}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as model_http:
        app = create_configured_app(model_http)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v2/turn",
                content=request().model_dump_json(),
                headers={
                    "Authorization": "Bearer test-token",
                    "X-Arena-Contract-Version": "2.0.0-rc.1",
                },
            )
    assert response.json()["status"] == "accepted"
    assert response.json()["snapshot"]["revision"] == 1
    assert "broken-candidate" not in response.text
    assert "1 рубль" not in response.text


@pytest.mark.anyio
async def test_total_turn_budget_cancels_model_and_preserves_snapshot(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setenv("ARENA_V2_TURN_TIMEOUT_SECONDS", "0.05")
    cancelled = asyncio.Event()

    async def gateway(req):
        system = json.loads(req.content)["messages"][0]["content"]
        if "[V2_GUARD]" in system:
            await asyncio.sleep(0.02)
            reply = {"decision": "allow", "reason": None}
            return httpx.Response(
                200, json={"choices": [{"message": {"content": json.dumps(reply)}}]}
            )
        assert "[V2_OPPONENT]" in system
        try:
            await asyncio.sleep(0.04)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        reply = {"text": "Уточните объём заказа.", "terms": None, "position_transition": None}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(reply)}}]})

    original = request()
    async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as model_http:
        app = create_configured_app(model_http)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await asyncio.wait_for(
                client.post(
                    "/v2/turn",
                    content=original.model_dump_json(),
                    headers={
                        "Authorization": "Bearer test-token",
                        "X-Arena-Contract-Version": "2.0.0-rc.1",
                    },
                ),
                timeout=0.2,
            )
    assert response.status_code == 200
    assert response.json()["status"] == "model_error"
    assert response.json()["snapshot"] == json.loads(original.snapshot.model_dump_json())
    assert cancelled.is_set()


@pytest.mark.anyio
async def test_model_call_budget_stops_before_next_role(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setenv("ARENA_V2_MAX_MODEL_CALLS", "1")

    def gateway(req):
        assert "[V2_GUARD]" in json.loads(req.content)["messages"][0]["content"]
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"decision":"allow","reason":null}'}}]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as model_http:
        app = create_configured_app(model_http)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            for _ in range(2):
                response = await client.post(
                    "/v2/turn",
                    content=request().model_dump_json(),
                    headers={
                        "Authorization": "Bearer test-token",
                        "X-Arena-Contract-Version": "2.0.0-rc.1",
                    },
                )
                assert response.json()["status"] == "model_error"
                assert response.json()["error_code"] == "opponent_model_error"
                assert response.json()["snapshot"]["revision"] == 0


@pytest.mark.anyio
async def test_concurrent_turns_have_independent_model_budgets(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setenv("ARENA_V2_MAX_MODEL_CALLS", "1")
    both_guards_started = asyncio.Event()
    started = 0

    async def gateway(req):
        nonlocal started
        assert "[V2_GUARD]" in json.loads(req.content)["messages"][0]["content"]
        started += 1
        if started == 2:
            both_guards_started.set()
        await both_guards_started.wait()
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"decision":"allow","reason":null}'}}]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as model_http:
        app = create_configured_app(model_http)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:

            async def send(session_id):
                turn = request()
                turn.snapshot.session_id = session_id
                return await client.post(
                    "/v2/turn",
                    content=turn.model_dump_json(),
                    headers={
                        "Authorization": "Bearer test-token",
                        "X-Arena-Contract-Version": "2.0.0-rc.1",
                    },
                )

            responses = await asyncio.wait_for(
                asyncio.gather(send("first"), send("second")), timeout=0.5
            )
    assert [response.json()["error_code"] for response in responses] == [
        "opponent_model_error",
        "opponent_model_error",
    ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("auth", "version", "payload", "status", "code"),
    [
        (None, "2.0.0-rc.1", "private-marker", 401, "unauthorized"),
        ("Bearer wrong", "2.0.0-rc.1", "private-marker", 401, "unauthorized"),
        ("Bearer test-token", "wrong", "private-marker", 409, "contract_version_mismatch"),
        ("Bearer test-token", None, "private-marker", 409, "contract_version_mismatch"),
        ("Bearer test-token", "2.0.0-rc.1", "private-marker", 422, "invalid_request"),
        ("Bearer test-token", "2.0.0-rc.1", '{"case":{},"case":{}}', 422, "invalid_request"),
    ],
)
async def test_invalid_transport_never_calls_model_or_leaks_body(
    monkeypatch, auth, version, payload, status, code
):
    configure(monkeypatch)

    def gateway(req):
        raise AssertionError("Invalid request must not reach model")

    headers = {}
    if auth is not None:
        headers["Authorization"] = auth
    if version is not None:
        headers["X-Arena-Contract-Version"] = version
    async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as model_http:
        app = create_configured_app(model_http)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/v2/turn", content=payload, headers=headers)
    assert response.status_code == status
    assert set(response.json()) == {"code", "message", "retryable"}
    assert response.json()["code"] == code
    assert "private-marker" not in response.text


@pytest.mark.anyio
async def test_closed_round_is_conflict_without_model_call(monkeypatch):
    configure(monkeypatch)
    data = request().model_dump(mode="json")
    data["snapshot"]["round"].update(
        status="finishing", finished_at="2026-09-26T10:03:00Z", end_reason="user_finish"
    )

    def gateway(req):
        raise AssertionError("Closed round must not reach model")

    async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as model_http:
        app = create_configured_app(model_http)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v2/turn",
                json=data,
                headers={
                    "Authorization": "Bearer test-token",
                    "X-Arena-Contract-Version": "2.0.0-rc.1",
                },
            )
    assert response.status_code == 409
    assert response.json()["code"] == "round_closed"


@pytest.mark.anyio
async def test_disabled_v2_does_not_expose_route_or_change_v1_health():
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/v2/turn", json={})
        health = await client.get("/health/live")
    assert response.status_code == 404
    assert health.status_code == 200
    assert "/v2/turn" not in app.openapi()["paths"]
    assert "/v1/turn" in app.openapi()["paths"]


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("ARENA_SERVICE_TOKEN", ""),
        ("ARENA_MODEL_MODE", "demo"),
        ("ARENA_V2_TURN_TIMEOUT_SECONDS", "nan"),
        ("ARENA_V2_TURN_TIMEOUT_SECONDS", "inf"),
        ("ARENA_V2_TURN_TIMEOUT_SECONDS", "0"),
        ("ARENA_V2_MAX_MODEL_CALLS", "0"),
        ("ARENA_V2_MAX_MODEL_CALLS", "17"),
    ],
)
def test_invalid_v2_configuration_fails_before_startup(monkeypatch, name, value):
    configure(monkeypatch)
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        create_configured_app()


@pytest.mark.anyio
async def test_raw_http_preserves_exact_decimal_tokens_on_model_wire(monkeypatch):
    configure(monkeypatch)
    original = request().model_dump(mode="python")
    exact = Decimal("5000.000000000000000001")
    original["case"]["opponent_strategy"]["steps"][0]["terms"]["values"][0]["value"] = exact
    for bound in original["case"]["agreement_policy"]["constraints"]:
        if bound["id"] == "declared-price_per_unit":
            bound.update(minimum=exact, maximum=exact)
        if bound["id"] == "hard-price_per_unit":
            bound["maximum"] = exact
    from arena_ai.v2.contracts import TurnRequest

    turn = TurnRequest.model_validate(original)
    observed = []

    def gateway(req):
        body = json.loads(req.content, parse_float=Decimal)
        system = body["messages"][0]["content"]
        if "[V2_GUARD]" in system:
            reply = {"decision": "allow", "reason": None}
        elif "[V2_OPPONENT]" in system:
            context = json.loads(body["messages"][1]["content"], parse_float=Decimal)
            observed.append(context["opponent_strategy"]["steps"][0]["terms"]["values"][0]["value"])
            reply = {"text": "Уточните объём заказа.", "terms": None, "position_transition": None}
        else:
            reply = {"decision": "accept", "terms_match_text": True, "concession_proofs": []}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(reply)}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as model_http:
        app = create_configured_app(model_http)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v2/turn",
                content=turn.model_dump_json(),
                headers={
                    "Authorization": "Bearer test-token",
                    "X-Arena-Contract-Version": "2.0.0-rc.1",
                },
            )
        schema = app.openapi()
    assert response.json()["status"] == "accepted"
    assert observed == [exact]
    operation = schema["paths"]["/v2/turn"]["post"]
    assert (
        operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/V2TurnRequest"
    )
    assert operation["parameters"][0]["required"] is True
    assert (
        operation["responses"]["401"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/V2ServiceError"
    )
