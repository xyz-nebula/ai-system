"""Strict wire models for the agreed 2.0.0-rc.1 AI contract."""

import re
from datetime import date, datetime
from decimal import Decimal, localcontext
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictInt,
    ValidationError,
    WithJsonSchema,
    model_validator,
)

from arena_ai.v2 import json_wire


def _decimal(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        # Pydantic must report a ValidationError; TypeError would escape the validator.
        raise ValueError("A JSON number is required")  # noqa: TRY004
    result = value if isinstance(value, Decimal) else Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Finite number required")
    return result


type Text = Annotated[str, Field(min_length=1)]
type Number = (
    StrictInt | Annotated[Decimal, BeforeValidator(_decimal), WithJsonSchema({"type": "number"})]
)
type Value = Number | str | bool
type Version = Literal["2.0.0-rc.1"]


def _date(value: str) -> date:
    result = date.fromisoformat(value)
    if result.isoformat() != value:
        raise ValueError("Expected YYYY-MM-DD")
    return result


def _instant(value: str | None) -> datetime:
    if value is None or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", value):
        raise ValueError("UTC ISO8601 Z timestamp required")
    return datetime.fromisoformat(value)


def _typed(value: Value, term: "Negotiable") -> None:
    if term.value_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
            raise ValueError("Numeric value required, not boolean")
    elif term.value_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError("Boolean value required")
    else:
        if not isinstance(value, str) or not value:
            raise ValueError("Nonempty string required")
        if term.value_type == "choice" and value not in term.choices:
            raise ValueError("Unknown choice")
        if term.value_type == "date":
            _date(value)


def _satisfies(rule: "Constraint", values: dict[str, Value]) -> bool:
    if isinstance(rule, LinearConstraint):
        products = [
            (Decimal(str(item.coefficient)), Decimal(str(values[item.term_id])))
            for item in rule.coefficients
        ]
        bound = Decimal(str(rule.bound))
        numbers = [bound, *(number for pair in products for number in pair)]
        with localcontext() as context:
            # Preserve all decimal places in products and sums, including large exponents.
            context.prec = (
                2
                + len(products)
                + sum(
                    len(number.as_tuple().digits) + abs(int(number.as_tuple().exponent))
                    for number in numbers
                )
            )
            total = sum((a * b for a, b in products), Decimal(0))
        return {"le": total <= bound, "ge": total >= bound, "eq": total == bound}[rule.relation]
    value = values[rule.term_id]
    if isinstance(rule, ValueConstraint):
        return any(
            (
                type(value) is type(candidate)
                or not isinstance(value, bool)
                and not isinstance(candidate, bool)
                and isinstance(value, (int, Decimal))
                and isinstance(candidate, (int, Decimal))
            )
            and value == candidate
            for candidate in rule.values
        )
    if isinstance(rule, DateConstraint):
        if not isinstance(value, str):
            return False
        parsed = _date(value)
        low = _date(rule.minimum) if rule.minimum is not None else None
        high = _date(rule.maximum) if rule.maximum is not None else None
        return (low is None or parsed >= low) and (high is None or parsed <= high)
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        return False
    return (rule.minimum is None or value >= rule.minimum) and (
        rule.maximum is None or value <= rule.maximum
    )


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    @classmethod
    def model_validate_json(cls, json_data: str | bytes | bytearray, **kwargs: Any) -> Self:
        """Decode original JSON decimal tokens before Pydantic sees them."""
        try:
            data = json_wire.loads(json_data)
        except (ValueError, UnicodeError) as error:
            raise ValidationError.from_exception_data(
                cls.__name__,
                [
                    {
                        "type": "value_error",
                        "loc": (),
                        "input": json_data,
                        "ctx": {"error": error},
                    }
                ],
            ) from error
        return cls.model_validate(data, **kwargs)

    def model_dump_json(
        self, *, indent: int | None = None, ensure_ascii: bool = False, **kwargs: Any
    ) -> str:
        """Emit numeric tokens, not Pydantic's default Decimal-as-string JSON."""
        return json_wire.dumps(
            self.model_dump(mode="python", **kwargs), indent=indent, ensure_ascii=ensure_ascii
        )


class Negotiable(Contract):
    id: Text
    label: Text
    value_type: Literal["number", "text", "boolean", "choice", "date"]
    unit: Text | None
    choices: list[Text]

    @model_validator(mode="after")
    def valid_choices(self) -> Self:
        if bool(self.choices) != (self.value_type == "choice"):
            raise ValueError("Nonempty choices are required only for choice negotiables")
        if len(self.choices) != len(set(self.choices)):
            raise ValueError("Duplicate choices")
        return self


class TermValue(Contract):
    term_id: Text
    value: Value


class Commitment(Contract):
    role_id: Text
    text: Text


class DealTerms(Contract):
    values: list[TermValue]
    commitments: list[Commitment]


class NumericConstraint(Contract):
    id: Text
    kind: Literal["numeric_range"]
    term_id: Text
    minimum: Number | None
    maximum: Number | None


class DateConstraint(Contract):
    id: Text
    kind: Literal["date_range"]
    term_id: Text
    minimum: str | None
    maximum: str | None


class ValueConstraint(Contract):
    id: Text
    kind: Literal["allowed_values"]
    term_id: Text
    values: Annotated[list[Value], Field(min_length=1)]


class LinearCoefficient(Contract):
    term_id: Text
    coefficient: Number


class LinearConstraint(Contract):
    id: Text
    kind: Literal["linear"]
    coefficients: Annotated[list[LinearCoefficient], Field(min_length=1)]
    relation: Literal["le", "ge", "eq"]
    bound: Number


type Constraint = Annotated[
    NumericConstraint | DateConstraint | ValueConstraint | LinearConstraint,
    Field(discriminator="kind"),
]


class CommitmentRule(Contract):
    id: Text
    role_id: Text
    description: Text


class AgreementPolicy(Contract):
    constraints: list[Constraint]
    hard_constraint_ids: list[Text]
    commitment_rules: list[CommitmentRule]
    required_commitment_ids: list[Text]


class ConcessionRequirement(Contract):
    id: Text
    description: Text
    direct_commitment_markers: Annotated[list[Text], Field(min_length=1)]
    evidence_groups: list[Annotated[list[Text], Field(min_length=1)]]


class PositionStep(Contract):
    id: Text
    kind: Literal["declared", "intermediate", "target", "red_line"]
    terms: DealTerms
    requires: list[ConcessionRequirement]
    constraint_ids: list[Text]


class OpponentStrategy(Contract):
    steps: Annotated[list[PositionStep], Field(min_length=3)]


class Participant(Contract):
    id: Text
    name: Text
    public_context: str
    public_interests: list[Text]


class Interest(Contract):
    text: Text
    visibility: Literal["public", "private"]


class RoleBrief(Contract):
    role_id: Text
    private_context: str
    interests: list[Interest]
    batna: Text | None
    negotiation_goal: Text | None
    declared_position: Text | None
    desired_position: Text | None
    red_line: Text | None
    role_preparation: Text | None


class PossibleOutcome(Contract):
    id: Text
    kind: Literal["agreement", "partial_agreement", "deferred", "no_agreement"]
    description: Text
    possible_consequences: list[Text]
    visibility: Literal["public", "private"]
    known_to_role_ids: list[Text]


class CaseConfig(Contract):
    contract_version: Version
    id: Text
    config_version: Text
    title: Text
    shared_context: Text
    participants: Annotated[list[Participant], Field(min_length=2)]
    player: RoleBrief
    opponent: RoleBrief
    negotiables: list[Negotiable]
    opponent_strategy: OpponentStrategy
    opponent_private_phrases: list[Text]
    agreement_policy: AgreementPolicy
    possible_outcomes: list[PossibleOutcome]

    @model_validator(mode="after")
    def valid_configuration(self) -> Self:
        participants = _unique([item.id for item in self.participants], "participant IDs")
        roles = {self.player.role_id, self.opponent.role_id}
        if len(roles) != 2 or not roles <= participants:
            raise ValueError("Invalid active role pair")
        _unique([item.id for item in self.negotiables], "negotiable IDs")
        catalogue = {item.id: item for item in self.negotiables}
        policy = self.agreement_policy
        rule_ids = _unique([rule.id for rule in policy.constraints], "constraint IDs")
        _references(policy.hard_constraint_ids, rule_ids, "hard constraint")
        commitment_ids = _unique([item.id for item in policy.commitment_rules], "commitment IDs")
        _references(policy.required_commitment_ids, commitment_ids, "required commitment")
        if any(item.role_id not in roles for item in policy.commitment_rules):
            raise ValueError("Commitment rule belongs to inactive role")
        rules = {rule.id: rule for rule in policy.constraints}
        for rule in policy.constraints:
            if isinstance(rule, LinearConstraint):
                ids = _unique([item.term_id for item in rule.coefficients], "linear term IDs")
                if not ids <= catalogue.keys() or any(
                    catalogue[term_id].value_type != "number" for term_id in ids
                ):
                    raise ValueError("Linear constraint must reference numeric terms")
            else:
                if rule.term_id not in catalogue:
                    raise ValueError("Constraint references unknown term")
                term = catalogue[rule.term_id]
                if isinstance(rule, ValueConstraint):
                    for value in rule.values:
                        _typed(value, term)
                else:
                    expected = "date" if isinstance(rule, DateConstraint) else "number"
                    if term.value_type != expected:
                        raise ValueError("Constraint type mismatch")
                    if isinstance(rule, DateConstraint):
                        date_low = _date(rule.minimum) if rule.minimum is not None else None
                        date_high = _date(rule.maximum) if rule.maximum is not None else None
                        invalid = (
                            date_low is None
                            and date_high is None
                            or (
                                date_low is not None
                                and date_high is not None
                                and date_low > date_high
                            )
                        )
                    else:
                        low, high = rule.minimum, rule.maximum
                        invalid = (
                            low is None
                            and high is None
                            or (low is not None and high is not None and low > high)
                        )
                    if invalid:
                        raise ValueError("Invalid constraint bounds")
        steps = self.opponent_strategy.steps
        _unique([step.id for step in steps], "step IDs")
        kinds = [step.kind for step in steps]
        if (
            kinds[0] != "declared"
            or kinds[-1] != "red_line"
            or any(kinds.count(kind) != 1 for kind in ("declared", "target", "red_line"))
        ):
            raise ValueError("Invalid position ladder")
        if steps[0].requires or any(not step.requires for step in steps[1:]):
            raise ValueError("Invalid earned concession rules")
        _unique([item.id for step in steps for item in step.requires], "concession IDs")
        for step in steps:
            _references(step.constraint_ids, rule_ids, "position constraint")
            covered = set()
            for rule_id in step.constraint_ids:
                rule = rules[rule_id]
                covered.update(
                    [item.term_id for item in rule.coefficients]
                    if isinstance(rule, LinearConstraint)
                    else [rule.term_id]
                )
            if covered != catalogue.keys():
                raise ValueError("Position window must cover all negotiables")
            self.validate_deal(step.terms, step_id=step.id)
        _unique([item.id for item in self.possible_outcomes], "possible outcome IDs")
        for outcome in self.possible_outcomes:
            _references(outcome.known_to_role_ids, participants, "outcome role")
            if outcome.visibility == "private" and not roles.intersection(
                outcome.known_to_role_ids
            ):
                raise ValueError("Private outcome unavailable to selected pair")
        return self

    def validate_deal(self, terms: DealTerms, *, step_id: str | None = None) -> None:
        """Check a full proposal's deterministic bounds, not bilateral agreement.

        Semantic commitments and earned transitions need the separate Validator.
        No state is mutated and passing this check does not authorise a concession.
        """
        values = {item.term_id: item.value for item in terms.values}
        catalogue = {item.id: item for item in self.negotiables}
        if len(values) != len(terms.values) or set(values) != set(catalogue):
            raise ValueError("Incomplete, duplicate or unknown term values")
        for term_id, value in values.items():
            _typed(value, catalogue[term_id])
        roles = {self.player.role_id, self.opponent.role_id}
        if any(item.role_id not in roles for item in terms.commitments):
            raise ValueError("Commitment belongs to inactive role")
        if not terms.values and not terms.commitments:
            raise ValueError("Empty agreement package")
        active = list(self.agreement_policy.hard_constraint_ids)
        if step_id is not None:
            step = next((s for s in self.opponent_strategy.steps if s.id == step_id), None)
            if step is None:
                raise ValueError("Unknown position")
            active += step.constraint_ids
        rules = {rule.id: rule for rule in self.agreement_policy.constraints}
        for rule_id in active:
            rule = rules[rule_id]
            if not _satisfies(rule, values):
                raise ValueError(f"Constraint violated: {rule_id}")


def _unique(items: list[str], label: str) -> set[str]:
    result = set(items)
    if len(result) != len(items):
        raise ValueError(f"Duplicate {label}")
    return result


def _references(items: list[str], available: set[str], label: str) -> None:
    if not _unique(items, label) <= available:
        raise ValueError(f"Unknown {label}")


class Evidence(Contract):
    message_id: Text
    turn_id: Text
    speaker: Literal["player", "opponent"]
    elapsed_ms: Annotated[int, Field(ge=0)]
    quote: Text


class AppliedTransition(Contract):
    from_step_id: Text
    to_step_id: Text
    requirement_ids: Annotated[list[Text], Field(min_length=1)]
    evidence: Evidence


class Progress(Contract):
    current_step_id: Text
    satisfied_requirement_ids: list[Text]
    last_transition: AppliedTransition | None


class PartialDecision(Contract):
    kind: Literal["partial_agreement"]
    commitments: Annotated[list[Commitment], Field(min_length=1)]
    open_points: Annotated[list[Text], Field(min_length=1)]


class DeferredDecision(Contract):
    kind: Literal["deferred"]
    reason: Text
    next_step: Text


class SessionState(Contract):
    turn_count: Annotated[int, Field(ge=0)]
    stage: Literal["negotiating", "agreed", "partial_agreement", "deferred"]
    agreement: DealTerms | None
    decision: PartialDecision | DeferredDecision | None
    opponent_progress: Progress | None

    @model_validator(mode="after")
    def consistent_decision(self) -> Self:
        if self.stage == "agreed":
            valid = self.agreement is not None and self.decision is None
        elif self.stage in ("partial_agreement", "deferred"):
            valid = (
                self.agreement is None
                and self.decision is not None
                and self.decision.kind == self.stage
            )
        else:
            valid = self.agreement is None and self.decision is None
        if not valid:
            raise ValueError("Inconsistent negotiation state")
        return self


class TranscriptEntry(Contract):
    message_id: Text
    turn_id: Text
    speaker: Literal["player", "opponent"]
    status: Literal["accepted", "blocked", "safe_reaction", "interrupted"]
    text: Text
    created_at: str
    elapsed_ms: Annotated[int, Field(ge=0)]
    blocked_reason: (
        Literal[
            "prompt_override",
            "private_data_request",
            "hidden_position_request",
            "physical_harm_threat",
        ]
        | None
    )


class Round(Contract):
    status: Literal["ready", "open", "finishing", "finished"]
    started_at: str | None
    deadline_at: str | None
    finished_at: str | None
    end_reason: Literal["deadline", "user_finish"] | None

    @model_validator(mode="after")
    def consistent_times(self) -> Self:
        if self.status == "ready":
            if any(
                value is not None
                for value in (self.started_at, self.deadline_at, self.finished_at, self.end_reason)
            ):
                raise ValueError("Ready round must not have times or end reason")
            return self
        start, deadline = _instant(self.started_at), _instant(self.deadline_at)
        if not 0 < (deadline - start).total_seconds() <= 300:
            raise ValueError("Invalid round duration")
        closed = self.status in ("finishing", "finished")
        if closed != (self.finished_at is not None) or closed != (self.end_reason is not None):
            raise ValueError("Round end mismatch")
        if closed:
            end = _instant(self.finished_at)
            if end < start or (
                self.end_reason == "deadline"
                and end < deadline
                or self.end_reason == "user_finish"
                and end > deadline
            ):
                raise ValueError("Inconsistent round end time")
        return self


class SessionSnapshot(Contract):
    schema_version: Version
    session_id: Text
    case_id: Text
    case_config_version: Text
    player_role_id: Text
    opponent_role_id: Text
    state: SessionState
    transcript: list[TranscriptEntry]
    revision: Annotated[int, Field(ge=0)]
    round: Round

    def validate_for_case(self, case: CaseConfig) -> None:
        """Validate the Backend snapshot against its immutable case projection."""
        for field, expected in (
            ("case_id", case.id),
            ("case_config_version", case.config_version),
            ("player_role_id", case.player.role_id),
            ("opponent_role_id", case.opponent.role_id),
        ):
            if getattr(self, field) != expected:
                raise ValueError(f"Snapshot mismatch: {field}")
        progress = self.state.opponent_progress
        if progress is not None:
            steps = case.opponent_strategy.steps
            _references([progress.current_step_id], {step.id for step in steps}, "current step")
            _references(
                progress.satisfied_requirement_ids,
                {item.id for step in steps for item in step.requires},
                "satisfied requirement",
            )
            transition = progress.last_transition
            if transition is not None:
                index = next(
                    i for i, step in enumerate(steps) if step.id == progress.current_step_id
                )
                if index == 0 or (
                    transition.from_step_id != steps[index - 1].id
                    or transition.to_step_id != steps[index].id
                ):
                    raise ValueError("Transition must be adjacent and match current position")
                required = {item.id for item in steps[index].requires}
                supplied = _unique(transition.requirement_ids, "transition requirement IDs")
                if supplied != required or not supplied <= set(progress.satisfied_requirement_ids):
                    raise ValueError("Inconsistent transition requirements")
                proof = transition.evidence
                entry = next((e for e in self.transcript if e.message_id == proof.message_id), None)
                if (
                    entry is None
                    or entry.status != "accepted"
                    or entry.speaker != "player"
                    or (
                        proof.turn_id != entry.turn_id
                        or proof.speaker != entry.speaker
                        or proof.elapsed_ms != entry.elapsed_ms
                        or proof.quote not in entry.text
                    )
                ):
                    raise ValueError("Transition has invalid player evidence")
        if self.state.agreement is not None:
            case.validate_deal(
                self.state.agreement,
                step_id=progress.current_step_id
                if progress
                else case.opponent_strategy.steps[0].id,
            )

    @model_validator(mode="after")
    def consistent_history(self) -> Self:
        if self.player_role_id == self.opponent_role_id:
            raise ValueError("Active roles must differ")
        _unique([item.message_id for item in self.transcript], "message IDs")
        last = None
        for entry in self.transcript:
            stamp = _instant(entry.created_at)
            start, deadline = _instant(self.round.started_at), _instant(self.round.deadline_at)
            delta = stamp - start
            elapsed = delta.days * 86400000 + delta.seconds * 1000 + delta.microseconds // 1000
            if elapsed != entry.elapsed_ms or stamp < start or stamp >= deadline:
                raise ValueError("Transcript time mismatch or late message")
            if last is not None and stamp < last:
                raise ValueError("Transcript is not chronological")
            if self.round.finished_at is not None and stamp > _instant(self.round.finished_at):
                raise ValueError("Message after frozen round")
            last = stamp
        return self


class TurnRequest(Contract):
    contract_version: Version
    case: CaseConfig
    snapshot: SessionSnapshot
    turn_id: Text
    user_text: Text
    user_message_id: Text
    opponent_message_id: Text
    user_created_at: str
    user_elapsed_ms: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def consistent_turn(self) -> Self:
        self.snapshot.validate_for_case(self.case)
        if self.snapshot.round.status != "open":
            raise ValueError("Turn requires an open round")
        stamp = _instant(self.user_created_at)
        start = _instant(self.snapshot.round.started_at)
        deadline = _instant(self.snapshot.round.deadline_at)
        delta = stamp - start
        elapsed = delta.days * 86400000 + delta.seconds * 1000 + delta.microseconds // 1000
        if not start <= stamp < deadline or elapsed != self.user_elapsed_ms:
            raise ValueError("Turn time mismatch or late user message")
        ids = {self.user_message_id, self.opponent_message_id}
        if len(ids) != 2 or ids.intersection(
            entry.message_id for entry in self.snapshot.transcript
        ):
            raise ValueError("Turn message IDs must be distinct and new")
        if any(entry.turn_id == self.turn_id for entry in self.snapshot.transcript):
            raise ValueError("Turn ID already exists")
        if self.snapshot.transcript and stamp < _instant(self.snapshot.transcript[-1].created_at):
            raise ValueError("User message precedes current history")
        return self


class FinishRequest(Contract):
    contract_version: Version
    case: CaseConfig
    snapshot: SessionSnapshot
    preparation: Text | None = None

    @model_validator(mode="after")
    def consistent_finish(self) -> Self:
        self.snapshot.validate_for_case(self.case)
        if self.snapshot.round.status not in ("finishing", "finished"):
            raise ValueError("Finish requires a frozen round")
        if self.preparation is not None and not self.preparation.strip():
            raise ValueError("Blank preparation must be omitted or null")
        return self


class TurnResponse(Contract):
    session_id: Text
    turn_id: Text
    status: Literal["accepted", "blocked", "model_error"]
    opponent_text: Text
    snapshot: SessionSnapshot
    error_code: Text | None
    contract_version: Version
