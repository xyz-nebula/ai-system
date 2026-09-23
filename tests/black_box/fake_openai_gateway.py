"""Deterministic OpenAI-compatible gateway for process-level contract tests."""

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

MODEL_ID = "qwen-black-box"
FAILURE_MODEL_ID = "qwen-black-box-failing-finish"


class FakeOpenAIHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def send_json(self, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if urlsplit(self.path).path == "/v1/models":
            self.send_json(
                HTTPStatus.OK,
                {
                    "object": "list",
                    "data": [{"id": MODEL_ID}, {"id": FAILURE_MODEL_ID}],
                },
            )
            return
        self.send_json(HTTPStatus.NOT_FOUND, {"error": {"message": "not found"}})

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/v1/chat/completions":
            self.send_json(HTTPStatus.NOT_FOUND, {"error": {"message": "not found"}})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length))
            model = request["model"]
            messages = request["messages"]
            system = messages[0]["content"]
            context = json.loads(messages[1]["content"])
            user_text = context.get("user_text", "")
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": {"message": "invalid request"}})
            return

        if system.startswith("[ARENA_GUARD]"):
            if "продолжить разговор" in user_text.casefold():
                self.send_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"error": {"message": "provider-private-diagnostic"}},
                )
                return
            if "не назвали" in user_text.casefold():
                completion = {
                    "decision": "block",
                    "reason": "hidden_position_request",
                }
            else:
                completion = {"decision": "allow", "reason": None}
        elif system.startswith("[ARENA_OPPONENT]"):
            if "2 недели" in user_text and "120%" in user_text:
                completion = {
                    "text": (
                        "Согласен: 2 недели контроля, KPI 120% и автоматическое повышение "
                        "после выполнения. Договорились."
                    ),
                    "resolution": {
                        "kind": "agreement",
                        "control_weeks": 2,
                        "kpi_percent": 120,
                        "automatic_raise": True,
                        "employee_commitments": ["Выполнить KPI 120% за две недели."],
                        "director_commitments": [
                            "Автоматически оформить повышение после выполнения KPI."
                        ],
                    },
                }
            else:
                completion = {
                    "text": "Давайте согласуем измеримые условия.",
                    "resolution": None,
                }
        elif system.startswith("[ARENA_VALIDATOR]"):
            completion = {"decision": "accept"}
        elif system.startswith("[ARENA_JUDGE]"):
            evidence = next(
                entry
                for entry in context["transcript"]
                if entry["speaker"] == "player" and entry["status"] == "accepted"
            )
            if model == FAILURE_MODEL_ID and context["college"] == "ownership":
                completion = {}
            else:
                completion = {
                    "college": context["college"],
                    "choice": "player",
                    "evidence_turn_id": evidence["turn_id"],
                    "evidence_quote": evidence["text"],
                    "observation": (
                        "Менеджер признал сомнения и предложил измеримую ответственность."
                    ),
                    "effect": "Разговор перешёл к проверяемым условиям.",
                    "comparison": "Менеджер дал более конкретное предложение.",
                }
        elif system.startswith("[ARENA_TRAINER]"):
            if model == FAILURE_MODEL_ID:
                self.send_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"error": {"message": "provider-private-diagnostic"}},
                )
                return
            evidence = next(
                entry
                for entry in context["transcript"]
                if entry["speaker"] == "player" and entry["status"] == "accepted"
            )
            preparation = context["preparation"]
            comparison_items = [
                {
                    "preparation_kind": "negotiation_goal",
                    "preparation_text": preparation["negotiation_goal"],
                    "status": "followed",
                    "evidence_turn_id": evidence["turn_id"],
                    "evidence_quote": evidence["text"],
                    "observation": "Менеджер двигался к измеримым условиям.",
                },
                {
                    "preparation_kind": "planned_question",
                    "preparation_text": preparation["planned_questions"][0],
                    "status": "adapted",
                    "evidence_turn_id": evidence["turn_id"],
                    "evidence_quote": evidence["text"],
                    "observation": "Подготовленный вопрос превратился в предложение.",
                },
            ]
            completion = {
                "summary": "Менеджер перевёл сомнения в измеримые условия.",
                "strengths": [
                    {
                        "evidence_turn_id": evidence["turn_id"],
                        "evidence_quote": evidence["text"],
                        "action": "Признал сомнения директора.",
                        "situation_change": "Снизил напряжение.",
                        "consequence": "Стало возможно обсуждать условия.",
                    }
                ],
                "mistakes": [],
                "next_try": ["Уточнить критерий проверки KPI."],
                "plan_vs_reality": {
                    "summary": "Оба элемента подготовки проявились в разговоре.",
                    "items": comparison_items,
                },
            }
        else:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": {"message": "unknown role"}})
            return

        self.send_json(
            HTTPStatus.OK,
            {
                "id": "fake-completion",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(completion, ensure_ascii=False),
                        }
                    }
                ],
            },
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), FakeOpenAIHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
