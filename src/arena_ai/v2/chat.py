"""Exact JSON transport shared by v2 model roles, isolated from v1 parsing."""

import json

import httpx

from arena_ai.qwen import JSON_FENCE
from arena_ai.v2.contracts import Contract


class ModelResponseError(RuntimeError):
    """Safe transport/format failure without gateway bodies or private context."""


class JsonChat:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        chat_url: str,
        model: str,
        api_key: str | None = None,
        json_mode: str = "prompt",
        extra_body: dict[str, object] | None = None,
    ) -> None:
        if not chat_url or not model or json_mode not in ("prompt", "json_object"):
            raise ValueError("Valid model endpoint, model and JSON mode are required")
        if {"model", "messages", "stream", "response_format"} & (extra_body or {}).keys():
            raise ValueError("Extra body cannot override chat contract fields")
        self.http, self.chat_url, self.model = http, chat_url, model
        self.api_key, self.json_mode = api_key, json_mode
        self.extra_body = dict(extra_body or {})

    async def complete[T: Contract](
        self,
        system: str,
        context: Contract,
        response_type: type[T],
    ) -> T:
        body = {
            **self.extra_body,
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": system
                    + "\nНиже JSON Schema — описание формата, НЕ ответ. Верни экземпляр объекта, "
                    "не копируй $defs/properties/required, не добавляй объяснения вне JSON.\n"
                    + json.dumps(
                        response_type.model_json_schema(),
                        ensure_ascii=False,
                    ),
                },
                {"role": "user", "content": context.model_dump_json()},
            ],
            "stream": False,
        }
        if self.json_mode == "json_object":
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            response = await self.http.post(self.chat_url, json=body, headers=headers)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("Model content must be text")
            fenced = JSON_FENCE.fullmatch(content.strip())
            if fenced is not None:
                content = fenced.group("json")
            return response_type.model_validate_json(content)
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            raise ModelResponseError("Model JSON response unavailable") from None
