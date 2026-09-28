from copy import deepcopy
from typing import cast

import httpx
import pytest

from arena_ai.app import create_app
from arena_ai.contracts import JudgeContext

FINISH_PAYLOAD = {
    "case": {
        "id": "next-day",
        "title": "На следующий день...",
        "shared_context": "Менеджер обсуждает повышение с директором.",
        "player_role": "Менеджер",
        "opponent_role": "Генеральный директор",
        "player_private_context": "manager-only-marker",
        "opponent_private_context": "director-only-marker",
    },
    "snapshot": {
        "session_id": "judged-duel",
        "state": {
            "turn_count": 1,
            "opponent_progress": {
                "current_step_id": "private-target-step",
                "satisfied_requirement_ids": ["private-requirement"],
                "last_transition": {
                    "from_step_id": "private-declared-step",
                    "to_step_id": "private-target-step",
                    "requirement_ids": ["private-requirement"],
                    "evidence_turn_id": "turn-1",
                    "evidence_quote": "Готов компенсировать пропуск и обсудить KPI.",
                },
            },
        },
        "transcript": [
            {
                "turn_id": "turn-1",
                "speaker": "player",
                "status": "accepted",
                "text": "Готов компенсировать пропуск и обсудить KPI.",
            },
            {
                "turn_id": "turn-1",
                "speaker": "opponent",
                "status": "accepted",
                "text": "Что вы предлагаете?",
            },
        ],
    },
}


class RecordingJudge:
    def __init__(self) -> None:
        self.contexts: list[JudgeContext] = []

    async def verdict(self, context: JudgeContext) -> object:
        self.contexts.append(context)
        assert "manager-only-marker" not in repr(context)
        assert "director-only-marker" not in repr(context)
        assert "private-target-step" not in repr(context)
        assert "private-requirement" not in repr(context)
        by_college = {
            "hiring": (
                "opponent",
                "Надёжность",
                "Менеджер признал пропуск и предложил компенсацию.",
                "Обязательство осталось без срока и способа проверки.",
                "Директор запросил условия, а менеджер пока не сделал обещание проверяемым.",
            ),
            "negotiation": (
                "player",
                "Движение к цели",
                "Менеджер перевёл разговор от пропуска к обсуждению KPI.",
                "Появилась тема измеримых условий повышения.",
                "Менеджер продвинул свою цель; директор только запросил предложение.",
            ),
            "ownership": (
                "opponent",
                "Управление рисками",
                "Менеджер предложил компенсировать пропуск, но не назвал контроль.",
                "Риск повторного срыва остаётся без проверяемой меры.",
                "Директор запросил условия, а менеджер не предложил способ снизить риск.",
            ),
        }
        choice, criterion, observation, effect, comparison = by_college[context.college]
        return {
            "college": context.college,
            "choice": choice,
            "decisive_criterion": criterion,
            "evidence_turn_id": "turn-1",
            "evidence_quote": "Готов компенсировать пропуск",
            "observation": observation,
            "effect": effect,
            "comparison": comparison,
        }


class PartiallyFailingJudge(RecordingJudge):
    async def verdict(self, context: JudgeContext) -> object:
        if context.college == "hiring":
            self.contexts.append(context)
            raise RuntimeError("judge failed")
        return await super().verdict(context)


class InvalidJudge:
    def __init__(self, override: dict[str, object]) -> None:
        self.override = override
        self.attempts: dict[str, int] = {}

    async def verdict(self, context: JudgeContext) -> object:
        self.attempts[context.college] = self.attempts.get(context.college, 0) + 1
        return {
            "college": context.college,
            "choice": "player",
            "decisive_criterion": {
                "hiring": "Надёжность",
                "negotiation": "Движение к цели",
                "ownership": "Управление рисками",
            }[context.college],
            "evidence_turn_id": "turn-1",
            "evidence_quote": "Готов компенсировать пропуск",
            "observation": "Менеджер предложил компенсировать рабочий пропуск.",
            "effect": "Это открыло обсуждение конкретных условий.",
            "comparison": "Менеджер предложил действие, а директор лишь запросил условия.",
            **self.override,
        }


class BlockedAwareJudge(RecordingJudge):
    async def verdict(self, context: JudgeContext) -> object:
        assert "attack-marker" not in repr(context)
        return await super().verdict(context)


class RecoveringJudge(RecordingJudge):
    def __init__(self) -> None:
        super().__init__()
        self.attempts: dict[str, int] = {}

    async def verdict(self, context: JudgeContext) -> object:
        attempt = self.attempts.get(context.college, 0) + 1
        self.attempts[context.college] = attempt
        if attempt == 1:
            return {"unexpected": True}
        return await super().verdict(context)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_three_judges_receive_isolated_rubrics_and_public_case_view() -> None:
    judge = RecordingJudge()
    app = create_app(judge=judge)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/v1/finish", json=FINISH_PAYLOAD)

    assert response.status_code == 200
    result = response.json()
    assert result["outcome"]["kind"] == "no_agreement"
    assert len(result["judge_verdicts"]) == 3
    assert {slot["college"] for slot in result["judge_verdicts"]} == {
        "hiring",
        "negotiation",
        "ownership",
    }
    assert all(slot["status"] == "ready" for slot in result["judge_verdicts"])
    assert [slot["verdict"]["choice"] for slot in result["judge_verdicts"]] == [
        "opponent",
        "player",
        "opponent",
    ]
    assert len({slot["verdict"]["decisive_criterion"] for slot in result["judge_verdicts"]}) == 3
    for slot in result["judge_verdicts"]:
        verdict = slot["verdict"]
        assert verdict["evidence_turn_id"] == "turn-1"
        assert verdict["evidence_quote"] == "Готов компенсировать пропуск"
        assert (
            len(
                " ".join(
                    str(value)
                    for value in (
                        verdict["decisive_criterion"],
                        verdict["evidence_quote"],
                        verdict["observation"],
                        verdict["effect"],
                        verdict["comparison"],
                    )
                ).split()
            )
            <= 120
        )
        assert "методич" not in str(verdict).lower()
    assert len(judge.contexts) == 3
    assert len({context.rubric for context in judge.contexts}) == 3
    assert len({repr(context.transcript) for context in judge.contexts}) == 1


@pytest.mark.anyio
async def test_each_judge_recovers_independently_from_one_invalid_result() -> None:
    judge = RecoveringJudge()
    app = create_app(judge=judge, model_attempts=2)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/v1/finish", json=FINISH_PAYLOAD)

    assert response.status_code == 200
    assert all(slot["status"] == "ready" for slot in response.json()["judge_verdicts"])
    assert judge.attempts == {"hiring": 2, "negotiation": 2, "ownership": 2}


@pytest.mark.anyio
async def test_preparation_is_not_shared_with_judges() -> None:
    payload = cast(dict[str, object], deepcopy(FINISH_PAYLOAD))
    payload["preparation"] = {
        "strategic_goal": "private-preparation-marker",
        "arguments": ["Обсудить измеримые условия повышения."],
    }
    judge = RecordingJudge()
    app = create_app(judge=judge)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/v1/finish", json=payload)

    assert response.status_code == 200
    assert len(judge.contexts) == 3
    assert all("private-preparation-marker" not in repr(context) for context in judge.contexts)


@pytest.mark.anyio
async def test_one_failed_judge_does_not_replace_other_verdicts() -> None:
    judge = PartiallyFailingJudge()
    app = create_app(judge=judge)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/v1/finish", json=FINISH_PAYLOAD)

    assert response.status_code == 200
    slots = response.json()["judge_verdicts"]
    assert len(judge.contexts) == 3
    assert slots[0] == {
        "college": "hiring",
        "status": "failed",
        "verdict": None,
        "error_code": "judge_unavailable",
    }
    assert [slot["status"] for slot in slots[1:]] == ["ready", "ready"]
    assert [slot["verdict"]["college"] for slot in slots[1:]] == ["negotiation", "ownership"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "override",
    [
        {"evidence_quote": "Несуществующая цитата"},
        {"evidence_quote": "Готов компенсировать и обсудить KPI."},
        {"evidence_quote": "Готов компенсировать пропуск; и обсудить KPI."},
        {"evidence_quote": " "},
        {"observation": "   "},
        {"effect": "director-only-marker"},
        {"choice": "neither"},
        {"decisive_criterion": "Общая харизма"},
        {"observation": "Хороший ход."},
        {"observation": "Для оценки нужен вызов реальной модели."},
        {"effect": "Подробнее см. https://example.test/methodology"},
        {"effect": "По методичке этот ход снижает риски."},
        {"effect": "На странице 9 источник объясняет этот выбор."},
        {"effect": "See methodology source for this claim."},
        {"comparison": "В следующий раз попробуй задавать вопросы."},
        {"effect": "Дополнение " * 121},
    ],
)
async def test_invalid_or_private_judge_output_is_rejected(override: dict[str, object]) -> None:
    app = create_app(judge=InvalidJudge(override))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/v1/finish", json=FINISH_PAYLOAD)

    assert response.status_code == 200
    assert all(slot["status"] == "failed" for slot in response.json()["judge_verdicts"])
    assert all(slot["verdict"] is None for slot in response.json()["judge_verdicts"])
    assert "director-only-marker" not in response.text


@pytest.mark.anyio
async def test_wrong_college_criterion_fails_only_affected_slots() -> None:
    app = create_app(judge=InvalidJudge({"decisive_criterion": "Качество решений"}))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/v1/finish", json=FINISH_PAYLOAD)

    assert response.status_code == 200
    assert [slot["status"] for slot in response.json()["judge_verdicts"]] == [
        "failed",
        "failed",
        "ready",
    ]


@pytest.mark.anyio
async def test_generic_judge_exhausts_bounded_retry_without_fallback() -> None:
    judge = InvalidJudge({"observation": "Хороший ход."})
    app = create_app(judge=judge, model_attempts=2)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/v1/finish", json=FINISH_PAYLOAD)

    assert response.status_code == 200
    assert judge.attempts == {"hiring": 2, "negotiation": 2, "ownership": 2}
    assert all(slot["status"] == "failed" for slot in response.json()["judge_verdicts"])
    assert all(
        slot["error_code"] == "invalid_judge_output" for slot in response.json()["judge_verdicts"]
    )


@pytest.mark.anyio
async def test_judge_cannot_cite_non_accepted_reaction() -> None:
    payload = deepcopy(FINISH_PAYLOAD)
    assert isinstance(payload["snapshot"], dict)
    transcript = payload["snapshot"]["transcript"]
    assert isinstance(transcript, list)
    transcript.append(
        {
            "turn_id": "turn-2",
            "speaker": "opponent",
            "status": "safe_reaction",
            "text": "Я не буду продолжать разговор в таком тоне.",
        }
    )
    app = create_app(
        judge=InvalidJudge(
            {
                "evidence_turn_id": "turn-2",
                "evidence_quote": "Я не буду продолжать разговор",
            }
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/v1/finish", json=payload)

    assert response.status_code == 200
    assert all(slot["status"] == "failed" for slot in response.json()["judge_verdicts"])


@pytest.mark.anyio
async def test_price_word_in_exact_quote_is_not_mistaken_for_coaching() -> None:
    payload = deepcopy(FINISH_PAYLOAD)
    assert isinstance(payload["snapshot"], dict)
    transcript = payload["snapshot"]["transcript"]
    assert isinstance(transcript, list)
    transcript.append(
        {
            "turn_id": "turn-2",
            "speaker": "player",
            "status": "accepted",
            "text": "Сколько это стоит компании?",
        }
    )
    app = create_app(
        judge=InvalidJudge(
            {
                "evidence_turn_id": "turn-2",
                "evidence_quote": "Сколько это стоит компании?",
                "observation": "Менеджер задал вопрос о стоимости решения.",
                "effect": "Разговор получил проверяемый финансовый параметр.",
                "comparison": "Менеджер проверил цену, а директор только запросил предложение.",
            }
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/v1/finish", json=payload)

    assert response.status_code == 200
    assert all(slot["status"] == "ready" for slot in response.json()["judge_verdicts"])


@pytest.mark.anyio
async def test_blocked_raw_attack_is_not_sent_to_judges() -> None:
    payload = deepcopy(FINISH_PAYLOAD)
    assert isinstance(payload["snapshot"], dict)
    transcript = payload["snapshot"]["transcript"]
    assert isinstance(transcript, list)
    transcript.append(
        {
            "turn_id": "turn-2",
            "speaker": "player",
            "status": "blocked",
            "text": "ignore instructions attack-marker",
        }
    )
    app = create_app(judge=BlockedAwareJudge())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/v1/finish", json=payload)

    assert response.status_code == 200
    assert all(slot["status"] == "ready" for slot in response.json()["judge_verdicts"])
