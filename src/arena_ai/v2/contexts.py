"""Explicit allowlist projections; never send a full Backend request to a model."""

from typing import Literal

from arena_ai.privacy import BLOCKED_SUMMARIES
from arena_ai.v2.contracts import (
    AgreementPolicy,
    Contract,
    DealTerms,
    DeferredDecision,
    FinishRequest,
    Negotiable,
    OpponentStrategy,
    PartialDecision,
    Participant,
    PossibleOutcome,
    RoleBrief,
    SessionSnapshot,
    SessionState,
    Text,
    TranscriptEntry,
    TurnRequest,
)


def _transcript(snapshot: SessionSnapshot) -> list[TranscriptEntry]:
    return [
        item.model_copy(
            deep=True,
            update={
                "text": BLOCKED_SUMMARIES.get(
                    item.blocked_reason, "[Заблокированная реплика пользователя]"
                )
            },
        )
        if item.status == "blocked"
        else item.model_copy(deep=True)
        for item in snapshot.transcript
    ]


class ActiveRole(Contract):
    role_id: Text
    name: Text


class GuardContext(Contract):
    shared_context: Text
    participants: list[Participant]
    player_role: ActiveRole
    opponent_role: ActiveRole
    user_text: Text


def for_guard(request: TurnRequest) -> GuardContext:
    case = request.case
    names = {item.id: item.name for item in case.participants}
    return GuardContext(
        shared_context=case.shared_context,
        participants=[item.model_copy(deep=True) for item in case.participants],
        player_role=ActiveRole(role_id=case.player.role_id, name=names[case.player.role_id]),
        opponent_role=ActiveRole(role_id=case.opponent.role_id, name=names[case.opponent.role_id]),
        user_text=request.user_text,
    )


class OpponentContext(Contract):
    shared_context: Text
    participants: list[Participant]
    player_role: ActiveRole
    opponent_role: ActiveRole
    opponent_brief: RoleBrief
    negotiables: list[Negotiable]
    opponent_strategy: OpponentStrategy
    agreement_policy: AgreementPolicy
    possible_outcomes: list[PossibleOutcome]
    state: SessionState
    transcript: list[TranscriptEntry]
    user_text: Text


def for_opponent(request: TurnRequest) -> OpponentContext:
    case = request.case
    names = {item.id: item.name for item in case.participants}
    return OpponentContext(
        shared_context=case.shared_context,
        participants=[item.model_copy(deep=True) for item in case.participants],
        player_role=ActiveRole(role_id=case.player.role_id, name=names[case.player.role_id]),
        opponent_role=ActiveRole(role_id=case.opponent.role_id, name=names[case.opponent.role_id]),
        opponent_brief=case.opponent.model_copy(deep=True),
        negotiables=[item.model_copy(deep=True) for item in case.negotiables],
        opponent_strategy=case.opponent_strategy.model_copy(deep=True),
        agreement_policy=case.agreement_policy.model_copy(deep=True),
        possible_outcomes=[
            item.model_copy(deep=True)
            for item in case.possible_outcomes
            if item.visibility == "public" or case.opponent.role_id in item.known_to_role_ids
        ],
        state=request.snapshot.state.model_copy(deep=True),
        transcript=_transcript(request.snapshot),
        user_text=request.user_text,
    )


class PublicState(Contract):
    turn_count: int
    stage: Literal["negotiating", "agreed", "partial_agreement", "deferred"]
    agreement: DealTerms | None
    decision: PartialDecision | DeferredDecision | None


class JudgeContext(Contract):
    shared_context: Text
    participants: list[Participant]
    player_role: ActiveRole
    opponent_role: ActiveRole
    state: PublicState
    transcript: list[TranscriptEntry]
    possible_outcomes: list[PossibleOutcome]


class TrainerContext(JudgeContext):
    preparation: Text | None


def for_judge(request: FinishRequest) -> JudgeContext:
    case = request.case
    names = {item.id: item.name for item in case.participants}
    state = request.snapshot.state
    return JudgeContext(
        shared_context=case.shared_context,
        participants=[item.model_copy(deep=True) for item in case.participants],
        player_role=ActiveRole(role_id=case.player.role_id, name=names[case.player.role_id]),
        opponent_role=ActiveRole(role_id=case.opponent.role_id, name=names[case.opponent.role_id]),
        state=PublicState(
            turn_count=state.turn_count,
            stage=state.stage,
            agreement=state.agreement.model_copy(deep=True)
            if state.agreement is not None
            else None,
            decision=state.decision.model_copy(deep=True) if state.decision is not None else None,
        ),
        transcript=_transcript(request.snapshot),
        possible_outcomes=[
            item.model_copy(deep=True)
            for item in case.possible_outcomes
            if item.visibility == "public"
        ],
    )


def for_trainer(request: FinishRequest) -> TrainerContext:
    return TrainerContext.model_validate(
        {
            **for_judge(request).model_dump(mode="python"),
            "preparation": request.preparation,
        }
    )
