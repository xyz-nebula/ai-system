"""HTTP boundary for a single text turn of a negotiation duel."""

from typing import Literal, Protocol

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScenarioConfig(Contract):
    id: str
    title: str
    shared_context: str
    player_role: str
    opponent_role: str
    player_private_context: str
    opponent_private_context: str


class SessionState(Contract):
    turn_count: int = Field(ge=0)


class TranscriptEntry(Contract):
    turn_id: str
    speaker: Literal["player", "opponent"]
    status: Literal["accepted"]
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
    opponent_text: str
    snapshot: SessionSnapshot


class OpponentContext(Contract):
    shared_context: str
    opponent_private_context: str
    player_role: str
    opponent_role: str
    state: SessionState
    transcript: list[TranscriptEntry]
    user_text: str


class Opponent(Protocol):
    async def respond(self, context: OpponentContext) -> str: ...


class DemoOpponent:
    async def respond(self, context: OpponentContext) -> str:
        if context.state.turn_count == 0:
            return (
                "Вчера мы говорили о большей ответственности. Как вы объясните сегодняшний пропуск?"
            )
        return "Мне нужны понятные условия, которые восстановят доверие. Что вы предлагаете?"


def create_app(opponent: Opponent | None = None) -> FastAPI:
    app = FastAPI(title="Arena AI", version="0.1.0")
    active_opponent = opponent if opponent is not None else DemoOpponent()

    @app.post("/v1/turn", response_model=TurnResponse)
    async def take_turn(request: TurnRequest) -> TurnResponse:
        context = OpponentContext(
            shared_context=request.scenario.shared_context,
            opponent_private_context=request.scenario.opponent_private_context,
            player_role=request.scenario.player_role,
            opponent_role=request.scenario.opponent_role,
            state=request.snapshot.state,
            transcript=request.snapshot.transcript,
            user_text=request.user_text,
        )
        opponent_text = await active_opponent.respond(context)
        snapshot = SessionSnapshot(
            session_id=request.snapshot.session_id,
            state=SessionState(turn_count=request.snapshot.state.turn_count + 1),
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
                    text=opponent_text,
                ),
            ],
        )
        return TurnResponse(
            session_id=snapshot.session_id,
            turn_id=request.turn_id,
            opponent_text=opponent_text,
            snapshot=snapshot,
        )

    return app


app = create_app()
