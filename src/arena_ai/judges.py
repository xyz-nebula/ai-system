"""Three isolated judge calls over the same public duel view."""

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
    visible_text = (
        f"{verdict.evidence_quote} {verdict.observation} {verdict.effect} {verdict.comparison}"
    ).casefold()
    private_phrases = (
        case.player_private_context,
        case.opponent_private_context,
        *case.opponent_private_phrases,
    )
    return not any(phrase.casefold() in visible_text for phrase in private_phrases if phrase)


async def judge_duel(
    case: CaseConfig,
    snapshot: SessionSnapshot,
    outcome: OutcomeResult,
    judge: Judge,
) -> list[JudgeSlot]:
    public_transcript = [
        entry.model_copy(update={"text": "[Заблокированная реплика пользователя]"})
        if entry.status == "blocked"
        else entry
        for entry in snapshot.transcript
    ]
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
            transcript=public_transcript,
            outcome=outcome,
        )
        try:
            raw_verdict = await judge.verdict(context)
        except Exception:  # noqa: BLE001 - isolate each external judge call
            slots.append(
                JudgeSlot(college=college, status="failed", error_code="judge_unavailable")
            )
            continue
        try:
            verdict = JudgeVerdict.model_validate(raw_verdict)
        except ValueError:
            verdict = None
        if verdict is None or not verdict_is_grounded(verdict, context, case):
            slots.append(
                JudgeSlot(college=college, status="failed", error_code="invalid_judge_output")
            )
            continue
        slots.append(JudgeSlot(college=college, status="ready", verdict=verdict))
    return slots
