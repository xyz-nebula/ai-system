"""Repeatable black-box evaluation for the team lead's fixed negotiation case."""

import argparse
import json
import math
import os
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from arena_ai.cli import DEMO_CASE
from arena_ai.contracts import (
    CaseConfig,
    FinishResponse,
    PreparationCard,
    ReadinessResponse,
    ServiceInfo,
    SessionSnapshot,
    SessionState,
    TranscriptEntry,
    TurnResponse,
)

SCENARIO_ID = "next-day-strong-agreement"
SCENARIO_CASE = CaseConfig.model_validate(DEMO_CASE)
SCENARIO_TURNS = (
    (
        "Понимаю ваши сомнения. Это было отравление, и я готов компенсировать последствия "
        "пропуска и подтвердить ответственность измеримым результатом."
    ),
    (
        "Предлагаю 2 недели контрольного периода с KPI 120% и автоматическим повышением "
        "после выполнения. Согласны?"
    ),
)
SCENARIO_PREPARATION = PreparationCard(
    negotiation_goal="Согласовать измеримые условия автоматического повышения.",
    planned_questions=["Какие срок и KPI подтвердят мою готовность?"],
)
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


def positive_timeout(value: str) -> float:
    try:
        result = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Тайм-аут должен быть числом секунд") from error
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("Тайм-аут должен быть положительным")
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
) -> tuple[dict[str, bool], dict[str, str], str | None, str | None]:
    checks = {name: False for name in CHECK_NAMES[2:]}
    if finished is None:
        return checks, {}, None, None

    rules = SCENARIO_CASE.agreement_rules
    agreement = finished.outcome.agreement
    checks["agreement_within_rules"] = bool(
        finished.outcome.kind == "agreement"
        and agreement is not None
        and rules.min_control_weeks <= agreement.control_weeks <= rules.max_control_weeks
        and rules.min_kpi_percent <= agreement.kpi_percent <= rules.max_kpi_percent
        and agreement.automatic_raise
    )

    judge_slots: dict[str, str] = {
        slot.college: slot.status for slot in finished.judge_verdicts
    }
    checks["three_judges_ready"] = judge_slots == {
        "hiring": "ready",
        "negotiation": "ready",
        "ownership": "ready",
    }
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
                (item.kind, item.text) for item in SCENARIO_PREPARATION.comparison_items()
            )
            actual = Counter(
                (item.preparation_kind, item.preparation_text) for item in comparison.items
            )
            checks["preparation_covered"] = actual == expected

    return checks, judge_slots, finished.outcome.kind, trainer.status


def run_once(client: httpx.Client, number: int) -> dict[str, Any]:
    snapshot = SessionSnapshot(
        session_id=str(uuid4()),
        state=SessionState(turn_count=0),
        transcript=[],
    )
    turn_results: list[dict[str, object]] = []
    accepted_turn_ids: list[str] = []

    for sequence, user_text in enumerate(SCENARIO_TURNS, start=1):
        turn_id = str(uuid4())
        try:
            response = client.post(
                "/v1/turn",
                json={
                    "case": SCENARIO_CASE.model_dump(mode="json"),
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
        "all_turns_accepted": len(turn_results) == len(SCENARIO_TURNS)
        and all(turn["status"] == "accepted" for turn in turn_results),
        "snapshot_consistent": snapshot_is_consistent(snapshot, accepted_turn_ids)
        and len(accepted_turn_ids) == len(SCENARIO_TURNS),
    }
    finished: FinishResponse | None = None
    finish_error: str | None = None
    if checks["all_turns_accepted"]:
        try:
            response = client.post(
                "/v1/finish",
                json={
                    "case": SCENARIO_CASE.model_dump(mode="json"),
                    "snapshot": snapshot.model_dump(mode="json"),
                    "preparation": SCENARIO_PREPARATION.filled_fields(),
                },
            )
            response.raise_for_status()
            finished = FinishResponse.model_validate(response.json())
        except (httpx.HTTPError, ValueError) as error:
            finish_error = type(error).__name__

    finish_checks, judge_slots, outcome_kind, trainer_status = evaluate_finish(
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
        "trainer_status": trainer_status,
        "checks": checks,
    }


def execute(api_url: str, runs: int, timeout: float) -> dict[str, Any]:
    token = os.environ.get("ARENA_SERVICE_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(base_url=api_url, headers=headers, timeout=timeout) as client:
        readiness_response = client.get("/health/ready")
        readiness_response.raise_for_status()
        readiness = ReadinessResponse.model_validate(readiness_response.json())
        if readiness.status != "ready":
            raise RuntimeError("AI service is not ready")
        info_response = client.get("/v1/info")
        info_response.raise_for_status()
        info = ServiceInfo.model_validate(info_response.json())
        results = [run_once(client, number) for number in range(1, runs + 1)]

    passed = sum(result["status"] == "passed" for result in results)
    return {
        "scenario_id": SCENARIO_ID,
        "service": info.model_dump(mode="json"),
        "runs_requested": runs,
        "summary": {"passed": passed, "failed": runs - passed},
        "runs": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Повторяемая оценка живого AI-контура на фиксированном кейсе"
    )
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--runs", type=positive_int, default=3)
    parser.add_argument("--timeout", type=positive_timeout, default=300.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        report = execute(args.api_url, args.runs, args.timeout)
    except (httpx.HTTPError, RuntimeError, ValueError) as error:
        parser.exit(2, f"Не удалось запустить оценку: {type(error).__name__}\n")

    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)
    raise SystemExit(0 if report["summary"]["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
