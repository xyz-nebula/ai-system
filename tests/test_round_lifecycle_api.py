import httpx
import pytest
from fastapi import FastAPI

from arena_ai.app import create_app
from arena_ai.scenarios import NEXT_DAY_CASE

CASE = {
    "id": "next-day",
    "title": "На следующий день...",
    "shared_context": "Повышение после пропущенного дня.",
    "player_role": "Менеджер",
    "opponent_role": "Генеральный директор",
    "player_private_context": "Сохранить договорённость о повышении.",
    "opponent_private_context": "Добиться подтверждения ответственности.",
}


def deal_terms(*, control_weeks: int) -> dict[str, object]:
    return {
        "control_weeks": control_weeks,
        "kpi_percent": 120,
        "automatic_raise": True,
        "employee_commitments": ["Выполнить KPI 120%"],
        "director_commitments": ["Автоматически повысить зарплату"],
    }


def agreement_result(*, control_weeks: int) -> dict[str, object]:
    return {
        "text": (
            f"Согласен: {control_weeks} недели контроля, KPI 120%, затем повышение автоматически."
        ),
        "resolution": {"kind": "agreement", **deal_terms(control_weeks=control_weeks)},
    }


class SequenceOpponent:
    def __init__(self, *results: object) -> None:
        self.results = iter(results)

    async def respond(self, context: object) -> object:
        return next(self.results)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def post_turn(
    app: FastAPI,
    *,
    snapshot: dict[str, object],
    turn_id: str,
    user_text: str,
    case: dict[str, object] | None = None,
) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post(
            "/v1/turn",
            json={
                "case": CASE if case is None else case,
                "snapshot": snapshot,
                "turn_id": turn_id,
                "user_text": user_text,
            },
        )


@pytest.mark.anyio
async def test_confirmed_agreement_survives_a_followup_refusal() -> None:
    app = create_app(
        opponent=SequenceOpponent(
            agreement_result(control_weeks=2),
            {"text": "Ваш отказ позицию не меняет. Что именно вы предлагаете взамен?"},
        )
    )
    first = await post_turn(
        app,
        snapshot={"session_id": "continued-deal", "state": {"turn_count": 0}, "transcript": []},
        turn_id="turn-1",
        user_text=("Предлагаю 2 недели контроля, KPI 120% и автоматическое повышение."),
    )
    assert first.status_code == 200
    first_result = first.json()
    assert first_result["status"] == "accepted"

    second = await post_turn(
        app,
        snapshot=first_result["snapshot"],
        turn_id="turn-2",
        user_text="Я передумал и больше ни на что не согласен.",
    )

    assert second.status_code == 200
    result = second.json()
    assert result["status"] == "accepted"
    assert result["snapshot"]["state"]["turn_count"] == 2
    assert result["snapshot"]["state"]["stage"] == "agreed"
    assert (
        result["snapshot"]["state"]["agreement"] == first_result["snapshot"]["state"]["agreement"]
    )
    assert result["snapshot"]["transcript"][-2]["text"] == (
        "Я передумал и больше ни на что не согласен."
    )


@pytest.mark.anyio
async def test_unilateral_demand_cannot_replace_a_confirmed_agreement() -> None:
    app = create_app(
        opponent=SequenceOpponent(
            agreement_result(control_weeks=2),
            agreement_result(control_weeks=1),
        )
    )
    first = await post_turn(
        app,
        snapshot={"session_id": "protected-deal", "state": {"turn_count": 0}, "transcript": []},
        turn_id="turn-1",
        user_text=("Предлагаю 2 недели контроля, KPI 120% и автоматическое повышение."),
    )
    first_snapshot = first.json()["snapshot"]

    second = await post_turn(
        app,
        snapshot=first_snapshot,
        turn_id="turn-2",
        user_text="Повышай меня прямо сейчас, новых условий я не предлагаю.",
    )

    assert second.status_code == 200
    assert second.json()["status"] == "model_error"
    assert second.json()["snapshot"] == first_snapshot
    assert second.json()["snapshot"]["state"]["agreement"]["control_weeks"] == 2


@pytest.mark.anyio
async def test_bare_assent_cannot_silently_change_the_confirmed_terms() -> None:
    app = create_app(
        opponent=SequenceOpponent(
            agreement_result(control_weeks=2),
            agreement_result(control_weeks=1),
        )
    )
    first = await post_turn(
        app,
        snapshot={"session_id": "bare-assent", "state": {"turn_count": 0}, "transcript": []},
        turn_id="turn-1",
        user_text=("Предлагаю 2 недели контроля, KPI 120% и автоматическое повышение."),
    )
    first_snapshot = first.json()["snapshot"]

    second = await post_turn(
        app,
        snapshot=first_snapshot,
        turn_id="turn-2",
        user_text="Согласен.",
    )

    assert second.status_code == 200
    assert second.json()["status"] == "model_error"
    assert second.json()["snapshot"] == first_snapshot


@pytest.mark.anyio
@pytest.mark.parametrize(
    "user_text",
    [
        "Предлагаю 1 неделю, KPI 120%, но без автоматического повышения.",
        "Согласен на 1 неделю и KPI 120%, автоматического повышения не будет.",
        "Предлагаю 1 неделю, KPI 120%, но без гарантированного автоматического повышения.",
        "Предлагаю 1 неделю, KPI 120%, автоматическое повышение не входит в условия.",
    ],
)
async def test_agreement_rejects_player_contradiction_on_automatic_raise(
    user_text: str,
) -> None:
    app = create_app(opponent=SequenceOpponent(agreement_result(control_weeks=1)))

    response = await post_turn(
        app,
        snapshot={"session_id": "automatic-conflict", "state": {"turn_count": 0}, "transcript": []},
        turn_id="turn-1",
        user_text=user_text,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "model_error"


@pytest.mark.anyio
async def test_agreement_rejects_public_text_that_contradicts_automatic_raise() -> None:
    result = agreement_result(control_weeks=1)
    result["text"] = "Согласен: 1 неделя, KPI 120%, повышение не автоматическое."
    app = create_app(opponent=SequenceOpponent(result))

    response = await post_turn(
        app,
        snapshot={
            "session_id": "automatic-output-conflict",
            "state": {"turn_count": 0},
            "transcript": [],
        },
        turn_id="turn-1",
        user_text="Предлагаю 1 неделю, KPI 120% и автоматическое повышение.",
    )

    assert response.status_code == 200
    assert response.json()["status"] == "model_error"


@pytest.mark.anyio
async def test_agreement_rejects_unconfirmed_employee_commitment() -> None:
    result = agreement_result(control_weeks=1)
    resolution = result["resolution"]
    assert isinstance(resolution, dict)
    resolution["employee_commitments"] = ["Передать директору квартиру"]
    app = create_app(opponent=SequenceOpponent(result))

    response = await post_turn(
        app,
        snapshot={
            "session_id": "invented-commitment",
            "state": {"turn_count": 0},
            "transcript": [],
        },
        turn_id="turn-1",
        user_text="Предлагаю 1 неделю, KPI 120% и автоматическое повышение.",
    )

    assert response.status_code == 200
    assert response.json()["status"] == "model_error"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("commitment", "user_text"),
    [
        (
            "Выполнить KPI 999%",
            "Обязуюсь выполнить KPI 120%. Предлагаю 1 неделю, KPI 120% и автоматическое повышение.",
        ),
        (
            "Не компенсировать пропущенный день",
            "Компенсирую пропущенный день. Предлагаю 1 неделю, KPI 120% и автоматическое повышение.",
        ),
        (
            "Компенсировать пропущенный день",
            "Компенсировать пропущенный день не буду. Предлагаю 1 неделю, KPI 120% и автоматическое повышение.",
        ),
    ],
)
async def test_agreement_rejects_changed_employee_commitment(
    commitment: str, user_text: str
) -> None:
    result = agreement_result(control_weeks=1)
    resolution = result["resolution"]
    assert isinstance(resolution, dict)
    resolution["employee_commitments"] = [commitment]
    app = create_app(opponent=SequenceOpponent(result))

    response = await post_turn(
        app,
        snapshot={"session_id": "changed-commitment", "state": {"turn_count": 0}, "transcript": []},
        turn_id="turn-1",
        user_text=user_text,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "model_error"


@pytest.mark.anyio
async def test_agreement_rejects_unstated_director_commitment() -> None:
    result = agreement_result(control_weeks=1)
    resolution = result["resolution"]
    assert isinstance(resolution, dict)
    resolution["director_commitments"] = [
        "Автоматически повысить зарплату и передать сотруднику квартиру"
    ]
    app = create_app(opponent=SequenceOpponent(result))

    response = await post_turn(
        app,
        snapshot={
            "session_id": "invented-director-promise",
            "state": {"turn_count": 0},
            "transcript": [],
        },
        turn_id="turn-1",
        user_text="Предлагаю 1 неделю, KPI 120% и автоматическое повышение.",
    )

    assert response.status_code == 200
    assert response.json()["status"] == "model_error"


@pytest.mark.anyio
async def test_director_commitment_cannot_contradict_nonautomatic_raise() -> None:
    case: dict[str, object] = {
        **CASE,
        "agreement_rules": {
            "min_control_weeks": 1,
            "max_control_weeks": 4,
            "min_kpi_percent": 100,
            "max_kpi_percent": 130,
            "require_automatic_raise": False,
        },
    }
    app = create_app(
        opponent=SequenceOpponent(
            {
                "text": "Согласен: 1 неделя, KPI 120%, повышение не автоматическое.",
                "resolution": {
                    "kind": "agreement",
                    "control_weeks": 1,
                    "kpi_percent": 120,
                    "automatic_raise": False,
                    "employee_commitments": ["Выполнить KPI 120%"],
                    "director_commitments": ["Автоматически повысить зарплату"],
                },
            }
        )
    )

    response = await post_turn(
        app,
        case=case,
        snapshot={
            "session_id": "contradictory-director-promise",
            "state": {"turn_count": 0},
            "transcript": [],
        },
        turn_id="turn-1",
        user_text="Предлагаю 1 неделю контроля, KPI 120%, повышение не автоматическое.",
    )

    assert response.status_code == 200
    assert response.json()["status"] == "model_error"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "user_text",
    [
        "Директор должен компенсировать пропущенный день. Предлагаю 1 неделю, KPI 120% и автоматическое повышение.",
        "Кто компенсирует пропущенный день? Предлагаю 1 неделю, KPI 120% и автоматическое повышение.",
        "Предлагаю 1 неделю, KPI 120% и автоматическое повышение, а он должен компенсировать пропущенный день.",
        "Предлагаю 1 неделю, KPI 120% и автоматическое повышение, а вы компенсируете пропущенный день.",
    ],
)
async def test_employee_commitment_needs_player_promise(user_text: str) -> None:
    result = agreement_result(control_weeks=1)
    resolution = result["resolution"]
    assert isinstance(resolution, dict)
    resolution["employee_commitments"] = ["Компенсировать пропущенный день"]
    app = create_app(opponent=SequenceOpponent(result))

    response = await post_turn(
        app,
        snapshot={"session_id": "no-player-promise", "state": {"turn_count": 0}, "transcript": []},
        turn_id="turn-1",
        user_text=user_text,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "model_error"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "user_text",
    [
        "Директор должен выполнить KPI 120%. Предлагаю 1 неделю, KPI 120% и автоматическое повышение.",
        "Кто должен выполнить KPI 120%? Предлагаю 1 неделю, KPI 120% и автоматическое повышение.",
        "Предлагаю 1 неделю, KPI 120% и автоматическое повышение, а вы должны выполнить KPI 120%.",
        "Предлагаю 1 неделю, KPI 120% и автоматическое повышение, а он выполнит KPI 120%.",
    ],
)
async def test_kpi_employee_commitment_cannot_have_ambiguous_owner(user_text: str) -> None:
    app = create_app(opponent=SequenceOpponent(agreement_result(control_weeks=1)))

    response = await post_turn(
        app,
        snapshot={
            "session_id": "ambiguous-kpi-owner",
            "state": {"turn_count": 0},
            "transcript": [],
        },
        turn_id="turn-1",
        user_text=user_text,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "model_error"


@pytest.mark.anyio
async def test_opponent_public_answer_cannot_deny_structured_employee_commitment() -> None:
    result = agreement_result(control_weeks=1)
    result["text"] = (
        "Согласен: 1 неделя, KPI 120%, повышение автоматически. "
        "Но компенсировать пропущенный день не нужно."
    )
    resolution = result["resolution"]
    assert isinstance(resolution, dict)
    resolution["employee_commitments"] = ["Компенсировать пропущенный день"]
    app = create_app(opponent=SequenceOpponent(result))

    response = await post_turn(
        app,
        snapshot={
            "session_id": "contradictory-public-answer",
            "state": {"turn_count": 0},
            "transcript": [],
        },
        turn_id="turn-1",
        user_text=(
            "Компенсирую пропущенный день. Предлагаю 1 неделю, KPI 120% и автоматическое повышение."
        ),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "model_error"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "user_text",
    [
        "Согласен, но компенсировать пропущенный день не буду.",
        "Согласен, но отказываюсь компенсировать пропущенный день.",
        "Согласен, но только на 2 недели контроля.",
        "Согласен, но без автоматического повышения.",
    ],
)
async def test_prior_offer_cannot_override_express_player_objection(user_text: str) -> None:
    result = agreement_result(control_weeks=1)
    resolution = result["resolution"]
    assert isinstance(resolution, dict)
    resolution["employee_commitments"] = ["Компенсировать пропущенный день"]
    app = create_app(
        opponent=SequenceOpponent(
            {
                "text": (
                    "Предлагаю 1 неделю контроля, KPI 120% и автоматическое повышение; "
                    "вы компенсируете пропущенный день."
                )
            },
            result,
        )
    )
    first = await post_turn(
        app,
        snapshot={
            "session_id": "offer-with-objection",
            "state": {"turn_count": 0},
            "transcript": [],
        },
        turn_id="turn-1",
        user_text="Какие условия вы предлагаете?",
    )
    assert first.json()["status"] == "accepted"

    second = await post_turn(
        app,
        snapshot=first.json()["snapshot"],
        turn_id="turn-2",
        user_text=user_text,
    )

    assert second.status_code == 200
    assert second.json()["status"] == "model_error"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "user_text",
    [
        "Не предлагаю 1 неделю, KPI 120% и автоматическое повышение.",
        "Я не говорил, что предлагаю 1 неделю, KPI 120% и автоматическое повышение.",
    ],
)
async def test_negated_player_deal_terms_are_not_an_offer(user_text: str) -> None:
    app = create_app(opponent=SequenceOpponent(agreement_result(control_weeks=1)))

    response = await post_turn(
        app,
        snapshot={"session_id": "negated-deal-offer", "state": {"turn_count": 0}, "transcript": []},
        turn_id="turn-1",
        user_text=user_text,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "model_error"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "user_text",
    [
        "Готов обсуждать 1 неделю, KPI 120% и автоматическое повышение.",
        "Готов рассмотреть 1 неделю, KPI 120% и автоматическое повышение.",
        "Предлагаю обсудить 1 неделю, KPI 120% и автоматическое повышение.",
        "Готов внимательно обсудить 1 неделю, KPI 120% и автоматическое повышение.",
        "Я готов к обсуждению 1 недели, KPI 120% и автоматического повышения.",
        "Предлагаю сначала рассмотреть 1 неделю, KPI 120% и автоматическое повышение.",
        "Готов обсудить 1 неделю, KPI 120% и автоматическое повышение. Обязуюсь выполнить KPI 120%.",
    ],
)
async def test_readiness_to_discuss_is_not_a_complete_offer(user_text: str) -> None:
    app = create_app(opponent=SequenceOpponent(agreement_result(control_weeks=1)))

    response = await post_turn(
        app,
        snapshot={
            "session_id": "discussion-not-deal",
            "state": {"turn_count": 0},
            "transcript": [],
        },
        turn_id="turn-1",
        user_text=user_text,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "model_error"


@pytest.mark.anyio
async def test_opponent_discussion_intent_cannot_set_agreement() -> None:
    result = agreement_result(control_weeks=1)
    result["text"] = "Согласен внимательно обсудить: 1 неделя, KPI 120%, повышение автоматически."
    app = create_app(opponent=SequenceOpponent(result))

    response = await post_turn(
        app,
        snapshot={
            "session_id": "opponent-discussion-only",
            "state": {"turn_count": 0},
            "transcript": [],
        },
        turn_id="turn-1",
        user_text="Предлагаю 1 неделю контроля, KPI 120% и автоматическое повышение.",
    )

    assert response.status_code == 200
    assert response.json()["status"] == "model_error"


@pytest.mark.anyio
async def test_bare_assent_cannot_accept_opponent_nonoffer() -> None:
    app = create_app(
        opponent=SequenceOpponent(
            {"text": "Я не предлагаю 1 неделю, KPI 120% и автоматическое повышение."},
            agreement_result(control_weeks=1),
        )
    )
    first = await post_turn(
        app,
        snapshot={"session_id": "not-an-offer", "state": {"turn_count": 0}, "transcript": []},
        turn_id="turn-1",
        user_text="Какие условия вы предлагаете?",
    )
    assert first.json()["status"] == "accepted"

    second = await post_turn(
        app,
        snapshot=first.json()["snapshot"],
        turn_id="turn-2",
        user_text="Согласен.",
    )

    assert second.status_code == 200
    assert second.json()["status"] == "model_error"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "user_text",
    ["Согласен обсудить.", "Согласен рассмотреть.", "Согласен вернуться к этому позже."],
)
async def test_discussion_intent_cannot_accept_a_valid_prior_offer(user_text: str) -> None:
    app = create_app(
        opponent=SequenceOpponent(
            {"text": "Предлагаю 1 неделю, KPI 120% и автоматическое повышение."},
            agreement_result(control_weeks=1),
        )
    )
    first = await post_turn(
        app,
        snapshot={
            "session_id": "discussion-after-offer",
            "state": {"turn_count": 0},
            "transcript": [],
        },
        turn_id="turn-1",
        user_text="Какие условия вы предлагаете?",
    )
    assert first.json()["status"] == "accepted"

    second = await post_turn(
        app,
        snapshot=first.json()["snapshot"],
        turn_id="turn-2",
        user_text=user_text,
    )

    assert second.status_code == 200
    assert second.json()["status"] == "model_error"


@pytest.mark.anyio
async def test_strategy_agreement_rejects_omitted_employee_obligations() -> None:
    strategy = NEXT_DAY_CASE.opponent_strategy
    assert strategy is not None
    target = strategy.steps[1]
    user_text = "Предлагаю 2 недели контроля, KPI 120% и автоматическое повышение."
    app = create_app(
        opponent=SequenceOpponent(
            {
                "text": "Согласен: 2 недели контроля, KPI 120% и автоматическое повышение.",
                "resolution": {"kind": "agreement", **target.terms.model_dump(mode="json")},
                "position_transition": {
                    "to_step_id": "target",
                    "requirement_ids": ["measurable-trial"],
                    "evidence_quote": user_text,
                },
            }
        )
    )

    response = await post_turn(
        app,
        case=NEXT_DAY_CASE.model_dump(mode="json"),
        snapshot={
            "session_id": "implicit-strategy-obligations",
            "state": {"turn_count": 0},
            "transcript": [],
        },
        turn_id="turn-1",
        user_text=user_text,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "model_error"


@pytest.mark.anyio
async def test_strategy_terms_can_be_offered_then_explicitly_accepted() -> None:
    strategy = NEXT_DAY_CASE.opponent_strategy
    assert strategy is not None
    target = strategy.steps[1]
    user_offer = "Предлагаю 2 недели контроля, KPI 120% и автоматическое повышение."
    app = create_app(
        opponent=SequenceOpponent(
            {
                "text": (
                    "Готов предложить 2 недели контроля, KPI 120% и автоматическое повышение. "
                    "Вы компенсируете последствия пропуска. "
                    "Вы выполняете KPI 120% за две недели. "
                    "Вы не допускаете новых нарушений дисциплины. "
                    "Вы сообщаете о форс-мажоре сразу."
                ),
                "position_transition": {
                    "to_step_id": "target",
                    "requirement_ids": ["measurable-trial"],
                    "evidence_quote": user_offer,
                },
            },
            {
                "text": "Согласен: 2 недели контроля, KPI 120% и автоматическое повышение.",
                "resolution": {"kind": "agreement", **target.terms.model_dump(mode="json")},
            },
        )
    )
    first = await post_turn(
        app,
        case=NEXT_DAY_CASE.model_dump(mode="json"),
        snapshot={
            "session_id": "strategy-offer-confirmation",
            "state": {"turn_count": 0},
            "transcript": [],
        },
        turn_id="turn-1",
        user_text=user_offer,
    )
    assert first.json()["status"] == "accepted"
    assert first.json()["snapshot"]["state"].get("agreement") is None

    second = await post_turn(
        app,
        case=NEXT_DAY_CASE.model_dump(mode="json"),
        snapshot=first.json()["snapshot"],
        turn_id="turn-2",
        user_text="Согласен с этим предложением.",
    )

    assert second.status_code == 200
    assert second.json()["status"] == "accepted"
    assert second.json()["snapshot"]["state"]["agreement"] == target.terms.model_dump(mode="json")


@pytest.mark.anyio
async def test_public_text_cannot_contradict_stored_agreement_without_strategy() -> None:
    app = create_app(
        opponent=SequenceOpponent(
            agreement_result(control_weeks=2),
            {"text": ("Тогда договорились: 1 неделя, KPI 120% и автоматическое повышение.")},
        )
    )
    first = await post_turn(
        app,
        snapshot={"session_id": "text-conflict", "state": {"turn_count": 0}, "transcript": []},
        turn_id="turn-1",
        user_text=("Предлагаю 2 недели контроля, KPI 120% и автоматическое повышение."),
    )
    first_snapshot = first.json()["snapshot"]

    second = await post_turn(
        app,
        snapshot=first_snapshot,
        turn_id="turn-2",
        user_text="Повышай меня быстрее.",
    )

    assert second.status_code == 200
    assert second.json()["status"] == "model_error"
    assert second.json()["snapshot"] == first_snapshot


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("later_result", "user_text"),
    [
        (
            {
                "text": "Согласован KPI, срок пока остаётся открытым.",
                "resolution": {
                    "kind": "partial_agreement",
                    "commitments": ["Выполнить KPI 120%"],
                    "open_points": ["Срок контроля"],
                },
            },
            "Предлагаю согласовать KPI, а срок оставить открытым.",
        ),
        (
            {
                "text": "Вернёмся к решению завтра.",
                "resolution": {
                    "kind": "deferred",
                    "reason": "Нужно дополнительное обсуждение",
                    "next_step": "Вернуться к разговору завтра",
                },
            },
            "Предлагаю отложить решение и вернуться завтра.",
        ),
    ],
)
async def test_partial_or_deferred_result_cannot_downgrade_confirmed_agreement(
    later_result: dict[str, object],
    user_text: str,
) -> None:
    app = create_app(
        opponent=SequenceOpponent(
            agreement_result(control_weeks=2),
            later_result,
        )
    )
    first = await post_turn(
        app,
        snapshot={"session_id": "no-downgrade", "state": {"turn_count": 0}, "transcript": []},
        turn_id="turn-1",
        user_text=("Предлагаю 2 недели контроля, KPI 120% и автоматическое повышение."),
    )
    first_snapshot = first.json()["snapshot"]

    second = await post_turn(
        app,
        snapshot=first_snapshot,
        turn_id="turn-2",
        user_text=user_text,
    )

    assert second.status_code == 200
    assert second.json()["status"] == "model_error"
    assert second.json()["snapshot"] == first_snapshot


@pytest.mark.anyio
async def test_latest_mutually_confirmed_agreement_replaces_previous_version_at_finish() -> None:
    app = create_app(
        opponent=SequenceOpponent(
            agreement_result(control_weeks=2),
            agreement_result(control_weeks=1),
        )
    )
    first = await post_turn(
        app,
        snapshot={"session_id": "revised-deal", "state": {"turn_count": 0}, "transcript": []},
        turn_id="turn-1",
        user_text=("Предлагаю 2 недели контроля, KPI 120% и автоматическое повышение."),
    )
    second = await post_turn(
        app,
        snapshot=first.json()["snapshot"],
        turn_id="turn-2",
        user_text=("Тогда предлагаю 1 неделю контроля, KPI 120% и автоматическое повышение."),
    )
    assert second.status_code == 200
    assert second.json()["status"] == "accepted"
    assert second.json()["snapshot"]["state"]["agreement"]["control_weeks"] == 1

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        finish = await client.post(
            "/v1/finish",
            json={"case": CASE, "snapshot": second.json()["snapshot"]},
        )

    assert finish.status_code == 200
    assert finish.json()["outcome"]["kind"] == "agreement"
    assert finish.json()["outcome"]["agreement"]["control_weeks"] == 1


@pytest.mark.anyio
async def test_legacy_agreed_snapshot_remains_readable_and_accepts_another_turn() -> None:
    legacy_snapshot: dict[str, object] = {
        "session_id": "legacy-agreed",
        "state": {
            "turn_count": 1,
            "stage": "agreed",
            "agreement": deal_terms(control_weeks=2),
        },
        "transcript": [
            {
                "turn_id": "turn-1",
                "speaker": "player",
                "status": "accepted",
                "text": "Предлагаю 2 недели, KPI 120% и автоматическое повышение.",
            },
            {
                "turn_id": "turn-1",
                "speaker": "opponent",
                "status": "accepted",
                "text": "Согласен: 2 недели, KPI 120%, повышение автоматически.",
            },
        ],
    }
    agreement = deal_terms(control_weeks=2)
    app = create_app(
        opponent=SequenceOpponent({"text": "Продолжим: какие детали вы хотите уточнить?"})
    )

    response = await post_turn(
        app,
        snapshot=legacy_snapshot,
        turn_id="turn-2",
        user_text="Хочу уточнить порядок проверки KPI.",
    )

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert response.json()["snapshot"]["state"]["agreement"] == agreement


@pytest.mark.anyio
async def test_legacy_agreement_restores_matching_strategy_position() -> None:
    strategy = NEXT_DAY_CASE.opponent_strategy
    assert strategy is not None
    target = strategy.steps[1]
    legacy_snapshot: dict[str, object] = {
        "session_id": "legacy-strategy-agreement",
        "state": {
            "turn_count": 1,
            "stage": "agreed",
            "agreement": target.terms.model_dump(mode="json"),
        },
        "transcript": [
            {
                "turn_id": "turn-1",
                "speaker": "player",
                "status": "accepted",
                "text": "Предлагаю 2 недели, KPI 120% и автоматическое повышение.",
            },
            {
                "turn_id": "turn-1",
                "speaker": "opponent",
                "status": "accepted",
                "text": "Согласен: 2 недели, KPI 120%, повышение автоматически.",
            },
        ],
    }
    app = create_app(opponent=SequenceOpponent({"text": "Продолжим с уже согласованной позиции."}))

    response = await post_turn(
        app,
        case=NEXT_DAY_CASE.model_dump(mode="json"),
        snapshot=legacy_snapshot,
        turn_id="turn-2",
        user_text="Хочу уточнить порядок проверки результата.",
    )

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert response.json()["snapshot"]["state"]["agreement"] == target.terms.model_dump(mode="json")
    assert response.json()["snapshot"]["state"]["opponent_progress"] == {
        "current_step_id": "target",
        "satisfied_requirement_ids": ["measurable-trial"],
        "restored_from_agreement": True,
    }


@pytest.mark.anyio
async def test_unmatched_legacy_agreement_rejects_contradictory_position_terms() -> None:
    legacy_agreement = {
        "control_weeks": 3,
        "kpi_percent": 125,
        "automatic_raise": True,
        "employee_commitments": ["Выполнить KPI 125% за три недели"],
        "director_commitments": ["Автоматически повысить зарплату"],
    }
    legacy_snapshot: dict[str, object] = {
        "session_id": "legacy-unmatched-agreement",
        "state": {
            "turn_count": 1,
            "stage": "agreed",
            "agreement": legacy_agreement,
        },
        "transcript": [
            {
                "turn_id": "turn-1",
                "speaker": "player",
                "status": "accepted",
                "text": "Согласен на 3 недели, KPI 125% и автоматическое повышение.",
            },
            {
                "turn_id": "turn-1",
                "speaker": "opponent",
                "status": "accepted",
                "text": "Согласен: 3 недели, KPI 125%, повышение автоматически.",
            },
        ],
    }
    app = create_app(
        opponent=SequenceOpponent(
            {"text": ("Моя новая позиция: 1 неделя, KPI 120% и автоматическое повышение.")}
        )
    )

    response = await post_turn(
        app,
        case=NEXT_DAY_CASE.model_dump(mode="json"),
        snapshot=legacy_snapshot,
        turn_id="turn-2",
        user_text="Хочу уточнить порядок проверки результата.",
    )

    assert response.status_code == 200
    assert response.json()["status"] == "model_error"
    assert response.json()["snapshot"] == legacy_snapshot


@pytest.mark.anyio
async def test_unmatched_legacy_agreement_can_move_to_next_valid_strategy_step() -> None:
    strategy = NEXT_DAY_CASE.opponent_strategy
    assert strategy is not None
    target = strategy.steps[1]
    legacy_agreement = {
        "control_weeks": 3,
        "kpi_percent": 125,
        "automatic_raise": True,
        "employee_commitments": ["Выполнить KPI 125% за три недели"],
        "director_commitments": ["Автоматически повысить зарплату"],
    }
    legacy_snapshot: dict[str, object] = {
        "session_id": "legacy-valid-replacement",
        "state": {
            "turn_count": 1,
            "stage": "agreed",
            "agreement": legacy_agreement,
        },
        "transcript": [
            {
                "turn_id": "turn-1",
                "speaker": "player",
                "status": "accepted",
                "text": "Согласен на 3 недели, KPI 125% и автоматическое повышение.",
            },
            {
                "turn_id": "turn-1",
                "speaker": "opponent",
                "status": "accepted",
                "text": "Согласен: 3 недели, KPI 125%, повышение автоматически.",
            },
        ],
    }
    user_text = (
        "Предлагаю 2 недели, KPI 120% и автоматическое повышение. "
        "Обязуюсь компенсировать последствия пропуска. "
        "Обязуюсь не допускать новых нарушений дисциплины. "
        "Обязуюсь сообщать о форс-мажоре сразу."
    )
    app = create_app(
        opponent=SequenceOpponent(
            {
                "text": ("Согласен: 2 недели, KPI 120% и автоматическое повышение."),
                "resolution": {
                    "kind": "agreement",
                    **target.terms.model_dump(mode="json"),
                },
                "position_transition": {
                    "to_step_id": "target",
                    "requirement_ids": ["measurable-trial"],
                    "evidence_quote": user_text,
                },
            }
        )
    )

    response = await post_turn(
        app,
        case=NEXT_DAY_CASE.model_dump(mode="json"),
        snapshot=legacy_snapshot,
        turn_id="turn-2",
        user_text=user_text,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert response.json()["snapshot"]["state"]["agreement"] == target.terms.model_dump(mode="json")
    assert response.json()["snapshot"]["state"]["opponent_progress"]["current_step_id"] == "target"


@pytest.mark.anyio
async def test_unmatched_legacy_agreement_cannot_skip_strategy_evidence() -> None:
    strategy = NEXT_DAY_CASE.opponent_strategy
    assert strategy is not None
    red_line = strategy.steps[2]
    legacy_agreement = {
        "control_weeks": 1,
        "kpi_percent": 125,
        "automatic_raise": True,
        "employee_commitments": ["Выполнить KPI 125% за неделю"],
        "director_commitments": ["Автоматически повысить зарплату"],
    }
    legacy_snapshot: dict[str, object] = {
        "session_id": "legacy-missing-step-evidence",
        "state": {"turn_count": 1, "stage": "agreed", "agreement": legacy_agreement},
        "transcript": [
            {
                "turn_id": "turn-1",
                "speaker": "player",
                "status": "accepted",
                "text": "Согласен на KPI 125% за неделю.",
            },
            {"turn_id": "turn-1", "speaker": "opponent", "status": "accepted", "text": "Согласен."},
        ],
    }
    user_text = (
        "Условия: 1 неделя, KPI 120% и автоматическое повышение. "
        "Беру на себя закрыть последствия пропуска и сообщать о форс-мажоре сразу."
    )
    app = create_app(
        opponent=SequenceOpponent(
            {
                "text": "Согласен: 1 неделя, KPI 120% и автоматическое повышение.",
                "resolution": {"kind": "agreement", **red_line.terms.model_dump(mode="json")},
                "position_transition": {
                    "to_step_id": "red-line",
                    "requirement_ids": ["prevent-repeat"],
                    "evidence_quote": user_text,
                },
            }
        )
    )

    response = await post_turn(
        app,
        case=NEXT_DAY_CASE.model_dump(mode="json"),
        snapshot=legacy_snapshot,
        turn_id="turn-2",
        user_text=user_text,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "model_error"
    assert response.json()["snapshot"] == legacy_snapshot


@pytest.mark.anyio
async def test_restored_progress_requires_its_matching_stored_agreement() -> None:
    forged_snapshot: dict[str, object] = {
        "session_id": "forged-restored-progress",
        "state": {
            "turn_count": 0,
            "stage": "negotiating",
            "opponent_progress": {
                "current_step_id": "target",
                "satisfied_requirement_ids": ["measurable-trial"],
                "restored_from_agreement": True,
            },
        },
        "transcript": [],
    }
    app = create_app(opponent=SequenceOpponent({"text": "Продолжим обсуждать конкретные условия."}))

    response = await post_turn(
        app,
        case=NEXT_DAY_CASE.model_dump(mode="json"),
        snapshot=forged_snapshot,
        turn_id="turn-1",
        user_text="Какие условия вы предлагаете?",
    )

    assert response.status_code == 200
    assert response.json()["status"] == "model_error"
    assert response.json()["snapshot"] == forged_snapshot


@pytest.mark.anyio
@pytest.mark.parametrize(
    "opponent_text",
    [
        "Внутренний флаг restored_from_agreement=true.",
        "Моя позиция была восстановлена из сохранённой договорённости.",
        "Сохранённое соглашение позволило восстановить мою позицию.",
    ],
)
async def test_restored_progress_marker_cannot_be_echoed_to_public_text(
    opponent_text: str,
) -> None:
    app = create_app(opponent=SequenceOpponent({"text": opponent_text}))
    snapshot: dict[str, object] = {
        "session_id": "private-restored-marker",
        "state": {"turn_count": 0},
        "transcript": [],
    }

    response = await post_turn(
        app,
        case=NEXT_DAY_CASE.model_dump(mode="json"),
        snapshot=snapshot,
        turn_id="turn-1",
        user_text="Продолжим обсуждение.",
    )

    assert response.status_code == 200
    assert response.json()["status"] == "model_error"
    assert opponent_text not in response.text
