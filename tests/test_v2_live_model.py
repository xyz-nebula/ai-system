"""Opt-in live regression; never contact the shared model during ordinary pytest."""

import asyncio
import os
from pathlib import Path

import httpx
import pytest

from arena_ai.qwen import QwenSettings
from arena_ai.v2.contracts import TurnRequest
from arena_ai.v2.live_eval import evaluate_decision, evaluate_validator


@pytest.mark.skipif(
    os.environ.get("ARENA_RUN_LIVE_V2") != "1",
    reason="Requires explicit ARENA_RUN_LIVE_V2=1 and a synthetic live model endpoint",
)
def test_live_commitment_only_turn_records_partial_not_full_agreement():
    base = TurnRequest.model_validate_json(
        (
            Path(__file__).resolve().parents[1] / "docs/api/v2/examples/supply-turn.request.json"
        ).read_bytes()
    )
    settings = QwenSettings.from_env()

    async def run():
        async with httpx.AsyncClient(
            timeout=settings.timeout_seconds, verify=settings.tls_verify
        ) as http:
            return await evaluate_decision(http, settings, base, kind="partial_agreement")

    report = asyncio.run(run())
    assert report["passed"], report
    assert report["stage"] == "partial_agreement"


@pytest.mark.skipif(
    os.environ.get("ARENA_RUN_LIVE_V2") != "1", reason="Requires explicit live model opt-in"
)
def test_live_paraphrased_old_commitment_cannot_earn_another_concession():
    base = TurnRequest.model_validate_json(
        (
            Path(__file__).resolve().parents[1] / "docs/api/v2/examples/supply-turn.request.json"
        ).read_bytes()
    )
    settings = QwenSettings.from_env()

    async def run():
        async with httpx.AsyncClient(
            timeout=settings.timeout_seconds, verify=settings.tls_verify
        ) as http:
            return await evaluate_validator(http, settings, base, scenario_names={"repeat"})

    report = asyncio.run(run())
    assert report["passed"], report
