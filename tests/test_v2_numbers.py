import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from arena_ai.v2.contracts import CaseConfig, DealTerms, TermValue


def test_wire_decimal_is_not_rounded_to_a_nearby_float() -> None:
    term = TermValue.model_validate_json('{"term_id":"price","value":0.100000000000000001}')
    assert term.value == Decimal("0.100000000000000001")
    assert term.value != Decimal("0.1")
    serialized = json.loads(term.model_dump_json(), parse_float=Decimal)
    assert serialized["value"] == Decimal("0.100000000000000001")
    assert not isinstance(serialized["value"], str)


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_wire_numbers_are_rejected(number: str) -> None:
    with pytest.raises(ValidationError):
        TermValue.model_validate_json('{"term_id":"price","value":' + number + "}")


@pytest.mark.parametrize("kind", ["numeric_range", "allowed_values", "linear"])
def test_exact_numeric_constraints_reject_a_nearby_out_of_bounds_decimal(kind: str) -> None:
    path = Path(__file__).resolve().parents[1] / "docs/api/v2/examples/supply-turn.request.json"
    data = json.loads(path.read_text())["case"]
    price = data["negotiables"][0]["id"]
    for rule in data["agreement_policy"]["constraints"]:
        if rule.get("term_id") == price:
            rule["minimum"] = rule["maximum"] = 0.1
    for step in data["opponent_strategy"]["steps"]:
        step["terms"]["values"][0]["value"] = 0.1
    exact_rule = {"id": "exact-rule", "kind": kind}
    if kind == "numeric_range":
        exact_rule.update(term_id=price, minimum=0.1, maximum=0.1)
    elif kind == "allowed_values":
        exact_rule.update(term_id=price, values=[0.1])
    else:
        exact_rule.update(
            coefficients=[{"term_id": price, "coefficient": 1}], relation="eq", bound=0.1
        )
    data["agreement_policy"]["constraints"].append(exact_rule)
    # Select just this hard rule to verify each kind, independently of other price bounds.
    data["agreement_policy"]["hard_constraint_ids"] = ["exact-rule"]
    case = CaseConfig.model_validate_json(json.dumps(data))
    original = case.opponent_strategy.steps[0].terms
    case.validate_deal(original)
    encoded = original.model_dump_json().replace('"value":0.1', '"value":0.100000000000000001', 1)
    with pytest.raises(ValueError, match="exact-rule"):
        case.validate_deal(DealTerms.model_validate_json(encoded))


def test_decimal_wire_encoder_preserves_text_and_dump_options() -> None:
    term = TermValue.model_validate_json('{"term_id":"Цена: 0.1, \\"text\\"","value":1e-30}')
    encoded = term.model_dump_json(indent=2, ensure_ascii=True)
    decoded = json.loads(encoded, parse_float=Decimal)
    assert decoded == {"term_id": 'Цена: 0.1, "text"', "value": Decimal("1e-30")}
    assert "\\u0426" in encoded
    assert json.loads(term.model_dump_json(exclude={"term_id"}), parse_float=Decimal) == {
        "value": Decimal("1e-30")
    }


def test_numeric_model_schema_keeps_numbers_not_decimal_strings() -> None:
    from arena_ai.v2.contracts import NumericConstraint

    def types(node: dict, schema: dict) -> set[str]:
        if "$ref" in node:
            return types(schema["$defs"][node["$ref"].split("/")[-1]], schema)
        if "anyOf" in node:
            return set().union(*(types(item, schema) for item in node["anyOf"]))
        return {node["type"]}

    for mode in ("validation", "serialization"):
        schema = NumericConstraint.model_json_schema(mode=mode)
        assert types(schema["properties"]["minimum"], schema) == {"integer", "number", "null"}
