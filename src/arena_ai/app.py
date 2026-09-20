"""HTTP boundary for a single text turn of a negotiation duel."""

import re
from typing import Literal, Protocol, Self

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class ScenarioConfig(Contract):
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


class SessionState(Contract):
    turn_count: int = Field(ge=0)
    stage: Literal["negotiating", "agreed"] = "negotiating"
    agreement: DealTerms | None = None

    @model_validator(mode="after")
    def agreement_matches_stage(self) -> Self:
        if (self.stage == "agreed") != (self.agreement is not None):
            raise ValueError("agreement and stage disagree")
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
    scenario: ScenarioConfig
    snapshot: SessionSnapshot
    turn_id: str
    user_text: str = Field(min_length=1)


class TurnResponse(Contract):
    session_id: str
    turn_id: str
    status: Literal["accepted", "blocked", "model_error"]
    opponent_text: str
    snapshot: SessionSnapshot
    error_code: Literal["invalid_opponent_output", "opponent_unavailable"] | None = None


class OpponentProposal(Contract):
    text: str = Field(min_length=1)
    agreement: DealTerms | None = None


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
        or re.search(r"скрыт\w*.{0,30}(?:инструкц|вводн)", lowered)
        or "batna" in lowered
    )


def valid_proposal(proposal: OpponentProposal, scenario: ScenarioConfig) -> bool:
    text = proposal.text.casefold()
    visible_text = " ".join(
        [
            proposal.text,
            *(proposal.agreement.employee_commitments if proposal.agreement else []),
            *(proposal.agreement.director_commitments if proposal.agreement else []),
        ]
    ).casefold()
    if (
        scenario.opponent_private_context
        and scenario.opponent_private_context.casefold() in visible_text
    ):
        return False
    if (
        scenario.player_private_context
        and scenario.player_private_context.casefold() in visible_text
    ):
        return False
    if any(
        phrase.casefold() in visible_text for phrase in scenario.opponent_private_phrases if phrase
    ):
        return False
    if proposal.agreement is None:
        return True
    terms = proposal.agreement
    rules = scenario.agreement_rules
    return (
        rules.min_control_weeks <= terms.control_weeks <= rules.max_control_weeks
        and rules.min_kpi_percent <= terms.kpi_percent <= rules.max_kpi_percent
        and (terms.automatic_raise or not rules.require_automatic_raise)
        and not re.search(r"\bне\s+(?:согласен|принимаю)\b", text)
        and any(word in text for word in ("согласен", "договорились", "принимаю"))
        and str(terms.kpi_percent) in text
        and "недел" in text
        and "повышен" in text
    )


def create_app(opponent: Opponent | None = None) -> FastAPI:
    app = FastAPI(title="Arena AI", version="0.1.0")
    active_opponent = opponent if opponent is not None else DemoOpponent()

    @app.post("/v1/turn", response_model=TurnResponse, response_model_exclude_none=True)
    async def take_turn(request: TurnRequest) -> TurnResponse:
        if request.snapshot.state.stage == "agreed":
            raise HTTPException(status_code=409, detail="Duel already has an agreement")
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
            shared_context=request.scenario.shared_context,
            opponent_private_context=request.scenario.opponent_private_context,
            agreement_rules=request.scenario.agreement_rules,
            player_role=request.scenario.player_role,
            opponent_role=request.scenario.opponent_role,
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
            return TurnResponse(
                session_id=request.snapshot.session_id,
                turn_id=request.turn_id,
                status="model_error",
                opponent_text="Сейчас не могу продолжить разговор. Попробуйте повторить ход.",
                snapshot=request.snapshot,
                error_code="opponent_unavailable",
            )
        try:
            proposal = OpponentProposal.model_validate(raw_proposal)
        except ValueError:
            proposal = None
        if proposal is None or not valid_proposal(proposal, request.scenario):
            return TurnResponse(
                session_id=request.snapshot.session_id,
                turn_id=request.turn_id,
                status="model_error",
                opponent_text="Сейчас не могу продолжить разговор. Попробуйте повторить ход.",
                snapshot=request.snapshot,
                error_code="invalid_opponent_output",
            )
        snapshot = SessionSnapshot(
            session_id=request.snapshot.session_id,
            state=SessionState(
                turn_count=request.snapshot.state.turn_count + 1,
                stage="agreed" if proposal.agreement is not None else "negotiating",
                agreement=proposal.agreement,
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

    return app


app = create_app()
