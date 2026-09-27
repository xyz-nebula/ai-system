"""Portable Pydantic 2 request models for the /v2/evaluate endpoint.

It can be copied into Backend without importing arena_ai.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

NonBlankText = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, pattern=r"\S"),
]


class EvaluationMessage(BaseModel):
    """One saved dialogue message; order is determined by its list position."""

    model_config = ConfigDict(extra="forbid", strict=True)

    text: NonBlankText
    is_ai: bool = Field(description="True: AI opponent; false: user.")


class EvaluationRequest(BaseModel):
    """Finished dialogue for judges and the post-dialogue trainer."""

    model_config = ConfigDict(extra="forbid", strict=True)

    role: NonBlankText = Field(description="User's active game role.")
    opponent_role: NonBlankText = Field(description="AI opponent's active game role.")
    case_description: NonBlankText = Field(
        description="Shared case context and conditions, without hidden opponent information."
    )
    messages: list[EvaluationMessage] = Field(
        min_length=1,
        description="Saved dialogue messages in chronological order, selected by Backend.",
    )
    preparations: NonBlankText | None = Field(
        default=None,
        description="User's personal preparation as one string, not author-provided role briefs.",
    )
