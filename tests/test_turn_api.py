import httpx
import pytest

from arena_ai.app import create_app


class FixedOpponent:
    async def respond(self, context: object) -> str:
        return "Давайте обсудим, как восстановить доверие после пропущенного дня."


class PrivacyCheckingOpponent:
    async def respond(self, context: object) -> str:
        visible_context = repr(context)
        assert "manager-only-marker" not in visible_context
        assert "director-only-marker" in visible_context
        return "Мне нужно подтверждение ответственности."


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_manager_can_take_first_text_turn() -> None:
    app = create_app(opponent=FixedOpponent())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/turn",
            json={
                "scenario": {
                    "id": "next-day",
                    "title": "На следующий день...",
                    "shared_context": "Менеджер пропустил рабочий день после разговора о повышении.",
                    "player_role": "Менеджер",
                    "opponent_role": "Генеральный директор",
                    "player_private_context": "Хочу сохранить договорённость о повышении.",
                    "opponent_private_context": "Не соглашаться на повышение без проверки ответственности.",
                },
                "snapshot": {"session_id": "demo-1", "state": {"turn_count": 0}, "transcript": []},
                "turn_id": "turn-1",
                "user_text": "Готов компенсировать последствия отсутствия. Что вас устроит?",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "demo-1",
        "turn_id": "turn-1",
        "opponent_text": "Давайте обсудим, как восстановить доверие после пропущенного дня.",
        "snapshot": {
            "session_id": "demo-1",
            "state": {"turn_count": 1},
            "transcript": [
                {
                    "turn_id": "turn-1",
                    "speaker": "player",
                    "status": "accepted",
                    "text": "Готов компенсировать последствия отсутствия. Что вас устроит?",
                },
                {
                    "turn_id": "turn-1",
                    "speaker": "opponent",
                    "status": "accepted",
                    "text": "Давайте обсудим, как восстановить доверие после пропущенного дня.",
                },
            ],
        },
    }


@pytest.mark.anyio
async def test_player_private_context_stays_out_of_opponent_input_across_turns() -> None:
    app = create_app(opponent=PrivacyCheckingOpponent())
    request = {
        "scenario": {
            "id": "next-day",
            "title": "На следующий день...",
            "shared_context": "Разговор о повышении после пропущенного дня.",
            "player_role": "Менеджер",
            "opponent_role": "Генеральный директор",
            "player_private_context": "manager-only-marker",
            "opponent_private_context": "director-only-marker",
        },
        "snapshot": {"session_id": "demo-2", "state": {"turn_count": 0}, "transcript": []},
        "turn_id": "turn-1",
        "user_text": "Что вам нужно для сохранения договорённости?",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post("/v1/turn", json=request)
        assert first.status_code == 200
        request["snapshot"] = first.json()["snapshot"]
        request["turn_id"] = "turn-2"
        request["user_text"] = "Могу компенсировать пропущенный день."
        second = await client.post("/v1/turn", json=request)

    assert second.status_code == 200
    assert second.json()["snapshot"]["state"]["turn_count"] == 2
    assert len(second.json()["snapshot"]["transcript"]) == 4
    assert "director-only-marker" not in second.text
