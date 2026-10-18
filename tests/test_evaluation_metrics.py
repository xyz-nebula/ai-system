import json
import logging
from datetime import datetime

import httpx
import pytest
from test_v2_evaluate_http import (
    HEADERS,
    evaluate_body,
    judge_example,
    outcome_example,
    reply_json,
    send_evaluation,
    trainer_example,
    verifier_reply,
)

from arena_ai.metrics_report import main as summarize_measurements

COLLEGES = ("hiring", "negotiation", "ownership")
INVENTED = {"message_index": 7, "is_ai": False, "quote": "Товар уже доставлен."}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def measured(monkeypatch, tmp_path):
    """Measurement file of a soft-validation service, the deployed mode."""
    path = tmp_path / "evaluations.jsonl"
    monkeypatch.setenv("ARENA_METRICS_FILE", str(path))
    monkeypatch.setenv("ARENA_EVALUATE_VALIDATION", "soft")
    return path


def soft_gateway(req):
    messages = json.loads(req.content)["messages"]
    system = messages[0]["content"]
    if "[V2_EVALUATE_OUTCOME]" in system:
        return reply_json(outcome_example())
    if "[V2_EVALUATE_JUDGE]" in system:
        return reply_json(judge_example(json.loads(messages[1]["content"])["college"]))
    if "[V2_EVALUATE_TRAINER]" in system:
        return reply_json(trainer_example())
    return httpx.Response(503)


def measurements(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def slots(path):
    """Slots of the single recorded evaluation, by name."""
    [record] = measurements(path)
    return {slot["slot"]: slot for slot in record["slots"]}


def quotes(exact=0, moved=0, substituted=0, dropped=0):
    return {"exact": exact, "moved": moved, "substituted": substituted, "dropped": dropped}


@pytest.mark.anyio
async def test_evaluation_appends_one_measurement_without_dialogue_text(monkeypatch, measured):
    response = await send_evaluation(monkeypatch, soft_gateway)

    assert response.status_code == 200
    [record] = measurements(measured)
    assert record["event"] == "evaluation"
    assert datetime.fromisoformat(record["recorded_at"]).tzinfo is not None
    assert record["duration_ms"] >= 0
    assert (record["validation"], record["model"]) == ("soft", "qwen")
    assert (record["messages"], record["user_messages"], record["preparation"]) == (2, 1, True)
    recorded = slots(measured)
    assert list(recorded) == ["outcome", *COLLEGES, "trainer"]
    assert all(
        slot["status"] == "ready" and slot["error_code"] is None for slot in recorded.values()
    )
    assert recorded["outcome"]["kind"] == "agreement"
    assert [
        (recorded[name]["choice"], recorded[name]["decisive_criterion"]) for name in COLLEGES
    ] == [
        ("user", "Надёжность"),
        ("user", "Движение к цели"),
        ("user", "Качество решений"),
    ]
    trainer = recorded["trainer"]
    assert (trainer["strengths"], trainer["mistakes"], trainer["missed_opportunities"]) == (1, 0, 0)
    assert (trainer["next_try"], trainer["goal_status"]) == (2, "achieved")
    written = measured.read_text(encoding="utf-8")
    body = evaluate_body()
    for text in (
        body["role"],
        body["opponent_role"],
        body["case_description"],
        body["preparations"],
        *(message["text"] for message in body["messages"]),
    ):
        assert text not in written


def with_usage(response, prompt_tokens, completion_tokens):
    payload = response.json()
    payload["usage"] = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
    return httpx.Response(200, json=payload)


@pytest.mark.anyio
async def test_each_slot_counts_its_own_model_calls_and_tokens(monkeypatch, measured):
    usage = {"outcome": (100, 10), "hiring": (200, 20), "negotiation": (210, 21)}

    def gateway(req):
        messages = json.loads(req.content)["messages"]
        context = json.loads(messages[1]["content"])
        name = (
            "outcome"
            if "[V2_EVALUATE_OUTCOME]" in messages[0]["content"]
            else context.get("college")
        )
        response = soft_gateway(req)
        # ownership and trainer replies carry no usage, like a gateway that omits it
        return with_usage(response, *usage[name]) if name in usage else response

    await send_evaluation(monkeypatch, gateway)

    counted = {
        name: (
            slot["model_calls"],
            slot["input_tokens"],
            slot["output_tokens"],
            slot["calls_without_usage"],
        )
        for name, slot in slots(measured).items()
    }
    assert counted == {
        "outcome": (1, 100, 10, 0),
        "hiring": (1, 200, 20, 0),
        "negotiation": (1, 210, 21, 0),
        "ownership": (1, None, None, 1),
        "trainer": (1, None, None, 1),
    }


@pytest.mark.anyio
async def test_soft_redraft_after_unparseable_reply_is_counted_in_its_slot(monkeypatch, measured):
    drafts = []

    def gateway(req):
        system = json.loads(req.content)["messages"][0]["content"]
        if "[V2_EVALUATE_TRAINER]" in system and not drafts:
            drafts.append(system)
            return httpx.Response(200, json={"choices": [{"message": {"content": "не JSON"}}]})
        return soft_gateway(req)

    await send_evaluation(monkeypatch, gateway)

    recorded = slots(measured)
    assert (recorded["trainer"]["status"], recorded["trainer"]["model_calls"]) == ("ready", 2)
    assert [slot["redrafts"] for slot in recorded.values()] == [0, 0, 0, 0, 1]


@pytest.mark.anyio
async def test_soft_quote_repairs_are_counted_per_slot(monkeypatch, measured):
    exact_user, exact_ai = outcome_example()["evidence"]
    moved = {**exact_ai, "quote": exact_user["quote"]}

    def gateway(req):
        system = json.loads(req.content)["messages"][0]["content"]
        if "[V2_EVALUATE_OUTCOME]" in system:
            return reply_json({**outcome_example(), "evidence": [exact_user, moved, INVENTED]})
        if "[V2_EVALUATE_TRAINER]" in system:
            feedback = trainer_example()
            # Praise for the AI's message is not the user's action and gets dropped.
            feedback["strengths"].append({**feedback["strengths"][0], "evidence": exact_ai})
            return reply_json(feedback)
        return soft_gateway(req)

    await send_evaluation(monkeypatch, gateway)

    assert {name: slot["quotes"] for name, slot in slots(measured).items()} == {
        "outcome": quotes(exact=1, moved=1, substituted=1),
        "hiring": quotes(exact=1),
        "negotiation": quotes(exact=1),
        "ownership": quotes(exact=1),
        # one strength, the dropped AI strength, one plan item and two goal quotes
        "trainer": quotes(exact=5, dropped=1),
    }


@pytest.mark.anyio
async def test_soft_judge_counts_only_quotes_its_verdict_publishes(monkeypatch, measured):
    exact_user, exact_ai = outcome_example()["evidence"]

    def gateway(req):
        messages = json.loads(req.content)["messages"]
        if "[V2_EVALUATE_JUDGE]" in messages[0]["content"]:
            return reply_json(
                {
                    **judge_example(json.loads(messages[1]["content"])["college"]),
                    "evidence": exact_user,
                    # Not a reply to the episode: the verdict quotes the real next reply instead.
                    "effect_evidence": exact_user,
                    "player_evidence": exact_user,
                    "opponent_evidence": exact_ai,
                    # Superseded by the two comparison quotes above and never published.
                    "comparison_evidence": [INVENTED, INVENTED],
                }
            )
        return soft_gateway(req)

    await send_evaluation(monkeypatch, gateway)

    recorded = slots(measured)
    assert [recorded[name]["quotes"] for name in COLLEGES] == [quotes(exact=3)] * 3


@pytest.mark.anyio
async def test_strict_redraft_counts_checker_calls_and_only_the_accepted_draft_quotes(
    monkeypatch, measured
):
    monkeypatch.setenv("ARENA_EVALUATE_VALIDATION", "strict")
    unspoken = {**INVENTED, "message_index": 0}

    def gateway(req):
        messages = json.loads(req.content)["messages"]
        system = messages[0]["content"]
        if "VERIFY]" in system or "[V2_EVALUATE_COMMENT_GROUNDING]" in system:
            return reply_json(verifier_reply(system))
        if "[V2_EVALUATE_JUDGE]" in system:
            college = json.loads(messages[1]["content"])["college"]
            first = "[V2_EVALUATE_JUDGE_REVISION]" not in system
            return reply_json(
                {
                    **judge_example(college),
                    # The first draft cites a line nobody said and is rejected by code.
                    "evidence": unspoken if first else judge_example(college)["evidence"],
                    "comparison_evidence": outcome_example()["evidence"],
                }
            )
        return soft_gateway(req)

    await send_evaluation(monkeypatch, gateway)

    recorded = slots(measured)
    assert (recorded["outcome"]["model_calls"], recorded["outcome"]["redrafts"]) == (2, 0)
    for name in COLLEGES:
        judged = recorded[name]
        assert judged["status"] == "ready"
        # first draft, redraft, comment grounding and judge verification
        assert (judged["model_calls"], judged["redrafts"]) == (4, 1)
        assert judged["quotes"] == quotes(exact=3)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("headers", "body", "status"),
    [
        ({**HEADERS, "Authorization": "Bearer wrong"}, None, 401),
        ({"Authorization": HEADERS["Authorization"]}, None, 409),
        (HEADERS, {**evaluate_body(), "messages": "нет"}, 422),
    ],
)
async def test_rejected_requests_are_not_measured(monkeypatch, measured, headers, body, status):
    response = await send_evaluation(monkeypatch, soft_gateway, body=body, headers=headers)

    assert response.status_code == status
    assert not measured.exists()


@pytest.mark.anyio
async def test_unwritable_measurement_file_never_breaks_the_evaluation(
    monkeypatch, measured, caplog
):
    monkeypatch.setenv("ARENA_METRICS_FILE", str(measured.parent / "missing" / measured.name))

    with caplog.at_level(logging.WARNING):
        response = await send_evaluation(monkeypatch, soft_gateway)

    assert response.status_code == 200
    assert response.json()["outcome"]["status"] == "ready"
    assert "evaluation_measurement_unwritten" in caplog.text


@pytest.mark.anyio
async def test_measurement_is_off_without_a_file_setting(monkeypatch, measured):
    monkeypatch.delenv("ARENA_METRICS_FILE")
    monkeypatch.chdir(measured.parent)

    response = await send_evaluation(monkeypatch, soft_gateway)

    assert response.status_code == 200
    assert list(measured.parent.iterdir()) == []


@pytest.mark.anyio
async def test_summary_reads_what_the_service_records(monkeypatch, measured, capsys):
    for _ in range(2):
        await send_evaluation(monkeypatch, soft_gateway)

    summarize_measurements([])
    summary = json.loads(capsys.readouterr().out)

    assert (summary["evaluations"], summary["skipped_lines"]) == (2, 0)
    assert {slot["ready_share"] for slot in summary["slots"].values()} == {1.0}
    assert summary["judges"]["ai_choice_share"] == 0.0
    assert summary["outcomes"] == {"agreement": 2}
    # The example gateway reports no usage, so token figures are flagged incomplete.
    assert summary["tokens_per_evaluation"]["complete"] is False
