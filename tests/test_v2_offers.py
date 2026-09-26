from pathlib import Path

import pytest

from arena_ai.v2.contracts import TurnRequest

EXAMPLES = Path(__file__).resolve().parents[1] / "docs/api/v2/examples"


def request() -> TurnRequest:
    return TurnRequest.model_validate_json((EXAMPLES / "supply-turn.request.json").read_text())


@pytest.mark.parametrize(
    "text",
    [
        "Если потом согласуем бюджет, я обязуюсь обеспечить объём заказа.",
        "Я не обязуюсь обеспечить объём заказа.",
        "Коллега сказал: «Я обязуюсь обеспечить объём заказа». Это не моё обещание.",
    ],
)
def test_obviously_conditional_negated_or_quoted_commitment_cannot_earn_concession(
    text: str,
) -> None:
    from arena_ai.v2.contracts import Evidence
    from arena_ai.v2.offers import (
        ConcessionProof,
        OfferAssessment,
        OpponentOffer,
        PositionTransition,
        check_offer,
    )

    data = request().model_dump(mode="python")
    data["user_text"] = text
    turn = TurnRequest.model_validate(data)
    offer = OpponentOffer(
        text="Цена 4800 рублей за единицу, поставка за 12 дней.",
        terms=turn.case.opponent_strategy.steps[1].terms,
        position_transition=PositionTransition(
            to_step_id="target", requirement_ids=["order-volume"]
        ),
    )
    assessment = OfferAssessment(
        decision="accept",
        terms_match_text=True,
        concession_proofs=[
            ConcessionProof(
                requirement_id="order-volume",
                is_new_direct_commitment=True,
                evidence=Evidence(
                    message_id=turn.user_message_id,
                    turn_id=turn.turn_id,
                    speaker="player",
                    elapsed_ms=turn.user_elapsed_ms,
                    quote=text,
                ),
            )
        ],
    )
    with pytest.raises(ValueError, match="unconditional unquoted"):
        check_offer(turn, offer, assessment)


def test_checked_offer_uses_current_window_and_does_not_mutate_the_request() -> None:
    from arena_ai.v2.offers import OfferAssessment, OpponentOffer, check_offer

    turn = request()
    before = turn.model_dump_json()
    offer = OpponentOffer(
        text="Цена 5000 за единицу, доставка за 14 дней.",
        terms=turn.case.opponent_strategy.steps[0].terms,
        position_transition=None,
    )
    result = check_offer(
        turn,
        offer,
        OfferAssessment(
            decision="accept",
            terms_match_text=True,
            concession_proofs=[],
        ),
    )
    assert result.opponent_progress.current_step_id == "declared"
    assert result.terms.values[0].value == 5000
    result.terms.values[0].value = 1
    assert turn.model_dump_json() == before


@pytest.mark.parametrize(
    "decision,matches", [("reject", True), ("uncertain", True), ("accept", False)]
)
def test_semantically_unchecked_or_mismatched_offer_is_rejected(
    decision: str, matches: bool
) -> None:
    from arena_ai.v2.offers import OfferAssessment, OpponentOffer, check_offer

    turn = request()
    offer = OpponentOffer(
        text="Цена 1 рубль.",
        terms=turn.case.opponent_strategy.steps[0].terms,
        position_transition=None,
    )
    with pytest.raises(ValueError):
        check_offer(
            turn,
            offer,
            OfferAssessment(
                decision=decision,
                terms_match_text=matches,
                concession_proofs=[],
            ),
        )


def test_earned_adjacent_concession_records_current_user_evidence() -> None:
    from arena_ai.v2.contracts import Evidence
    from arena_ai.v2.offers import (
        ConcessionProof,
        OfferAssessment,
        OpponentOffer,
        PositionTransition,
        check_offer,
    )

    data = request().model_dump(mode="python")
    data["user_text"] = "Я обязуюсь обеспечить объём заказа."
    turn = TurnRequest.model_validate(data)
    evidence = Evidence(
        message_id=turn.user_message_id,
        turn_id=turn.turn_id,
        speaker="player",
        elapsed_ms=turn.user_elapsed_ms,
        quote=turn.user_text,
    )
    offer = OpponentOffer(
        text="Цена 4800 за единицу, доставка за 12 дней.",
        terms=turn.case.opponent_strategy.steps[1].terms,
        position_transition=PositionTransition(
            to_step_id="target", requirement_ids=["order-volume"]
        ),
    )
    result = check_offer(
        turn,
        offer,
        OfferAssessment(
            decision="accept",
            terms_match_text=True,
            concession_proofs=[
                ConcessionProof(
                    requirement_id="order-volume",
                    is_new_direct_commitment=True,
                    evidence=evidence,
                )
            ],
        ),
    )
    assert result.opponent_progress.current_step_id == "target"
    assert result.opponent_progress.satisfied_requirement_ids == ["order-volume"]
    assert result.opponent_progress.last_transition.evidence.message_id == turn.user_message_id
    assert turn.snapshot.state.opponent_progress is None


@pytest.mark.parametrize(
    "mutation",
    [
        "skip",
        "missing_terms",
        "missing_proof",
        "wrong_message",
        "wrong_turn",
        "wrong_speaker",
        "wrong_time",
        "fragment_quote",
        "not_direct",
        "missing_markers",
        "repeat",
    ],
)
def test_invalid_concession_is_rejected_without_mutating_backend_state(mutation: str) -> None:
    from arena_ai.v2.offers import OfferAssessment, OpponentOffer, check_offer

    data = request().model_dump(mode="python")
    data["user_text"] = "Я обязуюсь обеспечить объём заказа."
    if mutation == "missing_markers":
        data["user_text"] = "Просто снизьте цену."
    if mutation == "repeat":
        data["snapshot"]["transcript"] = [
            {
                "message_id": "old-message",
                "turn_id": "old-turn",
                "speaker": "player",
                "status": "accepted",
                "text": data["user_text"],
                "blocked_reason": None,
                "created_at": data["snapshot"]["round"]["started_at"],
                "elapsed_ms": 0,
            }
        ]
    turn = TurnRequest.model_validate(data)
    offer = {
        "text": "Цена 4800 за единицу, доставка за 12 дней.",
        "terms": turn.case.opponent_strategy.steps[1].terms.model_dump(mode="python"),
        "position_transition": {"to_step_id": "target", "requirement_ids": ["order-volume"]},
    }
    proof = {
        "requirement_id": "order-volume",
        "is_new_direct_commitment": mutation != "not_direct",
        "evidence": {
            "message_id": turn.user_message_id,
            "turn_id": turn.turn_id,
            "speaker": "player",
            "elapsed_ms": turn.user_elapsed_ms,
            "quote": turn.user_text,
        },
    }
    if mutation == "skip":
        offer["position_transition"]["to_step_id"] = "red-line"
    elif mutation == "missing_terms":
        offer["terms"] = None
    elif mutation == "wrong_message":
        proof["evidence"]["message_id"] = "invented"
    elif mutation == "wrong_turn":
        proof["evidence"]["turn_id"] = "invented"
    elif mutation == "wrong_speaker":
        proof["evidence"]["speaker"] = "opponent"
    elif mutation == "wrong_time":
        proof["evidence"]["elapsed_ms"] += 1
    elif mutation == "fragment_quote":
        proof["evidence"]["quote"] = "обязуюсь"
    before = turn.model_dump_json()
    with pytest.raises(ValueError):
        check_offer(
            turn,
            OpponentOffer.model_validate(offer),
            OfferAssessment(
                decision="accept",
                terms_match_text=True,
                concession_proofs=[] if mutation == "missing_proof" else [proof],
            ),
        )
    assert turn.model_dump_json() == before


@pytest.mark.parametrize("mutation", ["value", "commitment"])
def test_existing_agreement_cannot_be_silently_changed(mutation: str) -> None:
    from arena_ai.v2.offers import OfferAssessment, OpponentOffer, check_offer

    data = request().model_dump(mode="python")
    old = data["case"]["opponent_strategy"]["steps"][0]["terms"]
    data["snapshot"]["state"].update(stage="agreed", agreement=old)
    turn = TurnRequest.model_validate(data)
    terms = turn.snapshot.state.agreement.model_copy(deep=True)
    if mutation == "value":
        terms.values[0].value = 4800
    else:
        terms.commitments[0].text = "Старые обязательства отменены"
    with pytest.raises(ValueError):
        check_offer(
            turn,
            OpponentOffer(text="Меняем условия.", terms=terms, position_transition=None),
            OfferAssessment(decision="accept", terms_match_text=True, concession_proofs=[]),
        )


def test_private_phrase_in_nested_commitments_is_not_publishable() -> None:
    from arena_ai.v2.offers import OfferAssessment, OpponentOffer, check_offer

    data = request().model_dump(mode="python")
    data["case"]["opponent_private_phrases"] = ["NEVER_PUBLISH_SENTINEL"]
    turn = TurnRequest.model_validate(data)
    terms = turn.case.opponent_strategy.steps[0].terms.model_copy(deep=True)
    terms.commitments[0].text = "NEVER_PUBLISH_SENTINEL"
    with pytest.raises(ValueError, match="private"):
        check_offer(
            turn,
            OpponentOffer(text="Принято", terms=terms, position_transition=None),
            OfferAssessment(decision="accept", terms_match_text=True, concession_proofs=[]),
        )


@pytest.mark.parametrize(
    "name,text",
    [
        ("supply-turn.request.json", "Я обязуюсь обеспечить объём заказа."),
        (
            "next-day-turn.request.json",
            "Я обязуюсь компенсировать последствия и сразу сообщать о проблемах.",
        ),
    ],
)
def test_concession_gate_uses_authored_rules_for_different_cases(name: str, text: str) -> None:
    from arena_ai.v2.contracts import Evidence
    from arena_ai.v2.offers import (
        ConcessionProof,
        OfferAssessment,
        OpponentOffer,
        PositionTransition,
        check_offer,
    )

    turn = TurnRequest.model_validate_json((EXAMPLES / name).read_text())
    data = turn.model_dump(mode="python")
    data["user_text"] = text
    turn = TurnRequest.model_validate(data)
    target = turn.case.opponent_strategy.steps[1]
    proof = Evidence(
        message_id=turn.user_message_id,
        turn_id=turn.turn_id,
        speaker="player",
        elapsed_ms=turn.user_elapsed_ms,
        quote=text,
    )
    result = check_offer(
        turn,
        OpponentOffer(
            text="Подтверждаю обсуждаемый пакет условий.",
            terms=target.terms,
            position_transition=PositionTransition(
                to_step_id=target.id, requirement_ids=[item.id for item in target.requires]
            ),
        ),
        OfferAssessment(
            decision="accept",
            terms_match_text=True,
            concession_proofs=[
                ConcessionProof(
                    requirement_id=item.id, is_new_direct_commitment=True, evidence=proof
                )
                for item in target.requires
            ],
        ),
    )
    assert result.opponent_progress.current_step_id == "target"


def test_current_progress_cannot_skip_to_an_earned_position_without_history() -> None:
    from arena_ai.v2.offers import OfferAssessment, OpponentOffer, check_offer

    data = request().model_dump(mode="python")
    data["snapshot"]["state"]["opponent_progress"] = {
        "current_step_id": "target",
        "satisfied_requirement_ids": ["order-volume"],
        "last_transition": None,
    }
    turn = TurnRequest.model_validate(data)
    with pytest.raises(ValueError, match="progress"):
        check_offer(
            turn,
            OpponentOffer(
                text="Цена 4800 за единицу, доставка за 12 дней.",
                terms=turn.case.opponent_strategy.steps[1].terms,
                position_transition=None,
            ),
            OfferAssessment(decision="accept", terms_match_text=True, concession_proofs=[]),
        )
