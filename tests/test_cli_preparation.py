import json
import sys
from pathlib import Path
from typing import Self

import httpx
import pytest

from arena_ai import cli


class RecordingClient:
    def __init__(self) -> None:
        self.turn_body: dict[str, object] | None = None
        self.finish_body: dict[str, object] | None = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def get(self, path: str) -> httpx.Response:
        assert path == "/v1/info"
        return httpx.Response(
            200,
            json={"mode": "demo", "model": None},
            request=httpx.Request("GET", f"http://test{path}"),
        )

    def post(self, path: str, *, json: dict[str, object], timeout: float) -> httpx.Response:
        if path == "/v1/turn":
            assert timeout == 210.0
            self.turn_body = json
            snapshot = json["snapshot"]
            turn_id = json["turn_id"]
            user_text = json["user_text"]
            assert isinstance(snapshot, dict)
            assert isinstance(snapshot["session_id"], str)
            assert isinstance(turn_id, str)
            assert isinstance(user_text, str)
            return httpx.Response(
                200,
                json={
                    "session_id": snapshot["session_id"],
                    "turn_id": turn_id,
                    "status": "accepted",
                    "opponent_text": "Какие условия вы предлагаете?",
                    "snapshot": {
                        "session_id": snapshot["session_id"],
                        "state": {"turn_count": 1},
                        "transcript": [
                            {
                                "turn_id": turn_id,
                                "speaker": "player",
                                "status": "accepted",
                                "text": user_text,
                            },
                            {
                                "turn_id": turn_id,
                                "speaker": "opponent",
                                "status": "accepted",
                                "text": "Какие условия вы предлагаете?",
                            },
                        ],
                    },
                    "error_code": None,
                },
                request=httpx.Request("POST", f"http://test{path}"),
            )
        assert path == "/v1/finish"
        assert timeout == 300.0
        self.finish_body = json
        return httpx.Response(
            200,
            json={
                "session_id": "cli-preparation",
                "outcome": {"kind": "no_agreement", "summary": "Соглашения пока нет."},
                "judge_verdicts": [
                    {
                        "college": "negotiation",
                        "status": "ready",
                        "verdict": {
                            "college": "negotiation",
                            "choice": "player",
                            "decisive_criterion": "Движение к цели",
                            "evidence_turn_id": "turn-1",
                            "evidence_quote": "обсудить KPI",
                            "observation": "Менеджер поднял тему измеримых условий.",
                            "effect": "Критерии вошли в обсуждение повышения.",
                            "comparison": "Менеджер предложил тему, а директор только запросил условия.",
                        },
                        "error_code": None,
                    }
                ],
                "trainer_feedback": {
                    "status": "ready",
                    "feedback": {
                        "summary": "Менеджер адаптировал подготовленный вопрос.",
                        "strengths": [
                            {
                                "evidence_turn_id": "turn-1",
                                "evidence_quote": "обсудить KPI",
                                "action": "Поднял тему критериев.",
                                "situation_change": "Критерии вошли в обсуждение.",
                                "consequence": "Можно согласовать измеримые условия.",
                            }
                        ],
                        "mistakes": [],
                        "next_try": ["Сформулируй вопрос дословно."],
                        "plan_vs_reality": {
                            "summary": "Вопрос о KPI был адаптирован.",
                            "items": [
                                {
                                    "preparation_kind": "planned_question",
                                    "preparation_text": "Какие KPI подтвердят готовность?",
                                    "status": "adapted",
                                    "evidence_turn_id": "turn-1",
                                    "evidence_quote": "обсудить KPI",
                                    "observation": "Тема появилась как предложение, а не вопрос.",
                                }
                            ],
                        },
                    },
                    "error_code": None,
                },
            },
            request=httpx.Request("POST", f"http://test{path}"),
        )


def test_cli_loads_preparation_for_finish_and_prints_the_comparison(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    preparation_path = tmp_path / "preparation.json"
    preparation = {
        "negotiation_goal": "Согласовать измеримые условия повышения.",
        "planned_questions": ["Какие KPI подтвердят готовность?"],
    }
    preparation_path.write_text(json.dumps(preparation, ensure_ascii=False))
    client = RecordingClient()
    monkeypatch.setattr(sys, "argv", ["arena-ai", "--preparation-file", str(preparation_path)])
    monkeypatch.setattr(cli.httpx, "Client", lambda **kwargs: client)
    commands = iter(["Предлагаю обсудить KPI.", ":finish"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(commands))

    cli.main()

    assert client.turn_body is not None
    assert "preparation" not in client.turn_body
    assert client.finish_body is not None
    assert client.finish_body["preparation"] == preparation
    output = capsys.readouterr().out
    assert "Сопоставление подготовки с поединком:" in output
    assert "Адаптировано" in output
    assert "обсудить KPI" in output
    assert "Решающий критерий: Движение к цели" in output
    assert "Выбор: Менеджер" in output


def test_cli_rejects_invalid_preparation_before_connecting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    preparation_path = tmp_path / "invalid-preparation.json"
    preparation_path.write_text('{"arguments": [""]}')
    monkeypatch.setattr(sys, "argv", ["arena-ai", "--preparation-file", str(preparation_path)])

    def unexpected_client(**kwargs: object) -> RecordingClient:
        raise AssertionError("invalid preparation must fail before connecting")

    monkeypatch.setattr(cli.httpx, "Client", unexpected_client)

    cli.main()

    assert "Не удалось загрузить карточку подготовки." in capsys.readouterr().out
