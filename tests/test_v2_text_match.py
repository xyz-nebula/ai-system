import asyncio
import json

import httpx
import pytest
from test_v2_cross_case_live import scenario

from arena_ai.v2.validator import OfferValidationError, QwenOfferValidator


def test_narrow_text_check_rejects_mismatch_without_mutating_request():
    turn, offer = scenario("resources")
    offer.text = "Предлагаю выделить аналитику 40 часов на проект."
    before = turn.model_dump_json()

    def gateway(req):
        body = json.loads(req.content)
        context = json.loads(body["messages"][1]["content"])
        if "[V2_TEXT_MATCH]" in body["messages"][0]["content"]:
            assert set(context) == {
                "negotiables",
                "text",
                "terms",
                "player_role_id",
                "opponent_role_id",
            }
            assert context["terms"]["values"] == [{"term_id": "subject", "value": 4}]
            reply = {"decision": "reject"}
        else:
            reply = {
                "decision": "accept",
                "terms_match_text": True,
                "concession_proofs": [
                    {
                        "requirement_id": "value-1",
                        "is_new_direct_commitment": True,
                        "evidence": context["current_user"],
                    }
                ],
            }
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(reply)}}]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as http:
            return await QwenOfferValidator(
                http, chat_url="http://model/chat", model="qwen"
            ).assess(turn, offer)

    result = asyncio.run(run())
    assert result.decision == "reject"
    assert result.terms_match_text is False
    assert result.concession_proofs == []
    assert turn.model_dump_json() == before


@pytest.mark.parametrize("decision", ["accept", "uncertain"])
def test_matching_text_never_grants_an_unearned_concession(decision):
    turn, offer = scenario("resources", pressure=True)

    def gateway(req):
        system = json.loads(req.content)["messages"][0]["content"]
        reply = (
            {"decision": decision}
            if "[V2_TEXT_MATCH]" in system
            else {"decision": "reject", "terms_match_text": True, "concession_proofs": []}
        )
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(reply)}}]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as http:
            return await QwenOfferValidator(
                http, chat_url="http://model/chat", model="qwen"
            ).assess(turn, offer)

    result = asyncio.run(run())
    assert result.decision == ("reject" if decision == "accept" else "uncertain")
    assert result.concession_proofs == []


@pytest.mark.parametrize("failure", ["http", "invalid-json", "extra-field", "timeout"])
def test_text_match_failure_is_safe_and_does_not_mutate_request(failure):
    turn, offer = scenario("resources")
    before = turn.model_dump_json()

    def gateway(req):
        assert "[V2_TEXT_MATCH]" in json.loads(req.content)["messages"][0]["content"]
        if failure == "http":
            return httpx.Response(503, text="private-secret")
        if failure == "timeout":
            raise httpx.ReadTimeout("private-secret", request=req)
        content = "broken" if failure == "invalid-json" else '{"decision":"accept","extra":1}'
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as http:
            return await QwenOfferValidator(
                http, chat_url="http://model/chat", model="qwen"
            ).assess(turn, offer)

    with pytest.raises(OfferValidationError, match="assessment unavailable") as error:
        asyncio.run(run())
    assert "private-secret" not in str(error.value)
    assert turn.model_dump_json() == before


def test_managed_turn_never_publishes_text_rejected_by_narrow_check():
    from test_v2_turn import settings

    from arena_ai.v2.turn import QwenTurnPipeline

    turn, offer = scenario("resources")
    offer.text = "Предлагаю выделить аналитику 40 часов на проект."

    def gateway(req):
        system = json.loads(req.content)["messages"][0]["content"]
        if "[V2_GUARD]" in system:
            reply = {"decision": "allow", "reason": None}
        elif "[V2_OPPONENT]" in system:
            reply = offer.model_dump(mode="json")
        elif "[V2_TEXT_MATCH]" in system:
            reply = {"decision": "reject"}
        else:
            raise AssertionError("Rejected offer must not reach other model checks")
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(reply)}}]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as http:
            return await QwenTurnPipeline(http, settings()).turn(turn)

    result = asyncio.run(run())
    assert result.status == "model_error"
    assert result.error_code == "validation_failed"
    assert result.snapshot == turn.snapshot
    assert "40" not in result.opponent_text
