"""Three isolated judge calls over the same public duel view."""

from functools import partial
from typing import Protocol

from arena_ai.contracts import (
    CaseConfig,
    JudgeCollege,
    JudgeContext,
    JudgeSlot,
    JudgeVerdict,
    OutcomeResult,
    SessionSnapshot,
)
from arena_ai.model_recovery import validated_model_call
from arena_ai.privacy import contains_private_phrase, public_transcript

COLLEGES: tuple[JudgeCollege, ...] = ("hiring", "negotiation", "ownership")
RUBRICS: dict[JudgeCollege, str] = {
    "hiring": (
        "Нанимающиеся на работу: к кому из участников я бы пошёл работать? "
        "Оцени надёжность, отношение к людям, управленческую твёрдость, заботу о команде "
        "и долгосрочные последствия управления."
    ),
    "negotiation": (
        "Отправляющие на переговоры: кого я отправлю вместо себя на сложные переговоры? "
        "Оцени движение к цели, управление другой стороной, работу с картиной мира, "
        "управление ролями и сохранение отношений."
    ),
    "ownership": (
        "Доверяющие собственность: кому я доверю деньги, компанию или другой значимый ресурс? "
        "Оцени качество решений, компетентность, ответственность, риски и последствия для ресурсов."
    ),
}


class Judge(Protocol):
    async def verdict(self, context: JudgeContext) -> object: ...


class DemoJudge:
    async def verdict(self, context: JudgeContext) -> object:
        evidence = next((entry for entry in context.transcript if entry.status == "accepted"), None)
        if evidence is None:
            raise ValueError("No transcript evidence")
        return {
            "college": context.college,
            "choice": "player" if context.college == "negotiation" else "opponent",
            "evidence_turn_id": evidence.turn_id,
            "evidence_quote": evidence.text[:120],
            "observation": "Участник сформулировал позицию в зафиксированном ходе.",
            "effect": "Это задало направление дальнейшего разговора.",
            "comparison": "Для содержательной оценки нужен вызов реальной модели.",
        }


def verdict_is_grounded(verdict: JudgeVerdict, context: JudgeContext, case: CaseConfig) -> bool:
    if verdict.college != context.college:
        return False
    if not any(
        entry.turn_id == verdict.evidence_turn_id and verdict.evidence_quote in entry.text
        for entry in context.transcript
    ):
        return False
    visible_text = f"{verdict.evidence_quote} {verdict.observation} {verdict.effect} {verdict.comparison}"
    return not contains_private_phrase(visible_text, case)


def validated_judge_verdict(
    raw: object,
    *,
    context: JudgeContext,
    case: CaseConfig,
) -> JudgeVerdict | None:
    try:
        verdict = JudgeVerdict.model_validate(raw)
    except ValueError:
        return None
    return verdict if verdict_is_grounded(verdict, context, case) else None


async def judge_duel(
    case: CaseConfig,
    snapshot: SessionSnapshot,
    outcome: OutcomeResult,
    judge: Judge,
    model_attempts: int = 1,
) -> list[JudgeSlot]:
    visible_transcript = public_transcript(snapshot.transcript)
    slots: list[JudgeSlot] = []
    for college in COLLEGES:
        context = JudgeContext(
            college=college,
            rubric=RUBRICS[college],
            case_id=case.id,
            case_title=case.title,
            shared_context=case.shared_context,
            player_role=case.player_role,
            opponent_role=case.opponent_role,
            state=snapshot.state,
            transcript=visible_transcript,
            outcome=outcome,
        )
        verdict_result = await validated_model_call(
            partial(judge.verdict, context),
            partial(validated_judge_verdict, context=context, case=case),
            attempts=model_attempts,
        )
        if verdict_result.value is None:
            slots.append(
                JudgeSlot(
                    college=college,
                    status="failed",
                    error_code=(
                        "judge_unavailable"
                        if verdict_result.failure == "unavailable"
                        else "invalid_judge_output"
                    ),
                )
            )
            continue
        slots.append(JudgeSlot(college=college, status="ready", verdict=verdict_result.value))
    return slots
