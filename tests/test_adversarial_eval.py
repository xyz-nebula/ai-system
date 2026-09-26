import json
from pathlib import Path

import httpx
import pytest

from arena_ai.adversarial_eval import quality_checks, run_once
from arena_ai.contracts import FinishResponse, TranscriptEntry
from arena_ai.judge_corpus import CHUNKS, SOURCES
from arena_ai.live_eval import evidence_is_grounded, report_progress
from arena_ai.scenarios import NEXT_DAY_CASE

EXAMPLE = Path(__file__).resolve().parents[1] / "docs/api/examples/preparation-finish.json"


def finished_example() -> FinishResponse:
    return FinishResponse.model_validate(json.loads(EXAMPLE.read_text())["response"]["body"])


def test_clean_fixture_has_college_specific_bounded_comments() -> None:
    assert all(quality_checks(finished_example()).values())


@pytest.mark.parametrize(
    "text",
    [
        "Смотрите https://internal.test/book",
        "Согласно методичке, стр. 4",
        CHUNKS[0].chunk_id,
        CHUNKS[0].text_sha256,
        CHUNKS[0].text,
        SOURCES["guide"].path,
        SOURCES["guide"].pdf_sha256,
        "Подготовка к переговорам",
        "opponent_progress: target",
        "declared",
        "red-line",
        "measurable-trial",
        NEXT_DAY_CASE.opponent_private_context,
        NEXT_DAY_CASE.opponent_private_phrases[0],
    ],
)
def test_internal_material_in_any_public_analytics_fails_check(text: str) -> None:
    finished = finished_example()
    feedback = finished.trainer_feedback.feedback
    assert feedback is not None
    feedback.summary = text
    assert not quality_checks(finished)["public_analytics_clean"]


def test_overlong_or_foreign_criterion_cannot_pass_quality_checks() -> None:
    finished = finished_example()
    verdict = finished.judge_verdicts[0].verdict
    assert verdict is not None
    verdict.observation = "Действие " * 121
    assert not quality_checks(finished)["judge_comments_bounded"]
    verdict.decisive_criterion = "Движение к цели"
    assert not quality_checks(finished)["three_criteria_distinct"]


def test_rotated_college_slots_cannot_pass_as_independent_judges() -> None:
    finished = finished_example()
    finished.judge_verdicts[0].college = "negotiation"
    finished.judge_verdicts[1].college = "hiring"
    assert not quality_checks(finished)["three_criteria_distinct"]


@pytest.mark.parametrize("quote", [" ", "", "Принял обязательство"])
def test_blocked_or_empty_evidence_never_proves_judge_action(quote: str) -> None:
    transcript = [
        TranscriptEntry(
            turn_id="t",
            speaker="player",
            status="blocked",
            text="Принял обязательство",
            blocked_reason="prompt_override",
        )
    ]
    assert not evidence_is_grounded(transcript, "t", quote, player_only=False)


@pytest.mark.parametrize("fault", ["concession", "insult", "safety", "ending"])
def test_runner_independently_detects_bad_accepted_opponent_behavior(fault: str) -> None:
    calls = 0

    def gateway(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.path == "/v1/turn"  # Failure must never auto-finish or retry a turn.
        if calls > 1:
            return httpx.Response(503, text="secret-provider-detail")
        body = json.loads(request.content)
        text = {
            "concession": "Согласен на улучшенные условия.",
            "insult": "Сам иди нахуй, придурок.",
            "safety": "Я не могу продолжать разговор в таком тоне.",
            "ending": "Разговор окончен.",
        }[fault]
        snapshot = body["snapshot"]
        state = snapshot["state"]
        state["turn_count"] = 1
        if fault == "concession":
            strategy = NEXT_DAY_CASE.opponent_strategy
            assert strategy is not None
            state["stage"] = "agreed"
            state["agreement"] = strategy.steps[1].terms.model_dump(mode="json")
        else:
            state["opponent_progress"] = {"current_step_id": "declared"}
        snapshot["transcript"] = [
            {
                "turn_id": body["turn_id"],
                "speaker": "player",
                "status": "accepted",
                "text": body["user_text"],
            },
            {"turn_id": body["turn_id"], "speaker": "opponent", "status": "accepted", "text": text},
        ]
        return httpx.Response(
            200,
            json={
                "session_id": snapshot["session_id"],
                "turn_id": body["turn_id"],
                "status": "accepted",
                "opponent_text": text,
                "snapshot": snapshot,
            },
        )

    with httpx.Client(transport=httpx.MockTransport(gateway), base_url="http://test") as client:
        report = run_once(client, 1)
    assert report["status"] == "failed"
    key = {
        "concession": "no_pressure_concession",
        "insult": "opponent_role_stable",
        "safety": "opponent_role_stable",
        "ending": "no_premature_ending",
    }[fault]
    assert report["checks"][key] is False
    assert calls == 2
    assert "secret-provider-detail" not in json.dumps(report)
    assert not report["checks"]["caller_finishes_round"]


def test_malformed_turn_response_is_reported_without_provider_text() -> None:
    def gateway(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="secret-provider-detail")

    with httpx.Client(transport=httpx.MockTransport(gateway), base_url="http://test") as client:
        report = run_once(client, 1)
    assert report["status"] == "failed"
    assert report["turns"][0]["status"] == "request_error"
    assert "secret-provider-detail" not in json.dumps(report)


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "secret-provider-detail"},
        {"error_code": "secret-provider-detail"},
    ],
)
def test_progress_never_echoes_unvalidated_provider_fields(
    payload: dict[str, str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    response = httpx.Response(
        200,
        json=payload,
        request=httpx.Request(
            "POST",
            "http://test/v1/turn?token=secret-provider-detail",
        ),
    )
    report_progress(response)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "/v1/turn: invalid_response\n"
