"""Check draft fixtures only; not a replacement for runtime validators."""

import json
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parent
SCHEMA = json.loads((ROOT / "case-contract-v2.schema.json").read_text())
EXAMPLES = {
    "next-day-turn.request.json": "TurnRequest",
    "supply-turn.request.json": "TurnRequest",
    "next-day-turn.response.json": "TurnResponse",
    "finish-with-preparation.request.json": "FinishRequest",
    "finish-without-preparation.request.json": "FinishRequest",
    "finish-partial.response.json": "FinishResponse",
}


def check(value, definition):
    schema = {key: item for key, item in SCHEMA.items() if key != "oneOf"}
    schema["$ref"] = f"#/$defs/{definition}"
    Draft202012Validator(schema).validate(value)
    if "case" in value:
        case, snapshot = value["case"], value["snapshot"]
        assert snapshot["case_id"] == case["id"]
        assert snapshot["case_config_version"] == case["config_version"]
        roles = [case["player"]["role_id"], case["opponent"]["role_id"]]
        assert roles[0] != roles[1]
        participants = [item["id"] for item in case["participants"]]
        assert len(participants) == len(set(participants))
        assert set(roles) <= set(participants)
        assert snapshot["player_role_id"] == roles[0]
        assert snapshot["opponent_role_id"] == roles[1]
        terms = {item["id"]: item for item in case["negotiables"]}
        assert len(terms) == len(case["negotiables"])
        if case["opponent_strategy"]:
            steps = case["opponent_strategy"]["steps"]
            ids = [step["id"] for step in steps]
            assert len(ids) == len(set(ids))
            kinds = [step["kind"] for step in steps]
            for kind in ("declared", "target", "red_line"):
                assert kinds.count(kind) == 1
            assert kinds[0] == "declared" and kinds[-1] == "red_line"
            for step in steps:
                values = step["terms"]["values"]
                assert {item["term_id"] for item in values} == set(terms)
                assert len(values) == len(terms)
                for item in values:
                    term = terms[item["term_id"]]
                    kind, actual = term["value_type"], item["value"]
                    if kind == "number":
                        assert type(actual) in (int, float)
                    elif kind == "boolean":
                        assert type(actual) is bool
                    else:
                        assert isinstance(actual, str)
                        if kind == "choice":
                            assert actual in term["choices"]
                for commitment in step["terms"]["commitments"]:
                    assert commitment["role_id"] in roles
        preparation = value.get("preparation")
        assert preparation is None or preparation.strip()
    if definition == "FinishResponse":
        slots = value["judge_verdicts"]
        assert {slot["college"] for slot in slots} == {"hiring", "negotiation", "ownership"}
        for slot in [*slots, value["trainer_feedback"]]:
            payload = slot.get("verdict", slot.get("feedback"))
            assert (payload is not None) == (slot["status"] == "ready")
            assert (slot["error_code"] is None) == (slot["status"] == "ready")


def main():
    Draft202012Validator.check_schema(SCHEMA)
    fixtures = {}
    for filename, definition in EXAMPLES.items():
        fixture = json.loads((ROOT / "examples" / filename).read_text())
        check(fixture, definition)
        fixtures[filename] = fixture

    original = fixtures["finish-with-preparation.request.json"]
    invalid = []
    extra = deepcopy(original)
    extra["unexpected"] = True
    invalid.append(extra)
    wrong_version = deepcopy(original)
    wrong_version["snapshot"]["case_config_version"] = "different"
    invalid.append(wrong_version)
    structured_preparation = deepcopy(original)
    structured_preparation["preparation"] = {"desired_position": "example"}
    invalid.append(structured_preparation)
    empty_preparation = deepcopy(original)
    empty_preparation["preparation"] = "   "
    invalid.append(empty_preparation)
    same_role = deepcopy(original)
    same_role["case"]["opponent"]["role_id"] = same_role["case"]["player"]["role_id"]
    invalid.append(same_role)
    for fixture in invalid:
        try:
            check(fixture, "FinishRequest")
        except (AssertionError, ValidationError):
            continue
        raise AssertionError("Invalid fixture was accepted")
    print(f"Draft valid: {len(EXAMPLES)} examples, {len(invalid)} negative checks")


if __name__ == "__main__":
    main()
