import json
from pathlib import Path

from arena_ai.v2.contracts import FinishRequest, TurnRequest

EXAMPLES = Path(__file__).resolve().parents[1] / "docs/api/v2/examples"


def turn_data() -> dict:
    data = json.loads((EXAMPLES / "next-day-turn.request.json").read_text())
    data["case"]["player"]["private_context"] = "PLAYER_PRIVATE_SENTINEL"
    data["case"]["player"]["batna"] = "PLAYER_BATNA_SENTINEL"
    data["case"]["opponent"]["private_context"] = "OPPONENT_PRIVATE_SENTINEL"
    data["case"]["possible_outcomes"] = [
        {
            "id": "player-only",
            "kind": "deferred",
            "description": "PLAYER_OUTCOME_SENTINEL",
            "possible_consequences": [],
            "visibility": "private",
            "known_to_role_ids": [data["case"]["player"]["role_id"]],
        },
        {
            "id": "opponent-only",
            "kind": "deferred",
            "description": "OPPONENT_OUTCOME_SENTINEL",
            "possible_consequences": [],
            "visibility": "private",
            "known_to_role_ids": [data["case"]["opponent"]["role_id"]],
        },
    ]
    return data


def test_opponent_input_uses_own_private_brief_not_player_brief() -> None:
    from arena_ai.v2.contexts import for_opponent

    request = TurnRequest.model_validate(turn_data())
    before = request.model_dump_json()
    context = for_opponent(request)
    serialized = context.model_dump_json()
    assert "OPPONENT_PRIVATE_SENTINEL" in serialized
    assert "OPPONENT_OUTCOME_SENTINEL" in serialized
    assert "PLAYER_PRIVATE_SENTINEL" not in serialized
    assert "PLAYER_BATNA_SENTINEL" not in serialized
    assert "PLAYER_OUTCOME_SENTINEL" not in serialized
    assert "preparation" not in context.model_dump()
    context.opponent_brief.private_context = "changed"
    assert request.model_dump_json() == before


def test_swapping_active_roles_changes_which_private_brief_opponent_receives() -> None:
    from arena_ai.v2.contexts import for_opponent

    data = turn_data()
    case = data["case"]
    case["player"], case["opponent"] = case["opponent"], case["player"]
    data["snapshot"]["player_role_id"] = case["player"]["role_id"]
    data["snapshot"]["opponent_role_id"] = case["opponent"]["role_id"]
    serialized = for_opponent(TurnRequest.model_validate(data)).model_dump_json()
    assert "PLAYER_PRIVATE_SENTINEL" in serialized
    assert "OPPONENT_PRIVATE_SENTINEL" not in serialized
    assert "PLAYER_OUTCOME_SENTINEL" in serialized
    assert "OPPONENT_OUTCOME_SENTINEL" not in serialized


def test_blocked_instructions_are_not_replayed_into_opponent_context() -> None:
    from arena_ai.v2.contexts import for_opponent

    data = turn_data()
    data["snapshot"]["transcript"] = [
        {
            "message_id": "old-user",
            "turn_id": "old-turn",
            "speaker": "player",
            "status": "blocked",
            "text": "BLOCKED_INJECTION_SENTINEL",
            "created_at": data["snapshot"]["round"]["started_at"],
            "elapsed_ms": 0,
            "blocked_reason": "prompt_override",
        }
    ]
    request = TurnRequest.model_validate(data)
    context = for_opponent(request)
    assert "BLOCKED_INJECTION_SENTINEL" not in context.model_dump_json()
    assert context.transcript[0].message_id == "old-user"
    assert request.snapshot.transcript[0].text == "BLOCKED_INJECTION_SENTINEL"


def test_guard_input_has_no_strategy_or_private_role_briefs() -> None:
    from arena_ai.v2.contexts import for_guard

    request = TurnRequest.model_validate(turn_data())
    context = for_guard(request)
    assert context.user_text == request.user_text
    serialized = context.model_dump_json()
    for sentinel in ("PLAYER_PRIVATE_SENTINEL", "OPPONENT_PRIVATE_SENTINEL", "OUTCOME_SENTINEL"):
        assert sentinel not in serialized
    assert set(context.model_dump()) == {
        "shared_context",
        "participants",
        "player_role",
        "opponent_role",
        "user_text",
    }


def test_judge_and_trainer_receive_public_view_with_plan_only_for_trainer() -> None:
    from arena_ai.v2.contexts import for_judge, for_trainer

    data = json.loads((EXAMPLES / "finish-with-preparation.request.json").read_text())
    data["case"] = turn_data()["case"]
    data["preparation"] = "PREPARATION_SENTINEL"
    data["snapshot"]["state"]["opponent_progress"] = {
        "current_step_id": data["case"]["opponent_strategy"]["steps"][0]["id"],
        "satisfied_requirement_ids": [],
        "last_transition": None,
    }
    request = FinishRequest.model_validate(data)
    before = request.model_dump_json()
    judge, trainer = for_judge(request), for_trainer(request)
    for context in (judge, trainer):
        serialized = context.model_dump_json()
        for sentinel in (
            "PLAYER_PRIVATE_SENTINEL",
            "OPPONENT_PRIVATE_SENTINEL",
            "OUTCOME_SENTINEL",
        ):
            assert sentinel not in serialized
        assert "opponent_progress" not in context.state.model_dump()
        assert "opponent_strategy" not in context.model_dump()
    assert "PREPARATION_SENTINEL" not in judge.model_dump_json()
    assert trainer.preparation == "PREPARATION_SENTINEL"
    trainer.transcript[0].text = "changed"
    assert request.model_dump_json() == before
