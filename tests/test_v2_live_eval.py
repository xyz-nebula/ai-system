import asyncio

import httpx
from test_v2_turn import request, settings

from arena_ai.v2.live_eval import evaluate_validator


def test_live_probe_does_not_count_model_errors_as_successful_rejections(capsys) -> None:
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(503, text="private-gateway-error"),
            )
        ) as http:
            return await evaluate_validator(http, settings(), request())

    report = asyncio.run(run())
    assert report["passed"] is False
    assert len(report["results"]) == 7
    errors = [item for item in report["results"] if item["decision"] == "model_error"]
    assert {item["scenario"] for item in errors} == {
        "direct",
        "pressure",
        "repeat",
        "unstructured-offer",
    }
    assert all(not item["passed"] for item in errors)
    assert "private-gateway-error" not in capsys.readouterr().out


def test_turn_probe_reports_model_failure_without_changed_snapshot() -> None:
    from arena_ai.v2.live_eval import evaluate_turn

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(503),
            )
        ) as http:
            return await evaluate_turn(http, settings(), request())

    report = asyncio.run(run())
    assert report["passed"] is False
    assert report["status"] == "model_error"
    assert report["snapshot_changed"] is False


def test_agreement_probe_requires_agreed_not_merely_accepted_turn() -> None:
    import json

    from arena_ai.v2.live_eval import evaluate_agreement

    def gateway(request):
        system = json.loads(request.content)["messages"][0]["content"]
        if "[V2_GUARD]" in system:
            content = {"decision": "allow", "reason": None}
        elif "[V2_OPPONENT]" in system:
            content = {
                "text": "Уточним место доставки.",
                "terms": None,
                "position_transition": None,
                "resolution": None,
            }
        else:
            content = {"decision": "accept", "terms_match_text": True, "concession_proofs": []}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(content, ensure_ascii=False),
                        }
                    }
                ]
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as http:
            return await evaluate_agreement(http, settings(), request())

    report = asyncio.run(run())
    assert report["status"] == "accepted"
    assert report["stage"] == "negotiating"
    assert report["passed"] is False


def test_validator_probe_can_target_one_scenario_without_hiding_failure() -> None:
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(503))
        ) as http:
            return await evaluate_validator(http, settings(), request(), scenario_names={"repeat"})

    report = asyncio.run(run())
    assert report["results"] == [{"scenario": "repeat", "decision": "model_error", "passed": False}]
    assert report["passed"] is False
