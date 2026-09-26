"""Small Validator probe, not end-to-end acceptance or an expert NLP evaluation."""

import argparse
import asyncio
import json
from pathlib import Path

import httpx

from arena_ai.qwen import QwenSettings
from arena_ai.v2.contracts import TranscriptEntry, TurnRequest
from arena_ai.v2.offers import OpponentOffer, PositionTransition
from arena_ai.v2.turn import QwenTurnPipeline
from arena_ai.v2.validator import OfferValidationError, QwenOfferValidator

SCENARIOS = (
    ("direct", "Я обязуюсь обеспечить объём заказа.", True),
    ("negation", "Я не обязуюсь обеспечить объём заказа.", False),
    ("conditional", "Если потом согласуем бюджет, я обязуюсь обеспечить объём заказа.", False),
    (
        "quotation",
        "Коллега сказал: «Я обязуюсь обеспечить объём заказа». Это не моё обещание.",
        False,
    ),
    ("pressure", "Снижай цену, иначе я переведу клиентов конкурентам.", False),
    ("repeat", "Я обязуюсь обеспечить объём заказа.", False),
    ("unstructured-offer", "Какие условия вы предлагаете?", False),
)


async def evaluate_turn(
    http: httpx.AsyncClient,
    settings: QwenSettings,
    request: TurnRequest,
) -> dict[str, object]:
    """One expected-accepted negotiating turn, not a complete session or HTTP API test."""
    before = request.snapshot.model_dump_json()
    response = await QwenTurnPipeline(http, settings).turn(request)
    changed = response.snapshot.model_dump_json() != before
    return {
        "scope": "v2-negotiating-turn-probe",
        "model": settings.model,
        "case_id": request.case.id,
        "status": response.status,
        "error_code": response.error_code,
        "snapshot_changed": changed,
        "passed": response.status == "accepted"
        and changed
        and response.snapshot.revision == request.snapshot.revision + 1,
    }


async def evaluate_validator(
    http: httpx.AsyncClient, settings: QwenSettings, base: TurnRequest
) -> dict[str, object]:
    """Use the authored supply example; output no transcript or private/model text."""
    if base.case.id != "demo-supply-v2":
        raise ValueError("This probe requires the authored supply example")
    validator = QwenOfferValidator.from_settings(http, settings)
    target = base.case.opponent_strategy.steps[1]
    offer = OpponentOffer(
        text=(
            "Предлагаю цену 4800 рублей за единицу и поставку за 12 дней. "
            "Вы оплачиваете товар по этой цене, я поставляю его в указанный срок."
        ),
        terms=target.terms.model_copy(deep=True),
        position_transition=PositionTransition(
            to_step_id=target.id,
            requirement_ids=[item.id for item in target.requires],
        ),
    )
    results = []
    for name, text, should_accept in SCENARIOS:
        data = base.model_dump(mode="python")
        data["user_text"] = text
        if name == "repeat":
            data["snapshot"]["revision"] = 1
            data["snapshot"]["state"]["turn_count"] = 1
            data["snapshot"]["transcript"] = [
                TranscriptEntry(
                    message_id="prior-user",
                    turn_id="prior-turn",
                    speaker="player",
                    status="accepted",
                    text="Я гарантирую согласованный объём закупки.",
                    created_at="2026-09-26T10:00:05Z",
                    elapsed_ms=5000,
                    blocked_reason=None,
                ).model_dump(mode="python"),
                TranscriptEntry(
                    message_id="prior-opponent",
                    turn_id="prior-turn",
                    speaker="opponent",
                    status="accepted",
                    text="Продолжим обсуждать условия поставки.",
                    created_at="2026-09-26T10:00:06Z",
                    elapsed_ms=6000,
                    blocked_reason=None,
                ).model_dump(mode="python"),
            ]
        turn = TurnRequest.model_validate(data)
        candidate = offer
        if name == "unstructured-offer":
            candidate = OpponentOffer(
                text="Предлагаю цену 1 рубль за единицу и поставку за 1 день.",
                terms=None,
                position_transition=None,
            )
        try:
            assessment = await validator.assess(turn, candidate)
            decision = assessment.decision
            passed = decision == "accept" if should_accept else decision in ("reject", "uncertain")
        except OfferValidationError:
            decision, passed = "model_error", False
        results.append({"scenario": name, "decision": decision, "passed": passed})
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    return {
        "scope": "v2-validator-supply-probe",
        "model": settings.model,
        "results": results,
        "passed": all(item["passed"] for item in results),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path, help="supply-turn.request.json")
    parser.add_argument("--mode", choices=("validator", "turn"), default="validator")
    args = parser.parse_args()
    request = TurnRequest.model_validate_json(args.request.read_bytes())
    settings = QwenSettings.from_env()

    async def run():
        async with httpx.AsyncClient(
            timeout=settings.timeout_seconds,
            verify=settings.tls_verify,
        ) as http:
            evaluator = evaluate_validator if args.mode == "validator" else evaluate_turn
            return await evaluator(http, settings, request)

    report = asyncio.run(run())
    print(json.dumps(report, ensure_ascii=False))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
