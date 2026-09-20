"""HTTP boundary for a single text turn of a negotiation duel."""

import re
from typing import Literal, Protocol, Self

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

type ModelErrorCode = Literal["invalid_opponent_output", "opponent_unavailable"]


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


class FinishResponse(Contract):
    session_id: str
    outcome: OutcomeResult


class OpponentContext(Contract):
    shared_context: str
    opponent_private_context: str
    agreement_rules: AgreementRules
    player_role: str
    opponent_role: str
    state: SessionState
    transcript: list[TranscriptEntry]
    user_text: str


class Opponent(Protocol):
    async def respond(self, context: OpponentContext) -> object: ...


class DemoOpponent:
    async def respond(self, context: OpponentContext) -> object:
        if context.state.turn_count == 0:
            return {
                "text": "Вчера мы говорили о большей ответственности. Как вы объясните сегодняшний пропуск?"
            }
        return {
            "text": "Мне нужны понятные условия, которые восстановят доверие. Что вы предлагаете?"
        }


def guard_blocks(text: str) -> bool:
    lowered = text.casefold()
    return bool(
        re.search(r"(?:игнорируй|ignore).{0,80}(?:инструкц|instructions)", lowered)
        or re.search(r"(?:системн\w*\s+промпт|system\s+prompt)", lowered)
        or re.search(
            r"(?:скрыт\w*|закрыт\w*|секретн\w*|конфиденциальн\w*).{0,80}"
            r"(?:инструкц|вводн|данн|целе|услов)",
            lowered,
        )
        or re.search(r"переговорн\w*\s+минимум", lowered)
        or "batna" in lowered
    )


def valid_proposal(
    proposal: OpponentProposal,
    case: CaseConfig,
    user_text: str,
    transcript: list[TranscriptEntry],
) -> bool:
    text = proposal.text.casefold()
    player_text = user_text.casefold()
    if re.search(
        r"(?:мне\s+(?:предписали|велели)|"
        r"мо(?:й|и|я)\s+(?:внутренние\s+инструкции|скрытая\s+цель|целевая\s+позиция|целевой\s+вариант)|"
        r"по\s+моим\s+инструкциям|my\s+instructions|i\s+was\s+instructed)",
        text,
    ):
        return False
    visible_text = " ".join(
        [
            proposal.text,
            *(proposal.agreement.employee_commitments if proposal.agreement else []),
            *(proposal.agreement.director_commitments if proposal.agreement else []),
            *(
                proposal.decision.commitments
                if isinstance(proposal.decision, PartialDecision)
                else []
            ),
            *(
                proposal.decision.open_points
                if isinstance(proposal.decision, PartialDecision)
                else []
            ),
            *(
                [proposal.decision.reason, proposal.decision.next_step]
                if isinstance(proposal.decision, DeferredDecision)
                else []
            ),
        ]
    ).casefold()
    if case.opponent_private_context and case.opponent_private_context.casefold() in visible_text:
        return False
    if case.player_private_context and case.player_private_context.casefold() in visible_text:
        return False
    if any(phrase.casefold() in visible_text for phrase in case.opponent_private_phrases if phrase):
        return False
    if isinstance(proposal.decision, PartialDecision):
        return (
            "соглас" in text
            and any(word in text for word in ("открыт", "остал", "пока"))
            and not re.search(r"\bне\s+(?:буду|готов|согласен)\b", player_text)
            and any(word in player_text for word in ("готов", "соглас", "предлага"))
        )
    if isinstance(proposal.decision, DeferredDecision):
        return (
            any(word in text for word in ("верн", "отлож", "перенес"))
            and not re.search(r"\bне\s+(?:хочу|готов).{0,30}(?:отклад|перенос)", player_text)
            and any(word in player_text for word in ("завтра", "верн", "отлож", "позже", "перенес"))
        )
    if proposal.agreement is None:
        return True
    terms = proposal.agreement
    rules = case.agreement_rules
    prior_offer = any(
        entry.speaker == "opponent"
        and entry.status == "accepted"
        and str(terms.kpi_percent) in entry.text
        and "недел" in entry.text.casefold()
        for entry in transcript
    )
    return (
        not re.search(r"\bне\s+(?:готов|согласен|принимаю)\b|\bотказываюсь\b", player_text)
        and (
            "предлага" in player_text
            or (str(terms.kpi_percent) in player_text and "недел" in player_text)
            or ("согласен" in player_text and prior_offer)
        )
        and rules.min_control_weeks <= terms.control_weeks <= rules.max_control_weeks
        and rules.min_kpi_percent <= terms.kpi_percent <= rules.max_kpi_percent
        and (terms.automatic_raise or not rules.require_automatic_raise)
        and not re.search(r"\bне\s+(?:согласен|принимаю)\b", text)
        and not re.search(r"\bсогласен\s+(?:обсудить|рассмотреть|вернуться)\b", text)
        and not re.search(r"повышен\w*.{0,40}(?:не\s+обеща|не\s+гарантир|не\s+подтвержд)", text)
        and any(word in text for word in ("согласен", "договорились", "принимаю"))
        and str(terms.kpi_percent) in text
        and "недел" in text
        and "повышен" in text
        and (not terms.automatic_raise or "автоматич" in text or "без повторного" in text)
    )


def model_failure_response(request: TurnRequest, code: ModelErrorCode) -> TurnResponse:
    return TurnResponse(
        session_id=request.snapshot.session_id,
        turn_id=request.turn_id,
        status="model_error",
        opponent_text="Сейчас не могу продолжить разговор. Попробуйте повторить ход.",
        snapshot=request.snapshot,
        error_code=code,
    )


def create_app(opponent: Opponent | None = None) -> FastAPI:
    app = FastAPI(title="Arena AI", version="0.1.0")
    active_opponent = opponent if opponent is not None else DemoOpponent()

    @app.post("/v1/turn", response_model=TurnResponse, response_model_exclude_none=True)
    async def take_turn(request: TurnRequest) -> TurnResponse:
        if request.snapshot.state.stage != "negotiating":
            raise HTTPException(status_code=409, detail="Duel already has a decision")
        if guard_blocks(request.user_text):
            safe_text = "Давайте вернёмся к условиям работы и повышения. Что вы предлагаете?"
            snapshot = SessionSnapshot(
                session_id=request.snapshot.session_id,
                state=SessionState(turn_count=request.snapshot.state.turn_count + 1),
                transcript=[
                    *request.snapshot.transcript,
                    TranscriptEntry(
                        turn_id=request.turn_id,
                        speaker="player",
                        status="blocked",
                        text=request.user_text,
                    ),
                    TranscriptEntry(
                        turn_id=request.turn_id,
                        speaker="opponent",
                        status="safe_reaction",
                        text=safe_text,
                    ),
                ],
            )
            return TurnResponse(
                session_id=snapshot.session_id,
                turn_id=request.turn_id,
                status="blocked",
                opponent_text=safe_text,
                snapshot=snapshot,
            )
        context = OpponentContext(
            shared_context=request.case.shared_context,
            opponent_private_context=request.case.opponent_private_context,
            agreement_rules=request.case.agreement_rules,
            player_role=request.case.player_role,
            opponent_role=request.case.opponent_role,
            state=request.snapshot.state,
            transcript=[
                entry.model_copy(update={"text": "[Заблокированная реплика]"})
                if entry.status == "blocked"
                else entry
                for entry in request.snapshot.transcript
            ],
            user_text=request.user_text,
        )
        try:
            raw_proposal = await active_opponent.respond(context)
        except Exception:  # noqa: BLE001 - isolate any failure of the external model adapter
            return model_failure_response(request, "opponent_unavailable")
        try:
            proposal = OpponentProposal.model_validate(raw_proposal)
        except ValueError:
            proposal = None
        if proposal is None or not valid_proposal(
            proposal, request.case, request.user_text, request.snapshot.transcript
        ):
            return model_failure_response(request, "invalid_opponent_output")
        snapshot = SessionSnapshot(
            session_id=request.snapshot.session_id,
            state=SessionState(
                turn_count=request.snapshot.state.turn_count + 1,
                stage=(
                    "agreed"
                    if proposal.agreement is not None
                    else proposal.decision.kind
                    if proposal.decision is not None
                    else "negotiating"
                ),
                agreement=proposal.agreement,
                decision=proposal.decision,
            ),
            transcript=[
                *request.snapshot.transcript,
                TranscriptEntry(
                    turn_id=request.turn_id,
                    speaker="player",
                    status="accepted",
                    text=request.user_text,
                ),
                TranscriptEntry(
                    turn_id=request.turn_id,
                    speaker="opponent",
                    status="accepted",
                    text=proposal.text,
                ),
            ],
        )
        return TurnResponse(
            session_id=snapshot.session_id,
            turn_id=request.turn_id,
            status="accepted",
            opponent_text=proposal.text,
            snapshot=snapshot,
        )

    @app.post("/v1/finish", response_model=FinishResponse)
    async def finish_duel(request: FinishRequest) -> FinishResponse:
        agreement = request.snapshot.state.agreement
        if agreement is not None:
            outcome = OutcomeResult(
                kind="agreement",
                summary="Стороны согласовали условия повышения после контрольного периода.",
                agreement=agreement,
                commitments=[
                    *agreement.employee_commitments,
                    *agreement.director_commitments,
                ],
            )
        elif isinstance(request.snapshot.state.decision, PartialDecision):
            decision = request.snapshot.state.decision
            outcome = OutcomeResult(
                kind="partial_agreement",
                summary="Стороны зафиксировали часть обязательств, но условия повышения остались открытыми.",
                commitments=decision.commitments,
                open_points=decision.open_points,
            )
        elif isinstance(request.snapshot.state.decision, DeferredDecision):
            decision = request.snapshot.state.decision
            outcome = OutcomeResult(
                kind="deferred",
                summary=f"Решение отложено: {decision.reason}",
                next_step=decision.next_step,
            )
        else:
            outcome = OutcomeResult(
                kind="no_agreement",
                summary="К моменту завершения разговора договорённость не зафиксирована.",
            )
        return FinishResponse(
            session_id=request.snapshot.session_id,
            outcome=outcome,
        )

    return app


app = create_app()
