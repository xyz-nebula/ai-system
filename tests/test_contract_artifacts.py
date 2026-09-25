import json
from pathlib import Path

from arena_ai.app import create_app
from arena_ai.contracts import (
    FinishRequest,
    FinishResponse,
    PreparationCard,
    TurnRequest,
    TurnResponse,
)

ROOT = Path(__file__).resolve().parents[1]


def test_committed_openapi_matches_application() -> None:
    committed = json.loads((ROOT / "docs" / "api" / "openapi.json").read_text())

    assert committed == create_app().openapi()


def test_managed_turn_examples_match_public_contracts_and_use_placeholders() -> None:
    examples = json.loads((ROOT / "docs" / "api" / "examples" / "managed-turn.json").read_text())
    case = examples["case"]
    scenarios = examples["scenarios"]

    for name in ("accepted", "blocked", "model_error", "agreement_continues"):
        request = TurnRequest.model_validate({"case": case, **scenarios[name]["request"]["body"]})
        response = TurnResponse.model_validate(scenarios[name]["response"]["body"])
        assert response.session_id == request.snapshot.session_id
        assert response.turn_id == request.turn_id

    TurnRequest.model_validate({"case": case, **scenarios["unauthorized"]["request"]["body"]})

    model_error = scenarios["model_error"]
    assert model_error["response"]["body"]["snapshot"] == model_error["request"]["body"]["snapshot"]
    assert examples["authorized_headers"]["Authorization"] == "Bearer <service-token>"
    assert examples["request_body_rule"].startswith("Send the top-level case")
    assert "not a closed round" in examples["round_lifecycle_rule"]
    assert "network timeouts" in examples["round_timer_rule"]
    assert case["player_private_context"].startswith("[REDACTED:")
    assert case["opponent_private_context"].startswith("[REDACTED:")


def test_backend_position_example_matches_internal_contract_without_real_ids() -> None:
    example = json.loads(
        (ROOT / "docs" / "api" / "examples" / "backend-position-turn.json").read_text()
    )

    request = TurnRequest.model_validate(example["request"]["body"])
    response = TurnResponse.model_validate(example["response"]["body"])
    serialized = json.dumps(example, ensure_ascii=False)

    assert example["audience"] == "Backend integration only"
    assert example["display_policy"].startswith("Do not forward")
    assert response.session_id == request.snapshot.session_id
    assert response.snapshot.state.opponent_progress is not None
    assert response.snapshot.state.opponent_progress.current_step_id == "backend-step-b"
    for real_identifier in ("measurable-trial", "prevent-repeat", "red-line"):
        assert real_identifier not in serialized


def test_preparation_finish_example_matches_public_contracts() -> None:
    example = json.loads(
        (ROOT / "docs" / "api" / "examples" / "preparation-finish.json").read_text()
    )

    request = FinishRequest.model_validate(example["request"]["body"])
    response = FinishResponse.model_validate(example["response"]["body"])
    cli_card = PreparationCard.model_validate_json(
        (ROOT / "docs" / "api" / "examples" / "preparation-card.json").read_text()
    )

    assert request.preparation is not None
    assert request.preparation.negotiation_goal == "Согласовать измеримые условия повышения."
    assert cli_card == request.preparation
    assert response.session_id == request.snapshot.session_id
    assert len(response.judge_verdicts) == 3
    assert {slot.college for slot in response.judge_verdicts} == {
        "hiring",
        "negotiation",
        "ownership",
    }
    assert (
        len({slot.verdict.decisive_criterion for slot in response.judge_verdicts if slot.verdict})
        == 3
    )
    for slot in response.judge_verdicts:
        assert slot.status == "ready"
        assert slot.verdict is not None
        verdict = slot.verdict
        assert any(
            entry.status == "accepted"
            and entry.turn_id == verdict.evidence_turn_id
            and verdict.evidence_quote in entry.text
            for entry in request.snapshot.transcript
        )
        comment = (
            f"{verdict.decisive_criterion} {verdict.evidence_quote} {verdict.observation} "
            f"{verdict.effect} {verdict.comparison}"
        )
        assert len(comment.split()) <= 120
        assert "[REDACTED:" not in comment
    assert response.trainer_feedback.feedback is not None
    comparison = response.trainer_feedback.feedback.plan_vs_reality
    assert comparison is not None
    assert comparison.items[0].status == "adapted"
    assert request.case.player_private_context.startswith("[REDACTED:")
    assert request.case.opponent_private_context.startswith("[REDACTED:")
