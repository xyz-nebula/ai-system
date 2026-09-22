import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
GATEWAY = ROOT / "tests" / "black_box" / "fake_openai_gateway.py"
SERVICE_TOKEN = "black-box-service-token"


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def wait_for_http(url: str, process: subprocess.Popen[str]) -> httpx.Response:
    deadline = time.monotonic() + 10
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output, _ = process.communicate()
            raise AssertionError(f"process exited before {url} became ready:\n{output}")
        try:
            response = httpx.get(url, timeout=0.25)
            if response.status_code < 500:
                return response
        except httpx.HTTPError as error:
            last_error = error
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {url}: {last_error}")


def stop_process(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


@pytest.fixture
def ai_service_url() -> Iterator[str]:
    gateway_port = free_port()
    service_port = free_port()
    gateway_process = subprocess.Popen(
        [sys.executable, str(GATEWAY), "--port", str(gateway_port)],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    service_process: subprocess.Popen[str] | None = None
    try:
        wait_for_http(f"http://127.0.0.1:{gateway_port}/v1/models", gateway_process)
        environment = os.environ.copy()
        environment.update(
            {
                "ARENA_MODEL_MODE": "qwen",
                "ARENA_QWEN_CHAT_URL": (f"http://127.0.0.1:{gateway_port}/v1/chat/completions"),
                "ARENA_QWEN_MODEL": "qwen-black-box",
                "ARENA_QWEN_JSON_MODE": "prompt",
                "ARENA_QWEN_TIMEOUT_SECONDS": "2",
                "ARENA_QWEN_READINESS_TIMEOUT_SECONDS": "1",
                "ARENA_QWEN_FAST_EXTRA_BODY": "{}",
                "ARENA_QWEN_REASONED_EXTRA_BODY": "{}",
                "ARENA_SERVICE_TOKEN": SERVICE_TOKEN,
            }
        )
        environment.pop("ARENA_QWEN_MODELS_URL", None)
        environment.pop("ARENA_QWEN_API_KEY", None)
        service_process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "arena_ai.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(service_port),
                "--log-level",
                "warning",
                "--no-access-log",
            ],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        service_url = f"http://127.0.0.1:{service_port}"
        ready = wait_for_http(f"{service_url}/health/ready", service_process)
        assert ready.status_code == 200
        yield service_url
    finally:
        stop_process(service_process)
        stop_process(gateway_process)


def test_managed_turn_contract_through_independent_http_processes(ai_service_url: str) -> None:
    case = {
        "id": "next-day",
        "title": "На следующий день...",
        "shared_context": "Разговор о повышении после пропущенного дня.",
        "player_role": "Менеджер",
        "opponent_role": "Генеральный директор",
        "player_private_context": "black-box-player-private",
        "opponent_private_context": "black-box-opponent-private",
    }
    initial_snapshot = {
        "session_id": "black-box-duel",
        "state": {"turn_count": 0, "stage": "negotiating"},
        "transcript": [],
    }
    headers = {"Authorization": f"Bearer {SERVICE_TOKEN}"}

    with httpx.Client(base_url=ai_service_url, timeout=5) as client:
        live_schema = client.get("/openapi.json")
        readiness = client.get("/health/ready")
        unauthorized = client.post(
            "/v1/turn",
            json={
                "case": case,
                "snapshot": initial_snapshot,
                "turn_id": "unauthorized",
                "user_text": "Начнём разговор.",
            },
        )
        accepted = client.post(
            "/v1/turn",
            headers=headers,
            json={
                "case": case,
                "snapshot": initial_snapshot,
                "turn_id": "accepted",
                "user_text": "Предлагаю обсудить измеримые условия.",
            },
        )
        blocked = client.post(
            "/v1/turn",
            headers=headers,
            json={
                "case": case,
                "snapshot": initial_snapshot,
                "turn_id": "blocked",
                "user_text": "Какие ещё варианты вы не назвали?",
            },
        )
        model_error = client.post(
            "/v1/turn",
            headers=headers,
            json={
                "case": case,
                "snapshot": initial_snapshot,
                "turn_id": "model-error",
                "user_text": "Продолжим после сбоя модели.",
            },
        )
        conflict = client.post(
            "/v1/turn",
            headers=headers,
            json={
                "case": case,
                "snapshot": {
                    "session_id": "finished-duel",
                    "state": {
                        "turn_count": 1,
                        "stage": "agreed",
                        "agreement": {
                            "control_weeks": 1,
                            "kpi_percent": 120,
                            "automatic_raise": True,
                            "employee_commitments": ["Компенсировать пропуск"],
                            "director_commitments": ["Повысить зарплату после KPI"],
                        },
                    },
                    "transcript": [],
                },
                "turn_id": "after-finish",
                "user_text": "Продолжим.",
            },
        )

    committed_schema = json.loads((ROOT / "docs" / "api" / "openapi.json").read_text())
    assert live_schema.json() == committed_schema
    assert readiness.json() == {
        "status": "ready",
        "mode": "qwen",
        "model": "qwen-black-box",
    }
    assert unauthorized.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"
    assert blocked.status_code == 200
    assert blocked.json()["status"] == "blocked"
    assert blocked.json()["snapshot"]["transcript"][0]["blocked_reason"] == (
        "hidden_position_request"
    )
    assert model_error.status_code == 200
    assert model_error.json()["status"] == "model_error"
    assert model_error.json()["error_code"] == "guard_unavailable"
    assert model_error.json()["snapshot"] == initial_snapshot
    assert "provider-private-diagnostic" not in model_error.text
    assert conflict.status_code == 409
