"""Independent coach feedback over the public duel record."""

from typing import Protocol

from arena_ai.contracts import (
    CaseConfig,
    OutcomeResult,
    PreparationCard,
    PreparationItem,
    SessionSnapshot,
    TrainerContext,
    TrainerFeedback,
    TrainerSlot,
)
from arena_ai.model_recovery import validated_model_call
from arena_ai.privacy import contains_private_phrase, public_duel_view


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
        result: dict[str, object] = {
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
        if context.preparation is not None:
            prepared_item = context.preparation.comparison_items()[0]
            result["plan_vs_reality"] = {
                "summary": "Демонстрационный режим не оценивает выполнение подготовки.",
                "items": [
                    {
                        "preparation_kind": prepared_item.kind,
                        "preparation_text": prepared_item.text,
                        "status": "not_observed",
                        "evidence_turn_id": None,
                        "evidence_quote": None,
                        "observation": "Для содержательного сопоставления нужен вызов реальной модели.",
                    }
                ],
            }
        return result


def player_evidence_is_grounded(
    context: TrainerContext,
    turn_id: str,
    quote: str,
    *,
    accepted_only: bool,
) -> bool:
    return any(
        entry.speaker == "player"
        and (not accepted_only or entry.status == "accepted")
        and entry.turn_id == turn_id
        and quote in entry.text
        for entry in context.transcript
    )


def preparation_comparison_is_grounded(
    feedback: TrainerFeedback, context: TrainerContext
) -> bool:
    comparison = feedback.plan_vs_reality
    if context.preparation is None:
        return comparison is None
    if comparison is None:
        return False
    prepared_items = set(context.preparation.comparison_items())
    for item in comparison.items:
        if (
            PreparationItem(kind=item.preparation_kind, text=item.preparation_text)
            not in prepared_items
        ):
            return False
        if item.status == "not_observed":
            continue
        if item.evidence_turn_id is None or item.evidence_quote is None:
            return False
        if not player_evidence_is_grounded(
            context,
            item.evidence_turn_id,
            item.evidence_quote,
            accepted_only=True,
        ):
            return False
    return True


def feedback_is_grounded(
    feedback: TrainerFeedback, context: TrainerContext, case: CaseConfig
) -> bool:
    if not preparation_comparison_is_grounded(feedback, context):
        return False
    points = [*feedback.strengths, *feedback.mistakes]
    if any(
        not player_evidence_is_grounded(
            context,
            point.evidence_turn_id,
            point.evidence_quote,
            accepted_only=False,
        )
        for point in points
    ):
        return False
    visible_text = " ".join(
        [
            feedback.summary,
            *feedback.next_try,
            *(
                []
                if feedback.plan_vs_reality is None
                else [
                    feedback.plan_vs_reality.summary,
                    *(
                        text
                        for item in feedback.plan_vs_reality.items
                        for text in (item.evidence_quote or "", item.observation)
                    ),
                ]
            ),
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
    preparation: PreparationCard | None = None,
    model_attempts: int = 1,
) -> TrainerSlot:
    if preparation is not None and not preparation.has_content():
        preparation = None
    public_view = public_duel_view(snapshot)
    context = TrainerContext(
        case_id=case.id,
        case_title=case.title,
        shared_context=case.shared_context,
        player_role=case.player_role,
        opponent_role=case.opponent_role,
        state=public_view.state,
        transcript=public_view.transcript,
        outcome=outcome,
        preparation=preparation,
    )
    def validated_feedback(raw: object) -> TrainerFeedback | None:
        try:
            feedback = TrainerFeedback.model_validate(raw)
        except ValueError:
            return None
        return feedback if feedback_is_grounded(feedback, context, case) else None

    feedback_result = await validated_model_call(
        lambda: trainer.feedback(context),
        validated_feedback,
        attempts=model_attempts,
    )
    if feedback_result.value is None:
        return TrainerSlot(
            status="failed",
            error_code=(
                "trainer_unavailable"
                if feedback_result.failure == "unavailable"
                else "invalid_trainer_output"
            ),
        )
    return TrainerSlot(status="ready", feedback=feedback_result.value)
