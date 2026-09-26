import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from arena_ai.v2.contracts import Negotiable

EXAMPLES = Path(__file__).resolve().parents[1] / "docs/api/v2/examples"


def fixture(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text())


def test_choice_negotiable_requires_a_nonempty_unique_catalogue() -> None:
    data = {
        "id": "format",
        "label": "Формат",
        "value_type": "choice",
        "unit": None,
        "choices": ["remote", "office"],
    }
    assert Negotiable.model_validate(data).model_dump(mode="json") == data
    for choices in ([], ["remote", "remote"]):
        with pytest.raises(ValidationError):
            Negotiable.model_validate({**data, "choices": choices})


def test_two_different_case_configs_round_trip_without_kpi_fields() -> None:
    from arena_ai.v2.contracts import CaseConfig

    for name in ("next-day-turn.request.json", "supply-turn.request.json"):
        data = fixture(name)["case"]
        case = CaseConfig.model_validate_json(json.dumps(data))
        assert case.model_dump(mode="json") == data


def test_full_proposal_must_satisfy_hard_and_selected_position_window() -> None:
    from arena_ai.v2.contracts import CaseConfig, DealTerms

    data = fixture("supply-turn.request.json")["case"]
    case = CaseConfig.model_validate(data)
    step = case.opponent_strategy.steps[0]
    case.validate_deal(step.terms, step_id=step.id)
    rule = next(
        rule
        for rule in case.agreement_policy.constraints
        if rule.kind == "numeric_range" and rule.id in step.constraint_ids
    )
    proposal = step.terms.model_dump(mode="json")
    value = next(value for value in proposal["values"] if value["term_id"] == rule.term_id)
    value["value"] = rule.maximum + 1
    with pytest.raises(ValueError, match="Constraint violated"):
        case.validate_deal(DealTerms.model_validate(proposal), step_id=step.id)
    with pytest.raises(ValueError, match="Unknown position"):
        case.validate_deal(step.terms, step_id="invented")


@pytest.mark.parametrize("mutation", ["boolean_number", "missing", "duplicate", "unknown", "role"])
def test_invalid_full_proposal_is_rejected_before_constraint_evaluation(mutation: str) -> None:
    from arena_ai.v2.contracts import CaseConfig, DealTerms

    case = CaseConfig.model_validate(fixture("supply-turn.request.json")["case"])
    data = case.opponent_strategy.steps[0].terms.model_dump(mode="json")
    if mutation == "boolean_number":
        data["values"][0]["value"] = True
    elif mutation == "missing":
        data["values"].pop()
    elif mutation == "duplicate":
        data["values"].append(deepcopy(data["values"][0]))
    elif mutation == "unknown":
        data["values"][0]["term_id"] = "invented"
    else:
        data["commitments"][0]["role_id"] = "hr"
    with pytest.raises(ValueError):
        case.validate_deal(DealTerms.model_validate(data))


def test_authored_typed_bounds_accept_valid_dates_choices_and_linear_budget() -> None:
    from arena_ai.v2.contracts import CaseConfig

    case = CaseConfig.model_validate(fixture("typed-bounds-turn.request.json")["case"])
    for step in case.opponent_strategy.steps:
        case.validate_deal(step.terms, step_id=step.id)


@pytest.mark.parametrize(
    "mutation",
    [
        "same_roles",
        "duplicate_participant",
        "unknown_role",
        "duplicate_term",
        "unknown_rule",
        "reversed_range",
        "unbounded_range",
        "wrong_rule_type",
        "duplicate_rule",
        "unknown_required_commitment",
        "inactive_commitment_role",
        "duplicate_step",
        "wrong_ladder",
        "missing_earned_rule",
        "missing_window",
        "invalid_exemplar",
        "unknown_outcome_role",
    ],
)
def test_invalid_authored_case_is_rejected_when_loaded(mutation: str) -> None:
    from arena_ai.v2.contracts import CaseConfig

    data = fixture("supply-turn.request.json")["case"]
    policy = data["agreement_policy"]
    steps = data["opponent_strategy"]["steps"]
    if mutation == "same_roles":
        data["player"]["role_id"] = data["opponent"]["role_id"]
    elif mutation == "duplicate_participant":
        data["participants"].append(deepcopy(data["participants"][0]))
    elif mutation == "unknown_role":
        data["player"]["role_id"] = "invented"
    elif mutation == "duplicate_term":
        data["negotiables"].append(deepcopy(data["negotiables"][0]))
    elif mutation == "unknown_rule":
        policy["hard_constraint_ids"].append("invented")
    elif mutation == "reversed_range":
        policy["constraints"][0].update(minimum=10, maximum=1)
    elif mutation == "unbounded_range":
        policy["constraints"][0].update(minimum=None, maximum=None)
    elif mutation == "wrong_rule_type":
        data["negotiables"][0]["value_type"] = "boolean"
    elif mutation == "duplicate_rule":
        policy["constraints"].append(deepcopy(policy["constraints"][0]))
    elif mutation == "unknown_required_commitment":
        policy["required_commitment_ids"].append("invented")
    elif mutation == "inactive_commitment_role":
        policy["commitment_rules"][0]["role_id"] = "hr"
    elif mutation == "duplicate_step":
        steps[1]["id"] = steps[0]["id"]
    elif mutation == "wrong_ladder":
        steps[0]["kind"] = "target"
    elif mutation == "missing_earned_rule":
        steps[-1]["requires"] = []
    elif mutation == "missing_window":
        steps[0]["constraint_ids"] = []
    elif mutation == "invalid_exemplar":
        steps[0]["terms"]["values"][0]["value"] = -1
    else:
        data["possible_outcomes"] = [
            {
                "id": "outcome",
                "kind": "deferred",
                "description": "Продолжить позже",
                "possible_consequences": [],
                "visibility": "private",
                "known_to_role_ids": ["invented"],
            }
        ]
    with pytest.raises(ValidationError):
        CaseConfig.model_validate(data)


@pytest.mark.parametrize(
    "name",
    [
        "next-day-turn.request.json",
        "finish-with-preparation.request.json",
        "empty-finish.request.json",
    ],
)
def test_session_snapshot_round_trips_without_changing_backend_history(name: str) -> None:
    from arena_ai.v2.contracts import SessionSnapshot

    data = fixture(name)["snapshot"]
    snapshot = SessionSnapshot.model_validate_json(json.dumps(data))
    assert snapshot.model_dump(mode="json") == data


@pytest.mark.parametrize(
    "mutation",
    [
        "ready_with_time",
        "no_start",
        "long_round",
        "reversed_deadline",
        "offset_time",
        "closed_without_reason",
        "early_deadline_finish",
        "duplicate_message",
        "late_message",
        "wrong_elapsed",
        "same_roles",
        "false_agreement",
        "unordered_history",
    ],
)
def test_inconsistent_snapshot_is_rejected(mutation: str) -> None:
    from arena_ai.v2.contracts import SessionSnapshot

    data = fixture("finish-with-preparation.request.json")["snapshot"]
    round_ = data["round"]
    if mutation == "ready_with_time":
        round_["status"] = "ready"
    elif mutation == "no_start":
        round_["started_at"] = None
    elif mutation == "long_round":
        round_["deadline_at"] = "2026-09-26T12:10:00Z"
    elif mutation == "reversed_deadline":
        round_["deadline_at"] = round_["started_at"]
    elif mutation == "offset_time":
        round_["started_at"] = "2026-09-26T12:00:00+00:00"
    elif mutation == "closed_without_reason":
        round_["end_reason"] = None
    elif mutation == "early_deadline_finish":
        round_["end_reason"] = "deadline"
        round_["finished_at"] = round_["started_at"]
    elif mutation == "duplicate_message":
        data["transcript"].append(deepcopy(data["transcript"][0]))
    elif mutation == "late_message":
        data["transcript"][-1]["created_at"] = round_["deadline_at"]
    elif mutation == "wrong_elapsed":
        data["transcript"][0]["elapsed_ms"] += 1
    elif mutation == "same_roles":
        data["player_role_id"] = data["opponent_role_id"]
    elif mutation == "false_agreement":
        data["state"]["stage"] = "agreed"
        data["state"]["agreement"] = None
    else:
        data["transcript"].reverse()
    with pytest.raises(ValidationError):
        SessionSnapshot.model_validate(data)


@pytest.mark.parametrize(
    "field", ["case_id", "case_config_version", "player_role_id", "opponent_role_id"]
)
def test_snapshot_must_match_pinned_case_and_roles(field: str) -> None:
    from arena_ai.v2.contracts import CaseConfig, SessionSnapshot

    data = fixture("supply-turn.request.json")
    case = CaseConfig.model_validate(data["case"])
    snapshot = SessionSnapshot.model_validate(data["snapshot"])
    snapshot.validate_for_case(case)
    changed = deepcopy(data["snapshot"])
    changed[field] = "different"
    with pytest.raises(ValueError, match="Snapshot mismatch"):
        SessionSnapshot.model_validate(changed).validate_for_case(case)


@pytest.mark.parametrize("mutation", ["unknown_step", "unknown_requirement", "bad_deal"])
def test_snapshot_cannot_restore_unknown_progress_or_out_of_bounds_agreement(mutation: str) -> None:
    from arena_ai.v2.contracts import CaseConfig, SessionSnapshot

    data = fixture("supply-turn.request.json")
    case = CaseConfig.model_validate(data["case"])
    snapshot = data["snapshot"]
    snapshot["state"]["opponent_progress"] = {
        "current_step_id": case.opponent_strategy.steps[0].id,
        "satisfied_requirement_ids": [],
        "last_transition": None,
    }
    if mutation == "unknown_step":
        snapshot["state"]["opponent_progress"]["current_step_id"] = "invented"
    elif mutation == "unknown_requirement":
        snapshot["state"]["opponent_progress"]["satisfied_requirement_ids"] = ["invented"]
    else:
        snapshot["state"]["stage"] = "agreed"
        snapshot["state"]["agreement"] = case.opponent_strategy.steps[0].terms.model_dump(
            mode="json"
        )
        snapshot["state"]["agreement"]["values"][0]["value"] = -1
    with pytest.raises(ValueError):
        SessionSnapshot.model_validate(snapshot).validate_for_case(case)


@pytest.mark.parametrize("value", [True, "12", float("nan"), float("inf")])
def test_numeric_constraints_do_not_coerce_strings_booleans_or_nonfinite_numbers(value) -> None:
    from arena_ai.v2.contracts import NumericConstraint

    with pytest.raises(ValidationError):
        NumericConstraint.model_validate(
            {
                "id": "bound",
                "kind": "numeric_range",
                "term_id": "price",
                "minimum": value,
                "maximum": None,
            }
        )


@pytest.mark.parametrize(
    "kind,value",
    [
        ("choice", "invented"),
        ("date", "2026-02-30"),
        ("date", "20260926"),
        ("boolean", 0),
        ("text", ""),
    ],
)
def test_proposals_enforce_declared_value_types_even_without_hard_rules(kind: str, value) -> None:
    from arena_ai.v2.contracts import CaseConfig, DealTerms

    data = fixture("supply-turn.request.json")["case"]
    term_id = data["negotiables"][0]["id"]
    data["negotiables"][0].update(value_type=kind, choices=["office"] if kind == "choice" else [])
    example = {"choice": "office", "date": "2026-09-26", "boolean": False, "text": "fixed"}[kind]
    for rule in data["agreement_policy"]["constraints"]:
        if rule.get("term_id") == term_id:
            rule.update(kind="allowed_values", values=[example])
            del rule["minimum"], rule["maximum"]
    for step in data["opponent_strategy"]["steps"]:
        step["terms"]["values"][0]["value"] = example
    case = CaseConfig.model_validate(data)
    proposal = case.opponent_strategy.steps[0].terms.model_dump(mode="json")
    proposal["values"][0]["value"] = value
    with pytest.raises(ValueError):
        case.validate_deal(DealTerms.model_validate(proposal))


def test_unknown_wire_fields_and_wrong_contract_versions_are_rejected() -> None:
    from arena_ai.v2.contracts import CaseConfig

    data = fixture("supply-turn.request.json")["case"]
    with pytest.raises(ValidationError):
        CaseConfig.model_validate({**data, "contract_version": "1"})
    with pytest.raises(ValidationError):
        CaseConfig.model_validate({**data, "system_prompt": "override"})


def test_restored_transition_cannot_use_invented_evidence() -> None:
    from arena_ai.v2.contracts import CaseConfig, SessionSnapshot

    data = fixture("supply-turn.request.json")
    case = CaseConfig.model_validate(data["case"])
    source, target = case.opponent_strategy.steps[:2]
    ids = [item.id for item in target.requires]
    data["snapshot"]["state"]["opponent_progress"] = {
        "current_step_id": target.id,
        "satisfied_requirement_ids": ids,
        "last_transition": {
            "from_step_id": source.id,
            "to_step_id": target.id,
            "requirement_ids": ids,
            "evidence": {
                "message_id": "invented",
                "turn_id": "invented",
                "speaker": "player",
                "elapsed_ms": 0,
                "quote": "Я согласен",
            },
        },
    }
    with pytest.raises(ValueError):
        SessionSnapshot.model_validate(data["snapshot"]).validate_for_case(case)


@pytest.mark.parametrize("name", ["next-day-turn.request.json", "supply-turn.request.json"])
def test_backend_turn_request_round_trips_with_assigned_message_ids(name: str) -> None:
    from arena_ai.v2.contracts import TurnRequest

    data = fixture(name)
    request = TurnRequest.model_validate_json(json.dumps(data))
    assert request.model_dump(mode="json") == data


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_case_version",
        "closed_round",
        "late_user",
        "wrong_elapsed",
        "same_message_ids",
        "existing_message_id",
        "existing_turn_id",
        "before_history",
    ],
)
def test_inconsistent_backend_turn_is_rejected_before_any_model_call(mutation: str) -> None:
    from arena_ai.v2.contracts import TurnRequest

    data = fixture("next-day-turn.request.json")
    if mutation == "wrong_case_version":
        data["snapshot"]["case_config_version"] = "old"
    elif mutation == "closed_round":
        data["snapshot"]["round"].update(
            status="finished",
            finished_at=data["snapshot"]["round"]["deadline_at"],
            end_reason="deadline",
        )
    elif mutation == "late_user":
        data["user_created_at"] = data["snapshot"]["round"]["deadline_at"]
    elif mutation == "wrong_elapsed":
        data["user_elapsed_ms"] += 1
    elif mutation == "same_message_ids":
        data["opponent_message_id"] = data["user_message_id"]
    else:
        data["snapshot"]["transcript"] = [
            {
                "message_id": "existing-message",
                "turn_id": "existing-turn",
                "speaker": "opponent",
                "status": "accepted",
                "text": "Начнём",
                "created_at": data["user_created_at"],
                "elapsed_ms": data["user_elapsed_ms"],
                "blocked_reason": None,
            }
        ]
        if mutation == "existing_message_id":
            data["user_message_id"] = "existing-message"
        elif mutation == "existing_turn_id":
            data["turn_id"] = "existing-turn"
        else:
            data["user_created_at"] = data["snapshot"]["round"]["started_at"]
            data["user_elapsed_ms"] = 0
    with pytest.raises(ValidationError):
        TurnRequest.model_validate(data)


@pytest.mark.parametrize(
    "name",
    [
        "finish-with-preparation.request.json",
        "finish-without-preparation.request.json",
        "empty-finish.request.json",
    ],
)
def test_finish_preserves_optional_single_string_preparation(name: str) -> None:
    from arena_ai.v2.contracts import FinishRequest

    data = fixture(name)
    request = FinishRequest.model_validate(data)
    assert request.model_dump(mode="json", exclude_unset=True) == data
    for invalid in ("", " \n\t", {"desired_position": "win"}):
        with pytest.raises(ValidationError):
            FinishRequest.model_validate({**data, "preparation": invalid})


def test_finish_requires_backend_to_freeze_the_round_first() -> None:
    from arena_ai.v2.contracts import FinishRequest

    data = fixture("finish-without-preparation.request.json")
    data["snapshot"]["round"].update(status="open", finished_at=None, end_reason=None)
    with pytest.raises(ValidationError, match="frozen"):
        FinishRequest.model_validate(data)
