"""Evaluation measurements: one text-free JSONL record per /v2/evaluate call."""

import json
import logging
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from arena_ai.judge_corpus import CORPUS_VERSION
from arena_ai.v2.evaluation_request import EvaluationRequest
from arena_ai.v2.evaluation_response import EvaluationResponse

type QuoteBinding = Literal["exact", "moved", "substituted"]


def no_quotes() -> dict[str, int]:
    # "dropped" counts quotes removed from the published slot, whatever their binding.
    return {"exact": 0, "moved": 0, "substituted": 0, "dropped": 0}


@dataclass
class SlotMeter:
    duration_ms: int = 0
    model_calls: int = 0
    redrafts: int = 0
    calls_with_usage: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    quotes: dict[str, int] = field(default_factory=no_quotes)

    def fields(self) -> dict[str, Any]:
        measured = self.calls_with_usage > 0
        return {
            "duration_ms": self.duration_ms,
            "model_calls": self.model_calls,
            "redrafts": self.redrafts,
            "input_tokens": self.input_tokens if measured else None,
            "output_tokens": self.output_tokens if measured else None,
            "calls_without_usage": self.model_calls - self.calls_with_usage,
            "quotes": self.quotes,
        }


# Task-local, like the model call budget: slots run sequentially inside one request.
current_meters: ContextVar[dict[str, SlotMeter] | None] = ContextVar(
    "v2_evaluation_meters", default=None
)
current_slot: ContextVar[SlotMeter | None] = ContextVar("v2_evaluation_slot", default=None)


@contextmanager
def measured_slot(name: str) -> Iterator[None]:
    """Attribute model calls inside the block to one evaluation slot, if measured."""
    meters = current_meters.get()
    if meters is None:
        yield
        return
    meter = meters[name] = SlotMeter()
    started = time.monotonic()
    token = current_slot.set(meter)
    try:
        yield
    finally:
        current_slot.reset(token)
        meter.duration_ms = round((time.monotonic() - started) * 1000)


def count_model_call() -> None:
    if (meter := current_slot.get()) is not None:
        meter.model_calls += 1


def count_redraft() -> None:
    """A rejected draft is generated afresh, so its quotes no longer count."""
    if (meter := current_slot.get()) is not None:
        meter.redrafts += 1
        meter.quotes = no_quotes()


def count_binding(binding: QuoteBinding) -> None:
    if (meter := current_slot.get()) is not None:
        meter.quotes[binding] += 1


def count_dropped(number: int) -> None:
    if (meter := current_slot.get()) is not None:
        meter.quotes["dropped"] += number


def count_usage(payload: object) -> None:
    """Add a chat completion's reported tokens; an absent or odd `usage` stays unknown."""
    meter = current_slot.get()
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if meter is None or not isinstance(usage, dict):
        return
    prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
    if type(prompt) is int and type(completion) is int:
        meter.calls_with_usage += 1
        meter.input_tokens += prompt
        meter.output_tokens += completion


def slot_results(result: EvaluationResponse) -> list[dict[str, Any]]:
    """Statuses and closed-list codes of each slot; never a quote or a sentence."""
    outcome = result.outcome
    slots: list[dict[str, Any]] = [
        {
            "slot": "outcome",
            "status": outcome.status,
            "error_code": outcome.error_code,
            "kind": None if outcome.assessment is None else outcome.assessment.kind,
        }
    ]
    for judged in result.judge_verdicts:
        verdict = judged.verdict
        slots.append(
            {
                "slot": judged.college,
                "status": judged.status,
                "error_code": judged.error_code,
                "choice": None
                if verdict is None
                else ("user" if verdict.choice == "player" else "ai"),
                "decisive_criterion": None if verdict is None else verdict.decisive_criterion,
            }
        )
    trainer = result.trainer_feedback
    feedback = trainer.feedback
    slots.append(
        {
            "slot": "trainer",
            "status": trainer.status,
            "error_code": trainer.error_code,
            "strengths": None if feedback is None else len(feedback.strengths),
            "mistakes": None if feedback is None else len(feedback.mistakes),
            "missed_opportunities": None
            if feedback is None
            else len(feedback.missed_opportunities),
            "next_try": None if feedback is None else len(feedback.next_try),
            "goal_status": None if feedback is None else feedback.goal_assessment.status,
        }
    )
    return slots


async def record_evaluation(
    path: Path | None,
    request: EvaluationRequest,
    evaluate: Callable[[], Awaitable[EvaluationResponse]],
    *,
    validation: str,
    model: str,
) -> EvaluationResponse:
    """Run one evaluation and, when a measurement file is set, append its record."""
    if path is None:
        return await evaluate()
    started = time.monotonic()
    meters: dict[str, SlotMeter] = {}
    token = current_meters.set(meters)
    try:
        result = await evaluate()
    finally:
        current_meters.reset(token)
    try:
        record = {
            "event": "evaluation",
            "evaluation_id": str(uuid4()),
            "recorded_at": datetime.now(UTC).isoformat(),
            "duration_ms": round((time.monotonic() - started) * 1000),
            "validation": validation,
            "model": model,
            "corpus_version": CORPUS_VERSION,
            "messages": len(request.messages),
            "user_messages": sum(not message.is_ai for message in request.messages),
            "preparation": request.preparations is not None,
            "slots": [
                {**slot, **meters.get(slot["slot"], SlotMeter()).fields()}
                for slot in slot_results(result)
            ],
        }
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as error:  # noqa: BLE001 - a lost measurement must never cost the evaluation
        logging.getLogger(__name__).warning(
            "evaluation_measurement_unwritten failure_type=%s",
            type(error).__name__,
            extra={"failure_type": type(error).__name__},
        )
    return result
