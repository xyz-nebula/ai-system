import asyncio
import json

import httpx
import pytest
from test_v2_turn import request, settings

from arena_ai.v2.contracts import TurnRequest
from arena_ai.v2.turn import QwenTurnPipeline


def partial_turn():
    data = request().model_dump(mode="python")
    data["user_text"] = "Согласен. Обязуюсь прислать перечень товаров. Цену и срок ещё обсудим."
    return TurnRequest.model_validate(data)


def partial_claim():
    return {
        "kind": "partial_agreement",
        "commitments": [{"role_id": "buyer", "text": "Прислать перечень товаров"}],
        "open_points": ["Цена", "Срок поставки"],
    }


def run_decision(turn, claim, *, assessment_change=None, opponent_text=None, fault=None):
    def gateway(req):
        messages = json.loads(req.content)["messages"]
        system = messages[0]["content"]
        context = json.loads(messages[1]["content"])
        if "[V2_GUARD]" in system:
            reply = {"decision": "allow", "reason": None}
        elif "[V2_OPPONENT]" in system:
            reply = {
                "text": opponent_text
                or "Согласен. Вы присылаете перечень товаров, цену и срок ещё обсудим.",
                "terms": None,
                "position_transition": None,
                "resolution": claim,
            }
            if fault == "null-term-values":
                reply["terms"] = {
                    "values": [
                        {"term_id": "price_per_unit", "value": None},
                        {"term_id": "delivery_days", "value": None},
                    ],
                    "commitments": claim["commitments"],
                }
        elif "[V2_DECISION_VALIDATOR]" in system:
            if fault == "http":
                return httpx.Response(503, text="private-gateway-error")
            if fault == "json":
                return httpx.Response(200, json={"choices": [{"message": {"content": "broken"}}]})
            assert "opponent_strategy" not in context
            assert "private_context" not in json.dumps(context)
            reply = {
                "decision": "accept",
                "player_acceptance": context["current_player"],
                "opponent_acceptance": context["current_opponent"],
                "commitment_proofs": [
                    {"commitment_index": 0, "evidence": context["current_player"]}
                ]
                if claim["kind"] == "partial_agreement"
                else [],
            }
            if assessment_change:
                assessment_change(reply)
        else:
            reply = {"decision": "accept", "terms_match_text": True, "concession_proofs": []}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(reply)}}]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as http:
            return await QwenTurnPipeline(http, settings()).turn(turn)

    return asyncio.run(run())


def test_mutual_partial_commitment_is_not_full_agreement_and_keeps_round_open():
    turn = partial_turn()
    before = turn.model_dump_json()
    result = run_decision(turn, partial_claim())
    assert result.status == "accepted"
    assert result.snapshot.state.stage == "partial_agreement"
    assert result.snapshot.state.agreement is None
    assert result.snapshot.state.decision.model_dump() == partial_claim()
    assert result.snapshot.round == turn.snapshot.round
    assert turn.model_dump_json() == before


def test_partial_reply_with_unknown_null_term_values_is_not_repaired_or_committed():
    turn = partial_turn()
    result = run_decision(turn, partial_claim(), fault="null-term-values")
    assert result.status == "model_error"
    assert result.error_code == "opponent_model_error"
    assert result.snapshot == turn.snapshot
    assert "Согласен" not in result.opponent_text


@pytest.mark.parametrize(
    "failure",
    [
        "reject",
        "uncertain",
        "missing-acceptance",
        "wrong-id",
        "wrong-role",
        "missing-proof",
        "duplicate-proof",
        "inactive-role",
        "duplicate-commitment",
        "private-open-point",
        "private-commitment",
        "conditional",
        "negated",
        "quoted",
    ],
)
def test_unverified_partial_decision_preserves_entire_snapshot(failure):
    data = partial_turn().model_dump(mode="python")
    claim = partial_claim()
    if failure == "inactive-role":
        claim["commitments"][0]["role_id"] = "hr"
    elif failure == "duplicate-commitment":
        claim["commitments"] *= 2
    elif failure == "private-open-point":
        claim["open_points"] = [data["case"]["opponent"]["private_context"]]
    elif failure == "private-commitment":
        claim["commitments"][0]["text"] = data["case"]["opponent"]["private_context"]
    elif failure == "conditional":
        data["user_text"] = "Если согласуем цену, согласен прислать перечень товаров."
    elif failure == "negated":
        data["user_text"] = "Я не согласен прислать перечень товаров."
    elif failure == "quoted":
        data["user_text"] = "Коллега сказал: «Я согласен прислать перечень товаров»."
    turn = TurnRequest.model_validate(data)

    def change(reply):
        if failure in ("reject", "uncertain"):
            reply["decision"] = failure
        elif failure == "missing-acceptance":
            reply["player_acceptance"] = None
        elif failure == "wrong-id":
            reply["player_acceptance"]["message_id"] = "invented"
        elif failure == "wrong-role":
            reply["commitment_proofs"][0]["evidence"] = reply["opponent_acceptance"]
        elif failure == "missing-proof":
            reply["commitment_proofs"] = []
        elif failure == "duplicate-proof":
            reply["commitment_proofs"] *= 2

    result = run_decision(turn, claim, assessment_change=change)
    assert result.status == "model_error"
    assert result.snapshot.model_dump_json() == turn.snapshot.model_dump_json()
    assert "Согласен" not in result.opponent_text


def test_mutual_deferral_records_reason_and_next_step_without_closing_round():
    data = request().model_dump(mode="python")
    data["user_text"] = (
        "Согласен отложить обсуждение: нужно уточнить бюджет. Я уточню бюджет и вернусь к обсуждению."
    )
    turn = TurnRequest.model_validate(data)
    claim = {
        "kind": "deferred",
        "reason": "Нужно уточнить бюджет",
        "next_step": "Покупатель уточнит бюджет и вернётся к обсуждению",
    }
    result = run_decision(
        turn,
        claim,
        opponent_text="Согласен отложить обсуждение до уточнения вами бюджета. После этого вернёмся к обсуждению.",
    )
    assert result.status == "accepted"
    assert result.snapshot.state.stage == "deferred"
    assert result.snapshot.state.decision.model_dump() == claim
    assert result.snapshot.state.agreement is None
    assert result.snapshot.round == turn.snapshot.round


@pytest.mark.parametrize(
    "failure",
    ["missing-player", "wrong-time", "extra-proof", "private-reason", "private-next-step"],
)
def test_invalid_deferred_decision_does_not_change_snapshot(failure):
    turn = partial_turn()
    claim = {"kind": "deferred", "reason": "Уточнить бюджет", "next_step": "Вернуться к обсуждению"}
    if failure == "private-reason":
        claim["reason"] = turn.case.opponent.private_context
    elif failure == "private-next-step":
        claim["next_step"] = turn.case.opponent.private_context

    def change(reply):
        if failure == "missing-player":
            reply["player_acceptance"] = None
        elif failure == "wrong-time":
            reply["opponent_acceptance"]["elapsed_ms"] += 1
        elif failure == "extra-proof":
            reply["commitment_proofs"] = [
                {"commitment_index": 0, "evidence": reply["player_acceptance"]}
            ]

    result = run_decision(turn, claim, assessment_change=change)
    assert result.status == "model_error"
    assert result.snapshot == turn.snapshot


@pytest.mark.parametrize("stored", ["full", "partial"])
@pytest.mark.parametrize("new_kind", ["partial_agreement", "deferred"])
def test_new_decision_cannot_erase_existing_commitments(stored, new_kind):
    data = partial_turn().model_dump(mode="python")
    if stored == "full":
        data["snapshot"]["state"].update(
            stage="agreed", agreement=data["case"]["opponent_strategy"]["steps"][0]["terms"]
        )
    else:
        old = partial_claim()
        old["commitments"][0]["text"] = "Передать список адресов"
        data["snapshot"]["state"].update(stage="partial_agreement", decision=old)
    turn = TurnRequest.model_validate(data)
    claim = (
        partial_claim()
        if new_kind == "partial_agreement"
        else {
            "kind": "deferred",
            "reason": "Уточнить бюджет",
            "next_step": "Вернуться к обсуждению",
        }
    )
    result = run_decision(turn, claim)
    assert result.status == "model_error"
    assert result.snapshot == turn.snapshot


def test_continuing_without_new_resolution_preserves_partial_decision():
    data = partial_turn().model_dump(mode="python")
    data["snapshot"]["state"].update(stage="partial_agreement", decision=partial_claim())
    turn = TurnRequest.model_validate(data)
    result = run_decision(turn, None, opponent_text="Какой вопрос обсудим следующим?")
    assert result.status == "accepted"
    assert result.snapshot.state.decision == turn.snapshot.state.decision
    assert result.snapshot.round == turn.snapshot.round


def test_partial_snapshot_cannot_assign_commitment_to_inactive_role():
    data = partial_turn().model_dump(mode="python")
    claim = partial_claim()
    claim["commitments"][0]["role_id"] = "hr"
    data["snapshot"]["state"].update(stage="partial_agreement", decision=claim)
    with pytest.raises(ValueError, match="inactive role"):
        TurnRequest.model_validate(data)


@pytest.mark.parametrize("fault", ["http", "json"])
def test_decision_model_failure_does_not_publish_claim_or_gateway_details(fault):
    turn = partial_turn()
    result = run_decision(turn, partial_claim(), fault=fault)
    assert result.status == "model_error"
    assert result.error_code == "decision_validation_failed"
    assert result.snapshot == turn.snapshot
    assert "Согласен" not in result.opponent_text
    assert "private-gateway-error" not in result.model_dump_json()


def test_partial_commitment_role_follows_selected_pair_not_fixed_buyer_role():
    data = partial_turn().model_dump(mode="python")
    data["case"]["player"], data["case"]["opponent"] = (
        data["case"]["opponent"],
        data["case"]["player"],
    )
    data["snapshot"]["player_role_id"], data["snapshot"]["opponent_role_id"] = "supplier", "buyer"
    data["user_text"] = "Согласен. Обязуюсь прислать каталог товаров. Цену и срок ещё обсудим."
    claim = partial_claim()
    claim["commitments"][0] = {"role_id": "supplier", "text": "Прислать каталог товаров"}
    turn = TurnRequest.model_validate(data)
    result = run_decision(
        turn, claim, opponent_text="Согласен. Вы пришлёте каталог, цену и срок ещё обсудим."
    )
    assert result.status == "accepted"
    assert result.snapshot.state.decision.commitments[0].role_id == "supplier"


def test_partial_commitments_from_both_sides_require_role_specific_proofs():
    turn = partial_turn()
    claim = partial_claim()
    claim["commitments"].append({"role_id": "supplier", "text": "Прислать каталог"})

    def prove_both(reply):
        reply["commitment_proofs"].append(
            {"commitment_index": 1, "evidence": reply["opponent_acceptance"]}
        )

    result = run_decision(
        turn,
        claim,
        assessment_change=prove_both,
        opponent_text="Согласен. Я пришлю каталог, вы — перечень товаров. Цену и срок ещё обсудим.",
    )
    assert result.status == "accepted"
    assert len(result.snapshot.state.decision.commitments) == 2
