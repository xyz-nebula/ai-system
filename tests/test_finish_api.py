import httpx
import pytest

from arena_ai.app import OpponentContext, create_app


class DealOpponent:
    async def respond(self, context: object) -> object:
        return {
            "text": "Согласен: одна неделя, KPI 120%, затем повышение автоматически.",
            "agreement": {
                "control_weeks": 1,
                "kpi_percent": 120,
                "automatic_raise": True,
                "employee_commitments": ["Компенсировать пропущенный день"],
                "director_commitments": ["Повысить зарплату после выполнения KPI"],
            },
        }


class PartialOpponent:
    async def respond(self, context: object) -> object:
        return {
            "text": "Согласуем компенсацию пропуска; KPI и дату повышения пока оставим открытыми.",
            "decision": {
                "kind": "partial_agreement",
                "commitments": ["Компенсировать пропущенный день"],
                "open_points": ["KPI и дата повышения"],
            },
        }


class DeferringOpponent:
    async def respond(self, context: object) -> object:
        return {
            "text": "Вернёмся к решению завтра после уточнения KPI.",
            "decision": {
                "kind": "deferred",
                "reason": "Нужно уточнить измеримый KPI",
                "next_step": "Завтра согласовать KPI и дату повышения",
            },
        }


class OfferThenDealOpponent:
    async def respond(self, context: OpponentContext) -> object:
        if context.state.turn_count == 0:
            return {"text": "Предлагаю одну неделю контроля и KPI 120%."}
        return {
            "text": "Согласен: одна неделя, KPI 120%, затем повышение автоматически.",
            "agreement": {
                "control_weeks": 1,
                "kpi_percent": 120,
                "automatic_raise": True,
                "employee_commitments": ["Компенсировать пропуск"],
                "director_commitments": ["Повысить зарплату после KPI"],
            },
        }


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_finishing_a_duel_without_a_deal_reports_no_agreement() -> None:
    case = {
        "id": "next-day",
        "title": "На следующий день...",
        "shared_context": "Менеджер и директор обсуждают повышение после пропуска.",
        "player_role": "Менеджер",
        "opponent_role": "Генеральный директор",
        "player_private_context": "Сохранить договорённость.",
        "opponent_private_context": "Минимум одна контрольная неделя.",
    }
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        turn = await client.post(
            "/v1/turn",
            json={
                "case": case,
                "snapshot": {
                    "session_id": "demo-finish",
                    "state": {"turn_count": 0},
                    "transcript": [],
                },
                "turn_id": "turn-1",
                "user_text": "Как восстановить ваше доверие?",
            },
        )
        assert turn.status_code == 200
        finish = await client.post(
            "/v1/finish", json={"case": case, "snapshot": turn.json()["snapshot"]}
        )

    assert finish.status_code == 200
    outcome = finish.json()["outcome"]
    assert outcome["kind"] == "no_agreement"
    assert outcome["agreement"] is None
    assert outcome["commitments"] == []
    assert "judge_verdicts" not in finish.json()


@pytest.mark.anyio
async def test_finished_agreement_reports_both_sides_commitments_without_skill_score() -> None:
    case = {
        "id": "next-day",
        "title": "На следующий день...",
        "shared_context": "Повышение после пропущенного дня.",
        "player_role": "Менеджер",
        "opponent_role": "Генеральный директор",
        "player_private_context": "Не больше месяца контроля.",
        "opponent_private_context": "Не меньше недели контроля.",
    }
    app = create_app(opponent=DealOpponent())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        turn = await client.post(
            "/v1/turn",
            json={
                "case": case,
                "snapshot": {
                    "session_id": "demo-agreement",
                    "state": {"turn_count": 0},
                    "transcript": [],
                },
                "turn_id": "turn-1",
                "user_text": "Предлагаю неделю контроля и KPI 120% с автоматическим повышением.",
            },
        )
        assert turn.status_code == 200
        assert turn.json()["status"] == "accepted"
        finish = await client.post(
            "/v1/finish", json={"case": case, "snapshot": turn.json()["snapshot"]}
        )

    assert finish.status_code == 200
    outcome = finish.json()["outcome"]
    assert outcome["kind"] == "agreement"
    assert outcome["agreement"]["control_weeks"] == 1
    assert outcome["agreement"]["kpi_percent"] == 120
    assert outcome["commitments"] == [
        "Компенсировать пропущенный день",
        "Повысить зарплату после выполнения KPI",
    ]
    assert "score" not in outcome


@pytest.mark.anyio
async def test_finish_reports_partial_agreement_and_open_points() -> None:
    case = {
        "id": "next-day",
        "title": "На следующий день...",
        "shared_context": "Повышение после пропуска.",
        "player_role": "Менеджер",
        "opponent_role": "Генеральный директор",
        "player_private_context": "Хочу сохранить договорённость.",
        "opponent_private_context": "Хочу дополнительных гарантий.",
    }
    app = create_app(opponent=PartialOpponent())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        turn = await client.post(
            "/v1/turn",
            json={
                "case": case,
                "snapshot": {
                    "session_id": "demo-partial",
                    "state": {"turn_count": 0},
                    "transcript": [],
                },
                "turn_id": "turn-1",
                "user_text": "Готов компенсировать пропуск, KPI обсудим отдельно.",
            },
        )
        assert turn.status_code == 200
        assert turn.json()["status"] == "accepted"
        finish = await client.post(
            "/v1/finish", json={"case": case, "snapshot": turn.json()["snapshot"]}
        )

    assert finish.status_code == 200
    assert finish.json()["outcome"]["kind"] == "partial_agreement"
    assert finish.json()["outcome"]["commitments"] == ["Компенсировать пропущенный день"]
    assert finish.json()["outcome"]["open_points"] == ["KPI и дата повышения"]
    assert finish.json()["outcome"]["agreement"] is None


@pytest.mark.anyio
async def test_finish_reports_deferral_and_next_step() -> None:
    case = {
        "id": "next-day",
        "title": "На следующий день...",
        "shared_context": "Повышение после пропуска.",
        "player_role": "Менеджер",
        "opponent_role": "Генеральный директор",
        "player_private_context": "Хочу сохранить договорённость.",
        "opponent_private_context": "Хочу дополнительных гарантий.",
    }
    app = create_app(opponent=DeferringOpponent())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        turn = await client.post(
            "/v1/turn",
            json={
                "case": case,
                "snapshot": {
                    "session_id": "demo-deferred",
                    "state": {"turn_count": 0},
                    "transcript": [],
                },
                "turn_id": "turn-1",
                "user_text": "Предлагаю завтра зафиксировать KPI.",
            },
        )
        assert turn.status_code == 200
        assert turn.json()["status"] == "accepted"
        finish = await client.post(
            "/v1/finish", json={"case": case, "snapshot": turn.json()["snapshot"]}
        )

    assert finish.status_code == 200
    assert finish.json()["outcome"]["kind"] == "deferred"
    assert finish.json()["outcome"]["next_step"] == "Завтра согласовать KPI и дату повышения"
    assert finish.json()["outcome"]["agreement"] is None


@pytest.mark.anyio
async def test_opponent_cannot_record_agreement_without_player_offer_or_assent() -> None:
    case = {
        "id": "next-day",
        "title": "На следующий день...",
        "shared_context": "Повышение после пропуска.",
        "player_role": "Менеджер",
        "opponent_role": "Генеральный директор",
        "player_private_context": "Хочу сохранить договорённость.",
        "opponent_private_context": "Хочу дополнительных гарантий.",
    }
    app = create_app(opponent=DealOpponent())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        turn = await client.post(
            "/v1/turn",
            json={
                "case": case,
                "snapshot": {
                    "session_id": "demo-refusal",
                    "state": {"turn_count": 0},
                    "transcript": [],
                },
                "turn_id": "turn-1",
                "user_text": "Повышение пока обсуждать не готов.",
            },
        )

    assert turn.status_code == 200
    assert turn.json()["status"] == "model_error"
    assert turn.json()["snapshot"]["state"]["turn_count"] == 0


@pytest.mark.anyio
async def test_opponent_cannot_unilaterally_record_partial_or_deferred_decision() -> None:
    case = {
        "id": "next-day",
        "title": "На следующий день...",
        "shared_context": "Повышение после пропуска.",
        "player_role": "Менеджер",
        "opponent_role": "Генеральный директор",
        "player_private_context": "Хочу сохранить договорённость.",
        "opponent_private_context": "Хочу дополнительных гарантий.",
    }
    for opponent, user_text in [
        (PartialOpponent(), "Компенсировать пропуск не буду."),
        (DeferringOpponent(), "Не хочу откладывать решение."),
    ]:
        app = create_app(opponent=opponent)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            turn = await client.post(
                "/v1/turn",
                json={
                    "case": case,
                    "snapshot": {
                        "session_id": "demo-refusal",
                        "state": {"turn_count": 0},
                        "transcript": [],
                    },
                    "turn_id": "turn-1",
                    "user_text": user_text,
                },
            )

        assert turn.status_code == 200
        assert turn.json()["status"] == "model_error"
        assert turn.json()["snapshot"]["state"]["turn_count"] == 0


@pytest.mark.anyio
async def test_bare_assent_without_any_offer_does_not_create_an_agreement() -> None:
    case = {
        "id": "next-day",
        "title": "На следующий день...",
        "shared_context": "Повышение после пропуска.",
        "player_role": "Менеджер",
        "opponent_role": "Генеральный директор",
        "player_private_context": "Хочу сохранить договорённость.",
        "opponent_private_context": "Хочу дополнительных гарантий.",
    }
    app = create_app(opponent=DealOpponent())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        turn = await client.post(
            "/v1/turn",
            json={
                "case": case,
                "snapshot": {
                    "session_id": "demo-bare-assent",
                    "state": {"turn_count": 0},
                    "transcript": [],
                },
                "turn_id": "turn-1",
                "user_text": "Согласен.",
            },
        )

    assert turn.status_code == 200
    assert turn.json()["status"] == "model_error"


@pytest.mark.anyio
async def test_player_can_accept_terms_from_a_previous_opponent_offer() -> None:
    case = {
        "id": "next-day",
        "title": "На следующий день...",
        "shared_context": "Повышение после пропуска.",
        "player_role": "Менеджер",
        "opponent_role": "Генеральный директор",
        "player_private_context": "Хочу сохранить договорённость.",
        "opponent_private_context": "Хочу дополнительных гарантий.",
    }
    app = create_app(opponent=OfferThenDealOpponent())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(
            "/v1/turn",
            json={
                "case": case,
                "snapshot": {
                    "session_id": "demo-accept-offer",
                    "state": {"turn_count": 0},
                    "transcript": [],
                },
                "turn_id": "turn-1",
                "user_text": "Что вы предлагаете?",
            },
        )
        assert first.status_code == 200
        second = await client.post(
            "/v1/turn",
            json={
                "case": case,
                "snapshot": first.json()["snapshot"],
                "turn_id": "turn-2",
                "user_text": "Согласен.",
            },
        )

    assert second.status_code == 200
    assert second.json()["status"] == "accepted"
    assert second.json()["snapshot"]["state"]["stage"] == "agreed"
