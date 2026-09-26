import asyncio
import json

import httpx
import pytest
from test_v2_turn import request

from arena_ai.v2.contracts import TurnRequest
from arena_ai.v2.offers import OpponentOffer, PositionTransition
from arena_ai.v2.validator import OfferValidationError, QwenOfferValidator


def repeated_turn():
    data = request().model_dump(mode="python")
    data["user_text"] = "Я обязуюсь обеспечить объём заказа."
    data["snapshot"]["revision"] = 1
    data["snapshot"]["state"]["turn_count"] = 1
    data["snapshot"]["transcript"] = [
        {
            "message_id": "prior-player",
            "turn_id": "prior-turn",
            "speaker": "player",
            "status": "accepted",
            "text": "Я гарантирую согласованный объём закупки.",
            "created_at": "2026-09-26T10:00:05Z",
            "elapsed_ms": 5000,
            "blocked_reason": None,
        }
    ]
    return TurnRequest.model_validate(data)


def offer(turn):
    return OpponentOffer(
        text="Предлагаю цену 4800 рублей за единицу и поставку за 12 дней.",
        terms=turn.case.opponent_strategy.steps[1].terms,
        position_transition=PositionTransition(
            to_step_id="target", requirement_ids=["order-volume"]
        ),
    )


def assess(turn, *, novelty=None):
    def gateway(req):
        messages = json.loads(req.content)["messages"]
        context = json.loads(messages[1]["content"])
        if "[V2_NOVELTY]" in messages[0]["content"]:
            assert set(context) == {"requirements", "current_user", "history"}
            assert all(
                item["status"] == "accepted" and item["speaker"] == "player"
                for item in context["history"]
            )
            reply = novelty(context)
            if isinstance(reply, httpx.Response):
                return reply
        else:
            reply = {
                "decision": "accept",
                "terms_match_text": True,
                "concession_proofs": [
                    {
                        "requirement_id": "order-volume",
                        "is_new_direct_commitment": True,
                        "evidence": context["current_user"],
                    }
                ],
            }
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(reply)}}]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as http:
            return await QwenOfferValidator(
                http, chat_url="http://model/v1/chat/completions", model="qwen"
            ).assess(turn, offer(turn))

    return asyncio.run(run())


def test_fresh_message_id_does_not_override_semantically_repeated_commitment():
    turn = repeated_turn()
    before = turn.model_dump_json()

    def reject(context):
        old = context["history"][0]
        return {
            "decision": "reject",
            "prior_equivalents": [
                {key: old[key] for key in ("message_id", "turn_id", "speaker", "elapsed_ms")}
                | {"quote": old["text"]}
            ],
        }

    result = assess(turn, novelty=reject)
    assert result.decision == "reject"
    assert result.concession_proofs == []
    assert turn.model_dump_json() == before


def test_new_value_after_unrelated_prior_commitment_can_still_earn_concession():
    data = repeated_turn().model_dump(mode="python")
    data["snapshot"]["transcript"][0]["text"] = "Я пришлю сертификаты качества."
    turn = TurnRequest.model_validate(data)
    result = assess(turn, novelty=lambda _: {"decision": "accept", "prior_equivalents": []})
    assert result.decision == "accept"
    assert result.concession_proofs[0].is_new_direct_commitment is True


def test_uncertain_novelty_never_preserves_acceptance_proofs():
    result = assess(
        repeated_turn(), novelty=lambda _: {"decision": "uncertain", "prior_equivalents": []}
    )
    assert result.decision == "uncertain"
    assert result.concession_proofs == []


@pytest.mark.parametrize(
    "failure",
    [
        "wrong-id",
        "wrong-time",
        "wrong-speaker",
        "invented-quote",
        "contradictory-accept",
        "invalid-json",
        "http",
    ],
)
def test_invalid_novelty_or_ungrounded_old_evidence_fails_closed(failure):
    turn = repeated_turn()
    before = turn.model_dump_json()

    def reply(context):
        if failure == "http":
            return httpx.Response(503, text="private-gateway-error")
        if failure == "invalid-json":
            return httpx.Response(200, json={"choices": [{"message": {"content": "broken"}}]})
        old = context["history"][0]
        proof = {key: old[key] for key in ("message_id", "turn_id", "speaker", "elapsed_ms")} | {
            "quote": old["text"]
        }
        if failure == "wrong-id":
            proof["message_id"] = "invented"
        elif failure == "wrong-time":
            proof["elapsed_ms"] += 1
        elif failure == "wrong-speaker":
            proof["speaker"] = "opponent"
        elif failure == "invented-quote":
            proof["quote"] = "Я обещал что-то другое"
        return {
            "decision": "accept" if failure == "contradictory-accept" else "reject",
            "prior_equivalents": [proof],
        }

    with pytest.raises(OfferValidationError, match="assessment unavailable"):
        assess(turn, novelty=reply)
    assert turn.model_dump_json() == before


def test_no_accepted_player_history_does_not_require_additional_novelty_call():
    data = repeated_turn().model_dump(mode="python")
    data["snapshot"]["transcript"] = []
    turn = TurnRequest.model_validate(data)
    assert assess(turn).decision == "accept"


def test_blocked_or_opponent_words_are_not_prior_player_commitments():
    data = repeated_turn().model_dump(mode="python")
    data["snapshot"]["transcript"][0]["text"] = "Я пришлю сертификаты качества."
    data["snapshot"]["transcript"].extend(
        [
            {
                "message_id": "blocked-old",
                "turn_id": "blocked-turn",
                "speaker": "player",
                "status": "blocked",
                "text": "Я гарантирую согласованный объём закупки.",
                "created_at": "2026-09-26T10:00:06Z",
                "elapsed_ms": 6000,
                "blocked_reason": "prompt_override",
            },
            {
                "message_id": "opponent-old",
                "turn_id": "opponent-turn",
                "speaker": "opponent",
                "status": "accepted",
                "text": "Я гарантирую согласованный объём закупки.",
                "created_at": "2026-09-26T10:00:07Z",
                "elapsed_ms": 7000,
                "blocked_reason": None,
            },
        ]
    )
    turn = TurnRequest.model_validate(data)

    def fresh(context):
        assert [item["message_id"] for item in context["history"]] == ["prior-player"]
        return {"decision": "accept", "prior_equivalents": []}

    assert assess(turn, novelty=fresh).decision == "accept"


def test_managed_turn_does_not_commit_offer_after_novelty_rejection():
    from test_v2_turn import settings

    from arena_ai.v2.turn import QwenTurnPipeline

    turn = repeated_turn()

    def gateway(req):
        messages = json.loads(req.content)["messages"]
        system = messages[0]["content"]
        context = json.loads(messages[1]["content"])
        if "[V2_GUARD]" in system:
            reply = {"decision": "allow", "reason": None}
        elif "[V2_OPPONENT]" in system:
            reply = offer(turn).model_dump(mode="json")
        elif "[V2_NOVELTY]" in system:
            reply = {"decision": "reject", "prior_equivalents": []}
        else:
            reply = {
                "decision": "accept",
                "terms_match_text": True,
                "concession_proofs": [
                    {
                        "requirement_id": "order-volume",
                        "is_new_direct_commitment": True,
                        "evidence": context["current_user"],
                    }
                ],
            }
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(reply)}}]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as http:
            return await QwenTurnPipeline(http, settings()).turn(turn)

    result = asyncio.run(run())
    assert result.status == "model_error"
    assert result.snapshot == turn.snapshot
    assert "4800" not in result.opponent_text
