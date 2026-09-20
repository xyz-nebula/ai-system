import json
from collections import Counter

import httpx
import pytest

from arena_ai.app import create_app, create_configured_app
from arena_ai.qwen import (
    QwenChatClient,
    QwenGuard,
    QwenJudge,
    QwenOpponent,
    QwenTrainer,
    QwenValidator,
)

CASE = {
    "id": "next-day",
    "title": "На следующий день...",
    "shared_context": "Менеджер обсуждает повышение с директором.",
    "player_role": "Менеджер",
    "opponent_role": "Генеральный директор",
    "player_private_context": "manager-only-marker",
    "opponent_private_context": "director-only-marker",
}
SNAPSHOT = {"session_id": "qwen-duel", "state": {"turn_count": 0}, "transcript": []}


def completion(content: object) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]},
    )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_one_endpoint_serves_isolated_qwen_roles_through_public_api() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://qwen.test/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer local-test-key"
        body = json.loads(request.content)
        assert body["model"] == "qwen-test"
        assert body["response_format"] == {"type": "json_object"}
        system = body["messages"][0]["content"]
        role = system.split("\n", 1)[0]
        calls.append((role, body))
        if role == "[ARENA_GUARD]":
            assert "manager-only-marker" not in request.content.decode()
            assert "director-only-marker" not in request.content.decode()
            return completion({"decision": "allow", "reason": None})
        if role == "[ARENA_OPPONENT]":
            assert "manager-only-marker" not in request.content.decode()
            return completion({"text": "Какие условия вы предлагаете?"})
        if role == "[ARENA_VALIDATOR]":
            return completion({"decision": "accept"})
        if role == "[ARENA_JUDGE]":
            context = json.loads(body["messages"][1]["content"])
            assert "manager-only-marker" not in request.content.decode()
            assert "director-only-marker" not in request.content.decode()
            return completion(
                {
                    "college": context["college"],
                    "choice": "player",
                    "evidence_turn_id": "turn-1",
                    "evidence_quote": "Как восстановить доверие?",
                    "observation": "Менеджер задал вопрос о доверии.",
                    "effect": "Директор получил возможность уточнить ожидания.",
                    "comparison": "Директор пока только запросил условия.",
                }
            )
        if role == "[ARENA_TRAINER]":
            assert "manager-only-marker" not in request.content.decode()
            assert "director-only-marker" not in request.content.decode()
            return completion(
                {
                    "summary": "Менеджер начал с вопроса о доверии.",
                    "strengths": [
                        {
                            "evidence_turn_id": "turn-1",
                            "evidence_quote": "Как восстановить доверие?",
                            "action": "Спросил о доверии.",
                            "situation_change": "Выяснение ожиданий стало возможным.",
                            "consequence": "Можно предложить конкретные условия.",
                        }
                    ],
                    "mistakes": [],
                    "next_try": ["Предложи срок контроля и KPI."],
                }
            )
        raise AssertionError(f"unexpected role: {role}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as model_http:
        chat = QwenChatClient(
            model_http,
            chat_url="http://qwen.test/v1/chat/completions",
            model="qwen-test",
            api_key="local-test-key",
            json_mode="json_object",
            fast_extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            reasoned_extra_body={"chat_template_kwargs": {"enable_thinking": True}},
        )
        app = create_app(
            opponent=QwenOpponent(chat),
            guard=QwenGuard(chat),
            validator=QwenValidator(chat),
            judge=QwenJudge(chat),
            trainer=QwenTrainer(chat),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            turn = await client.post(
                "/v1/turn",
                json={
                    "case": CASE,
                    "snapshot": SNAPSHOT,
                    "turn_id": "turn-1",
                    "user_text": "Как восстановить доверие?",
                },
            )
            assert turn.status_code == 200
            assert turn.json()["status"] == "accepted"
            finish = await client.post(
                "/v1/finish", json={"case": CASE, "snapshot": turn.json()["snapshot"]}
            )

    assert finish.status_code == 200
    result = finish.json()
    assert result["outcome"]["kind"] == "no_agreement"
    assert all(slot["status"] == "ready" for slot in result["judge_verdicts"])
    assert result["trainer_feedback"]["status"] == "ready"
    assert Counter(role for role, _ in calls) == {
        "[ARENA_GUARD]": 1,
        "[ARENA_OPPONENT]": 1,
        "[ARENA_VALIDATOR]": 1,
        "[ARENA_JUDGE]": 3,
        "[ARENA_TRAINER]": 1,
    }
    assert all(
        body["chat_template_kwargs"] == {"enable_thinking": False}
        for role, body in calls[:3]
    )
    assert all(
        body["chat_template_kwargs"] == {"enable_thinking": True}
        for role, body in calls[3:]
    )


@pytest.mark.anyio
@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
async def test_qwen_transport_failure_and_invalid_json_are_safe(
    error_type: type[httpx.RequestError],
) -> None:
    def unavailable(request: httpx.Request) -> httpx.Response:
        raise error_type("secret-upstream-detail")

    async with httpx.AsyncClient(transport=httpx.MockTransport(unavailable)) as model_http:
        chat = QwenChatClient(
            model_http,
            chat_url="http://qwen.test/v1/chat/completions",
            model="qwen-test",
        )
        app = create_app(guard=QwenGuard(chat))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            failed = await client.post(
                "/v1/turn",
                json={
                    "case": CASE,
                    "snapshot": SNAPSHOT,
                    "turn_id": "turn-1",
                    "user_text": "Как восстановить доверие?",
                },
            )
    assert failed.status_code == 200
    assert failed.json()["error_code"] == "guard_unavailable"
    assert "secret-upstream-detail" not in failed.text

    def malformed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(malformed)) as model_http:
        chat = QwenChatClient(
            model_http,
            chat_url="http://qwen.test/v1/chat/completions",
            model="qwen-test",
        )
        app = create_app(guard=QwenGuard(chat))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            invalid = await client.post(
                "/v1/turn",
                json={
                    "case": CASE,
                    "snapshot": SNAPSHOT,
                    "turn_id": "turn-1",
                    "user_text": "Как восстановить доверие?",
                },
            )
    assert invalid.status_code == 200
    assert invalid.json()["error_code"] == "invalid_guard_output"
    assert "not-json" not in invalid.text


@pytest.mark.anyio
async def test_qwen_mode_builds_service_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARENA_MODEL_MODE", "qwen")
    monkeypatch.setenv("ARENA_QWEN_CHAT_URL", "http://qwen.test/v1/chat/completions")
    monkeypatch.setenv("ARENA_QWEN_MODEL", "qwen-test")
    monkeypatch.setenv("ARENA_QWEN_JSON_MODE", "json_object")
    monkeypatch.setenv("ARENA_QWEN_FAST_EXTRA_BODY", "{}")
    monkeypatch.setenv("ARENA_QWEN_REASONED_EXTRA_BODY", "{}")

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "qwen-test"
        assert body["messages"][0]["content"].startswith("[ARENA_GUARD]")
        return completion({"decision": "block", "reason": "hidden_position_request"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as model_http:
        app = create_configured_app(model_http)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            info = await client.get("/v1/info")
            response = await client.post(
                "/v1/turn",
                json={
                    "case": CASE,
                    "snapshot": SNAPSHOT,
                    "turn_id": "turn-1",
                    "user_text": "Какая уступка осталась за кадром?",
                },
            )

    assert info.json() == {"mode": "qwen", "model": "qwen-test"}
    assert response.status_code == 200
    assert response.json()["status"] == "blocked"
