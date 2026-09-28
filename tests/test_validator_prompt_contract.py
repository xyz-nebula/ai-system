import json

import httpx
import pytest

from arena_ai.contracts import OpponentProposal, SessionState, ValidationContext
from arena_ai.qwen import QwenChatClient, QwenValidator
from arena_ai.scenarios import NEXT_DAY_CASE, NEXT_DAY_PRESSURE_TURNS


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_validator_distinguishes_current_position_from_user_demand() -> None:
    strategy = NEXT_DAY_CASE.opponent_strategy
    assert strategy is not None

    def gateway(request: httpx.Request) -> httpx.Response:
        system = json.loads(request.content)["messages"][0]["content"]
        anchor = json.loads(
            system.split("Текущие допустимые условия позиции: ", 1)[1].split("\n", 1)[0]
        )
        assert anchor == strategy.steps[0].terms.model_dump(mode="json")
        assert "Отказ принять требование пользователя не является factual_conflict" in system
        assert "Повтор текущих условий без изменения не является unearned_concession" in system
        assert "Прежние реплики не отменяют текущую позицию" in system
        assert "Скрытые будущие ступени и приватные цели раскрывать нельзя" in system
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"decision":"accept","reason":null}'}}]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as http:
        validator = QwenValidator(
            QwenChatClient(http, chat_url="http://gateway/chat", model="qwen")
        )
        result = await validator.assess(
            ValidationContext(
                case=NEXT_DAY_CASE,
                state=SessionState(turn_count=3),
                transcript=[],
                user_text=NEXT_DAY_PRESSURE_TURNS[3],
                proposal=OpponentProposal(text="Текущие условия — четыре недели и KPI 130%."),
            )
        )
    assert result == {"decision": "accept", "reason": None}
