"""Derive factual results from an accepted duel snapshot."""

from arena_ai.contracts import (
    DeferredDecision,
    OutcomeResult,
    PartialDecision,
    SessionSnapshot,
)


def determine_outcome(snapshot: SessionSnapshot) -> OutcomeResult:
    agreement = snapshot.state.agreement
    if agreement is not None:
        return OutcomeResult(
            kind="agreement",
            summary="Стороны согласовали условия повышения после контрольного периода.",
            agreement=agreement,
            commitments=[
                *agreement.employee_commitments,
                *agreement.director_commitments,
            ],
        )
    if isinstance(snapshot.state.decision, PartialDecision):
        decision = snapshot.state.decision
        return OutcomeResult(
            kind="partial_agreement",
            summary="Стороны зафиксировали часть обязательств, но условия повышения остались открытыми.",
            commitments=decision.commitments,
            open_points=decision.open_points,
        )
    if isinstance(snapshot.state.decision, DeferredDecision):
        decision = snapshot.state.decision
        return OutcomeResult(
            kind="deferred",
            summary=f"Решение отложено: {decision.reason}",
            next_step=decision.next_step,
        )
    return OutcomeResult(
        kind="no_agreement",
        summary="К моменту завершения разговора договорённость не зафиксирована.",
        reason=(
            "Стороны не зафиксировали взаимное согласие по KPI, контрольному периоду "
            "и условиям повышения."
        ),
    )
