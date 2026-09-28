import json

import httpx
import pytest
from test_judges_api import FINISH_PAYLOAD

from arena_ai.app import create_app
from arena_ai.qwen import QwenChatClient, QwenTrainer


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("paraphrase", [False, True])
async def test_trainer_prompt_preserves_exact_preparation_identity(paraphrase: bool) -> None:
    original = "Договориться о проверяемом повышении после выполнения KPI."
    calls = []

    def gateway(request: httpx.Request) -> httpx.Response:
        system = json.loads(request.content)["messages"][0]["content"]
        assert "preparation_text копируй дословно, не сокращай и не перефразируй" in system
        items = json.loads(
            system.split("Канонические элементы подготовки: ", 1)[1].split("\n", 1)[0]
        )
        assert items == [{"kind": "negotiation_goal", "text": original}]
        calls.append(True)
        feedback = {
            "summary": "Подготовленная цель не проявилась в предложении условий.",
            "strengths": [
                {
                    "evidence_turn_id": "turn-1",
                    "evidence_quote": "Готов компенсировать пропуск",
                    "action": "Менеджер предложил компенсацию.",
                    "situation_change": "Возникло конкретное предложение.",
                    "consequence": "Можно обсуждать обязательства.",
                }
            ],
            "mistakes": [],
            "next_try": ["Назовите измеримые условия повышения."],
            "plan_vs_reality": {
                "summary": "Цель не проявилась.",
                "items": [
                    {
                        "preparation_kind": "negotiation_goal",
                        "preparation_text": "Добиться повышения по KPI."
                        if paraphrase
                        else original,
                        "status": "not_observed",
                        "evidence_turn_id": None,
                        "evidence_quote": None,
                        "observation": "В реплике не предложены условия повышения.",
                    }
                ],
            },
        }
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(feedback)}}]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as model:
        trainer = QwenTrainer(QwenChatClient(model, chat_url="http://gateway/chat", model="qwen"))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(trainer=trainer)), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v1/finish", json={**FINISH_PAYLOAD, "preparation": {"negotiation_goal": original}}
            )
    assert calls == [True]
    slot = response.json()["trainer_feedback"]
    assert slot["status"] == ("failed" if paraphrase else "ready")
    if paraphrase:
        assert slot["error_code"] == "invalid_trainer_output"
