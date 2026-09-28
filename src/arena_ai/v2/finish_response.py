"""Finish wire response with all analytical slots from the agreed contract."""

from typing import Annotated, Literal

from pydantic import Field

from arena_ai.contracts import JudgeCollege
from arena_ai.v2.contracts import Commitment, Contract, DealTerms, Evidence, Text, Version
from arena_ai.v2.finish import Consequence, SourcedAction
from arena_ai.v2.judges import JudgeVerdict


class Outcome(Contract):
    kind: Literal["agreement", "partial_agreement", "deferred", "no_agreement"]
    summary: Text
    agreement: DealTerms | None
    commitments: list[Commitment]
    open_points: list[Text]
    next_step: Text | None
    reason: Text | None
    analysis_status: Literal["ready", "partial", "failed"]
    analysis_error_code: Literal["outcome_analysis_unavailable", "invalid_outcome_analysis"] | None
    concessions: list[SourcedAction]
    costs: list[SourcedAction]
    consequences: list[Consequence]
    evidence: list[Evidence]


class JudgeSlot(Contract):
    college: JudgeCollege
    status: Literal["ready", "failed"]
    verdict: JudgeVerdict | None
    error_code: (
        Literal[
            "judge_unavailable",
            "invalid_judge_output",
            "judge_retrieval_unavailable",
            "invalid_judge_retrieval",
            "insufficient_evidence",
        ]
        | None
    )


class CoachingPoint(Contract):
    evidence: Evidence
    action: Text
    situation_change: Text
    consequence: Text


class PreparationComparisonItem(Contract):
    preparation_text: Text
    status: Literal["followed", "adapted", "not_observed"]
    evidence: Evidence | None
    observation: Text


class PreparationComparison(Contract):
    summary: Text
    items: Annotated[list[PreparationComparisonItem], Field(min_length=1)]


class GoalAssessment(Contract):
    status: Literal["achieved", "partially_achieved", "not_achieved", "not_assessable"]
    goal_text: Text | None
    explanation: Text
    evidence: list[Evidence]


class TrainerFeedback(Contract):
    summary: Text
    strengths: list[CoachingPoint]
    mistakes: list[CoachingPoint]
    next_try: Annotated[list[Text], Field(min_length=2, max_length=3)]
    plan_vs_reality: PreparationComparison | None
    missed_opportunities: list[CoachingPoint]
    goal_assessment: GoalAssessment


class TrainerSlot(Contract):
    status: Literal["ready", "failed"]
    feedback: TrainerFeedback | None
    error_code: (
        Literal["trainer_unavailable", "invalid_trainer_output", "insufficient_evidence"] | None
    )


class FinishResponse(Contract):
    session_id: Text
    outcome: Outcome
    judge_verdicts: Annotated[list[JudgeSlot], Field(min_length=3, max_length=3)]
    trainer_feedback: TrainerSlot
    contract_version: Version
