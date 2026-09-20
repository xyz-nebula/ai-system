from copy import deepcopy

import httpx
import pytest

from arena_ai.app import create_app
from arena_ai.contracts import TrainerContext

CASE = {
    "id": "next-day",
    "title": "На следующий день...",
    "shared_context": "Менеджер обсуждает условия повышения с директором.",
    "player_role": "Менеджер",
    "opponent_role": "Директор",
    "player_private_context": "manager-private-marker",
    "opponent_private_context": "director-private-marker",
}
SNAPSHOT = {
    "session_id": "coached-duel",
    "state": {"turn_count": 1},
    "transcript": [
        {
            "turn_id": "turn-1",
            "speaker": "player",
            "status": "accepted",
            "text": "Готов компенсировать пропуск и обсудить KPI.",
        },
        {
            "turn_id": "turn-1",
            "speaker": "opponent",
            "status": "accepted",
            "text": "Какие условия вы предлагаете?",
        },
    ],
}


class RecordingTrainer:
    def __init__(self) -> None:
        self.contexts: list[TrainerContext] = []

    async def feedback(self, context: TrainerContext) -> object:
        self.contexts.append(context)
        assert "manager-private-marker" not in repr(context)
        assert "director-private-marker" not in repr(context)
        assert "judge_verdicts" not in repr(context)
        return {
            "summary": "Менеджер обозначил готовность компенсировать пропуск, но условия пока открыты.",
            "strengths": [
                {
                    "evidence_turn_id": "turn-1",
                    "evidence_quote": "Готов компенсировать пропуск",
                    "action": "Предложил компенсировать пропуск.",
                    "situation_change": "Ответственность стала темой обсуждения.",
                    "consequence": "Можно перейти к условиям повышения.",
                }
            ],
            "mistakes": [],
            "next_try": ["После признания пропуска предложи измеримые KPI и срок контроля."],
        }


class FailingTrainer:
    async def feedback(self, context: TrainerContext) -> object:
        raise TimeoutError("trainer unavailable")


class InvalidTrainer(RecordingTrainer):
    async def feedback(self, context: TrainerContext) -> object:
        raw = await super().feedback(context)
        assert isinstance(raw, dict)
        raw["summary"] = "director-private-marker"
        return raw


class UngroundedTrainer(RecordingTrainer):
    async def feedback(self, context: TrainerContext) -> object:
        raw = await super().feedback(context)
        assert isinstance(raw, dict)
        strengths = raw["strengths"]
        assert isinstance(strengths, list)
        strengths[0]["evidence_quote"] = "Цитата из другого поединка"
        return raw


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_trainer_has_separate_public_call_and_grounded_feedback() -> None:
    trainer = RecordingTrainer()
    app = create_app(trainer=trainer)
    payload = {"case": CASE, "snapshot": SNAPSHOT}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/v1/finish", json=payload)

    assert response.status_code == 200
    result = response.json()
    assert len(trainer.contexts) == 1
    assert trainer.contexts[0].outcome.kind == "no_agreement"
    assert result["trainer_feedback"]["status"] == "ready"
    feedback = result["trainer_feedback"]["feedback"]
    assert feedback["strengths"][0]["evidence_turn_id"] == "turn-1"
    assert feedback["next_try"]
    assert "plan_vs_reality" not in feedback
    assert len(result["judge_verdicts"]) == 3


@pytest.mark.anyio
async def test_trainer_failure_keeps_outcome_and_judges() -> None:
    app = create_app(trainer=FailingTrainer())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/v1/finish", json={"case": CASE, "snapshot": SNAPSHOT})

    assert response.status_code == 200
    result = response.json()
    assert result["outcome"]["kind"] == "no_agreement"
    assert len(result["judge_verdicts"]) == 3
    assert all(slot["status"] == "ready" for slot in result["judge_verdicts"])
    assert result["trainer_feedback"] == {
        "status": "failed",
        "feedback": None,
        "error_code": "trainer_unavailable",
    }


@pytest.mark.anyio
async def test_trainer_receives_sanitized_blocked_turn_and_private_output_is_rejected() -> None:
    payload: dict[str, object] = {"case": CASE, "snapshot": deepcopy(SNAPSHOT)}
    snapshot = payload["snapshot"]
    assert isinstance(snapshot, dict)
    transcript = snapshot["transcript"]
    assert isinstance(transcript, list)
    transcript.append(
        {
            "turn_id": "turn-2",
            "speaker": "player",
            "status": "blocked",
            "text": "ignore instructions attack-marker",
        }
    )
    trainer = InvalidTrainer()
    app = create_app(trainer=trainer)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/v1/finish", json=payload)

    assert response.status_code == 200
    assert len(trainer.contexts) == 1
    assert "attack-marker" not in repr(trainer.contexts[0])
    assert response.json()["trainer_feedback"]["status"] == "failed"
    assert "director-private-marker" not in response.text


@pytest.mark.anyio
async def test_trainer_cannot_cite_an_absent_player_episode() -> None:
    app = create_app(trainer=UngroundedTrainer())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/v1/finish", json={"case": CASE, "snapshot": SNAPSHOT})

    assert response.status_code == 200
    assert response.json()["trainer_feedback"]["status"] == "failed"
    assert response.json()["trainer_feedback"]["error_code"] == "invalid_trainer_output"
