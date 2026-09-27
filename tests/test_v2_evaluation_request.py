import pytest
from pydantic import ValidationError

from arena_ai.v2.evaluation_request import EvaluationRequest


def payload():
    return {
        "role": "Менеджер",
        "opponent_role": "Директор",
        "case_description": "Обсуждение повышения",
        "messages": [{"text": "  Какие условия?\n", "is_ai": False}],
        "preparations": "Моя цель — выяснить условия",
    }


def test_request_round_trip_preserves_text():
    data = payload()
    request = EvaluationRequest.model_validate(data)
    assert request.model_dump() == data
    assert EvaluationRequest.model_validate_json(request.model_dump_json()) == request


def test_preparation_is_optional():
    data = payload()
    del data["preparations"]
    assert EvaluationRequest.model_validate(data).preparations is None
    data["preparations"] = None
    assert EvaluationRequest.model_validate(data).preparations is None


@pytest.mark.parametrize("field", ["role", "opponent_role", "case_description", "preparations"])
@pytest.mark.parametrize("value", ["", " \n\t", 123])
def test_rejects_invalid_text(field, value):
    data = payload()
    data[field] = value
    with pytest.raises(ValidationError):
        EvaluationRequest.model_validate(data)


@pytest.mark.parametrize("value", [0, 1, "false", "true", None])
def test_author_flag_is_a_boolean(value):
    data = payload()
    data["messages"][0]["is_ai"] = value
    with pytest.raises(ValidationError):
        EvaluationRequest.model_validate(data)


@pytest.mark.parametrize(
    "messages",
    [[], [{"text": " \n", "is_ai": False}], [{"text": "Hi", "is_ai": True, "id": "1"}]],
)
def test_rejects_invalid_messages(messages):
    data = payload()
    data["messages"] = messages
    with pytest.raises(ValidationError):
        EvaluationRequest.model_validate(data)


def test_rejects_unknown_request_fields():
    data = payload()
    data["snapshot"] = {}
    with pytest.raises(ValidationError):
        EvaluationRequest.model_validate(data)
