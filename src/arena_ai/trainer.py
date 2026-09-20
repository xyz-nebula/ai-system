"""Independent coach feedback over the public duel record."""

from typing import Protocol

from arena_ai.contracts import (
    CaseConfig,
    OutcomeResult,
    SessionSnapshot,
    TrainerContext,
    TrainerFeedback,
    TrainerSlot,
)
from arena_ai.privacy import contains_private_phrase, public_transcript


class Trainer(Protocol):
    async def feedback(self, context: TrainerContext) -> object: ...


class DemoTrainer:
    async def feedback(self, context: TrainerContext) -> object:
        evidence = next(
            (
                entry
                for entry in context.transcript
                if entry.speaker == "player" and entry.status == "accepted"
            ),
            None,
        )
        if evidence is None:
            raise ValueError("No accepted player turn")
        return {
            "summary": "Демонстрационный разбор без оценки качества переговоров моделью.",
            "strengths": [
                {
                    "evidence_turn_id": evidence.turn_id,
                    "evidence_quote": evidence.text[:120],
                    "action": "Менеджер сформулировал реплику для обсуждения.",
                    "situation_change": "Реплика стала частью переговоров.",
                    "consequence": "Её можно сопоставить с последующим ответом директора.",
                }
            ],
            "mistakes": [],
            "next_try": [
                "В следующей попытке явно предложите срок контроля, измеримый KPI и условие повышения."
            ],
        }


def feedback_is_grounded(
    feedback: TrainerFeedback, context: TrainerContext, case: CaseConfig
) -> bool:
    points = [*feedback.strengths, *feedback.mistakes]
    if any(
        not any(
            entry.speaker == "player"
            and entry.turn_id == point.evidence_turn_id
            and point.evidence_quote in entry.text
            for entry in context.transcript
        )
        for point in points
    ):
        return False
    visible_text = " ".join(
        [
            feedback.summary,
            *feedback.next_try,
            *(
                field
                for point in points
                for field in (
                    point.evidence_quote,
                    point.action,
                    point.situation_change,
                    point.consequence,
                )
            ),
        ]
    )
    return not contains_private_phrase(visible_text, case)


async def train_duel(
    case: CaseConfig,
    snapshot: SessionSnapshot,
    outcome: OutcomeResult,
    trainer: Trainer,
) -> TrainerSlot:
    context = TrainerContext(
        case_id=case.id,
        case_title=case.title,
        shared_context=case.shared_context,
        player_role=case.player_role,
        opponent_role=case.opponent_role,
        state=snapshot.state,
        transcript=public_transcript(snapshot.transcript),
        outcome=outcome,
    )
    try:
        raw_feedback = await trainer.feedback(context)
    except Exception:  # noqa: BLE001 - isolate the trainer model call
        return TrainerSlot(status="failed", error_code="trainer_unavailable")
    try:
        feedback = TrainerFeedback.model_validate(raw_feedback)
    except ValueError:
        feedback = None
    if feedback is None or not feedback_is_grounded(feedback, context, case):
        return TrainerSlot(status="failed", error_code="invalid_trainer_output")
    return TrainerSlot(status="ready", feedback=feedback)
