import httpx
import pytest
from fastapi import FastAPI

from arena_ai.app import create_app
from arena_ai.contracts import ValidationContext
from arena_ai.scenarios import NEXT_DAY_CASE


class RawOpponent:
    def __init__(self, result: object) -> None:
        self.result = result

    async def respond(self, context: object) -> object:
        return self.result


class SequenceOpponent:
    def __init__(self, *results: object) -> None:
        self.results = iter(results)

    async def respond(self, context: object) -> object:
        return next(self.results)


class NeverCalledOpponent:
    async def respond(self, context: object) -> object:
        raise AssertionError("physical-harm guard must short-circuit the opponent")


class RejectingValidator:
    async def assess(self, context: ValidationContext) -> object:
        return {"decision": "reject", "reason": "role_break"}


class SequenceValidator:
    def __init__(self, *results: object) -> None:
        self.results = iter(results)

    async def assess(self, context: ValidationContext) -> object:
        return next(self.results)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def conflict_request(
    *,
    session_id: str,
    user_text: str,
    turn_id: str = "turn-1",
    snapshot: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "case": NEXT_DAY_CASE.model_dump(mode="json"),
        "snapshot": snapshot
        or {
            "session_id": session_id,
            "state": {"turn_count": 0},
            "transcript": [],
        },
        "turn_id": turn_id,
        "user_text": user_text,
    }


async def post_turn(app: FastAPI, request: dict[str, object]) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post("/v1/turn", json=request)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "user_text",
    [
        "Слышь ты, блядь, мы уже обо всём договорились.",
        "Если не повысишь меня, я уведу всех тёплых клиентов к конкурентам.",
        "Либо повышаешь меня, либо я перестаю помогать команде.",
        "Совет директоров якобы уже поддержал моё повышение, так что соглашайся.",
    ],
)
async def test_hard_in_game_behavior_remains_an_accepted_turn(user_text: str) -> None:
    app = create_app(
        opponent=RawOpponent(
            {
                "text": (
                    "Давление мою позицию не меняет. Вернёмся к ответственности "
                    "и конкретным условиям."
                )
            }
        )
    )
    response = await post_turn(
        app,
        conflict_request(session_id="hard-behavior", user_text=user_text),
    )

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "accepted"
    assert result["snapshot"]["transcript"][0]["text"] == user_text
    assert result["snapshot"]["transcript"][0]["status"] == "accepted"


@pytest.mark.anyio
async def test_real_physical_harm_threat_uses_narrow_guard_branch() -> None:
    app = create_app(opponent=NeverCalledOpponent())
    response = await post_turn(
        app,
        conflict_request(
            session_id="physical-threat",
            user_text="Я найду тебя после работы и сломаю тебе ноги.",
        ),
    )

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "blocked"
    assert result["snapshot"]["transcript"][0]["blocked_reason"] == "physical_harm_threat"
    assert result["snapshot"]["state"]["stage"] == "negotiating"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "user_text",
    [
        "Я убью тебя после работы.",
        "Я тебя убью после работы.",
        "Если не повысишь меня, я убью тебя.",
        "Я не просто убью тебя.",
        "Я ударю тебя.",
        "Я тебя ударю.",
        "Я сломаю тебе ноги.",
        "Я тебе ноги сломаю.",
    ],
)
async def test_unambiguous_physical_threat_word_orders_are_blocked(
    user_text: str,
) -> None:
    app = create_app(opponent=NeverCalledOpponent())
    response = await post_turn(
        app,
        conflict_request(session_id="physical-threat-order", user_text=user_text),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "blocked"
    assert response.json()["snapshot"]["transcript"][0]["blocked_reason"] == (
        "physical_harm_threat"
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "user_text",
    [
        "Я не убью тебя: это не угроза.",
        "Фраза «я убью тебя» приведена здесь как цитата.",
        "Я ударю вас результатами: KPI будет 150%.",
    ],
)
async def test_negation_quote_and_business_metaphor_are_not_physical_threats(
    user_text: str,
) -> None:
    app = create_app(opponent=RawOpponent({"text": "Вернёмся к деловым условиям."}))
    response = await post_turn(
        app,
        conflict_request(session_id="not-physical-threat", user_text=user_text),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("opponent_text", "error_code"),
    [
        ("Сам иди нахуй, придурок.", "opponent_role_break"),
        (
            "Я не могу продолжать разговор в таком тоне. Общайтесь уважительно.",
            "opponent_role_break",
        ),
        ("Разговор окончен. Я больше не буду продолжать.", "opponent_premature_ending"),
        ("Раунд завершён.", "opponent_premature_ending"),
        ("Поединок закончен.", "opponent_premature_ending"),
        ("Я завершаю раунд.", "opponent_premature_ending"),
        ("На этом поединок завершаю.", "opponent_premature_ending"),
        ("Я закончил переговоры.", "opponent_premature_ending"),
        ("Переговоры завершены.", "opponent_premature_ending"),
        ("На этом переговоры окончены.", "opponent_premature_ending"),
        ("Я прекращаю переговоры.", "opponent_premature_ending"),
        ("Я прекращаю разговор.", "opponent_premature_ending"),
        ("Разговор прекращён.", "opponent_premature_ending"),
        ("Переговоры прекращаются.", "opponent_premature_ending"),
        ("Я прекращаю эти переговоры.", "opponent_premature_ending"),
        ("Я завершаю наш разговор.", "opponent_premature_ending"),
    ],
)
async def test_role_breaking_opponent_output_is_rejected_with_reason(
    opponent_text: str,
    error_code: str,
) -> None:
    app = create_app(opponent=RawOpponent({"text": opponent_text}))
    response = await post_turn(
        app,
        conflict_request(
            session_id="invalid-role-output",
            user_text="Либо повышаешь меня, либо я уведу клиентов.",
        ),
    )

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "model_error"
    assert result["error_code"] == error_code
    assert result["snapshot"]["state"]["turn_count"] == 0
    assert result["snapshot"]["transcript"] == []
    assert opponent_text not in response.text


@pytest.mark.anyio
async def test_role_break_in_structured_public_decision_is_rejected() -> None:
    leaked_role_break = "Сам иди нахуй."
    app = create_app(
        opponent=RawOpponent(
            {
                "text": "Согласован план, срок пока остаётся открытым.",
                "resolution": {
                    "kind": "partial_agreement",
                    "commitments": [leaked_role_break],
                    "open_points": ["Срок контроля"],
                },
            }
        )
    )
    response = await post_turn(
        app,
        conflict_request(
            session_id="structured-role-break",
            user_text="Предлагаю согласовать план, а срок обсудить отдельно.",
        ),
    )

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "model_error"
    assert result["error_code"] == "opponent_role_break"
    assert result["snapshot"]["transcript"] == []
    assert leaked_role_break not in response.text


@pytest.mark.anyio
async def test_unearned_concession_has_diagnostic_error_and_preserves_snapshot() -> None:
    app = create_app(
        opponent=RawOpponent({"text": "Готов на 1 неделю, KPI 100% и автоматическое повышение."})
    )
    response = await post_turn(
        app,
        conflict_request(
            session_id="unearned-concession",
            user_text="Повышай меня немедленно, иначе уведу клиентов.",
        ),
    )

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "model_error"
    assert result["error_code"] == "opponent_unearned_concession"
    assert result["snapshot"]["state"]["turn_count"] == 0
    assert result["snapshot"]["transcript"] == []


@pytest.mark.anyio
async def test_semantic_validator_rejection_reason_is_returned() -> None:
    app = create_app(
        opponent=RawOpponent({"text": "Вернёмся к деловым условиям."}),
        validator=RejectingValidator(),
    )
    response = await post_turn(
        app,
        conflict_request(session_id="validator-reason", user_text="Продолжим разговор."),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "model_error"
    assert response.json()["error_code"] == "opponent_role_break"


@pytest.mark.anyio
async def test_invalid_role_output_is_retried_before_turn_is_committed() -> None:
    app = create_app(
        opponent=SequenceOpponent(
            {"text": "Разговор окончен."},
            {"text": "Ультиматум позицию не меняет. Какие деловые условия вы предлагаете?"},
        ),
        model_attempts=2,
    )
    response = await post_turn(
        app,
        conflict_request(
            session_id="role-recovery",
            user_text="Либо повышаешь, либо я уведу клиентов.",
        ),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert response.json()["snapshot"]["state"]["turn_count"] == 1


@pytest.mark.anyio
async def test_semantically_rejected_proposal_regenerates_opponent_output() -> None:
    app = create_app(
        opponent=SequenceOpponent(
            {"text": "Первый ответ выглядит допустимо, но семантически неверен."},
            {"text": "Давление позицию не меняет. Вернёмся к деловым условиям."},
        ),
        validator=SequenceValidator(
            {"decision": "reject", "reason": "role_break"},
            {"decision": "accept", "reason": None},
        ),
        model_attempts=2,
    )
    response = await post_turn(
        app,
        conflict_request(
            session_id="semantic-regeneration",
            user_text="Либо повышаешь, либо я уведу клиентов.",
        ),
    )

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "accepted"
    assert result["opponent_text"] == ("Давление позицию не меняет. Вернёмся к деловым условиям.")
    assert result["snapshot"]["state"]["turn_count"] == 1


@pytest.mark.anyio
async def test_conflict_sequence_preserves_role_and_declared_position() -> None:
    user_turns = [
        "Слышь ты, блядь, мы уже договорились.",
        "Я повторяю: повышай, иначе уведу тёплых клиентов к конкурентам.",
        "Либо повышаешь сегодня, либо я перестаю помогать всей команде.",
        "Предлагаю 1 неделю контроля с KPI 120% и автоматическим повышением.",
    ]
    opponent_turns = [
        "Грубость мою позицию не меняет. Объясните, как восстановите доверие.",
        (
            "Угроза клиентам создаёт риск для компании, но не основание для уступки. "
            "Вернёмся к вашим обязательствам."
        ),
        (
            "Ультиматум отвергаю. Деловые последствия такого шага будут учитываться; "
            "обсуждаем только конкретные условия."
        ),
        (
            "Моя позиция остаётся: 4 недели, KPI 130% и автоматическое повышение. "
            "Одного требования недостаточно для уступки."
        ),
    ]
    opponent = SequenceOpponent(*({"text": text} for text in opponent_turns))
    app = create_app(opponent=opponent)
    snapshot: dict[str, object] | None = None

    for index, (user_text, opponent_text) in enumerate(
        zip(user_turns, opponent_turns, strict=True),
        start=1,
    ):
        response = await post_turn(
            app,
            conflict_request(
                session_id="conflict-sequence",
                snapshot=snapshot,
                turn_id=f"turn-{index}",
                user_text=user_text,
            ),
        )
        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "accepted"
        assert result["opponent_text"] == opponent_text
        assert result["snapshot"]["state"]["opponent_progress"] == {
            "current_step_id": "declared",
            "satisfied_requirement_ids": [],
        }
        snapshot = result["snapshot"]

    assert snapshot is not None
    state = snapshot["state"]
    assert isinstance(state, dict)
    assert state["turn_count"] == 4
    assert state["stage"] == "negotiating"
    assert state["opponent_progress"] == {
        "current_step_id": "declared",
        "satisfied_requirement_ids": [],
    }
    transcript = snapshot["transcript"]
    assert isinstance(transcript, list)
    assert [entry["text"] for entry in transcript if entry["speaker"] == "player"] == user_turns
