"""Build the configured model roles and own their HTTP transport."""

from dataclasses import dataclass

import httpx

from arena_ai.qwen import (
    QwenChatClient,
    QwenGuard,
    QwenJudge,
    QwenOpponent,
    QwenReadinessProbe,
    QwenSettings,
    QwenTrainer,
    QwenValidator,
)


@dataclass(frozen=True)
class QwenRuntime:
    opponent: QwenOpponent
    guard: QwenGuard
    validator: QwenValidator
    judge: QwenJudge
    trainer: QwenTrainer
    readiness: QwenReadinessProbe
    owned_http: httpx.AsyncClient | None
    model_id: str


def build_qwen_runtime(model_http: httpx.AsyncClient | None = None) -> QwenRuntime:
    settings = QwenSettings.from_env()
    actual_http = (
        model_http
        if model_http is not None
        else httpx.AsyncClient(timeout=settings.timeout_seconds)
    )
    chat = QwenChatClient(
        actual_http,
        chat_url=settings.chat_url,
        model=settings.model,
        api_key=settings.api_key,
        json_mode=settings.json_mode,
        fast_extra_body=settings.fast_extra_body,
        reasoned_extra_body=settings.reasoned_extra_body,
    )
    return QwenRuntime(
        opponent=QwenOpponent(chat),
        guard=QwenGuard(chat),
        validator=QwenValidator(chat),
        judge=QwenJudge(chat),
        trainer=QwenTrainer(chat),
        readiness=QwenReadinessProbe(
            actual_http,
            models_url=settings.models_url,
            model=settings.model,
            timeout_seconds=settings.readiness_timeout_seconds,
            api_key=settings.api_key,
        ),
        owned_http=actual_http if model_http is None else None,
        model_id=settings.model,
    )
