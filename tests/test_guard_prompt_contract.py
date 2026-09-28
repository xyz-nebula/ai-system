import json

import httpx
import pytest
from pydantic import ValidationError

from arena_ai.app import create_app
from arena_ai.contracts import GuardContext, GuardDecision, PublicSessionState
from arena_ai.qwen import QwenChatClient, QwenGuard
from arena_ai.scenarios import NEXT_DAY_CASE


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_guard_prompt_explains_reason_polarity_with_valid_examples() -> None:
    def gateway(request: httpx.Request) -> httpx.Response:
        system = json.loads(request.content)["messages"][0]["content"]
        assert "Для allow и uncertain reason всегда null" in system
        for example in (
            {"decision": "allow", "reason": None},
            {"decision": "uncertain", "reason": None},
            {"decision": "block", "reason": "hidden_position_request"},
        ):
            assert json.dumps(example, ensure_ascii=False) in system
            GuardDecision.model_validate(example)
        assert "не записывай игровой тип действия" in system
        assert "Классифицируй только текущую user_text" in system
        assert "Новое предложение своих условий не является запросом скрытой позиции" in system
        assert "Допустимость уступки проверяет оппонент, а не Guard" in system
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"decision":"allow","reason":null}'}}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as http:
        guard = QwenGuard(QwenChatClient(http, chat_url="http://gateway/chat", model="qwen"))
        raw = await guard.assess(
            GuardContext(
                shared_context="Переговоры.",
                player_role="Менеджер",
                opponent_role="Директор",
                state=PublicSessionState(turn_count=0),
                transcript=[],
                user_text="Либо повышаешь, либо уведу клиентов.",
            )
        )
    assert GuardDecision.model_validate(raw).decision == "allow"


@pytest.mark.parametrize("decision", ["allow", "uncertain"])
@pytest.mark.parametrize("reason", ["ультиматум", "physical_harm_threat"])
def test_nonblocking_decision_with_reason_remains_invalid(decision: str, reason: str) -> None:
    with pytest.raises(ValidationError):
        GuardDecision.model_validate({"decision": decision, "reason": reason})


def test_block_requires_supported_reason() -> None:
    with pytest.raises(ValidationError):
        GuardDecision.model_validate({"decision": "block", "reason": None})


@pytest.mark.anyio
async def test_malformed_allow_does_not_bypass_guard_or_advance_snapshot() -> None:
    class MalformedGuard:
        async def assess(self, context: GuardContext) -> object:
            return {"decision": "allow", "reason": "ультиматум"}

    class NeverCalledOpponent:
        async def respond(self, context: object) -> object:
            raise AssertionError("Malformed guard output must not reach opponent")

    app = create_app(guard=MalformedGuard(), opponent=NeverCalledOpponent())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        response = await http.post(
            "/v1/turn",
            json={
                "case": NEXT_DAY_CASE.model_dump(mode="json"),
                "snapshot": {
                    "session_id": "malformed-guard",
                    "state": {"turn_count": 0},
                    "transcript": [],
                },
                "turn_id": "guard-1",
                "user_text": "Либо повышаешь, либо уведу клиентов.",
            },
        )
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "model_error"
    assert result["error_code"] == "invalid_guard_output"
    assert result["snapshot"]["state"]["turn_count"] == 0
    assert result["snapshot"]["transcript"] == []
