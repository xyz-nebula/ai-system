"""Repeatable black-box evaluation for the team lead's fixed negotiation case."""

import argparse
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from arena_ai.cli_args import positive_timeout
from arena_ai.contracts import (
    FinishResponse,
    ReadinessResponse,
    ServiceInfo,
    SessionSnapshot,
    SessionState,
    TranscriptEntry,
    TurnResponse,
)
from arena_ai.scenarios import (
    NEXT_DAY_CASE,
    NEXT_DAY_STRONG_PREPARATION,
    NEXT_DAY_STRONG_TURNS,
)

SCENARIO_ID = "next-day-strong-agreement"
CHECK_NAMES = (
    "all_turns_accepted",
    "snapshot_consistent",
    "agreement_within_rules",
    "three_judges_ready",
    "judge_evidence_grounded",
    "trainer_ready",
    "trainer_evidence_grounded",
    "preparation_covered",
)


def positive_int(value: str) -> int:
    try:
        result = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Значение должно быть целым числом") from error
    if result <= 0:
        raise argparse.ArgumentTypeError("Значение должно быть положительным")
    return result


def evidence_is_grounded(
    transcript: list[TranscriptEntry],
    turn_id: str,
    quote: str,
    *,
    player_only: bool,
) -> bool:
    return any(
        entry.turn_id == turn_id
        and (not player_only or entry.speaker == "player")
        and quote in entry.text
        for entry in transcript
    )


def snapshot_is_consistent(snapshot: SessionSnapshot, turn_ids: list[str]) -> bool:
    if snapshot.state.turn_count != len(turn_ids) or len(snapshot.transcript) != len(turn_ids) * 2:
        return False
    for index, turn_id in enumerate(turn_ids):
        player, opponent = snapshot.transcript[index * 2 : index * 2 + 2]
        if (
            player.turn_id != turn_id
            or player.speaker != "player"
            or player.status != "accepted"
            or opponent.turn_id != turn_id
            or opponent.speaker != "opponent"
            or opponent.status != "accepted"
        ):
            return False
    return True


def evaluate_finish(
    finished: FinishResponse | None,
    snapshot: SessionSnapshot,
) -> tuple[
    dict[str, bool],
    dict[str, dict[str, str | None]],
    str | None,
    dict[str, str | None] | None,
]:
    checks = {name: False for name in CHECK_NAMES[2:]}
    if finished is None:
        return checks, {}, None, None

    rules = NEXT_DAY_CASE.agreement_rules
    agreement = finished.outcome.agreement
    checks["agreement_within_rules"] = bool(
        finished.outcome.kind == "agreement"
        and agreement is not None
        and rules.min_control_weeks <= agreement.control_weeks <= rules.max_control_weeks
        and rules.min_kpi_percent <= agreement.kpi_percent <= rules.max_kpi_percent
        and agreement.automatic_raise
    )

    judge_slots: dict[str, dict[str, str | None]] = {
        slot.college: {"status": slot.status, "error_code": slot.error_code}
        for slot in finished.judge_verdicts
    }
    checks["three_judges_ready"] = set(judge_slots) == {
        "hiring",
        "negotiation",
        "ownership",
    } and all(slot["status"] == "ready" for slot in judge_slots.values())
    checks["judge_evidence_grounded"] = len(finished.judge_verdicts) == 3 and all(
        slot.verdict is not None
        and evidence_is_grounded(
            snapshot.transcript,
            slot.verdict.evidence_turn_id,
            slot.verdict.evidence_quote,
            player_only=False,
        )
        for slot in finished.judge_verdicts
    )

    trainer = finished.trainer_feedback
    checks["trainer_ready"] = trainer.status == "ready" and trainer.feedback is not None
    if trainer.feedback is not None:
        points = [*trainer.feedback.strengths, *trainer.feedback.mistakes]
        checks["trainer_evidence_grounded"] = bool(points) and all(
            evidence_is_grounded(
                snapshot.transcript,
                point.evidence_turn_id,
                point.evidence_quote,
                player_only=True,
            )
            for point in points
        )
        comparison = trainer.feedback.plan_vs_reality
        if comparison is not None:
            expected = Counter(
                (item.kind, item.text) for item in NEXT_DAY_STRONG_PREPARATION.comparison_items()
            )
            actual = Counter(
                (item.preparation_kind, item.preparation_text) for item in comparison.items
            )
            checks["preparation_covered"] = actual == expected

    trainer_report = {"status": trainer.status, "error_code": trainer.error_code}
    return checks, judge_slots, finished.outcome.kind, trainer_report


def run_once(client: httpx.Client, number: int) -> dict[str, Any]:
    snapshot = SessionSnapshot(
        session_id=str(uuid4()),
        state=SessionState(turn_count=0),
        transcript=[],
    )
    turn_results: list[dict[str, object]] = []
    accepted_turn_ids: list[str] = []

    for sequence, user_text in enumerate(NEXT_DAY_STRONG_TURNS, start=1):
        turn_id = str(uuid4())
        try:
            response = client.post(
                "/v1/turn",
                json={
                    "case": NEXT_DAY_CASE.model_dump(mode="json"),
                    "snapshot": snapshot.model_dump(mode="json"),
                    "turn_id": turn_id,
                    "user_text": user_text,
                },
            )
            response.raise_for_status()
            result = TurnResponse.model_validate(response.json())
        except (httpx.HTTPError, ValueError) as error:
            turn_results.append(
                {
                    "sequence": sequence,
                    "status": "request_error",
                    "error_code": type(error).__name__,
                }
            )
            break
        turn_results.append(
            {
                "sequence": sequence,
                "status": result.status,
                "error_code": result.error_code,
            }
        )
        if result.status != "accepted":
            break
        snapshot = result.snapshot
        accepted_turn_ids.append(turn_id)

    checks = {
        "all_turns_accepted": len(turn_results) == len(NEXT_DAY_STRONG_TURNS)
        and all(turn["status"] == "accepted" for turn in turn_results),
        "snapshot_consistent": snapshot_is_consistent(snapshot, accepted_turn_ids)
        and len(accepted_turn_ids) == len(NEXT_DAY_STRONG_TURNS),
    }
    finished: FinishResponse | None = None
    finish_error: str | None = None
    if checks["all_turns_accepted"]:
        try:
            response = client.post(
                "/v1/finish",
                json={
                    "case": NEXT_DAY_CASE.model_dump(mode="json"),
                    "snapshot": snapshot.model_dump(mode="json"),
                    "preparation": NEXT_DAY_STRONG_PREPARATION.filled_fields(),
                },
            )
            response.raise_for_status()
            finished = FinishResponse.model_validate(response.json())
        except (httpx.HTTPError, ValueError) as error:
            finish_error = type(error).__name__

    finish_checks, judge_slots, outcome_kind, trainer = evaluate_finish(
        finished, snapshot
    )
    checks.update(finish_checks)
    return {
        "run": number,
        "status": "passed" if all(checks.values()) else "failed",
        "turns": turn_results,
        "finish_error": finish_error,
        "outcome_kind": outcome_kind,
        "judge_slots": judge_slots,
        "trainer": trainer,
        "checks": checks,
    }


def report_for(
    runs_requested: int,
    *,
    service: ServiceInfo | None,
    readiness: ReadinessResponse | None,
    startup_error: str | None,
    runs: list[dict[str, Any]],
) -> dict[str, Any]:
    passed = sum(run["status"] == "passed" for run in runs)
    failed = runs_requested - passed
    return {
        "scenario_id": SCENARIO_ID,
        "service": None if service is None else service.model_dump(mode="json"),
        "readiness": (
            None
            if readiness is None
            else readiness.model_dump(mode="json", exclude_none=True)
        ),
        "startup_error": startup_error,
        "runs_requested": runs_requested,
        "summary": {"passed": passed, "failed": failed},
        "runs": runs,
    }


def execute(api_url: str, runs: int, timeout: float) -> tuple[dict[str, Any], int]:
    token = os.environ.get("ARENA_SERVICE_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    service: ServiceInfo | None = None
    readiness: ReadinessResponse | None = None
    try:
        with httpx.Client(base_url=api_url, headers=headers, timeout=timeout) as client:
            info_response = client.get("/v1/info")
            info_response.raise_for_status()
            service = ServiceInfo.model_validate(info_response.json())

            readiness_response = client.get("/health/ready")
            readiness = ReadinessResponse.model_validate(readiness_response.json())
            if readiness_response.is_error or readiness.status != "ready":
                startup_error = readiness.category or "HTTPStatusError"
                return (
                    report_for(
                        runs,
                        service=service,
                        readiness=readiness,
                        startup_error=startup_error,
                        runs=[],
                    ),
                    2,
                )
            results = [run_once(client, number) for number in range(1, runs + 1)]
    except (httpx.HTTPError, ValueError) as error:
        return (
            report_for(
                runs,
                service=service,
                readiness=readiness,
                startup_error=type(error).__name__,
                runs=[],
            ),
            2,
        )

    report = report_for(
        runs,
        service=service,
        readiness=readiness,
        startup_error=None,
        runs=results,
    )
    return report, 0 if report["summary"]["failed"] == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Повторяемая оценка живого AI-контура на фиксированном кейсе"
    )
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--runs", type=positive_int, default=3)
    parser.add_argument("--timeout", type=positive_timeout, default=300.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report, exit_code = execute(args.api_url, args.runs, args.timeout)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output is not None:
        try:
            args.output.write_text(f"{rendered}\n", encoding="utf-8")
        except OSError as error:
            parser.exit(2, f"Не удалось сохранить отчёт: {type(error).__name__}\n")
    print(rendered)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
