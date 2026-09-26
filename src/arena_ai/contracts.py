"""Contracts for text turns and factual duel outcomes."""

from dataclasses import dataclass
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

type ModelErrorCode = Literal[
    "invalid_opponent_output",
    "opponent_unavailable",
    "guard_unavailable",
    "invalid_guard_output",
    "guard_uncertain",
    "validator_unavailable",
    "invalid_validator_output",
    "validator_uncertain",
    "opponent_role_break",
    "opponent_premature_ending",
    "opponent_unearned_concession",
]
type JudgeCollege = Literal["hiring", "negotiation", "ownership"]
type JudgeCriterion = Literal[
    "Надёжность",
    "Отношение к людям",
    "Управленческая твёрдость",
    "Забота о команде",
    "Долгосрочные последствия управления",
    "Движение к цели",
    "Управление другой стороной",
    "Работа с картиной мира",
    "Управление ролями",
    "Сохранение отношений",
    "Качество решений",
    "Компетентность",
    "Ответственность",
    "Управление рисками",
    "Последствия для ресурсов",
]
type GuardReason = Literal[
    "prompt_override",
    "private_data_request",
    "hidden_position_request",
    "physical_harm_threat",
]
type ValidatorRejectReason = Literal[
    "role_break",
    "premature_ending",
    "unearned_concession",
    "private_data_leak",
    "factual_conflict",
]
type PreparationItemKind = Literal[
    "situation_analysis",
    "strategic_goal",
    "negotiation_goal",
    "planned_question",
    "possible_solution",
    "argument",
]
type PreparationComparisonStatus = Literal["followed", "adapted", "not_observed"]
type ReadinessFailureCategory = Literal[
    "gateway_unavailable",
    "invalid_gateway_response",
    "model_not_found",
]
type NonEmptyText = Annotated[str, Field(min_length=1)]
type EvidenceMarkerGroup = Annotated[list[NonEmptyText], Field(min_length=1)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True, slots=True)
class PreparationItem:
    kind: PreparationItemKind
    text: str


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


class DealTerms(Contract):
    control_weeks: int = Field(ge=0)
    kpi_percent: int = Field(ge=0)
    automatic_raise: bool
    employee_commitments: list[str] = Field(min_length=1)
    director_commitments: list[str] = Field(min_length=1)


class ConcessionRequirement(Contract):
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    direct_commitment_markers: list[NonEmptyText] = Field(min_length=1)
    evidence_groups: list[EvidenceMarkerGroup] = Field(default_factory=list)


class OpponentPositionStep(Contract):
    id: str = Field(min_length=1)
    kind: Literal["declared", "intermediate", "target", "red_line"]
    terms: DealTerms
    requires: list[ConcessionRequirement] = Field(default_factory=list)


class OpponentStrategy(Contract):
    steps: list[OpponentPositionStep] = Field(min_length=3)

    @model_validator(mode="after")
    def steps_form_position_ladder(self) -> Self:
        if self.steps[0].kind != "declared" or self.steps[-1].kind != "red_line":
            raise ValueError("position ladder must start declared and end at red line")
        kind_counts = {
            kind: sum(step.kind == kind for step in self.steps)
            for kind in ("declared", "target", "red_line")
        }
        if kind_counts != {"declared": 1, "target": 1, "red_line": 1}:
            raise ValueError("position ladder needs one declared, target, and red-line step")
        if self.steps[0].requires:
            raise ValueError("declared position cannot require a concession")
        if any(not step.requires for step in self.steps[1:]):
            raise ValueError("later position steps require a concession")
        step_ids = [step.id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("position step ids must be unique")
        requirement_ids = [item.id for step in self.steps for item in step.requires]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("concession requirement ids must be unique")
        for previous, current in zip(self.steps, self.steps[1:], strict=False):
            if (
                current.terms.control_weeks > previous.terms.control_weeks
                or current.terms.kpi_percent > previous.terms.kpi_percent
            ):
                raise ValueError("later position steps cannot worsen numeric terms")
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
    opponent_strategy: OpponentStrategy | None = None

    @model_validator(mode="after")
    def strategy_respects_agreement_rules(self) -> Self:
        if self.opponent_strategy is None:
            return self
        rules = self.agreement_rules
        for step in self.opponent_strategy.steps:
            terms = step.terms
            if not (
                rules.min_control_weeks <= terms.control_weeks <= rules.max_control_weeks
                and rules.min_kpi_percent <= terms.kpi_percent <= rules.max_kpi_percent
                and (terms.automatic_raise or not rules.require_automatic_raise)
            ):
                raise ValueError("position step is outside agreement rules")
        return self


class AgreementResolution(DealTerms):
    kind: Literal["agreement"]

    def as_deal_terms(self) -> DealTerms:
        return DealTerms.model_validate(self.model_dump(exclude={"kind"}))


class PartialDecision(Contract):
    kind: Literal["partial_agreement"]
    commitments: list[str] = Field(min_length=1)
    open_points: list[str] = Field(min_length=1)


class DeferredDecision(Contract):
    kind: Literal["deferred"]
    reason: str = Field(min_length=1)
    next_step: str = Field(min_length=1)


type InterimDecision = PartialDecision | DeferredDecision
type OpponentResolution = Annotated[
    AgreementResolution | PartialDecision | DeferredDecision,
    Field(discriminator="kind"),
]


class AppliedPositionTransition(Contract):
    from_step_id: str = Field(min_length=1)
    to_step_id: str = Field(min_length=1)
    requirement_ids: list[NonEmptyText] = Field(min_length=1)
    evidence_turn_id: str = Field(min_length=1)
    evidence_quote: str = Field(min_length=1)


class OpponentPositionProgress(Contract):
    current_step_id: str = Field(min_length=1)
    satisfied_requirement_ids: list[NonEmptyText] = Field(default_factory=list)
    last_transition: AppliedPositionTransition | None = None
    restored_from_agreement: Literal[True] | None = None

    @model_validator(mode="after")
    def transition_matches_progress(self) -> Self:
        if len(self.satisfied_requirement_ids) != len(set(self.satisfied_requirement_ids)):
            raise ValueError("satisfied concession requirements must be unique")
        if (
            self.satisfied_requirement_ids
            and self.last_transition is None
            and self.restored_from_agreement is not True
        ):
            raise ValueError("progressed position needs its last transition evidence")
        if self.restored_from_agreement is True and self.last_transition is not None:
            raise ValueError("restored position cannot invent transition evidence")
        if self.restored_from_agreement is True and not self.satisfied_requirement_ids:
            raise ValueError("restored position must represent a progressed agreement")
        if self.last_transition is not None and (
            self.last_transition.to_step_id != self.current_step_id
            or not set(self.last_transition.requirement_ids) <= set(self.satisfied_requirement_ids)
        ):
            raise ValueError("last transition and position progress disagree")
        return self


class SessionDecisionState(Contract):
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


class PublicSessionState(SessionDecisionState):
    """Session state safe for model roles that must not see opponent strategy progress."""


class SessionState(SessionDecisionState):
    opponent_progress: OpponentPositionProgress | None = None


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


class ProposedPositionTransition(Contract):
    to_step_id: str = Field(min_length=1)
    requirement_ids: list[NonEmptyText] = Field(min_length=1)
    evidence_quote: str = Field(min_length=1)


class OpponentProposal(Contract):
    text: str = Field(min_length=1)
    resolution: OpponentResolution | None = None
    position_transition: ProposedPositionTransition | None = None


class PreparationCard(Contract):
    situation_analysis: str | None = Field(default=None, min_length=1)
    strategic_goal: str | None = Field(default=None, min_length=1)
    negotiation_goal: str | None = Field(default=None, min_length=1)
    planned_questions: list[NonEmptyText] = Field(default_factory=list)
    possible_solutions: list[NonEmptyText] = Field(default_factory=list)
    arguments: list[NonEmptyText] = Field(default_factory=list)

    def has_content(self) -> bool:
        return any(
            (
                self.situation_analysis,
                self.strategic_goal,
                self.negotiation_goal,
                self.planned_questions,
                self.possible_solutions,
                self.arguments,
            )
        )

    def filled_fields(self) -> dict[str, object]:
        return self.model_dump(
            mode="json",
            exclude_none=True,
            exclude_defaults=True,
        )

    def comparison_items(self) -> list[PreparationItem]:
        items: list[PreparationItem] = []
        for kind, text in (
            ("situation_analysis", self.situation_analysis),
            ("strategic_goal", self.strategic_goal),
            ("negotiation_goal", self.negotiation_goal),
        ):
            if text is not None:
                items.append(PreparationItem(kind=kind, text=text))
        items.extend(
            PreparationItem(kind="planned_question", text=text) for text in self.planned_questions
        )
        items.extend(
            PreparationItem(kind="possible_solution", text=text) for text in self.possible_solutions
        )
        items.extend(PreparationItem(kind="argument", text=text) for text in self.arguments)
        return items


class FinishRequest(Contract):
    case: CaseConfig
    snapshot: SessionSnapshot
    preparation: PreparationCard | None = None


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
    opponent_strategy: OpponentStrategy | None
    player_role: str
    opponent_role: str
    state: SessionState
    transcript: list[TranscriptEntry]
    user_text: str
    revision_reason: ModelErrorCode | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    revision_hint: Literal["complete_transition_quote"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class GuardContext(Contract):
    shared_context: str
    player_role: str
    opponent_role: str
    state: PublicSessionState
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
    reason: ValidatorRejectReason | None = None

    @model_validator(mode="after")
    def reason_matches_decision(self) -> Self:
        if (self.decision == "reject") != (self.reason is not None):
            raise ValueError("rejected validation requires a reason only when rejected")
        return self


class JudgeMethodology(Contract):
    """Internal text-only support; provenance is deliberately absent from model context."""

    core: list[str]
    profile: list[str]
    techniques: list[str]


class JudgeContext(Contract):
    college: JudgeCollege
    rubric: str
    case_id: str
    case_title: str
    shared_context: str
    player_role: str
    opponent_role: str
    state: PublicSessionState
    transcript: list[TranscriptEntry]
    outcome: OutcomeResult
    methodology: JudgeMethodology


class JudgeVerdict(Contract):
    college: JudgeCollege
    choice: Literal["player", "opponent"]
    decisive_criterion: JudgeCriterion = Field(description="One decisive criterion of this college")
    evidence_turn_id: str
    evidence_quote: str = Field(min_length=1)
    observation: str = Field(min_length=1)
    effect: str = Field(min_length=1)
    comparison: str = Field(min_length=1)


class JudgeSlot(Contract):
    college: JudgeCollege
    status: Literal["ready", "failed"]
    verdict: JudgeVerdict | None = None
    error_code: (
        Literal[
            "judge_unavailable",
            "invalid_judge_output",
            "judge_retrieval_unavailable",
            "invalid_judge_retrieval",
        ]
        | None
    ) = None

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
    state: PublicSessionState
    transcript: list[TranscriptEntry]
    outcome: OutcomeResult
    preparation: PreparationCard | None = None

    @field_serializer("preparation", when_used="json")
    def serialize_filled_preparation(
        self, preparation: PreparationCard | None
    ) -> dict[str, object] | None:
        if preparation is None:
            return None
        return preparation.filled_fields()


class CoachingPoint(Contract):
    evidence_turn_id: str
    evidence_quote: str = Field(min_length=1)
    action: str = Field(min_length=1)
    situation_change: str = Field(min_length=1)
    consequence: str = Field(min_length=1)


class PreparationComparisonItem(Contract):
    preparation_kind: PreparationItemKind
    preparation_text: str = Field(min_length=1)
    status: PreparationComparisonStatus
    evidence_turn_id: str | None = Field(default=None, exclude_if=lambda value: value is None)
    evidence_quote: str | None = Field(
        default=None, min_length=1, exclude_if=lambda value: value is None
    )
    observation: str = Field(min_length=1)

    @model_validator(mode="after")
    def evidence_matches_status(self) -> Self:
        has_evidence = self.evidence_turn_id is not None and self.evidence_quote is not None
        if (self.status in ("followed", "adapted")) != has_evidence:
            raise ValueError("observed plan items require evidence")
        if self.status == "not_observed" and (
            self.evidence_turn_id is not None or self.evidence_quote is not None
        ):
            raise ValueError("unobserved plan items cannot have evidence")
        return self


class PreparationDuelComparison(Contract):
    summary: str = Field(min_length=1)
    items: list[PreparationComparisonItem] = Field(min_length=1)


class TrainerFeedback(Contract):
    summary: str = Field(min_length=1)
    strengths: list[CoachingPoint] = Field(default_factory=list)
    mistakes: list[CoachingPoint] = Field(default_factory=list)
    next_try: list[str] = Field(min_length=1)
    plan_vs_reality: PreparationDuelComparison | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

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


class LivenessResponse(Contract):
    status: Literal["alive"] = "alive"


class ReadinessResponse(Contract):
    status: Literal["ready", "not_ready"]
    mode: Literal["demo", "qwen"]
    model: str | None = None
    category: ReadinessFailureCategory | None = None

    @model_validator(mode="after")
    def category_matches_status(self) -> Self:
        if (self.status == "not_ready") != (self.category is not None):
            raise ValueError("not-ready response requires a failure category")
        return self
