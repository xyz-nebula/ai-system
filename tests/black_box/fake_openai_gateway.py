"""Deterministic OpenAI-compatible gateway for process-level contract tests."""

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

MODEL_ID = "qwen-black-box"


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
            self.send_json(HTTPStatus.OK, {"object": "list", "data": [{"id": MODEL_ID}]})
            return
        self.send_json(HTTPStatus.NOT_FOUND, {"error": {"message": "not found"}})

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/v1/chat/completions":
            self.send_json(HTTPStatus.NOT_FOUND, {"error": {"message": "not found"}})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length))
            messages = request["messages"]
            system = messages[0]["content"]
            context = json.loads(messages[1]["content"])
            user_text = context.get("user_text", "")
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": {"message": "invalid request"}})
            return

        if system.startswith("[ARENA_GUARD]"):
            if "сбоя модели" in user_text.casefold():
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
            completion = {
                "text": "Давайте согласуем измеримые условия.",
                "agreement": None,
                "decision": None,
            }
        elif system.startswith("[ARENA_VALIDATOR]"):
            completion = {"decision": "accept"}
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
