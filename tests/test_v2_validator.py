import asyncio
import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from arena_ai.v2.contracts import TurnRequest
from arena_ai.v2.offers import OpponentOffer


def test_validator_assesses_offer_through_model_http_without_mutating_turn() -> None:
    from arena_ai.v2.validator import QwenOfferValidator

    turn = TurnRequest.model_validate_json(
        (
            Path(__file__).resolve().parents[1] / "docs/api/v2/examples/supply-turn.request.json"
        ).read_text()
    )
    before = turn.model_dump_json()
    offer = OpponentOffer(text="Уточните объём заказа.", terms=None, position_transition=None)

    def gateway(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        context = json.loads(body["messages"][1]["content"])
        assert context["offer"]["text"] == "Уточните объём заказа."
        assert context["current_user"]["quote"] == turn.user_text
        assert "preparation" not in context
        assert "commitment_rules" not in context["opponent"]["agreement_policy"]
        assert "required_commitment_ids" not in context["opponent"]["agreement_policy"]
        assert request.headers["authorization"] == "Bearer test-secret"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"decision":"accept","terms_match_text":true,"concession_proofs":[]}'
                        }
                    }
                ]
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as http:
            return await QwenOfferValidator(
                http,
                chat_url="http://model/v1/chat/completions",
                model="qwen",
                api_key="test-secret",
            ).assess(turn, offer)

    result = asyncio.run(run())
    assert result.decision == "accept"
    assert turn.model_dump_json() == before


def test_uncertain_assessment_preserves_exact_numeric_offer_on_model_wire() -> None:
    from arena_ai.v2.validator import QwenOfferValidator

    turn = TurnRequest.model_validate_json(
        (
            Path(__file__).resolve().parents[1] / "docs/api/v2/examples/supply-turn.request.json"
        ).read_text()
    )
    terms = turn.case.opponent_strategy.steps[0].terms.model_copy(deep=True)
    terms.values[0].value = Decimal("5000.000000000000000001")
    offer = OpponentOffer(text="Обсудим цену.", terms=terms, position_transition=None)

    def gateway(request):
        body = json.loads(request.content)
        context = json.loads(body["messages"][1]["content"], parse_float=Decimal)
        assert context["offer"]["terms"]["values"][0]["value"] == Decimal("5000.000000000000000001")
        assert context["player_brief"]["batna"] == "Обратиться к другому поставщику."
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"decision":"uncertain","terms_match_text":false,"concession_proofs":[]}'
                        }
                    }
                ]
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as http:
            return await QwenOfferValidator(
                http,
                chat_url="http://model/v1/chat/completions",
                model="qwen",
            ).assess(turn, offer)

    assert asyncio.run(run()).decision == "uncertain"


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        'Объяснение: {"decision":"accept","terms_match_text":true,"concession_proofs":[]}',
        '{"decision":"accept","terms_match_text":false,"concession_proofs":[]}',
        '{"decision":"accept","terms_match_text":true,"concession_proofs":[],"extra":1}',
    ],
)
def test_invalid_or_inconsistent_assessment_fails_closed(content: str) -> None:
    from arena_ai.v2.validator import OfferValidationError, QwenOfferValidator

    turn = TurnRequest.model_validate_json(
        (
            Path(__file__).resolve().parents[1] / "docs/api/v2/examples/supply-turn.request.json"
        ).read_text()
    )
    offer = OpponentOffer(text="Уточните объём.", terms=None, position_transition=None)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
            )
        ) as http:
            return await QwenOfferValidator(
                http,
                chat_url="http://model/v1/chat/completions",
                model="qwen",
            ).assess(turn, offer)

    with pytest.raises(OfferValidationError, match="assessment unavailable"):
        asyncio.run(run())


@pytest.mark.parametrize("failure", ["http", "timeout", "shape", "empty"])
def test_gateway_failure_never_returns_an_acceptance_or_leaks_details(failure: str) -> None:
    from arena_ai.v2.validator import OfferValidationError, QwenOfferValidator

    turn = TurnRequest.model_validate_json(
        (
            Path(__file__).resolve().parents[1] / "docs/api/v2/examples/supply-turn.request.json"
        ).read_text()
    )
    before = turn.model_dump_json()
    offer = OpponentOffer(text="Уточните объём.", terms=None, position_transition=None)

    def gateway(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("private-secret", request=request)
        if failure == "http":
            return httpx.Response(500, text="private-secret")
        return httpx.Response(200, json={} if failure == "shape" else {"choices": []})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as http:
            return await QwenOfferValidator(
                http,
                chat_url="http://model/v1/chat/completions",
                model="qwen",
            ).assess(turn, offer)

    with pytest.raises(OfferValidationError) as caught:
        asyncio.run(run())
    assert "private-secret" not in str(caught.value)
    assert turn.model_dump_json() == before


def test_complete_json_fence_is_accepted_without_json_repair() -> None:
    from arena_ai.v2.validator import QwenOfferValidator

    turn = TurnRequest.model_validate_json(
        (
            Path(__file__).resolve().parents[1] / "docs/api/v2/examples/supply-turn.request.json"
        ).read_bytes()
    )
    offer = OpponentOffer(text="Уточните объём.", terms=None, position_transition=None)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "message": {
                                    "content": '```json\n{"decision":"accept","terms_match_text":true,"concession_proofs":[]}\n```'
                                }
                            }
                        ]
                    },
                )
            )
        ) as http:
            return await QwenOfferValidator(
                http,
                chat_url="http://model/v1/chat/completions",
                model="qwen",
            ).assess(turn, offer)

    assert asyncio.run(run()).decision == "accept"
