import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
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


@contextmanager
def running_ai_service(model_id: str = "qwen-black-box") -> Iterator[str]:
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
                "ARENA_QWEN_MODEL": model_id,
                "ARENA_QWEN_JSON_MODE": "prompt",
                "ARENA_QWEN_TIMEOUT_SECONDS": "2",
                "ARENA_QWEN_READINESS_TIMEOUT_SECONDS": "1",
                "ARENA_QWEN_FAST_EXTRA_BODY": "{}",
                "ARENA_QWEN_REASONED_EXTRA_BODY": "{}",
                "ARENA_SERVICE_TOKEN": SERVICE_TOKEN,
                "ARENA_QDRANT_URL": f"http://127.0.0.1:{gateway_port}",
                "ARENA_EMBEDDINGS_URL": f"http://127.0.0.1:{gateway_port}",
                "ARENA_JUDGE_COLLECTION": "arena_judge_methodology_v1",
                "ARENA_RETRIEVAL_TIMEOUT_SECONDS": "2",
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


@pytest.fixture
def ai_service_url() -> Iterator[str]:
    with running_ai_service() as service_url:
        yield service_url


@pytest.fixture
def failing_finish_ai_service_url() -> Iterator[str]:
    with running_ai_service("qwen-black-box-failing-finish") as service_url:
        yield service_url


def test_managed_turn_contract_through_independent_http_processes(ai_service_url: str) -> None:
    examples = json.loads((ROOT / "docs" / "api" / "examples" / "managed-turn.json").read_text())
    scenarios = examples["scenarios"]
    headers = {"Authorization": f"Bearer {SERVICE_TOKEN}"}

    with httpx.Client(base_url=ai_service_url, timeout=5) as client:
        live_schema = client.get("/openapi.json")
        readiness = client.get("/health/ready")

        def send_scenario(name: str, *, authorized: bool = True) -> httpx.Response:
            request = scenarios[name]["request"]
            body = {"case": examples["case"], **request["body"]}
            return client.request(
                request["method"],
                request["path"],
                headers=headers if authorized else request.get("headers", {}),
                json=body,
            )

        responses = {
            "accepted": send_scenario("accepted"),
            "blocked": send_scenario("blocked"),
            "model_error": send_scenario("model_error"),
            "agreement_continues": send_scenario("agreement_continues"),
            "unauthorized": send_scenario("unauthorized", authorized=False),
        }

    committed_schema = json.loads((ROOT / "docs" / "api" / "openapi.json").read_text())
    assert live_schema.json() == committed_schema
    assert readiness.json() == {
        "status": "ready",
        "mode": "qwen",
        "model": "qwen-black-box",
    }
    for name, response in responses.items():
        documented = scenarios[name]["response"]
        assert response.status_code == documented["status_code"]
        assert response.json() == documented["body"]
    assert "provider-private-diagnostic" not in responses["model_error"].text


def test_live_evaluation_cli_reports_a_passing_fixed_case(
    ai_service_url: str, tmp_path: Path
) -> None:
    environment = os.environ.copy()
    environment["ARENA_SERVICE_TOKEN"] = SERVICE_TOKEN
    report_path = tmp_path / "live-eval.json"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "arena_ai.live_eval",
            "--api-url",
            ai_service_url,
            "--runs",
            "1",
            "--timeout",
            "5",
            "--output",
            str(report_path),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["scenario_id"] == "next-day-strong-agreement"
    assert report["service"] == {"mode": "qwen", "model": "qwen-black-box"}
    assert report["readiness"] == {
        "status": "ready",
        "mode": "qwen",
        "model": "qwen-black-box",
    }
    assert report["runs_requested"] == 1
    assert report["summary"] == {"passed": 1, "failed": 0}
    assert report["runs"][0]["status"] == "passed"
    assert [turn["status"] for turn in report["runs"][0]["turns"]] == [
        "accepted",
        "accepted",
    ]
    assert report["runs"][0]["outcome_kind"] == "agreement"
    assert report["runs"][0]["judge_slots"] == {
        "hiring": {"status": "ready", "error_code": None},
        "negotiation": {"status": "ready", "error_code": None},
        "ownership": {"status": "ready", "error_code": None},
    }
    assert report["runs"][0]["trainer"] == {"status": "ready", "error_code": None}
    assert all(report["runs"][0]["checks"].values())
    assert json.loads(report_path.read_text()) == report


def test_live_evaluation_cli_reports_a_failed_run_without_leaking_token(
    ai_service_url: str,
) -> None:
    wrong_token = "must-not-appear-in-the-report"
    environment = os.environ.copy()
    environment["ARENA_SERVICE_TOKEN"] = wrong_token

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "arena_ai.live_eval",
            "--api-url",
            ai_service_url,
            "--runs",
            "1",
            "--timeout",
            "5",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 1
    report = json.loads(completed.stdout)
    assert report["summary"] == {"passed": 0, "failed": 1}
    assert report["runs"][0]["status"] == "failed"
    assert report["runs"][0]["turns"] == [
        {
            "sequence": 1,
            "status": "request_error",
            "error_code": "HTTPStatusError",
        }
    ]
    assert wrong_token not in completed.stdout
    assert wrong_token not in completed.stderr


def test_live_evaluation_cli_keeps_safe_finish_failure_codes(
    failing_finish_ai_service_url: str,
) -> None:
    environment = os.environ.copy()
    environment["ARENA_SERVICE_TOKEN"] = SERVICE_TOKEN

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "arena_ai.live_eval",
            "--api-url",
            failing_finish_ai_service_url,
            "--runs",
            "1",
            "--timeout",
            "5",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 1
    report = json.loads(completed.stdout)
    assert report["runs"][0]["judge_slots"]["ownership"] == {
        "status": "failed",
        "error_code": "invalid_judge_output",
    }
    assert report["runs"][0]["trainer"] == {
        "status": "failed",
        "error_code": "trainer_unavailable",
    }
    assert "provider-private-diagnostic" not in completed.stdout


def test_live_evaluation_cli_saves_a_safe_report_when_service_is_unavailable(
    tmp_path: Path,
) -> None:
    unavailable_url = f"http://127.0.0.1:{free_port()}"
    report_path = tmp_path / "unavailable.json"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "arena_ai.live_eval",
            "--api-url",
            unavailable_url,
            "--runs",
            "1",
            "--timeout",
            "0.1",
            "--output",
            str(report_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 2
    report = json.loads(completed.stdout)
    assert report == json.loads(report_path.read_text())
    assert report["service"] is None
    assert report["readiness"] is None
    assert report["startup_error"] == "ConnectError"
    assert report["summary"] == {"passed": 0, "failed": 1}
    assert report["runs"] == []
