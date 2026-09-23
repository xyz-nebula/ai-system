"""Bounded attempts for stateless model calls before committing domain results."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

type ModelFailure = Literal["unavailable", "invalid"]


@dataclass(frozen=True, slots=True)
class ModelCallResult[T]:
    value: T | None
    failure: ModelFailure | None


async def validated_model_call[T](
    call: Callable[[], Awaitable[object]],
    validate: Callable[[object], T | None],
    *,
    attempts: int,
) -> ModelCallResult[T]:
    if attempts < 1:
        raise ValueError("model attempts must be positive")
    failure: ModelFailure = "unavailable"
    for _ in range(attempts):
        try:
            raw = await call()
        except Exception:  # noqa: BLE001 - isolate the external model adapter
            failure = "unavailable"
            continue
        value = validate(raw)
        if value is not None:
            return ModelCallResult(value=value, failure=None)
        failure = "invalid"
    return ModelCallResult(value=None, failure=failure)
