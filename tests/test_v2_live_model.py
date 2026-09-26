"""Opt-in live regression; never contact the shared model during ordinary pytest."""

import asyncio
import os
from pathlib import Path

import httpx
import pytest

from arena_ai.qwen import QwenSettings
from arena_ai.v2.contracts import TurnRequest
from arena_ai.v2.live_eval import evaluate_decision, evaluate_validator
from arena_ai.v2.offers import OpponentOffer, PositionTransition
from arena_ai.v2.validator import QwenOfferValidator


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
def test_live_new_direct_commitment_allows_matching_offer_with_unambiguous_references():
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
            return await evaluate_validator(http, settings, base, scenario_names={"direct"})

    report = asyncio.run(run())
    assert report["passed"], report


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


@pytest.mark.skipif(
    os.environ.get("ARENA_RUN_LIVE_V2") != "1", reason="Requires explicit live model opt-in"
)
def test_live_unambiguous_references_do_not_excuse_mismatching_values():
    base = TurnRequest.model_validate_json(
        (
            Path(__file__).resolve().parents[1] / "docs/api/v2/examples/supply-turn.request.json"
        ).read_bytes()
    )
    data = base.model_dump(mode="python")
    data["user_text"] = "Я обязуюсь обеспечить объём заказа."
    turn = TurnRequest.model_validate(data)
    offer = OpponentOffer(
        text="Предлагаю цену 1 рубль за единицу и поставку за 1 день. Вы оплатите по этой цене, я поставлю в указанный срок.",
        terms=turn.case.opponent_strategy.steps[1].terms,
        position_transition=PositionTransition(
            to_step_id="target", requirement_ids=["order-volume"]
        ),
    )
    settings = QwenSettings.from_env()

    async def run():
        async with httpx.AsyncClient(
            timeout=settings.timeout_seconds, verify=settings.tls_verify
        ) as http:
            return await QwenOfferValidator.from_settings(http, settings).assess(turn, offer)

    assessment = asyncio.run(run())
    assert assessment.decision in ("reject", "uncertain")
