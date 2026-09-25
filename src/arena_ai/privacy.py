"""Checks shared by model output boundaries."""

from dataclasses import dataclass

from arena_ai.contracts import (
    CaseConfig,
    GuardReason,
    PublicSessionState,
    SessionSnapshot,
    TranscriptEntry,
)

BLOCKED_SUMMARIES: dict[GuardReason, str] = {
    "prompt_override": "[Заблокировано: попытка изменить инструкции сервиса]",
    "private_data_request": "[Заблокировано: запрос закрытых вводных]",
    "hidden_position_request": "[Заблокировано: запрос скрытой переговорной позиции]",
}


@dataclass(frozen=True, slots=True)
class PublicDuelView:
    state: PublicSessionState
    transcript: list[TranscriptEntry]


def contains_private_phrase(text: str, case: CaseConfig) -> bool:
    visible_text = text.casefold()
    private_phrases = (
        case.player_private_context,
        case.opponent_private_context,
        *case.opponent_private_phrases,
    )
    return any(phrase.casefold() in visible_text for phrase in private_phrases if phrase)


def public_transcript(entries: list[TranscriptEntry]) -> list[TranscriptEntry]:
    return [
        entry.model_copy(
            update={
                "text": BLOCKED_SUMMARIES.get(
                    entry.blocked_reason, "[Заблокированная реплика пользователя]"
                )
            }
        )
        if entry.status == "blocked"
        else entry
        for entry in entries
    ]


def public_session_state(snapshot: SessionSnapshot) -> PublicSessionState:
    """Remove opponent-only strategy progress from evaluative model contexts."""

    return PublicSessionState.model_validate(
        snapshot.state.model_dump(mode="python", exclude={"opponent_progress"})
    )


def public_duel_view(snapshot: SessionSnapshot) -> PublicDuelView:
    """Project a snapshot once for model roles that must not see opponent-only state."""

    return PublicDuelView(
        state=public_session_state(snapshot),
        transcript=public_transcript(snapshot.transcript),
    )
