"""Check the public API; optionally generate a minimal duel without recording its text."""

import argparse
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import httpx

from arena_ai.cli_args import positive_timeout
from arena_ai.contracts import FinishResponse, TurnResponse
from arena_ai.scenarios import NEXT_DAY_CASE, NEXT_DAY_STRONG_PREPARATION, NEXT_DAY_STRONG_TURNS


def check_live_duel(client: httpx.Client, headers: dict[str, str]) -> tuple[dict, dict[str, bool]]:
    checks = dict.fromkeys(
        (
            "live_turn_accepted",
            "live_snapshot_advanced",
            "live_finish_received",
            "three_judges_ready",
            "trainer_ready",
        ),
        False,
    )
    session_id, turn_id = str(uuid4()), str(uuid4())
    case = NEXT_DAY_CASE.model_dump(mode="json")
    print("live_turn_started", file=sys.stderr, flush=True)
    response = client.post(
        "/v1/turn",
        headers=headers,
        json={
            "case": case,
            "snapshot": {
                "session_id": session_id,
                "state": {"turn_count": 0},
                "transcript": [],
            },
            "turn_id": turn_id,
            "user_text": NEXT_DAY_STRONG_TURNS[0],
        },
    )
    response.raise_for_status()
    turn = TurnResponse.model_validate(response.json())
    summary = {
        "turn_status": turn.status,
        "turn_error": turn.error_code,
        "judge_slots": {},
        "judge_errors": {},
        "trainer": None,
        "trainer_error": None,
    }
    checks["live_turn_accepted"] = turn.status == "accepted"
    checks["live_snapshot_advanced"] = (
        turn.session_id == session_id
        and turn.turn_id == turn_id
        and turn.snapshot.session_id == session_id
        and turn.snapshot.state.turn_count == 1
        and len(turn.snapshot.transcript) == 2
    )
    if not checks["live_turn_accepted"] or not checks["live_snapshot_advanced"]:
        return summary, checks
    print("live_finish_started", file=sys.stderr, flush=True)
    response = client.post(
        "/v1/finish",
        headers=headers,
        json={
            "case": case,
            "snapshot": turn.snapshot.model_dump(mode="json"),
            "preparation": NEXT_DAY_STRONG_PREPARATION.model_dump(mode="json"),
        },
    )
    response.raise_for_status()
    finish = FinishResponse.model_validate(response.json())
    summary["judge_slots"] = {slot.college: slot.status for slot in finish.judge_verdicts}
    summary["judge_errors"] = {
        slot.college: slot.error_code
        for slot in finish.judge_verdicts
        if slot.error_code is not None
    }
    summary["trainer"] = finish.trainer_feedback.status
    summary["trainer_error"] = finish.trainer_feedback.error_code
    checks["live_finish_received"] = finish.session_id == session_id
    checks["three_judges_ready"] = summary["judge_slots"] == {
        "hiring": "ready",
        "negotiation": "ready",
        "ownership": "ready",
    }
    checks["trainer_ready"] = finish.trainer_feedback.status == "ready"
    return summary, checks


def main() -> None:
    parser = argparse.ArgumentParser(description="Безопасный smoke серверного AI API")
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--timeout", type=positive_timeout, default=15.0)
    parser.add_argument("--live-duel", action="store_true", help="Один настоящий ход и finish")
    args = parser.parse_args()
    token = os.environ.get("ARENA_SERVICE_TOKEN")
    if not token:
        print(json.dumps({"status": "failed", "error": "service_token_required"}))
        raise SystemExit(2)
    checks = dict.fromkeys(
        (
            "process_live",
            "model_ready",
            "service_info",
            "openapi_matches",
            "turn_requires_token",
            "finish_requires_token",
            "turn_validates_request",
            "finish_requires_accepted_turn",
        ),
        False,
    )
    headers = {"Authorization": f"Bearer {token}"}
    report: dict[str, object] = {"checks": checks}
    try:
        schema = json.loads(
            (Path(__file__).resolve().parents[1] / "docs/api/openapi.json").read_text()
        )
        with httpx.Client(base_url=args.api_url, timeout=args.timeout) as client:
            live = client.get("/health/live")
            checks["process_live"] = live.status_code == 200 and live.json() == {"status": "alive"}
            ready = client.get("/health/ready")
            checks["model_ready"] = (
                ready.status_code == 200 and ready.json().get("status") == "ready"
            )
            info = client.get("/v1/info")
            checks["service_info"] = info.status_code == 200 and info.json().get("mode") == "qwen"
            api = client.get("/openapi.json")
            checks["openapi_matches"] = api.status_code == 200 and api.json() == schema
            for role in ("turn", "finish"):
                checks[f"{role}_requires_token"] = (
                    client.post(f"/v1/{role}", json={}).status_code == 401
                )
            checks["turn_validates_request"] = (
                client.post("/v1/turn", json={}, headers=headers).status_code == 422
            )
            empty_finish = {
                "case": NEXT_DAY_CASE.model_dump(mode="json"),
                "snapshot": {
                    "session_id": "deployment-smoke",
                    "state": {"turn_count": 0},
                    "transcript": [],
                },
            }
            checks["finish_requires_accepted_turn"] = (
                client.post("/v1/finish", json=empty_finish, headers=headers).status_code == 409
            )
            if args.live_duel and all(checks.values()):
                live_summary, live_checks = check_live_duel(client, headers)
                report["live_duel"] = live_summary
                checks.update(live_checks)
    except (httpx.HTTPError, ValueError, OSError):
        # Never print provider responses, URLs with credentials or request bodies.
        report.update(status="failed", error="probe_unavailable")
        print(json.dumps(report))
        raise SystemExit(2) from None
    passed = all(checks.values())
    report["status"] = "passed" if passed else "failed"
    print(json.dumps(report))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
