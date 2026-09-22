import json
from pathlib import Path

from arena_ai.app import create_app
from arena_ai.contracts import TurnRequest, TurnResponse

ROOT = Path(__file__).resolve().parents[1]


def test_committed_openapi_matches_application() -> None:
    committed = json.loads((ROOT / "docs" / "api" / "openapi.json").read_text())

    assert committed == create_app().openapi()


def test_managed_turn_examples_match_public_contracts_and_use_placeholders() -> None:
    examples = json.loads((ROOT / "docs" / "api" / "examples" / "managed-turn.json").read_text())
    case = examples["case"]
    scenarios = examples["scenarios"]

    for name in ("accepted", "blocked", "model_error"):
        request = TurnRequest.model_validate({"case": case, **scenarios[name]["request"]["body"]})
        response = TurnResponse.model_validate(scenarios[name]["response"]["body"])
        assert response.session_id == request.snapshot.session_id
        assert response.turn_id == request.turn_id

    for name in ("state_conflict", "unauthorized"):
        TurnRequest.model_validate({"case": case, **scenarios[name]["request"]["body"]})

    model_error = scenarios["model_error"]
    assert model_error["response"]["body"]["snapshot"] == model_error["request"]["body"]["snapshot"]
    assert examples["authorized_headers"]["Authorization"] == "Bearer <service-token>"
    assert case["player_private_context"].startswith("[REDACTED:")
    assert case["opponent_private_context"].startswith("[REDACTED:")
