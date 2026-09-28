"""Small Validator probe, not end-to-end acceptance or an expert NLP evaluation."""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Literal

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
        "stage": response.snapshot.state.stage,
        "passed": response.status == "accepted"
        and changed
        and response.snapshot.revision == request.snapshot.revision + 1,
    }


async def evaluate_agreement(
    http: httpx.AsyncClient,
    settings: QwenSettings,
    base: TurnRequest,
) -> dict[str, object]:
    """One explicit full agreement on the authored supply example, not all outcomes."""
    if base.case.id != "demo-supply-v2":
        raise ValueError("This probe requires the authored supply example")
    data = base.model_dump(mode="python")
    data["user_text"] = (
        "Согласен на цену 5000 рублей за единицу и поставку за 14 дней. "
        "Обязуюсь оплатить товар по цене 5000 рублей за единицу."
    )
    report = await evaluate_turn(http, settings, TurnRequest.model_validate(data))
    report["scope"] = "v2-full-agreement-probe"
    report["passed"] = report["passed"] and report["stage"] == "agreed"
    return report


async def evaluate_decision(
    http: httpx.AsyncClient,
    settings: QwenSettings,
    base: TurnRequest,
    *,
    kind: Literal["partial_agreement", "deferred"],
) -> dict[str, object]:
    """Expected mutual decision on a synthetic case; not finish or expert acceptance."""
    if base.case.id != "demo-supply-v2":
        raise ValueError("This probe requires the authored supply example")
    data = base.model_dump(mode="python")
    data["user_text"] = (
        "Согласен зафиксировать частичную договорённость: я обязуюсь прислать перечень "
        "товаров. Цену и срок пока не согласовали, обсудим их позже."
        if kind == "partial_agreement"
        else "Согласен перенести обсуждение: мне нужно уточнить бюджет. "
        "Я уточню бюджет и вернусь к обсуждению условий. Зафиксируем этот следующий шаг."
    )
    turn = TurnRequest.model_validate(data)
    response = await QwenTurnPipeline(http, settings).turn(turn)
    decision = response.snapshot.state.decision
    return {
        "scope": f"v2-{kind}-probe",
        "model": settings.model,
        "case_id": turn.case.id,
        "status": response.status,
        "error_code": response.error_code,
        "stage": response.snapshot.state.stage,
        "passed": response.status == "accepted"
        and response.snapshot.revision == turn.snapshot.revision + 1
        and response.snapshot.state.stage == kind
        and decision is not None
        and decision.kind == kind
        and response.snapshot.state.agreement is None
        and response.snapshot.round == turn.snapshot.round,
    }


async def evaluate_validator(
    http: httpx.AsyncClient,
    settings: QwenSettings,
    base: TurnRequest,
    *,
    scenario_names: set[str] | None = None,
) -> dict[str, object]:
    """Use the authored supply example; output no transcript or private/model text."""
    if base.case.id != "demo-supply-v2":
        raise ValueError("This probe requires the authored supply example")
    if scenario_names is not None and (
        not scenario_names or not scenario_names <= {name for name, _, _ in SCENARIOS}
    ):
        raise ValueError("Select known nonempty validator scenarios")
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
        if scenario_names is not None and name not in scenario_names:
            continue
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
    parser.add_argument(
        "--mode",
        choices=("validator", "turn", "agreement", "partial_agreement", "deferred"),
        default="validator",
    )
    parser.add_argument("--scenario", choices=[name for name, _, _ in SCENARIOS], action="append")
    args = parser.parse_args()
    if args.scenario and args.mode != "validator":
        parser.error("--scenario is available only for --mode validator")
    request = TurnRequest.model_validate_json(args.request.read_bytes())
    settings = QwenSettings.from_env()

    async def run():
        async with httpx.AsyncClient(
            timeout=settings.timeout_seconds,
            verify=settings.tls_verify,
        ) as http:
            if args.mode == "validator":
                return await evaluate_validator(
                    http,
                    settings,
                    request,
                    scenario_names=set(args.scenario) if args.scenario else None,
                )
            if args.mode in ("partial_agreement", "deferred"):
                return await evaluate_decision(http, settings, request, kind=args.mode)
            evaluator = evaluate_turn if args.mode == "turn" else evaluate_agreement
            return await evaluator(http, settings, request)

    report = asyncio.run(run())
    print(json.dumps(report, ensure_ascii=False))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
