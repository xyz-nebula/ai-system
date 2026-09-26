import asyncio
import json
from pathlib import Path

import httpx
import pytest

from arena_ai.qwen import QwenSettings
from arena_ai.v2.contracts import TurnRequest


def settings() -> QwenSettings:
    return QwenSettings(
        chat_url="http://model/v1/chat/completions",
        models_url="http://model/v1/models",
        model="qwen",
        api_key=None,
        json_mode="prompt",
        timeout_seconds=60,
        readiness_timeout_seconds=3,
        tls_verify=True,
        fast_extra_body={},
        reasoned_extra_body={},
        model_attempts=1,
    )


def request() -> TurnRequest:
    return TurnRequest.model_validate_json(
        (
            Path(__file__).resolve().parents[1] / "docs/api/v2/examples/supply-turn.request.json"
        ).read_bytes()
    )


def test_managed_negotiating_turn_adds_only_a_checked_pair_to_candidate_snapshot() -> None:
    from arena_ai.v2.turn import QwenTurnPipeline

    turn = request()
    before = turn.model_dump_json()

    def gateway(request):
        messages = json.loads(request.content)["messages"]
        system = messages[0]["content"]
        context = json.loads(messages[1]["content"])
        if "[V2_GUARD]" in system:
            assert "opponent_strategy" not in context
            content = {"decision": "allow", "reason": None}
        elif "[V2_OPPONENT]" in system:
            assert "player_brief" not in context
            content = {
                "text": "Какой объём вы готовы заказать?",
                "terms": None,
                "position_transition": None,
            }
        else:
            content = {"decision": "accept", "terms_match_text": True, "concession_proofs": []}
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]},
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as http:
            return await QwenTurnPipeline(http, settings()).turn(turn)

    result = asyncio.run(run())
    assert result.status == "accepted"
    assert result.opponent_text == "Какой объём вы готовы заказать?"
    assert result.snapshot.revision == turn.snapshot.revision + 1
    assert result.snapshot.state.turn_count == 1
    assert [entry.message_id for entry in result.snapshot.transcript] == [
        turn.user_message_id,
        turn.opponent_message_id,
    ]
    assert result.snapshot.state.stage == "negotiating"
    assert turn.model_dump_json() == before


@pytest.mark.parametrize(
    "reply",
    [
        {"decision": "uncertain", "reason": None},
        {"decision": "block", "reason": None},
    ],
)
def test_uncertain_or_malformed_guard_preserves_the_entire_snapshot(reply) -> None:
    from arena_ai.v2.turn import QwenTurnPipeline

    turn = request()

    def gateway(request):
        assert "[V2_GUARD]" in json.loads(request.content)["messages"][0]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(reply),
                        }
                    }
                ]
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as http:
            return await QwenTurnPipeline(http, settings()).turn(turn)

    result = asyncio.run(run())
    assert result.status == "model_error"
    assert result.snapshot.model_dump_json() == turn.snapshot.model_dump_json()


def test_blocked_input_adds_safe_reaction_without_calling_opponent() -> None:
    from arena_ai.v2.turn import QwenTurnPipeline

    turn = request()

    def gateway(request):
        assert "[V2_GUARD]" in json.loads(request.content)["messages"][0]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"decision":"block","reason":"prompt_override"}',
                        }
                    }
                ]
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as http:
            return await QwenTurnPipeline(http, settings()).turn(turn)

    result = asyncio.run(run())
    assert result.status == "blocked"
    assert [entry.status for entry in result.snapshot.transcript] == ["blocked", "safe_reaction"]
    assert result.snapshot.transcript[0].blocked_reason == "prompt_override"
    assert result.snapshot.state == turn.snapshot.state.model_copy(update={"turn_count": 1})


@pytest.mark.parametrize("stage", ["opponent", "validator"])
def test_model_failure_after_allow_does_not_commit_user_or_opponent(stage: str) -> None:
    from arena_ai.v2.turn import QwenTurnPipeline

    turn = request()

    def gateway(request):
        system = json.loads(request.content)["messages"][0]["content"]
        if "[V2_GUARD]" in system:
            content = '{"decision":"allow","reason":null}'
        elif "[V2_OPPONENT]" in system and stage == "validator":
            content = '{"text":"Уточните объём.","terms":null,"position_transition":null}'
        else:
            return httpx.Response(503, text="private-secret")
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as http:
            return await QwenTurnPipeline(http, settings()).turn(turn)

    result = asyncio.run(run())
    assert result.status == "model_error"
    assert result.snapshot.model_dump_json() == turn.snapshot.model_dump_json()
    assert "private-secret" not in result.model_dump_json()


def test_earned_transition_is_grounded_in_the_committed_candidate_player_message() -> None:
    from arena_ai.v2.turn import QwenTurnPipeline

    data = request().model_dump(mode="python")
    data["user_text"] = "Я обязуюсь обеспечить объём заказа."
    turn = TurnRequest.model_validate(data)

    def gateway(request):
        messages = json.loads(request.content)["messages"]
        if "[V2_GUARD]" in messages[0]["content"]:
            content = {"decision": "allow", "reason": None}
        elif "[V2_OPPONENT]" in messages[0]["content"]:
            content = {
                "text": "Цена 4800 рублей за единицу, поставка за 12 дней.",
                "terms": turn.case.opponent_strategy.steps[1].terms.model_dump(mode="python"),
                "position_transition": {
                    "to_step_id": "target",
                    "requirement_ids": ["order-volume"],
                },
            }
        else:
            content = {
                "decision": "accept",
                "terms_match_text": True,
                "concession_proofs": [
                    {
                        "requirement_id": "order-volume",
                        "is_new_direct_commitment": True,
                        "evidence": json.loads(messages[1]["content"])["current_user"],
                    }
                ],
            }
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(content, ensure_ascii=False),
                        }
                    }
                ]
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as http:
            return await QwenTurnPipeline(http, settings()).turn(turn)

    result = asyncio.run(run())
    assert result.status == "accepted"
    assert result.snapshot.state.opponent_progress.current_step_id == "target"
    proof = result.snapshot.state.opponent_progress.last_transition.evidence
    assert proof.quote == result.snapshot.transcript[0].text
    assert proof.message_id == turn.user_message_id
    result.snapshot.validate_for_case(turn.case)
