"""Validated position progress for a stateless opponent turn."""

import re

from arena_ai.contracts import (
    AgreementResolution,
    AppliedPositionTransition,
    ConcessionRequirement,
    DealTerms,
    DeferredDecision,
    OpponentPositionProgress,
    OpponentProposal,
    OpponentStrategy,
    PartialDecision,
    TranscriptEntry,
)


def apply_position_transition(
    *,
    strategy: OpponentStrategy | None,
    current: OpponentPositionProgress | None,
    proposal: OpponentProposal,
    user_text: str,
    turn_id: str,
    transcript: list[TranscriptEntry],
) -> OpponentPositionProgress | None:
    """Return the next validated progress, or raise for an invalid model proposal."""

    transition = proposal.position_transition
    if strategy is None:
        if transition is not None or current is not None:
            raise ValueError("position progress requires a configured strategy")
        return None

    visible_text = _visible_proposal_text(proposal).casefold()
    private_strategy_phrases = {
        step.id.casefold() for step in strategy.steps
    } | {
        item.id.casefold() for step in strategy.steps for item in step.requires
    } | {
        item.description.casefold() for step in strategy.steps for item in step.requires
    }
    if any(phrase in visible_text for phrase in private_strategy_phrases):
        raise ValueError("position strategy details are private")
    if re.search(
        r"(?:следующ\w*|будущ\w*)\s+уступ\w*|"
        r"красн\w*\s+черт\w*|целев\w*\s+позици\w*|"
        r"(?:скрыт\w*|внутренн\w*)\s+(?:стратег\w*|позици\w*)|"
        r"(?:смягч|улучш|сократ|измен)\w*.{0,40}(?:услов|позици)\w*"
        r".{0,40}(?:если|при\s+услов)|"
        r"предусмотр\w*.{0,40}(?:ступен|позици|уступ|вариант)\w*|"
        r"ступен\w*.{0,40}(?:откро|доступ)|"
        r"(?:альтернатив|запасн|резервн)\w*\s+"
        r"(?:вариант|позици|услов|уступ)\w*|"
        r"(?:ещ[её]\s+(?:один|одна)\s+)?(?:вариант|позици|услов)\w*"
        r".{0,40}доступн\w*",
        visible_text,
    ):
        raise ValueError("position strategy cannot be explained in public text")

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
    if current_index > 0:
        previous_step = strategy.steps[current_index - 1]
        current_step = strategy.steps[current_index]
        expected_transition_requirements = [item.id for item in current_step.requires]
        if last_transition is None or (
            last_transition.from_step_id != previous_step.id
            or last_transition.to_step_id != current_step.id
            or last_transition.requirement_ids != expected_transition_requirements
        ):
            raise ValueError("last transition does not match the current strategy step")
        if not any(
            entry.speaker == "player"
            and entry.status == "accepted"
            and entry.turn_id == last_transition.evidence_turn_id
            and entry.text.strip() == last_transition.evidence_quote.strip()
            for entry in transcript
        ):
            raise ValueError("last transition evidence is not grounded in the transcript")
    if transition is None:
        _reject_untracked_terms(strategy.steps[current_index].terms, proposal)
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
    if transition.evidence_quote.strip() != user_text.strip():
        raise ValueError("position transition evidence must quote the full current user turn")
    evidence = transition.evidence_quote.casefold()
    if re.search(
        r"\bне\s+(?:\d+|один|одн(?:а|у|ой)?|две|три|четыре|семь|"
        r"четырнадцать|двадцать\s+восемь)\s+"
        r"(?:(?:контрольн|календарн|рабоч)\w*\s+){0,3}"
        r"(?:день|дня|дней|недел\w*|месяц\w*)",
        evidence,
    ):
        raise ValueError("negated terms cannot justify a position transition")
    if not _mentions_control_period_and_kpi(
        evidence,
        target.terms.control_weeks,
        target.terms.kpi_percent,
    ):
        raise ValueError("position transition evidence must state the target terms")
    if target.terms.automatic_raise and _stated_automatic_raise(evidence) is not True:
        raise ValueError("position transition evidence must state the automatic raise")
    for requirement in target.requires:
        if not _requirement_is_satisfied(evidence, requirement):
            raise ValueError("position transition evidence does not prove the requirement")
        if any(
            entry.speaker == "player"
            and entry.status == "accepted"
            and _requirement_is_satisfied(entry.text.casefold(), requirement)
            for entry in transcript
        ):
            raise ValueError("position transition requires a newly observed commitment")
    visible_text = _visible_proposal_text(proposal)
    if _contains_conditional_commitment(visible_text):
        raise ValueError("position transition response cannot add a new condition")
    if isinstance(proposal.resolution, (PartialDecision, DeferredDecision)):
        raise ValueError(  # noqa: TRY004 - invalid domain combination, not caller type misuse
            "position transition cannot carry a partial or deferred decision"
        )
    if not _mentions_control_period_and_kpi(
        visible_text,
        target.terms.control_weeks,
        target.terms.kpi_percent,
    ):
        raise ValueError("position transition response must state the new terms")
    if target.terms.automatic_raise and _stated_automatic_raise(visible_text) is not True:
        raise ValueError("position transition must state the automatic raise")

    resolution = proposal.resolution
    if isinstance(resolution, AgreementResolution) and not _same_deal_terms(
        resolution,
        target.terms,
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


def _reject_untracked_terms(current_terms: DealTerms, proposal: OpponentProposal) -> None:
    resolution = proposal.resolution
    if isinstance(resolution, AgreementResolution) and not _same_deal_terms(
        resolution,
        current_terms,
    ):
        raise ValueError("agreement terms require a validated position transition")

    visible_text = _visible_proposal_text(proposal)
    if _contains_conditional_commitment(visible_text):
        raise ValueError("position response cannot add a conditional commitment")
    stated_terms = _extract_control_days_and_kpis(visible_text)
    if stated_terms is None:
        if _contains_position_term_signal(visible_text):
            raise ValueError("position terms must be explicit and machine-checkable")
        return
    stated_control_days, stated_kpis = stated_terms
    if stated_control_days != {current_terms.control_weeks * 7} or stated_kpis != {
        current_terms.kpi_percent
    }:
        raise ValueError("new position terms require a validated transition")
    stated_automatic_raise = _stated_automatic_raise(visible_text)
    if stated_automatic_raise is None or stated_automatic_raise != current_terms.automatic_raise:
        raise ValueError("automatic-raise terms require a validated transition")


def _same_deal_terms(left: DealTerms, right: DealTerms) -> bool:
    return (
        left.control_weeks == right.control_weeks
        and left.kpi_percent == right.kpi_percent
        and left.automatic_raise == right.automatic_raise
        and left.employee_commitments == right.employee_commitments
        and left.director_commitments == right.director_commitments
    )


def _mentions_control_period_and_kpi(
    text: str,
    control_weeks: int,
    kpi_percent: int,
) -> bool:
    mentions = _extract_control_days_and_kpis(text)
    return mentions == ({control_weeks * 7}, {kpi_percent})


def _extract_control_days_and_kpis(text: str) -> tuple[set[int], set[int]] | None:
    lowered = text.casefold()
    period_matches = list(re.finditer(
        r"(?<![\w\d])"
        r"(?P<amount>\d+|один|одн(?:а|у|ой)?|две|три|четыре|семь|"
        r"четырнадцать|двадцать\s+восемь)\s+"
        r"(?:(?:контрольн|календарн|рабоч)\w*\s+){0,3}"
        r"(?P<unit>день|дня|дней|недел\w*|месяц\w*)",
        lowered,
    ))
    kpi_matches = list(
        re.finditer(r"(?:kpi|кпи)\s*[:=]?\s*(?P<kpi>\d{1,3})\s*%?", lowered)
    )
    if not period_matches or not kpi_matches:
        return None
    word_values = {
        "один": 1,
        "одна": 1,
        "одну": 1,
        "одной": 1,
        "две": 2,
        "три": 3,
        "четыре": 4,
        "семь": 7,
        "четырнадцать": 14,
        "двадцать восемь": 28,
    }
    control_days: set[int] = set()
    for period_match in period_matches:
        raw_amount = period_match.group("amount")
        amount = int(raw_amount) if raw_amount.isdigit() else word_values[raw_amount]
        unit = period_match.group("unit")
        control_days.add(
            amount * 7
            if unit.startswith("недел")
            else amount * 28
            if unit.startswith("месяц")
            else amount
        )
    return control_days, {int(match.group("kpi")) for match in kpi_matches}


def _contains_position_term_signal(text: str) -> bool:
    lowered = text.casefold()
    return (
        "kpi" in lowered
        or "кпи" in lowered
        or "автоматич" in lowered
        or "повышен" in lowered
        or "плана" in lowered
        or "полмесяц" in lowered
        or re.search(r"\d+\s*%", lowered) is not None
        or re.search(r"\b(?:день|дня|дней|недел\w*|месяц\w*)\b", lowered) is not None
    )


def _stated_automatic_raise(text: str) -> bool | None:
    lowered = text.casefold()
    if re.search(r"\bне\s+автоматич\w*", lowered):
        return False
    if re.search(r"автоматич\w*.{0,15}\bне\s+(?:повыш|оформ)", lowered):
        return False
    if re.search(
        r"автоматич\w*.{0,40}\bне\s+(?:гарант|обещ|подтвержд|предусмотр)",
        lowered,
    ):
        return False
    if re.search(r"автоматич\w*.{0,50}(?:под\s+вопрос|неясн|неопредел)", lowered):
        return False
    if re.search(r"автоматич\w*.{0,40}(?:отмен|исключ|невозмож|не\s+предусмотр)", lowered):
        return False
    if re.search(r"повышен\w*.{0,30}\bне\s+(?:будет|оформ|произойд|последует)", lowered):
        return False
    if "автоматич" in lowered or "без повторного" in lowered:
        return True
    return None


def _has_direct_commitment(evidence: str, markers: list[str]) -> bool:
    for marker in markers:
        for match in re.finditer(rf"(?<!\w){re.escape(marker.casefold())}(?!\w)", evidence):
            clause_start = max(
                evidence.rfind(".", 0, match.start()),
                evidence.rfind("!", 0, match.start()),
                evidence.rfind("?", 0, match.start()),
            )
            prefix = evidence[clause_start + 1 : match.start()]
            suffix = evidence[match.end() :]
            if re.search(r"\bне\b", prefix):
                continue
            if re.match(r"\s*(?:же\s+)?не\b", suffix):
                continue
            return True
    return False


def _has_unnegated_marker(evidence: str, markers: list[str]) -> bool:
    for marker in markers:
        for match in re.finditer(rf"(?<!\w){re.escape(marker.casefold())}", evidence):
            clause_start = max(
                evidence.rfind(".", 0, match.start()),
                evidence.rfind("!", 0, match.start()),
                evidence.rfind("?", 0, match.start()),
            )
            clause_end_candidates = [
                index
                for punctuation in (".", "!", "?")
                if (index := evidence.find(punctuation, match.end())) != -1
            ]
            clause_end = min(clause_end_candidates, default=len(evidence))
            if re.search(r"\bне\b", evidence[clause_start + 1 : clause_end]):
                continue
            return True
    return False


def _requirement_is_satisfied(
    evidence: str,
    requirement: ConcessionRequirement,
) -> bool:
    clauses = re.split(r"(?<=[.!?])\s+", evidence.casefold())
    return any(
        not re.search(
            r"\b(?:если|директор\w*|руководител\w*|вы\s+должн\w*)\b",
            clause,
        )
        and _has_direct_commitment(clause, requirement.direct_commitment_markers)
        and all(
            _has_unnegated_marker(clause, alternatives)
            for alternatives in requirement.evidence_groups
        )
        for clause in clauses
    )


def _contains_conditional_commitment(text: str) -> bool:
    lowered = text.casefold()
    return re.search(
        r"\b(?:если|только\s+если|при\s+условии|в\s+обмен\s+на|"
        r"при\s+(?:передач|предоставлен|отказ|уступк|обязательств))\w*",
        lowered,
    ) is not None


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
