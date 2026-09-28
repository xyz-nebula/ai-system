import pytest
from test_v2_turn import request

from arena_ai.v2.contracts import Evidence, TurnRequest
from arena_ai.v2.offers import OfferAssessment, OpponentOffer


def agreed_turn() -> TurnRequest:
    data = request().model_dump(mode="python")
    data["user_text"] = (
        "Согласен на цену 5000 рублей за единицу и поставку за 14 дней. "
        "Обязуюсь оплатить товар по цене 5000 рублей за единицу."
    )
    return TurnRequest.model_validate(data)


def test_full_agreement_cannot_silently_drop_earlier_partial_commitment():
    from arena_ai.v2.agreements import (
        AgreementAssessment,
        CommitmentProof,
        RuleProof,
        check_agreement,
    )

    data = agreed_turn().model_dump(mode="python")
    data["snapshot"]["state"].update(
        stage="partial_agreement",
        decision={
            "kind": "partial_agreement",
            "commitments": [{"role_id": "buyer", "text": "Передать список адресов"}],
            "open_points": ["Цена"],
        },
    )
    turn = TurnRequest.model_validate(data)
    offer = OpponentOffer.model_validate(
        {
            "text": "Согласен. Поставлю товар за 14 дней, вы оплачиваете по 5000 рублей за единицу.",
            "terms": turn.case.opponent_strategy.steps[0].terms.model_dump(mode="python"),
            "position_transition": None,
            "resolution": {"kind": "agreement"},
        }
    )
    player = Evidence(
        message_id=turn.user_message_id,
        turn_id=turn.turn_id,
        speaker="player",
        elapsed_ms=turn.user_elapsed_ms,
        quote=turn.user_text,
    )
    opponent = Evidence(
        message_id=turn.opponent_message_id,
        turn_id=turn.turn_id,
        speaker="opponent",
        elapsed_ms=turn.user_elapsed_ms,
        quote=offer.text,
    )
    assessment = AgreementAssessment(
        decision="accept",
        player_acceptance=player,
        opponent_acceptance=opponent,
        commitment_proofs=[
            CommitmentProof(commitment_index=0, evidence=opponent),
            CommitmentProof(commitment_index=1, evidence=player),
        ],
        rule_proofs=[RuleProof(rule_id="explicit-player-commitment", evidence=player)],
    )
    with pytest.raises(ValueError, match="partial commitments"):
        check_agreement(
            turn,
            offer,
            OfferAssessment(decision="accept", terms_match_text=True, concession_proofs=[]),
            assessment,
        )


def test_complete_mutual_agreement_requires_all_commitments_and_authored_rules() -> None:
    from arena_ai.v2.agreements import (
        AgreementAssessment,
        CommitmentProof,
        RuleProof,
        check_agreement,
    )

    turn = agreed_turn()
    offer = OpponentOffer.model_validate(
        {
            "text": "Согласен. Поставлю товар за 14 дней, вы оплачиваете по 5000 рублей за единицу.",
            "terms": turn.case.opponent_strategy.steps[0].terms.model_dump(mode="python"),
            "position_transition": None,
            "resolution": {"kind": "agreement"},
        }
    )
    player = Evidence(
        message_id=turn.user_message_id,
        turn_id=turn.turn_id,
        speaker="player",
        elapsed_ms=turn.user_elapsed_ms,
        quote=turn.user_text,
    )
    opponent = Evidence(
        message_id=turn.opponent_message_id,
        turn_id=turn.turn_id,
        speaker="opponent",
        elapsed_ms=turn.user_elapsed_ms,
        quote=offer.text,
    )
    assessment = AgreementAssessment(
        decision="accept",
        player_acceptance=player,
        opponent_acceptance=opponent,
        commitment_proofs=[
            CommitmentProof(commitment_index=0, evidence=opponent),
            CommitmentProof(commitment_index=1, evidence=player),
        ],
        rule_proofs=[RuleProof(rule_id="explicit-player-commitment", evidence=player)],
    )
    before = turn.model_dump_json()
    result = check_agreement(
        turn,
        offer,
        OfferAssessment(
            decision="accept",
            terms_match_text=True,
            concession_proofs=[],
        ),
        assessment,
    )
    assert result.values[0].value == 5000
    assert result.values[1].value == 14
    result.values[0].value = 1
    assert turn.model_dump_json() == before


@pytest.mark.parametrize(
    "text",
    [
        "Если согласуем бюджет, я согласен на цену 5000 рублей и поставку за 14 дней.",
        "Я не согласен на цену 5000 рублей и поставку за 14 дней.",
        "Коллега сказал: «Я согласен на цену 5000 рублей и поставку за 14 дней».",
    ],
)
def test_conditional_negated_or_quoted_acceptance_never_becomes_full_agreement(text: str) -> None:
    from arena_ai.v2.agreements import (
        AgreementAssessment,
        CommitmentProof,
        RuleProof,
        check_agreement,
    )

    data = agreed_turn().model_dump(mode="python")
    data["user_text"] = text
    turn = TurnRequest.model_validate(data)
    offer = OpponentOffer.model_validate(
        {
            "text": "Согласен. Поставлю товар за 14 дней, вы оплачиваете по 5000 рублей за единицу.",
            "terms": turn.case.opponent_strategy.steps[0].terms.model_dump(mode="python"),
            "position_transition": None,
            "resolution": {"kind": "agreement"},
        }
    )
    player = Evidence(
        message_id=turn.user_message_id,
        turn_id=turn.turn_id,
        speaker="player",
        elapsed_ms=turn.user_elapsed_ms,
        quote=text,
    )
    opponent = Evidence(
        message_id=turn.opponent_message_id,
        turn_id=turn.turn_id,
        speaker="opponent",
        elapsed_ms=turn.user_elapsed_ms,
        quote=offer.text,
    )
    assessment = AgreementAssessment(
        decision="accept",
        player_acceptance=player,
        opponent_acceptance=opponent,
        commitment_proofs=[
            CommitmentProof(commitment_index=0, evidence=opponent),
            CommitmentProof(commitment_index=1, evidence=player),
        ],
        rule_proofs=[RuleProof(rule_id="explicit-player-commitment", evidence=player)],
    )
    with pytest.raises(ValueError, match="unconditional own acceptance"):
        check_agreement(
            turn,
            offer,
            OfferAssessment(
                decision="accept",
                terms_match_text=True,
                concession_proofs=[],
            ),
            assessment,
        )


@pytest.fixture
def claim():
    from arena_ai.v2.agreements import AgreementAssessment, CommitmentProof, RuleProof

    turn = agreed_turn()
    offer = OpponentOffer.model_validate(
        {
            "text": "Согласен. Поставлю товар за 14 дней, вы оплачиваете по 5000 рублей за единицу.",
            "terms": turn.case.opponent_strategy.steps[0].terms.model_dump(mode="python"),
            "position_transition": None,
            "resolution": {"kind": "agreement"},
        }
    )
    player = Evidence(
        message_id=turn.user_message_id,
        turn_id=turn.turn_id,
        speaker="player",
        elapsed_ms=turn.user_elapsed_ms,
        quote=turn.user_text,
    )
    opponent = Evidence(
        message_id=turn.opponent_message_id,
        turn_id=turn.turn_id,
        speaker="opponent",
        elapsed_ms=turn.user_elapsed_ms,
        quote=offer.text,
    )
    assessment = AgreementAssessment(
        decision="accept",
        player_acceptance=player,
        opponent_acceptance=opponent,
        commitment_proofs=[
            CommitmentProof(commitment_index=0, evidence=opponent),
            CommitmentProof(commitment_index=1, evidence=player),
        ],
        rule_proofs=[RuleProof(rule_id="explicit-player-commitment", evidence=player)],
    )
    return turn, offer, assessment


@pytest.mark.parametrize(
    "fault",
    [
        "missing-player",
        "missing-opponent",
        "uncertain",
        "reject",
        "wrong-message",
        "wrong-time",
        "wrong-speaker",
        "partial-acceptance-quote",
        "missing-commitment",
        "duplicate-commitment",
        "wrong-commitment-role",
        "missing-rule",
        "unknown-rule",
        "duplicate-rule",
        "wrong-rule-role",
        "unquoted-commitment",
        "out-of-window",
        "not-a-claim",
        "no-terms",
    ],
)
def test_forged_incomplete_or_unchecked_agreement_is_rejected(claim, fault: str) -> None:
    from arena_ai.v2.agreements import AgreementAssessment, check_agreement

    turn, offer, assessment = claim
    data = assessment.model_dump(mode="python")
    if fault == "missing-player":
        data["player_acceptance"] = None
    elif fault == "missing-opponent":
        data["opponent_acceptance"] = None
    elif fault in ("uncertain", "reject"):
        data["decision"] = fault
    elif fault == "wrong-message":
        data["player_acceptance"]["message_id"] = "forged"
    elif fault == "wrong-time":
        data["opponent_acceptance"]["elapsed_ms"] += 1
    elif fault == "wrong-speaker":
        data["opponent_acceptance"]["speaker"] = "player"
    elif fault == "partial-acceptance-quote":
        data["player_acceptance"]["quote"] = "Согласен"
    elif fault == "missing-commitment":
        data["commitment_proofs"].pop()
    elif fault == "duplicate-commitment":
        data["commitment_proofs"].append(data["commitment_proofs"][0])
    elif fault == "wrong-commitment-role":
        data["commitment_proofs"][0]["evidence"] = data["player_acceptance"]
    elif fault == "missing-rule":
        data["rule_proofs"] = []
    elif fault == "unknown-rule":
        data["rule_proofs"][0]["rule_id"] = "unknown"
    elif fault == "duplicate-rule":
        data["rule_proofs"].append(data["rule_proofs"][0])
    elif fault == "wrong-rule-role":
        data["rule_proofs"][0]["evidence"] = data["opponent_acceptance"]
    elif fault == "unquoted-commitment":
        data["commitment_proofs"][0]["evidence"]["quote"] = "Поставлю за 1 день"
    elif fault == "out-of-window":
        offer.terms.values[0].value = 1
    elif fault == "not-a-claim":
        offer.resolution = None
    elif fault == "no-terms":
        offer.terms = None
    with pytest.raises(ValueError):
        check_agreement(
            turn,
            offer,
            OfferAssessment(
                decision="accept",
                terms_match_text=True,
                concession_proofs=[],
            ),
            AgreementAssessment.model_validate(data),
        )


def test_agreement_commitments_and_rules_follow_swapped_active_roles(claim) -> None:
    from arena_ai.v2.agreements import (
        AgreementAssessment,
        CommitmentProof,
        RuleProof,
        check_agreement,
    )

    original, _, _ = claim
    data = original.model_dump(mode="python")
    data["case"]["player"], data["case"]["opponent"] = (
        data["case"]["opponent"],
        data["case"]["player"],
    )
    data["snapshot"]["player_role_id"], data["snapshot"]["opponent_role_id"] = "supplier", "buyer"
    data["user_text"] = (
        "Согласен на цену 5000 рублей за единицу. Обязуюсь поставить товар за 14 дней."
    )
    turn = TurnRequest.model_validate(data)
    offer = OpponentOffer.model_validate(
        {
            "text": "Согласен на поставку за 14 дней. Обязуюсь оплатить товар по 5000 рублей за единицу.",
            "terms": turn.case.opponent_strategy.steps[0].terms.model_dump(mode="python"),
            "position_transition": None,
            "resolution": {"kind": "agreement"},
        }
    )
    player = Evidence(
        message_id=turn.user_message_id,
        turn_id=turn.turn_id,
        speaker="player",
        elapsed_ms=turn.user_elapsed_ms,
        quote=turn.user_text,
    )
    opponent = Evidence(
        message_id=turn.opponent_message_id,
        turn_id=turn.turn_id,
        speaker="opponent",
        elapsed_ms=turn.user_elapsed_ms,
        quote=offer.text,
    )
    assessment = AgreementAssessment(
        decision="accept",
        player_acceptance=player,
        opponent_acceptance=opponent,
        commitment_proofs=[
            CommitmentProof(commitment_index=0, evidence=player),
            CommitmentProof(commitment_index=1, evidence=opponent),
        ],
        rule_proofs=[RuleProof(rule_id="explicit-player-commitment", evidence=opponent)],
    )
    result = check_agreement(
        turn,
        offer,
        OfferAssessment(
            decision="accept",
            terms_match_text=True,
            concession_proofs=[],
        ),
        assessment,
    )
    assert result.commitments[0].role_id == "supplier"
    assert result.commitments[1].role_id == "buyer"
