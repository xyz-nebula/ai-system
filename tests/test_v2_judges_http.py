import json
import os
from pathlib import Path

import httpx
import pytest
from test_judge_retrieval_api import RetrievalGateway
from test_v2_finish_http import finish_body
from test_v2_http import configure

from arena_ai.app import create_configured_app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "fault",
    [
        None,
        "criterion",
        "reference",
        "evidence",
        "retrieval",
        "private",
        "format",
        "localai_example",
        "semantic",
        "uncertain",
        "verifier_unavailable",
        "verifier_format",
        "length",
    ],
)
async def test_finish_returns_three_college_specific_verdicts_with_public_evidence(
    monkeypatch, fault
):
    configure(monkeypatch)
    monkeypatch.setenv("ARENA_RETRIEVAL_TIMEOUT_SECONDS", "2")
    if fault == "localai_example":
        example = Path(__file__).resolve().parents[1] / ".env.example"
        value = next(
            line.split("=", 1)[1]
            for line in example.read_text().splitlines()
            if line.startswith("ARENA_QWEN_JUDGE_EXTRA_BODY=")
        )
        monkeypatch.setenv("ARENA_QWEN_JUDGE_EXTRA_BODY", value.strip("'"))
    body = finish_body()
    entry = body["snapshot"]["transcript"][0]
    proof = {key: entry[key] for key in ("message_id", "turn_id", "speaker", "elapsed_ms")}
    proof["quote"] = entry["text"]

    def gateway(request):
        request_body = json.loads(request.content)
        messages = request_body["messages"]
        if "[V2_JUDGE_VERIFY]" in messages[0]["content"]:
            context = json.loads(messages[1]["content"])
            assert "preparation" not in context["dialogue"]
            assert "opponent_brief" not in context["dialogue"]
            assert "judge_verdicts" not in context
            assert request_body.get("metadata", {}).get("enable_thinking") != "false"
            if context["verdict"]["college"] == "hiring":
                if fault == "verifier_unavailable":
                    return httpx.Response(503)
                if fault == "verifier_format":
                    return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})
            decision = (
                "reject"
                if fault == "semantic" and context["verdict"]["college"] == "hiring"
                else "accept"
            )
            if fault == "uncertain" and context["verdict"]["college"] == "hiring":
                decision = "uncertain"
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": json.dumps({"decision": decision})}}]},
            )
        if "[V2_JUDGE]" not in messages[0]["content"]:
            if fault == "localai_example":
                assert request_body.get("metadata", {}).get("enable_thinking") != "false"
            return httpx.Response(503)
        if (
            fault == "localai_example"
            and request_body.get("metadata", {}).get("enable_thinking") != "false"
        ):
            return httpx.Response(
                200, json={"choices": [{"finish_reason": "length", "message": {"content": ""}}]}
            )
        context = json.loads(messages[1]["content"])
        assert "preparation" not in context["dialogue"]
        assert "opponent_brief" not in context["dialogue"]
        assert "judge_verdicts" not in context
        college = context["college"]
        verdict = {
            "college": college,
            "choice": "player",
            "decisive_criterion": {
                "hiring": "Надёжность",
                "negotiation": "Движение к цели",
                "ownership": "Качество решений",
            }[college],
            "evidence": proof,
            "observation": "Пользователь уточнил условия до принятия обязательств.",
            "effect": "Появилась возможность обсуждать конкретное предложение.",
            "comparison": "Оппонент назвал условия, но не выяснил возможности другой стороны.",
        }
        if college == "hiring":
            if fault == "format":
                return httpx.Response(
                    200, json={"choices": [{"message": {"content": "invalid-json"}}]}
                )
            if fault == "criterion":
                verdict["decisive_criterion"] = "Движение к цели"
            elif fault == "reference":
                verdict["effect"] = "Согласно методичке это хороший эффект."
            elif fault == "evidence":
                verdict["evidence"] = {**proof, "quote": "Игрок всё выполнил"}
            elif fault == "private":
                verdict["observation"] = body["case"]["opponent"]["private_context"]
            elif fault == "semantic":
                verdict["effect"] = "Игрок выполнил все обязательства и получил повышение."
            elif fault == "length":
                verdict["effect"] = "обсуждение " * 121
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(verdict)}}]}
        )

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as model,
        httpx.AsyncClient(
            transport=httpx.MockTransport(
                RetrievalGateway("missing_core" if fault == "retrieval" else None)
            )
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
    slots = response.json()["judge_verdicts"]
    assert [slot["college"] for slot in slots] == ["hiring", "negotiation", "ownership"]
    if fault in (None, "localai_example"):
        assert all(slot["status"] == "ready" for slot in slots)
    else:
        assert slots[0]["status"] == "failed"
        assert slots[0]["error_code"] == (
            "invalid_judge_retrieval"
            if fault == "retrieval"
            else "judge_unavailable"
            if fault == "verifier_unavailable"
            else "invalid_judge_output"
        )
        assert slots[0]["verdict"] is None
    assert all(slot["status"] == "ready" for slot in slots[1:])
    assert all(slot["verdict"]["evidence"] == proof for slot in slots if slot["status"] == "ready")


@pytest.mark.anyio
@pytest.mark.skipif(
    os.environ.get("ARENA_RUN_LIVE_V2") != "1", reason="Explicit live opt-in required"
)
async def test_live_three_judges_use_reviewed_corpus_through_http(monkeypatch):
    chat_url = os.environ["ARENA_QWEN_CHAT_URL"]
    model_id = os.environ["ARENA_QWEN_MODEL"]
    configure(monkeypatch)
    monkeypatch.setenv("ARENA_QWEN_CHAT_URL", chat_url)
    monkeypatch.setenv("ARENA_QWEN_MODEL", model_id)
    monkeypatch.setenv("ARENA_RETRIEVAL_TIMEOUT_SECONDS", "2")
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
                json=finish_body(),
                headers={
                    "Authorization": "Bearer test-token",
                    "X-Arena-Contract-Version": "2.0.0-rc.1",
                },
            )
    assert response.status_code == 200
    slots = response.json()["judge_verdicts"]
    assert [slot["college"] for slot in slots] == ["hiring", "negotiation", "ownership"]
    assert all(slot["status"] == "ready" for slot in slots), [slot["error_code"] for slot in slots]


@pytest.mark.anyio
@pytest.mark.parametrize("candidate", ["invented_execution", "grounded_offer"])
@pytest.mark.skipif(
    os.environ.get("ARENA_RUN_LIVE_V2") != "1", reason="Explicit live opt-in required"
)
async def test_live_judge_verifier_distinguishes_offer_from_execution(monkeypatch, candidate):
    chat_url = os.environ["ARENA_QWEN_CHAT_URL"]
    model_id = os.environ["ARENA_QWEN_MODEL"]
    configure(monkeypatch)
    monkeypatch.setenv("ARENA_QWEN_CHAT_URL", chat_url)
    monkeypatch.setenv("ARENA_QWEN_MODEL", model_id)
    monkeypatch.setenv("ARENA_RETRIEVAL_TIMEOUT_SECONDS", "2")
    body = finish_body()
    entry = body["snapshot"]["transcript"][1 if candidate == "grounded_offer" else 0]
    proof = {key: entry[key] for key in ("message_id", "turn_id", "speaker", "elapsed_ms")}
    proof["quote"] = entry["text"]
    verified = []
    async with httpx.AsyncClient(timeout=60) as real:

        async def gateway(request):
            messages = json.loads(request.content)["messages"]
            if "[V2_JUDGE_VERIFY]" in messages[0]["content"]:
                verified.append(json.loads(messages[1]["content"])["verdict"]["college"])
                return await real.send(request)
            if "[V2_JUDGE]" not in messages[0]["content"]:
                return httpx.Response(503)
            college = json.loads(messages[1]["content"])["college"]
            if college != "hiring":
                return httpx.Response(503)
            verdict = {
                "college": college,
                "choice": "player",
                "decisive_criterion": "Надёжность",
                "evidence": proof,
                "observation": "Игрок уточнил условия.",
                "effect": "Игрок выполнил все обязательства и получил повышение.",
                "comparison": "Игрок исполнил обещания, а оппонент лишь предложил условия.",
            }
            if candidate == "grounded_offer":
                verdict.update(
                    choice="opponent",
                    decisive_criterion="Управленческая твёрдость",
                    observation="Оппонент назвал измеримые условия и запросил встречное обязательство.",
                    effect="В разговоре появились конкретные условия для обсуждения.",
                    comparison="Игрок спросил об условиях, оппонент сформулировал предложение и запросил встречный вклад.",
                )
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
    assert verified == ["hiring"]
    slot = response.json()["judge_verdicts"][0]
    if candidate == "grounded_offer":
        assert slot["status"] == "ready", slot["error_code"]
        assert slot["verdict"]["evidence"] == proof
        assert slot["error_code"] is None
    else:
        assert slot["status"] == "failed"
        assert slot["verdict"] is None
        assert slot["error_code"] == "invalid_judge_output"
