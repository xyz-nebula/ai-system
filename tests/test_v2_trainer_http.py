import json
import os
from pathlib import Path

import httpx
import pytest
from test_v2_finish_http import finish_body
from test_v2_http import configure

from arena_ai.app import create_configured_app


@pytest.fixture
def anyio_backend():
    return "asyncio"


def feedback_example():
    path = (
        Path(__file__).resolve().parents[1]
        / "tests/fixtures/v2/examples/finish-with-preparation.response.json"
    )
    return json.loads(path.read_bytes())["trainer_feedback"]["feedback"]


@pytest.mark.anyio
@pytest.mark.parametrize("prepared", [True, False])
async def test_finish_returns_trainer_feedback_grounded_in_user_plan_and_dialogue(
    monkeypatch, prepared
):
    configure(monkeypatch)
    body = finish_body()
    expected = feedback_example()
    if not prepared:
        body["preparation"] = None
        expected["plan_vs_reality"] = None
        expected["goal_assessment"] = {
            "status": "not_assessable",
            "goal_text": None,
            "explanation": "Личная цель не записана пользователем.",
            "evidence": [],
        }

    def gateway(request):
        messages = json.loads(request.content)["messages"]
        if "[V2_TRAINER_VERIFY]" in messages[0]["content"]:
            context = json.loads(messages[1]["content"])
            assert context["dialogue"]["preparation"] == body["preparation"]
            assert "opponent_brief" not in context["dialogue"]
            reply = {"decision": "accept"}
        elif "[V2_TRAINER]" in messages[0]["content"]:
            context = json.loads(messages[1]["content"])
            assert context["preparation"] == body["preparation"]
            assert "opponent_brief" not in context
            assert body["case"]["opponent"]["private_context"] not in messages[1]["content"]
            assert "judge_verdicts" not in context
            reply = expected
        else:
            return httpx.Response(503)
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
    assert response.status_code == 200
    assert response.json()["trainer_feedback"] == {
        "status": "ready",
        "feedback": expected,
        "error_code": None,
    }
    assert response.json()["outcome"]["kind"] == "no_agreement"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "candidate",
    ["grounded", "invented_result", "generated", "generated_prepared", "generated_plan_only"],
)
@pytest.mark.skipif(
    os.environ.get("ARENA_RUN_LIVE_V2") != "1", reason="Explicit live opt-in required"
)
async def test_live_trainer_publishes_only_grounded_feedback(monkeypatch, candidate):
    url, model_id = os.environ["ARENA_QWEN_CHAT_URL"], os.environ["ARENA_QWEN_MODEL"]
    configure(monkeypatch)
    monkeypatch.setenv("ARENA_QWEN_CHAT_URL", url)
    monkeypatch.setenv("ARENA_QWEN_MODEL", model_id)
    body = finish_body()
    reply = feedback_example()
    if candidate == "invented_result":
        reply["strengths"][0]["consequence"] = "Пользователь уже получил повышение зарплаты."
    if candidate == "generated":
        body["preparation"] = None
    elif candidate == "generated_prepared":
        body["preparation"] = (
            "Моя цель — выяснить условия повышения. План: спросить, какие условия предлагает директор."
        )
    elif candidate == "generated_plan_only":
        body["preparation"] = "План: спросить про условия. Цель пока не сформулирована."
    public_model_responses = []
    async with httpx.AsyncClient(timeout=60) as real:

        async def gateway(request):
            messages = json.loads(request.content)["messages"]
            if "[V2_TRAINER_VERIFY]" in messages[0]["content"]:
                response = await real.send(request)
                public_model_responses.append(response.json()["choices"][0]["message"]["content"])
                return response
            if "[V2_TRAINER]" in messages[0]["content"]:
                if candidate.startswith("generated"):
                    response = await real.send(request)
                    public_model_responses.append(
                        response.json()["choices"][0]["message"]["content"]
                    )
                    return response
                return httpx.Response(
                    200, json={"choices": [{"message": {"content": json.dumps(reply)}}]}
                )
            return httpx.Response(503)

        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(gateway), timeout=60) as model,
            httpx.AsyncClient(
                transport=httpx.MockTransport(lambda request: httpx.Response(503))
            ) as retrieval,
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
    slot = result["trainer_feedback"]
    if candidate == "invented_result":
        assert slot == {
            "status": "failed",
            "feedback": None,
            "error_code": "invalid_trainer_output",
        }
    else:
        assert slot["status"] == "ready", (slot["error_code"], public_model_responses)
        if candidate == "grounded":
            assert slot["feedback"] == reply
        elif candidate == "generated_prepared":
            feedback = slot["feedback"]
            assert feedback["goal_assessment"]["status"] == "achieved"
            assert feedback["goal_assessment"]["goal_text"] in body["preparation"]
            assert "выяснить условия" in feedback["goal_assessment"]["goal_text"].lower()
            assert feedback["plan_vs_reality"] is not None
            assert any(
                item["status"] == "followed" for item in feedback["plan_vs_reality"]["items"]
            )
        else:
            if candidate == "generated":
                assert slot["feedback"]["plan_vs_reality"] is None
            else:
                assert slot["feedback"]["plan_vs_reality"] is not None
            assert slot["feedback"]["goal_assessment"]["status"] == "not_assessable"
            assert slot["feedback"]["goal_assessment"]["goal_text"] is None
            assert 2 <= len(slot["feedback"]["next_try"]) <= 3


@pytest.mark.anyio
@pytest.mark.parametrize(
    "fault",
    [
        "evidence",
        "opponent_action",
        "goal",
        "plan",
        "private",
        "reject",
        "uncertain",
        "unavailable",
        "format",
    ],
)
async def test_finish_does_not_publish_invalid_or_unverified_coaching(monkeypatch, fault):
    configure(monkeypatch)
    body = finish_body()
    candidate = feedback_example()
    if fault == "evidence":
        candidate["strengths"][0]["evidence"]["quote"] = "Я всё выполнил"
    elif fault == "opponent_action":
        entry = body["snapshot"]["transcript"][-1]
        proof = {key: entry[key] for key in ("message_id", "turn_id", "speaker", "elapsed_ms")}
        proof["quote"] = entry["text"]
        candidate["mistakes"] = [
            {
                "evidence": proof,
                "action": "Не ответил на запрос обязательства",
                "situation_change": "Переговоры остановлены",
                "consequence": "Сделка не достигнута",
            }
        ]
    elif fault == "goal":
        candidate["goal_assessment"]["goal_text"] = "Получить миллион рублей"
    elif fault == "plan":
        candidate["plan_vs_reality"]["items"][0]["preparation_text"] = "Выдуманный план"
    elif fault == "private":
        candidate["summary"] = body["case"]["opponent"]["private_context"]
    elif fault in ("reject", "uncertain"):
        candidate["strengths"][0]["consequence"] = "Пользователь уже получил повышение."

    def gateway(request):
        messages = json.loads(request.content)["messages"]
        if "[V2_TRAINER_VERIFY]" in messages[0]["content"]:
            if fault == "unavailable":
                return httpx.Response(503)
            reply = {"decision": fault if fault in ("reject", "uncertain") else "accept"}
        elif "[V2_TRAINER]" in messages[0]["content"]:
            reply = {} if fault == "format" else candidate
        else:
            return httpx.Response(503)
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
    assert response.status_code == 200
    assert response.json()["trainer_feedback"] == {
        "status": "failed",
        "feedback": None,
        "error_code": "trainer_unavailable" if fault == "unavailable" else "invalid_trainer_output",
    }
    assert response.json()["outcome"]["kind"] == "no_agreement"
