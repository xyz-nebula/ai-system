"""Read-only offer gate; semantic Validator evidence is mandatory, not inferred."""

import re
from typing import Annotated, Literal

from pydantic import Field

from arena_ai.v2.contracts import (
    AppliedTransition,
    Contract,
    DealTerms,
    Evidence,
    Progress,
    Text,
    TurnRequest,
)


class PositionTransition(Contract):
    to_step_id: Text
    requirement_ids: Annotated[list[Text], Field(min_length=1)]


class ConcessionProof(Contract):
    requirement_id: Text
    is_new_direct_commitment: bool
    evidence: Evidence


class OpponentOffer(Contract):
    text: Text
    terms: DealTerms | None
    position_transition: PositionTransition | None


class OfferAssessment(Contract):
    decision: Literal["accept", "reject", "uncertain"]
    terms_match_text: bool
    concession_proofs: list[ConcessionProof]


class CheckedOffer(Contract):
    text: Text
    terms: DealTerms | None
    opponent_progress: Progress


class ConcessionSyntaxError(ValueError):
    """Conservative syntax veto; absence never proves a semantic commitment."""


def require_unconditional_unquoted_commitment(
    request: TurnRequest,
    offer: OpponentOffer,
) -> None:
    """Fail closed on obvious RU/EN conditions, negation and quoted authored markers.

    This is a limited veto, not a language parser. A sentence with both conditional
    context and a real promise may be conservatively refused; semantic acceptance
    still requires the model and grounded proof.
    """
    if offer.position_transition is None:
        return
    quote = request.user_text.casefold()
    markers = [
        marker.casefold()
        for step in request.case.opponent_strategy.steps
        if step.id == offer.position_transition.to_step_id
        for requirement in step.requires
        for marker in requirement.direct_commitment_markers
    ]
    quoted = [
        part
        for group in re.findall(r'«([^»]*)»|“([^”]*)”|"([^"]*)"', quote)
        for part in group
        if part
    ]
    if re.search(r"\b(?:если|при\s+условии|if|unless|provided\s+that)\b", quote) or any(
        re.search(r"(?<!\w)(?:не|not)\s+" + re.escape(marker), quote)
        or any(re.search(r"(?<!\w)" + re.escape(marker), part) for part in quoted)
        for marker in markers
    ):
        raise ConcessionSyntaxError("Concession requires unconditional unquoted commitment")


def check_offer(
    request: TurnRequest, offer: OpponentOffer, assessment: OfferAssessment
) -> CheckedOffer:
    """Check an offer without treating it as agreement or committing history."""
    request.snapshot.validate_for_case(request.case)
    require_unconditional_unquoted_commitment(request, offer)
    if assessment.decision != "accept" or not assessment.terms_match_text:
        raise ValueError("Offer requires a certain semantic acceptance and matching public text")
    visible = [offer.text]
    if offer.terms is not None:
        visible += [item.value for item in offer.terms.values if isinstance(item.value, str)]
        visible += [item.text for item in offer.terms.commitments]
    private = [
        request.case.player.private_context,
        request.case.opponent.private_context,
        *request.case.opponent_private_phrases,
    ]
    if any(
        phrase and phrase.casefold() in text.casefold() for phrase in private for text in visible
    ):
        raise ValueError("Offer contains a private phrase")
    stored = request.snapshot.state.agreement
    if stored is not None and offer.position_transition is not None:
        raise ValueError("Stored agreement cannot concede without validated renegotiation")
    if (
        stored is not None
        and offer.terms is not None
        and (
            {item.term_id: item.value for item in stored.values}
            != {item.term_id: item.value for item in offer.terms.values}
            or sorted((item.role_id, item.text) for item in stored.commitments)
            != sorted((item.role_id, item.text) for item in offer.terms.commitments)
        )
    ):
        raise ValueError("Stored agreement cannot be silently changed")
    current = request.snapshot.state.opponent_progress
    progress = (
        current.model_copy(deep=True)
        if current
        else Progress(
            current_step_id=request.case.opponent_strategy.steps[0].id,
            satisfied_requirement_ids=[],
            last_transition=None,
        )
    )
    steps = request.case.opponent_strategy.steps
    index = next(i for i, step in enumerate(steps) if step.id == progress.current_step_id)
    earned = {item.id for step in steps[1 : index + 1] for item in step.requires}
    if set(progress.satisfied_requirement_ids) != earned or (
        len(progress.satisfied_requirement_ids) != len(earned)
        or index > 0
        and progress.last_transition is None
    ):
        raise ValueError("Stored progress lacks earned transition history")
    transition = offer.position_transition
    if transition is not None:
        if index + 1 >= len(steps) or transition.to_step_id != steps[index + 1].id:
            raise ValueError("Concession must advance to the adjacent position")
        target = steps[index + 1]
        required = {item.id for item in target.requires}
        if set(transition.requirement_ids) != required or len(transition.requirement_ids) != len(
            required
        ):
            raise ValueError("Transition must satisfy exactly the target requirements")
        proofs = {item.requirement_id: item for item in assessment.concession_proofs}
        if set(proofs) != required or len(proofs) != len(assessment.concession_proofs):
            raise ValueError("Missing, extra or duplicate concession evidence")
        if required.intersection(progress.satisfied_requirement_ids):
            raise ValueError("Concession requirement already used")
        for requirement in target.requires:
            proof = proofs[requirement.id]
            evidence = proof.evidence
            if not proof.is_new_direct_commitment or (
                evidence.message_id != request.user_message_id
                or evidence.turn_id != request.turn_id
                or evidence.speaker != "player"
                or evidence.elapsed_ms != request.user_elapsed_ms
                or evidence.quote != request.user_text
            ):
                raise ValueError(
                    "Concession requires new direct evidence from the current user turn"
                )
            quote = evidence.quote.casefold()

            def contains(markers: list[str], quote: str = quote) -> bool:
                return any(
                    re.search(r"(?<!\w)" + re.escape(marker.casefold()), quote)
                    for marker in markers
                )

            if not contains(requirement.direct_commitment_markers) or not all(
                contains(group) for group in requirement.evidence_groups
            ):
                raise ValueError("Concession evidence lacks authored markers")
            if any(
                entry.status == "accepted"
                and entry.speaker == "player"
                and entry.text == evidence.quote
                for entry in request.snapshot.transcript
            ):
                raise ValueError("Repeated commitment is not a new concession")
        if offer.terms is None:
            raise ValueError("Transition must include an explicit full offer")
        progress = Progress(
            current_step_id=target.id,
            satisfied_requirement_ids=[
                *progress.satisfied_requirement_ids,
                *[item.id for item in target.requires],
            ],
            last_transition=AppliedTransition(
                from_step_id=progress.current_step_id,
                to_step_id=target.id,
                requirement_ids=[item.id for item in target.requires],
                evidence=assessment.concession_proofs[0].evidence.model_copy(deep=True),
            ),
        )
    elif assessment.concession_proofs:
        raise ValueError("Concession evidence without a transition")
    if offer.terms is not None:
        request.case.validate_deal(offer.terms, step_id=progress.current_step_id)
    return CheckedOffer(
        text=offer.text,
        terms=offer.terms.model_copy(deep=True) if offer.terms is not None else None,
        opponent_progress=progress,
    )
