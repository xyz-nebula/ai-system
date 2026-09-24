"""Checks shared by model output boundaries."""

from arena_ai.contracts import CaseConfig, GuardReason, SessionState, TranscriptEntry

BLOCKED_SUMMARIES: dict[GuardReason, str] = {
    "prompt_override": "[Заблокировано: попытка изменить инструкции сервиса]",
    "private_data_request": "[Заблокировано: запрос закрытых вводных]",
    "hidden_position_request": "[Заблокировано: запрос скрытой переговорной позиции]",
}


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


def public_session_state(state: SessionState) -> SessionState:
    """Remove opponent-only strategy progress from evaluative model contexts."""

    return state.model_copy(update={"opponent_progress": None})
