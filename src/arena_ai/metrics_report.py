"""Summarize evaluation measurements into metrics: `arena-ai-metrics`."""

import argparse
import json
import math
import os
import statistics
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from arena_ai.judges import COLLEGES

SLOTS = ("outcome", *COLLEGES, "trainer")


def share(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def median(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def nearest_rank(values: Sequence[float], percent: int) -> float | None:
    """Nearest-rank percentile: always an observed value, never an interpolation."""
    return sorted(values)[math.ceil(percent / 100 * len(values)) - 1] if values else None


def mean(values: Sequence[float]) -> float | None:
    return round(statistics.fmean(values), 1) if values else None


def tokens(slots: list[dict[str, Any]], kind: str) -> int:
    """Reported tokens only; calls without usage are counted separately, never as zero."""
    return sum(slot[f"{kind}_tokens"] or 0 for slot in slots)


def quote_binding(slots: list[dict[str, Any]]) -> dict[str, Any]:
    """Shares of the model's quotes in ready slots; dropped is a subset, not a binding."""
    counts: Counter[str] = Counter()
    for slot in slots:
        if slot["status"] == "ready":
            counts.update(slot["quotes"])
    total = counts["exact"] + counts["moved"] + counts["substituted"]
    return {
        "total": total,
        **{
            kind: share(counts[kind], total)
            for kind in ("exact", "moved", "substituted", "dropped")
        },
    }


def judge_choices(measurements: list[dict[str, Any]]) -> dict[str, Any]:
    ready = [
        [slot for slot in record["slots"] if slot["slot"] in COLLEGES and slot["status"] == "ready"]
        for record in measurements
    ]
    votes = [slot for judged in ready for slot in judged]
    complete = [judged for judged in ready if len(judged) == len(COLLEGES)]

    def ai_share(chosen: list[dict[str, Any]]) -> float | None:
        return share(sum(slot["choice"] == "ai" for slot in chosen), len(chosen))

    return {
        "ai_choice_share": ai_share(votes),
        "ai_choice_share_by_college": {
            college: ai_share([slot for slot in votes if slot["slot"] == college])
            for college in COLLEGES
        },
        "unanimous_share": share(
            sum(len({slot["choice"] for slot in judged}) == 1 for judged in complete),
            len(complete),
        ),
        "unanimous_base": len(complete),
        "decisive_criteria": {
            college: dict(
                Counter(slot["decisive_criterion"] for slot in votes if slot["slot"] == college)
            )
            for college in COLLEGES
        },
    }


def utc_time(text: str) -> datetime:
    """ISO time; a value without a zone, such as a bare date, is UTC."""
    value = datetime.fromisoformat(text)
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def read_measurements(
    path: Path, since: datetime | None, until: datetime | None
) -> tuple[list[dict[str, Any]], int]:
    """Evaluation records inside [since, until), plus the count of unreadable lines."""
    if not path.exists():
        return [], 0  # a fresh volume: nothing has been evaluated yet
    measurements, skipped = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            recorded_at = utc_time(record["recorded_at"])
        except (ValueError, KeyError, TypeError):
            skipped += 1
            continue
        if record.get("event") != "evaluation":
            skipped += 1
        elif (since is None or recorded_at >= since) and (until is None or recorded_at < until):
            measurements.append(record)
    return measurements, skipped


def summarize(measurements: list[dict[str, Any]], *, skipped_lines: int = 0) -> dict[str, Any]:
    measurements = sorted(measurements, key=lambda record: utc_time(record["recorded_at"]))
    count = len(measurements)
    by_slot = {
        name: [slot for record in measurements for slot in record["slots"] if slot["slot"] == name]
        for name in SLOTS
    }
    durations = [record["duration_ms"] for record in measurements]
    inputs = [tokens(record["slots"], "input") for record in measurements]
    outputs = [tokens(record["slots"], "output") for record in measurements]
    totals = [sum(pair) for pair in zip(inputs, outputs, strict=True)]
    without_usage = sum(slot["calls_without_usage"] for slots in by_slot.values() for slot in slots)
    return {
        "evaluations": count,
        "skipped_lines": skipped_lines,
        "period": {
            "first": measurements[0]["recorded_at"] if measurements else None,
            "last": measurements[-1]["recorded_at"] if measurements else None,
        },
        "duration_ms": {
            "median": median(durations),
            "p95": nearest_rank(durations, 95),
            "max": max(durations, default=None),
        },
        "tokens_per_evaluation": {
            "input_mean": mean(inputs),
            "output_mean": mean(outputs),
            "total_mean": mean(totals),
            "total_median": median(totals),
            "complete": without_usage == 0,
            "calls_without_usage": without_usage,
        },
        "slots": {
            name: {
                "ready_share": share(sum(slot["status"] == "ready" for slot in slots), count),
                "error_codes": dict(
                    Counter(slot["error_code"] for slot in slots if slot["error_code"])
                ),
                "redraft_share": share(sum(slot["redrafts"] > 0 for slot in slots), count),
                # A slot failed before any model call took no model time to speak of.
                "duration_ms_median": median(
                    [slot["duration_ms"] for slot in slots if slot["model_calls"] > 0]
                ),
                # Per evaluation, so the slot means add up to the evaluation mean.
                "tokens_mean": {
                    "input": round(tokens(slots, "input") / count, 1) if count else None,
                    "output": round(tokens(slots, "output") / count, 1) if count else None,
                },
            }
            for name, slots in by_slot.items()
        },
        "quotes": quote_binding([slot for slots in by_slot.values() for slot in slots]),
        "judges": judge_choices(measurements),
        "outcomes": dict(
            Counter(slot["kind"] for slot in by_slot["outcome"] if slot["status"] == "ready")
        ),
    }


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Сводка замеров оценки поединков")
    parser.add_argument(
        "--file",
        type=Path,
        default=os.getenv("ARENA_METRICS_FILE") or None,
        help="файл замеров (по умолчанию ARENA_METRICS_FILE)",
    )
    parser.add_argument(
        "--since", type=utc_time, help="с этого момента включительно, ISO 8601; без зоны — UTC"
    )
    parser.add_argument("--until", type=utc_time, help="до этого момента, ISO 8601; без зоны — UTC")
    args = parser.parse_args(argv)
    if args.file is None:
        parser.error("Укажите --file или ARENA_METRICS_FILE")
    measurements, skipped = read_measurements(args.file, args.since, args.until)
    print(json.dumps(summarize(measurements, skipped_lines=skipped), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
