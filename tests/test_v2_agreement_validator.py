import asyncio
import json

import httpx
from test_v2_agreements import agreed_turn
from test_v2_turn import settings

from arena_ai.v2.offers import OfferAssessment, OpponentOffer


def test_agreement_validator_checks_each_role_commitment_through_http() -> None:
    from arena_ai.v2.agreement_validator import QwenAgreementValidator

    turn = agreed_turn()
    offer = OpponentOffer.model_validate(
        {
            "text": "Согласен. Поставлю товар за 14 дней, вы оплачиваете по 5000 рублей за единицу.",
            "terms": turn.case.opponent_strategy.steps[0].terms.model_dump(mode="python"),
            "position_transition": None,
            "resolution": {"kind": "agreement"},
        }
    )
    before = turn.model_dump_json()

    def gateway(request: httpx.Request) -> httpx.Response:
        context = json.loads(json.loads(request.content)["messages"][1]["content"])
        assert "preparation" not in context
        assert "opponent_strategy" not in context
        assert "player_brief" not in context
        assert context["terms"]["values"][0]["value"] == 5000
        assert context["commitment_catalogue"][0]["speaker"] == "opponent"
        assert context["commitment_catalogue"][0]["commitment_index"] == 0
        assert context["commitment_catalogue"][1]["speaker"] == "player"
        player, opponent = context["current_player"], context["current_opponent"]
        content = {
            "decision": "accept",
            "player_acceptance": player,
            "opponent_acceptance": opponent,
            "commitment_proofs": [
                {"commitment_index": 0, "evidence": opponent},
                {"commitment_index": 1, "evidence": player},
            ],
            "rule_proofs": [{"rule_id": "explicit-player-commitment", "evidence": player}],
        }
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
            return await QwenAgreementValidator(http, settings()).assess(
                turn,
                offer,
                OfferAssessment(
                    decision="accept",
                    terms_match_text=True,
                    concession_proofs=[],
                ),
            )

    assert asyncio.run(run()).decision == "accept"
    assert turn.model_dump_json() == before
