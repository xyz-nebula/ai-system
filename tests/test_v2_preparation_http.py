import json
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft202012Validator
from test_v2_http import configure

from arena_ai.app import create_configured_app

EXAMPLES = Path(__file__).resolve().parents[1] / "tests/fixtures/v2/examples"
HEADERS = {"Authorization": "Bearer test-token", "X-Arena-Contract-Version": "2.0.0-rc.1"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


def request_body():
    return json.loads((EXAMPLES / "preparation-review.request.json").read_bytes())


@pytest.mark.anyio
async def test_review_returns_feedback_without_replacing_user_block(monkeypatch):
    configure(monkeypatch)
    body = request_body()
    expected = json.loads((EXAMPLES / "preparation-review.response.json").read_bytes())

    def gateway(request):
        messages = json.loads(request.content)["messages"]
        context = json.loads(messages[1]["content"])
        if "[V2_PREPARATION_REVIEW_VERIFY]" in messages[0]["content"]:
            assert context["request"]["block_text"] == "Добиться повышения."
            reply = {"decision": "accept"}
        else:
            assert context["context"]["player"]["role_id"] == "manager"
            assert "opponent" not in context["context"]
            assert context["section_id"] == "negotiation_goal"
            reply = expected["feedback"]
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(reply)}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as model:
        app = create_configured_app(model)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/v2/preparation/review", json=body, headers=HEADERS)
            schema = (await client.get("/openapi.json")).json()
    assert response.status_code == 200
    assert response.json() == expected
    canonical = json.loads((EXAMPLES.parent / "contract.schema.json").read_bytes())
    Draft202012Validator(
        {"$ref": "#/$defs/PreparationReviewResponse", "$defs": canonical["$defs"]}
    ).validate(response.json())
    operation = schema["paths"]["/v2/preparation/review"]["post"]
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/V2PreparationReviewRequest"
    }
    Draft202012Validator(
        {
            "$ref": "#/components/schemas/V2PreparationReviewResponse",
            "components": schema["components"],
        }
    ).validate(response.json())


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["auth", "version", "blank", "roles", "section", "hidden"])
async def test_review_rejects_invalid_input_before_model(monkeypatch, fault):
    configure(monkeypatch)
    body, headers = request_body(), dict(HEADERS)
    if fault == "auth":
        headers.pop("Authorization")
    elif fault == "version":
        headers["X-Arena-Contract-Version"] = "wrong"
    elif fault == "blank":
        body["block_text"] = " "
    elif fault == "roles":
        body["context"]["opponent_role_id"] = "manager"
    elif fault == "section":
        body["section_id"] = "unknown"
    else:
        body["context"]["opponent"] = body["context"]["player"]

    def gateway(request):
        pytest.fail("Invalid input reached the model")

    async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as model:
        app = create_configured_app(model)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/v2/preparation/review", json=body, headers=headers)
    assert response.status_code == (401 if fault == "auth" else 409 if fault == "version" else 422)


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["reject", "uncertain", "unavailable", "format", "reference"])
async def test_review_does_not_publish_unverified_feedback(monkeypatch, fault):
    configure(monkeypatch)
    body = request_body()
    expected = json.loads((EXAMPLES / "preparation-review.response.json").read_bytes())

    def gateway(request):
        system = json.loads(request.content)["messages"][0]["content"]
        if "[V2_PREPARATION_REVIEW_VERIFY]" in system:
            if fault == "unavailable":
                return httpx.Response(503)
            reply = {"decision": fault if fault in ("reject", "uncertain") else "accept"}
        else:
            reply = {} if fault == "format" else expected["feedback"]
            if fault == "reference":
                reply["summary"] = "Читайте методичку https://example.test"
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(reply)}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as model:
        app = create_configured_app(model)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/v2/preparation/review", json=body, headers=HEADERS)
    assert response.status_code == 200
    result = response.json()
    assert result["revision_id"] == body["revision_id"]
    assert result["section_id"] == body["section_id"]
    assert result["status"] == "failed"
    assert result["feedback"] is None
    assert result["error_code"] == (
        "preparation_review_unavailable" if fault == "unavailable" else "invalid_preparation_review"
    )
