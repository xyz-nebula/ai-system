"""Read-only full-deal gate: a proposal is not a mutual agreement."""

import re
from typing import Annotated, Literal

from pydantic import Field

from arena_ai.v2.contracts import Contract, DealTerms, Evidence, Text, TurnRequest
from arena_ai.v2.offers import OfferAssessment, OpponentOffer, check_offer


class CommitmentProof(Contract):
    commitment_index: Annotated[int, Field(ge=0)]
    evidence: Evidence


class RuleProof(Contract):
    rule_id: Text
    evidence: Evidence


class AgreementAssessment(Contract):
    decision: Literal["accept", "reject", "uncertain"]
    player_acceptance: Evidence | None
    opponent_acceptance: Evidence | None
    commitment_proofs: list[CommitmentProof]
    rule_proofs: list[RuleProof]


class AgreementSyntaxError(ValueError):
    """Limited acceptance veto; absence does not establish semantic agreement."""


def require_unconditional_own_acceptance(text: str) -> None:
    """Conservatively inspect the first sentence, not conditional action triggers.

    This is not a language parser. Ambiguous acceptance requires another turn;
    later sentences and material contradictions still require semantic validation.
    """
    sentence = re.split(r"(?<!\d)[.!?](?!\d)|\n", text.casefold(), maxsplit=1)[0]
    act = r"(?:соглас(?:ен|на|ны)|принима(?:ю|ем)|подтвержда(?:ю|ем)|agree|accept)"
    quoted = [
        part
        for group in re.findall(r'«([^»]*)»|“([^”]*)”|"([^"]*)"', sentence)
        for part in group
        if part
    ]
    if (
        re.search(r"\b(?:если|при\s+условии|if|unless|provided\s+that)\b", sentence)
        or re.search(r"\b(?:не|not|don't|do\s+not)\s+" + act, sentence)
        or any(re.search(r"\b" + act, part) for part in quoted)
    ):
        raise AgreementSyntaxError("Agreement requires unconditional own acceptance")


def _evidence_is_grounded(
    evidence: Evidence,
    request: TurnRequest,
    offer: OpponentOffer,
    speaker: Literal["player", "opponent"],
    *,
    current: bool = False,
) -> bool:
    if evidence.speaker != speaker or not any(c.isalnum() for c in evidence.quote):
        return False
    message_id = request.user_message_id if speaker == "player" else request.opponent_message_id
    text = request.user_text if speaker == "player" else offer.text
    if evidence.message_id == message_id:
        return (
            evidence.turn_id == request.turn_id
            and evidence.elapsed_ms == request.user_elapsed_ms
            and (evidence.quote == text if current else evidence.quote in text)
        )
    return not current and any(
        entry.message_id == evidence.message_id
        and entry.turn_id == evidence.turn_id
        and entry.speaker == speaker
        and entry.status == "accepted"
        and entry.elapsed_ms == evidence.elapsed_ms
        and evidence.quote in entry.text
        for entry in request.snapshot.transcript
    )


def check_agreement(
    request: TurnRequest,
    offer: OpponentOffer,
    offer_assessment: OfferAssessment,
    assessment: AgreementAssessment,
) -> DealTerms:
    checked = check_offer(request, offer, offer_assessment)
    if offer.resolution is None or checked.terms is None or assessment.decision != "accept":
        raise ValueError(
            "Full agreement requires an explicit checked package and certain assessment"
        )
    for speaker, evidence in (
        ("player", assessment.player_acceptance),
        ("opponent", assessment.opponent_acceptance),
    ):
        if evidence is None or not _evidence_is_grounded(
            evidence,
            request,
            offer,
            speaker,
            current=True,
        ):
            raise ValueError("Agreement requires current mutual acceptance evidence")
        require_unconditional_own_acceptance(evidence.quote)
    proofs = {item.commitment_index: item.evidence for item in assessment.commitment_proofs}
    if set(proofs) != set(range(len(checked.terms.commitments))) or len(proofs) != len(
        assessment.commitment_proofs
    ):
        raise ValueError("Every package commitment requires exactly one proof")
    for index, commitment in enumerate(checked.terms.commitments):
        speaker = "player" if commitment.role_id == request.case.player.role_id else "opponent"
        if not _evidence_is_grounded(proofs[index], request, offer, speaker):
            raise ValueError("Commitment has invalid role-grounded evidence")
    policy = request.case.agreement_policy
    rules = {item.id: item for item in policy.commitment_rules}
    supplied = {item.rule_id: item.evidence for item in assessment.rule_proofs}
    if set(supplied) != set(policy.required_commitment_ids) or len(supplied) != len(
        assessment.rule_proofs
    ):
        raise ValueError("Agreement requires exactly the authored mandatory commitment rules")
    for rule_id, evidence in supplied.items():
        speaker = "player" if rules[rule_id].role_id == request.case.player.role_id else "opponent"
        if not _evidence_is_grounded(evidence, request, offer, speaker):
            raise ValueError("Mandatory commitment rule has invalid role-grounded evidence")
    return checked.terms.model_copy(deep=True)
