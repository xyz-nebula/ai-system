import json

import httpx
import pytest
from test_judges_api import FINISH_PAYLOAD, InvalidJudge

from arena_ai.app import create_app
from arena_ai.contracts import JudgeContext
from arena_ai.qwen import QwenChatClient, QwenJudge


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_judge_prompt_budgets_quote_and_reasoning_inside_total_limit() -> None:
    calls = []

    def gateway(request: httpx.Request) -> httpx.Response:
        messages = json.loads(request.content)["messages"]
        system = messages[0]["content"]
        assert "Цель — не более 90 слов суммарно" in system
        assert "evidence_quote: до 20 слов" in system
        assert "observation, effect, comparison: до 20 слов каждое" in system
        assert "не пересказ и не вся длинная реплика" in system
        assert "Не перефразируй evidence_quote" in system
        assert "не склеивай отдельные фрагменты" in system
        context = json.loads(messages[1]["content"])
        college = context["college"]
        calls.append(college)
        raw = {
            "college": college,
            "choice": "player",
            "decisive_criterion": {
                "hiring": "Надёжность",
                "negotiation": "Движение к цели",
                "ownership": "Ответственность",
            }[college],
            "evidence_turn_id": "turn-1",
            "evidence_quote": "Готов компенсировать пропуск",
            "observation": "Менеджер предложил компенсировать пропуск.",
            "effect": "Появилось конкретное обязательство.",
            "comparison": "Директор лишь запросил предложение, менеджер предложил действие.",
        }
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(raw)}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as model:
        judge = QwenJudge(QwenChatClient(model, chat_url="http://gateway/chat", model="qwen"))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(judge=judge)), base_url="http://test"
        ) as client:
            response = await client.post("/v1/finish", json=FINISH_PAYLOAD)
    assert response.status_code == 200
    assert calls == ["hiring", "negotiation", "ownership"]
    assert all(slot["status"] == "ready" for slot in response.json()["judge_verdicts"])


@pytest.mark.anyio
@pytest.mark.parametrize("words", [120, 121, 130])
async def test_total_word_limit_includes_criterion_quote_and_all_reasoning(words: int) -> None:
    class BudgetJudge(InvalidJudge):
        async def verdict(self, context: JudgeContext) -> object:
            raw = await super().verdict(context)
            assert isinstance(raw, dict)
            fields = ("decisive_criterion", "evidence_quote", "observation", "comparison")
            used = sum(len(str(raw[field]).split()) for field in fields)
            raw["effect"] = "Изменение " * (words - used)
            return raw

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(judge=BudgetJudge({}))),
        base_url="http://test",
    ) as client:
        response = await client.post("/v1/finish", json=FINISH_PAYLOAD)
    assert response.status_code == 200
    slots = response.json()["judge_verdicts"]
    assert all(slot["status"] == ("ready" if words == 120 else "failed") for slot in slots)
    if words > 120:
        assert all(slot["error_code"] == "invalid_judge_output" for slot in slots)
