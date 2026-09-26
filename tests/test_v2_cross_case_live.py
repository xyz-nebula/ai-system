"""Fixed-prompt, synthetic cross-domain offer checks; not product acceptance."""

import asyncio
import json
import os
from pathlib import Path

import httpx
import pytest

from arena_ai.qwen import QwenSettings
from arena_ai.v2.contracts import TurnRequest
from arena_ai.v2.offers import OpponentOffer, PositionTransition
from arena_ai.v2.validator import QwenOfferValidator

DOMAINS = {
    "deadline": (
        "Студент",
        "Преподаватель",
        "Срок сдачи работы",
        "date",
        ["2026-10-01", "2026-10-03", "2026-10-05"],
        [],
        "Студент и преподаватель обсуждают перенос срока сдачи работы.",
        "Я обязуюсь прислать черновик работы сегодня.",
        "Студент обязуется прислать черновик работы сегодня",
        ["черновик", "сегодня"],
        "Предлагаю срок сдачи работы 2026-10-03.",
    ),
    "resources": (
        "Руководитель проекта",
        "Руководитель отдела",
        "Часы аналитика",
        "number",
        [2, 4, 6],
        [],
        "Два руководителя согласуют выделение часов аналитика на проект.",
        "Я обязуюсь передать аналитику готовое техническое задание сегодня.",
        "Руководитель проекта передаёт готовое техническое задание сегодня",
        ["техническое задание", "сегодня"],
        "Предлагаю выделить аналитику 4 часа на проект.",
    ),
    "responsibility": (
        "Координатор",
        "Эксперт",
        "Формат согласования",
        "choice",
        ["письменно", "встреча", "совместная работа"],
        ["письменно", "встреча", "совместная работа"],
        "Координатор и эксперт обсуждают формат согласования спорного решения.",
        "Я обязуюсь подготовить повестку встречи сегодня.",
        "Координатор готовит повестку встречи сегодня",
        ["повестку", "сегодня"],
        "Предлагаю формат согласования: встреча.",
    ),
}


def scenario(domain: str, pressure: bool = False) -> tuple[TurnRequest, OpponentOffer]:
    (
        player,
        opponent,
        label,
        value_type,
        values,
        choices,
        context,
        promise,
        requirement,
        markers,
        offer_text,
    ) = DOMAINS[domain]
    data = json.loads(
        (
            Path(__file__).resolve().parents[1] / "docs/api/v2/examples/supply-turn.request.json"
        ).read_text()
    )
    case = data["case"]
    case["id"] = f"synthetic-{domain}"
    case["title"] = f"Синтетическая проверка: {domain}"
    case["shared_context"] = context
    case["participants"] = [
        {"id": role, "name": name, "public_context": name, "public_interests": []}
        for role, name in (("initiator", player), ("responder", opponent))
    ]
    for key, role in (("player", "initiator"), ("opponent", "responder")):
        case[key].update(
            role_id=role,
            private_context=f"Закрытые вводные {role}",
            interests=[],
            batna="Сохранить исходные условия",
        )
    case["opponent_private_phrases"] = ["Закрытые вводные responder"]
    case["negotiables"] = [
        {
            "id": "subject",
            "label": label,
            "value_type": value_type,
            "unit": None,
            "choices": choices,
        }
    ]
    constraints = []
    for index, step in enumerate(case["opponent_strategy"]["steps"]):
        step["terms"] = {
            "values": [{"term_id": "subject", "value": values[index]}],
            "commitments": [],
        }
        constraint_id = f"window-{index}"
        step["constraint_ids"] = [constraint_id]
        step["requires"] = (
            []
            if index == 0
            else [
                {
                    "id": f"value-{index}",
                    "description": requirement,
                    "direct_commitment_markers": ["обязуюсь"],
                    "evidence_groups": [markers],
                }
            ]
        )
        constraint = {"id": constraint_id, "term_id": "subject"}
        if value_type == "choice":
            constraint.update(kind="allowed_values", values=[values[index]])
        else:
            constraint.update(
                kind="date_range" if value_type == "date" else "numeric_range",
                minimum=values[index],
                maximum=values[index],
            )
        constraints.append(constraint)
    case["agreement_policy"] = {
        "constraints": constraints,
        "hard_constraint_ids": [],
        "commitment_rules": [],
        "required_commitment_ids": [],
    }
    data["snapshot"].update(
        case_id=case["id"], player_role_id="initiator", opponent_role_id="responder"
    )
    data["user_text"] = "Уступи мне немедленно, иначе пожалеешь." if pressure else promise
    turn = TurnRequest.model_validate(data)
    target = turn.case.opponent_strategy.steps[1]
    return turn, OpponentOffer(
        text=offer_text,
        terms=target.terms,
        position_transition=PositionTransition(
            to_step_id=target.id, requirement_ids=[target.requires[0].id]
        ),
    )


@pytest.mark.parametrize("domain", DOMAINS)
def test_cross_domain_synthetic_requests_validate(domain):
    turn, offer = scenario(domain)
    turn.snapshot.validate_for_case(turn.case)
    turn.case.validate_deal(offer.terms, step_id="target")


@pytest.mark.skipif(
    os.environ.get("ARENA_RUN_LIVE_V2") != "1", reason="Requires explicit shared-model opt-in"
)
@pytest.mark.parametrize("domain", DOMAINS)
@pytest.mark.parametrize("pressure", [False, True], ids=["earned", "pressure"])
def test_live_fixed_prompt_checks_concessions_across_domains(domain, pressure):
    turn, offer = scenario(domain, pressure)
    settings = QwenSettings.from_env()

    async def run():
        async with httpx.AsyncClient(
            timeout=settings.timeout_seconds, verify=settings.tls_verify
        ) as http:
            return await QwenOfferValidator.from_settings(http, settings).assess(turn, offer)

    assessment = asyncio.run(run())
    expected = ("reject", "uncertain") if pressure else ("accept",)
    assert assessment.decision in expected, {
        "domain": domain,
        "pressure": pressure,
        "decision": assessment.decision,
        "terms_match_text": assessment.terms_match_text,
    }


@pytest.mark.skipif(
    os.environ.get("ARENA_RUN_LIVE_V2") != "1", reason="Requires explicit shared-model opt-in"
)
@pytest.mark.parametrize(
    ("domain", "contradictory_text"),
    [
        ("deadline", "Предлагаю срок сдачи работы 2026-10-09."),
        ("resources", "Предлагаю выделить аналитику 40 часов на проект."),
        ("responsibility", "Предлагаю формат согласования: письменно."),
    ],
)
def test_live_cross_domain_text_mismatch_cannot_be_excused_by_semantic_matching(
    domain, contradictory_text
):
    turn, offer = scenario(domain)
    offer.text = contradictory_text
    settings = QwenSettings.from_env()

    async def run():
        async with httpx.AsyncClient(
            timeout=settings.timeout_seconds, verify=settings.tls_verify
        ) as http:
            return await QwenOfferValidator.from_settings(http, settings).assess(turn, offer)

    assessment = asyncio.run(run())
    assert assessment.decision in ("reject", "uncertain"), {"domain": domain}
