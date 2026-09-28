"""Text-only assessment wire models; evidence points into the input message list."""

from typing import Annotated, Literal

from pydantic import Field

from arena_ai.contracts import JudgeCollege, JudgeCriterion
from arena_ai.v2.contracts import Contract, Version
from arena_ai.v2.evaluation_request import NonBlankText


class IndexedEvidence(Contract):
    message_index: Annotated[int, Field(ge=0, strict=True)]
    is_ai: Annotated[bool, Field(strict=True)]
    quote: NonBlankText


class EvaluationOutcome(Contract):
    kind: Literal["agreement", "partial_agreement", "deferred", "no_agreement", "not_assessable"]
    summary: NonBlankText
    agreed_terms: list[NonBlankText]
    open_points: list[NonBlankText]
    next_step: NonBlankText | None
    evidence: Annotated[list[IndexedEvidence], Field(min_length=1)]


class EvaluationOutcomeSlot(Contract):
    basis: Literal["dialogue_inference"] = "dialogue_inference"
    status: Literal["ready", "failed"]
    assessment: EvaluationOutcome | None
    error_code: Literal["outcome_analysis_unavailable", "invalid_outcome_analysis"] | None


class EvaluationJudgeVerdict(Contract):
    college: JudgeCollege
    choice: Literal["player", "opponent"]
    decisive_criterion: JudgeCriterion
    evidence: IndexedEvidence
    observation: NonBlankText
    effect: NonBlankText
    comparison: NonBlankText


class EvaluationJudgeSlot(Contract):
    college: JudgeCollege
    status: Literal["ready", "failed"]
    verdict: EvaluationJudgeVerdict | None
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


class EvaluationCoachingPoint(Contract):
    evidence: IndexedEvidence
    action: NonBlankText
    situation_change: NonBlankText
    consequence: NonBlankText


class EvaluationPreparationItem(Contract):
    preparation_text: NonBlankText
    status: Literal["followed", "adapted", "not_observed"]
    evidence: IndexedEvidence | None
    observation: NonBlankText


class EvaluationPreparationComparison(Contract):
    summary: NonBlankText
    items: Annotated[list[EvaluationPreparationItem], Field(min_length=1)]


class EvaluationGoalAssessment(Contract):
    status: Literal["achieved", "partially_achieved", "not_achieved", "not_assessable"]
    goal_text: NonBlankText | None
    explanation: NonBlankText
    evidence: list[IndexedEvidence]


class EvaluationTrainerFeedback(Contract):
    summary: NonBlankText
    strengths: list[EvaluationCoachingPoint]
    mistakes: list[EvaluationCoachingPoint]
    next_try: Annotated[list[NonBlankText], Field(min_length=2, max_length=3)]
    plan_vs_reality: EvaluationPreparationComparison | None
    missed_opportunities: list[EvaluationCoachingPoint]
    goal_assessment: EvaluationGoalAssessment


class EvaluationTrainerSlot(Contract):
    status: Literal["ready", "failed"]
    feedback: EvaluationTrainerFeedback | None
    error_code: (
        Literal["trainer_unavailable", "invalid_trainer_output", "insufficient_evidence"] | None
    )


class EvaluationResponse(Contract):
    contract_version: Version = "2.0.0-rc.1"
    outcome: EvaluationOutcomeSlot
    judge_verdicts: Annotated[list[EvaluationJudgeSlot], Field(min_length=3, max_length=3)]
    trainer_feedback: EvaluationTrainerSlot
