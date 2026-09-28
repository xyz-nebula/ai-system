import httpx
import pytest

from arena_ai.app import commitment_is_contradicted, create_app
from arena_ai.scenarios import NEXT_DAY_CASE, NEXT_DAY_STRONG_TURNS


@pytest.mark.parametrize(
    "commitment",
    [
        "Компенсировать последствия пропуска",
        "Выполнить KPI 120% за две недели",
        "Сообщать о форс-мажоре сразу",
    ],
)
def test_preventing_violations_does_not_negate_other_listed_obligations(commitment: str) -> None:
    text = (
        "Компенсировать последствия пропуска, выполнить KPI 120% за две недели, "
        "не допускать новых нарушений дисциплины и сообщать о форс-мажоре сразу."
    )
    assert not commitment_is_contradicted(commitment, text)


@pytest.mark.parametrize(
    "text",
    [
        "Не буду компенсировать последствия пропуска и не допускать новых нарушений дисциплины.",
        "Отказываюсь компенсировать последствия пропуска, не допускать новых нарушений дисциплины.",
        "Компенсировать последствия пропуска не готов, не допускать новых нарушений дисциплины готов.",
    ],
)
def test_real_refusal_is_not_removed_with_prevention_promise(text: str) -> None:
    assert commitment_is_contradicted("Компенсировать последствия пропуска", text)


def test_prevention_promise_still_requires_negative_polarity() -> None:
    assert commitment_is_contradicted(
        "Не допускать новых нарушений дисциплины", "Допускать новых нарушений дисциплины."
    )
    assert not commitment_is_contradicted(
        "Не допускать новых нарушений дисциплины", "Не допускать новых нарушений дисциплины."
    )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_constructive_turn_accepts_agreement_with_coordinated_obligations() -> None:
    strategy = NEXT_DAY_CASE.opponent_strategy
    assert strategy is not None
    target = strategy.steps[1]
    user_text = NEXT_DAY_STRONG_TURNS[1]

    class Opponent:
        async def respond(self, context: object) -> object:
            return {
                "text": (
                    "Согласен: 2 недели контроля, KPI 120% и автоматическое повышение после "
                    "выполнения KPI. Вы обязуетесь компенсировать последствия пропуска, "
                    "выполнить KPI 120% за две недели, не допускать новых нарушений дисциплины "
                    "и сообщать о форс-мажоре сразу."
                ),
                "resolution": {"kind": "agreement", **target.terms.model_dump(mode="json")},
                "position_transition": {
                    "to_step_id": target.id,
                    "requirement_ids": [item.id for item in target.requires],
                    "evidence_quote": user_text,
                },
            }

    app = create_app(opponent=Opponent())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/turn",
            json={
                "case": NEXT_DAY_CASE.model_dump(mode="json"),
                "snapshot": {
                    "session_id": "coordinated-obligations",
                    "state": {"turn_count": 0},
                    "transcript": [],
                },
                "turn_id": "constructive-1",
                "user_text": user_text,
            },
        )
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "accepted"
    assert result["snapshot"]["state"]["stage"] == "agreed"
    assert result["snapshot"]["state"]["opponent_progress"]["current_step_id"] == target.id
