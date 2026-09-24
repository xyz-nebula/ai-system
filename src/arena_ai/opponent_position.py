"""Validated position progress for a stateless opponent turn."""

import re

from arena_ai.contracts import (
    AgreementResolution,
    AppliedPositionTransition,
    DeferredDecision,
    OpponentPositionProgress,
    OpponentProposal,
    OpponentStrategy,
    PartialDecision,
)


def apply_position_transition(
    *,
    strategy: OpponentStrategy | None,
    current: OpponentPositionProgress | None,
    proposal: OpponentProposal,
    user_text: str,
    turn_id: str,
) -> OpponentPositionProgress | None:
    """Return the next validated progress, or raise for an invalid model proposal."""

    transition = proposal.position_transition
    if strategy is None:
        if transition is not None or current is not None:
            raise ValueError("position progress requires a configured strategy")
        return None

    visible_text = _visible_proposal_text(proposal).casefold()
    internal_ids = {
        step.id.casefold() for step in strategy.steps
    } | {
        item.id.casefold() for step in strategy.steps for item in step.requires
    }
    if any(identifier in visible_text for identifier in internal_ids):
        raise ValueError("position identifiers are private")

    step_ids = [step.id for step in strategy.steps]
    if current is None:
        current_step_id = strategy.steps[0].id
        satisfied_ids: list[str] = []
        last_transition = None
    else:
        if current.current_step_id not in step_ids:
            raise ValueError("current position step is not in the strategy")
        current_step_id = current.current_step_id
        current_index = step_ids.index(current_step_id)
        expected_satisfied_ids = [
            item.id
            for step in strategy.steps[1 : current_index + 1]
            for item in step.requires
        ]
        if current.satisfied_requirement_ids != expected_satisfied_ids:
            raise ValueError("position progress does not match completed steps")
        satisfied_ids = list(current.satisfied_requirement_ids)
        last_transition = current.last_transition

    current_index = step_ids.index(current_step_id)
    if transition is None:
        _reject_untracked_later_terms(strategy, current_index, proposal)
        return OpponentPositionProgress(
            current_step_id=current_step_id,
            satisfied_requirement_ids=satisfied_ids,
            last_transition=last_transition,
        )

    if current_index + 1 >= len(strategy.steps):
        raise ValueError("red-line position cannot concede further")
    target = strategy.steps[current_index + 1]
    if transition.to_step_id != target.id:
        raise ValueError("position transition must advance exactly one step")

    required_ids = [item.id for item in target.requires]
    if transition.requirement_ids != required_ids:
        raise ValueError("position transition must satisfy the target requirements")
    if set(required_ids) & set(satisfied_ids):
        raise ValueError("position transition needs new concession requirements")
    if transition.evidence_quote not in user_text:
        raise ValueError("position transition evidence must quote the current user turn")
    if not _mentions_terms(proposal.text, target.terms.control_weeks, target.terms.kpi_percent):
        raise ValueError("position transition response must state the new terms")
    if target.terms.automatic_raise and not (
        "автоматич" in proposal.text.casefold() or "без повторного" in proposal.text.casefold()
    ):
        raise ValueError("position transition must state the automatic raise")

    resolution = proposal.resolution
    if isinstance(resolution, AgreementResolution) and (
        resolution.control_weeks != target.terms.control_weeks
        or resolution.kpi_percent != target.terms.kpi_percent
        or resolution.automatic_raise != target.terms.automatic_raise
    ):
        raise ValueError("agreement and position transition terms disagree")

    return OpponentPositionProgress(
        current_step_id=target.id,
        satisfied_requirement_ids=[*satisfied_ids, *required_ids],
        last_transition=AppliedPositionTransition(
            from_step_id=current_step_id,
            to_step_id=target.id,
            requirement_ids=required_ids,
            evidence_turn_id=turn_id,
            evidence_quote=transition.evidence_quote,
        ),
    )


def _reject_untracked_later_terms(
    strategy: OpponentStrategy,
    current_index: int,
    proposal: OpponentProposal,
) -> None:
    for step in strategy.steps[current_index + 1 :]:
        if _mentions_terms(proposal.text, step.terms.control_weeks, step.terms.kpi_percent):
            raise ValueError("later position terms require a validated transition")


def _mentions_terms(text: str, control_weeks: int, kpi_percent: int) -> bool:
    lowered = text.casefold()
    mentions_weeks = re.search(rf"(?<!\d){control_weeks}(?!\d)", lowered) is not None
    mentions_kpi = re.search(rf"(?<!\d){kpi_percent}(?!\d)", lowered) is not None
    return mentions_weeks and mentions_kpi and "недел" in lowered


def _visible_proposal_text(proposal: OpponentProposal) -> str:
    resolution = proposal.resolution
    parts = [proposal.text]
    if isinstance(resolution, AgreementResolution):
        parts.extend(resolution.employee_commitments)
        parts.extend(resolution.director_commitments)
    elif isinstance(resolution, PartialDecision):
        parts.extend(resolution.commitments)
        parts.extend(resolution.open_points)
    elif isinstance(resolution, DeferredDecision):
        parts.extend((resolution.reason, resolution.next_step))
    return " ".join(parts)
