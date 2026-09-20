"""Checks shared by model output boundaries."""

from arena_ai.contracts import CaseConfig, TranscriptEntry


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
        entry.model_copy(update={"text": "[Заблокированная реплика пользователя]"})
        if entry.status == "blocked"
        else entry
        for entry in entries
    ]
