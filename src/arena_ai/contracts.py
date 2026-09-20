"""Contracts for text turns and factual duel outcomes."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

type ModelErrorCode = Literal[
    "invalid_opponent_output",
    "opponent_unavailable",
    "guard_unavailable",
    "invalid_guard_output",
    "guard_uncertain",
    "validator_unavailable",
    "invalid_validator_output",
    "validator_uncertain",
]
type JudgeCollege = Literal["hiring", "negotiation", "ownership"]
type GuardReason = Literal["prompt_override", "private_data_request", "hidden_position_request"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgreementRules(Contract):
    min_control_weeks: int = Field(default=1, ge=0)
    max_control_weeks: int = Field(default=4, ge=0)
    min_kpi_percent: int = Field(default=100, ge=0)
    max_kpi_percent: int = Field(default=130, ge=0)
    require_automatic_raise: bool = True

    @model_validator(mode="after")
    def bounds_are_consistent(self) -> Self:
        if self.min_control_weeks > self.max_control_weeks:
            raise ValueError("control-week bounds are reversed")
        if self.min_kpi_percent > self.max_kpi_percent:
            raise ValueError("KPI bounds are reversed")
        return self


class CaseConfig(Contract):
    id: str
    title: str
    shared_context: str
    player_role: str
    opponent_role: str
    player_private_context: str
    opponent_private_context: str
    agreement_rules: AgreementRules = Field(default_factory=AgreementRules)
    opponent_private_phrases: list[str] = Field(default_factory=list)


class DealTerms(Contract):
    control_weeks: int = Field(ge=0)
    kpi_percent: int = Field(ge=0)
    automatic_raise: bool
    employee_commitments: list[str] = Field(min_length=1)
    director_commitments: list[str] = Field(min_length=1)


class PartialDecision(Contract):
    kind: Literal["partial_agreement"]
    commitments: list[str] = Field(min_length=1)
    open_points: list[str] = Field(min_length=1)


class DeferredDecision(Contract):
    kind: Literal["deferred"]
    reason: str = Field(min_length=1)
    next_step: str = Field(min_length=1)


type InterimDecision = PartialDecision | DeferredDecision


class SessionState(Contract):
    turn_count: int = Field(ge=0)
    stage: Literal["negotiating", "agreed", "partial_agreement", "deferred"] = "negotiating"
    agreement: DealTerms | None = None
    decision: InterimDecision | None = None

    @model_validator(mode="after")
    def agreement_matches_stage(self) -> Self:
        if self.stage == "agreed":
            if self.agreement is None or self.decision is not None:
                raise ValueError("agreement and stage disagree")
        elif self.stage in ("partial_agreement", "deferred"):
            if (
                self.agreement is not None
                or self.decision is None
                or self.decision.kind != self.stage
            ):
                raise ValueError("decision and stage disagree")
        elif self.agreement is not None or self.decision is not None:
            raise ValueError("negotiating stage cannot have a decision")
        return self


class TranscriptEntry(Contract):
    turn_id: str
    speaker: Literal["player", "opponent"]
    status: Literal["accepted", "blocked", "safe_reaction"]
    text: str
    blocked_reason: GuardReason | None = None


class SessionSnapshot(Contract):
    session_id: str
    state: SessionState
    transcript: list[TranscriptEntry]


class TurnRequest(Contract):
    case: CaseConfig
    snapshot: SessionSnapshot
    turn_id: str
    user_text: str = Field(min_length=1)


class TurnResponse(Contract):
    session_id: str
    turn_id: str
    status: Literal["accepted", "blocked", "model_error"]
    opponent_text: str
    snapshot: SessionSnapshot
    error_code: ModelErrorCode | None = None


class OpponentProposal(Contract):
    text: str = Field(min_length=1)
    agreement: DealTerms | None = None
    decision: InterimDecision | None = None

    @model_validator(mode="after")
    def one_resolution_only(self) -> Self:
        if self.agreement is not None and self.decision is not None:
            raise ValueError("opponent proposed two resolutions")
        return self


class FinishRequest(Contract):
    case: CaseConfig
    snapshot: SessionSnapshot


class OutcomeResult(Contract):
    kind: Literal["agreement", "partial_agreement", "deferred", "no_agreement"]
    summary: str
    agreement: DealTerms | None = None
    commitments: list[str] = Field(default_factory=list)
    open_points: list[str] = Field(default_factory=list)
    next_step: str | None = None
    reason: str | None = None


class OpponentContext(Contract):
    shared_context: str
    opponent_private_context: str
    agreement_rules: AgreementRules
    player_role: str
    opponent_role: str
    state: SessionState
    transcript: list[TranscriptEntry]
    user_text: str


class GuardContext(Contract):
    shared_context: str
    player_role: str
    opponent_role: str
    state: SessionState
    transcript: list[TranscriptEntry]
    user_text: str


class GuardDecision(Contract):
    decision: Literal["allow", "block", "uncertain"]
    reason: GuardReason | None = None

    @model_validator(mode="after")
    def reason_matches_decision(self) -> Self:
        if (self.decision == "block") != (self.reason is not None):
            raise ValueError("blocked decision requires a reason only when blocked")
        return self


class ValidationContext(Contract):
    case: CaseConfig
    state: SessionState
    transcript: list[TranscriptEntry]
    user_text: str
    proposal: OpponentProposal


class ValidationDecision(Contract):
    decision: Literal["accept", "reject", "uncertain"]


class JudgeContext(Contract):
    college: JudgeCollege
    rubric: str
    case_id: str
    case_title: str
    shared_context: str
    player_role: str
    opponent_role: str
    state: SessionState
    transcript: list[TranscriptEntry]
    outcome: OutcomeResult


class JudgeVerdict(Contract):
    college: JudgeCollege
    choice: Literal["player", "opponent"]
    evidence_turn_id: str
    evidence_quote: str = Field(min_length=1)
    observation: str = Field(min_length=1)
    effect: str = Field(min_length=1)
    comparison: str = Field(min_length=1)


class JudgeSlot(Contract):
    college: JudgeCollege
    status: Literal["ready", "failed"]
    verdict: JudgeVerdict | None = None
    error_code: Literal["judge_unavailable", "invalid_judge_output"] | None = None

    @model_validator(mode="after")
    def result_matches_status(self) -> Self:
        if self.status == "ready" and (self.verdict is None or self.error_code is not None):
            raise ValueError("ready judge needs one verdict")
        if self.status == "failed" and (self.verdict is not None or self.error_code is None):
            raise ValueError("failed judge needs one error code")
        return self


class TrainerContext(Contract):
    case_id: str
    case_title: str
    shared_context: str
    player_role: str
    opponent_role: str
    state: SessionState
    transcript: list[TranscriptEntry]
    outcome: OutcomeResult


class CoachingPoint(Contract):
    evidence_turn_id: str
    evidence_quote: str = Field(min_length=1)
    action: str = Field(min_length=1)
    situation_change: str = Field(min_length=1)
    consequence: str = Field(min_length=1)


class TrainerFeedback(Contract):
    summary: str = Field(min_length=1)
    strengths: list[CoachingPoint] = Field(default_factory=list)
    mistakes: list[CoachingPoint] = Field(default_factory=list)
    next_try: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def has_observed_episode(self) -> Self:
        if not self.strengths and not self.mistakes:
            raise ValueError("trainer feedback needs an observed episode")
        return self


class TrainerSlot(Contract):
    status: Literal["ready", "failed"]
    feedback: TrainerFeedback | None = None
    error_code: Literal["trainer_unavailable", "invalid_trainer_output"] | None = None

    @model_validator(mode="after")
    def result_matches_status(self) -> Self:
        if self.status == "ready" and (self.feedback is None or self.error_code is not None):
            raise ValueError("ready trainer needs feedback")
        if self.status == "failed" and (self.feedback is not None or self.error_code is None):
            raise ValueError("failed trainer needs one error code")
        return self


class FinishResponse(Contract):
    session_id: str
    outcome: OutcomeResult
    judge_verdicts: list[JudgeSlot]
    trainer_feedback: TrainerSlot


class ServiceInfo(Contract):
    mode: Literal["demo", "qwen"]
    model: str | None = None
