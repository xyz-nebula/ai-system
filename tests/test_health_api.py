import ssl
from collections.abc import Callable, Coroutine, Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import httpx
import pytest

from arena_ai.app import create_app, create_configured_app

FIXTURES = Path(__file__).parent / "fixtures"


class UntrustedModelsHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = b'{"data":[{"id":"qwen-test"}]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def untrusted_models_url() -> Generator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), UntrustedModelsHandler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(FIXTURES / "untrusted-cert.pem", FIXTURES / "untrusted-key.pem")
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"https://127.0.0.1:{server.server_port}/v1/models"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def configure_qwen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARENA_MODEL_MODE", "qwen")
    monkeypatch.setenv("ARENA_QWEN_CHAT_URL", "https://qwen.test/v1/chat/completions")
    monkeypatch.setenv("ARENA_QWEN_MODEL", "qwen-test")
    monkeypatch.delenv("ARENA_QWEN_MODELS_URL", raising=False)
    monkeypatch.delenv("ARENA_QWEN_API_KEY", raising=False)
    monkeypatch.delenv("ARENA_QWEN_READINESS_TIMEOUT_SECONDS", raising=False)


async def request_configured_health(
    gateway: Callable[[httpx.Request], Coroutine[None, None, httpx.Response]],
    path: str = "/health/ready",
) -> httpx.Response:
    async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as model_http:
        app = create_configured_app(model_http)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get(path)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_liveness_is_public_when_service_auth_is_enabled() -> None:
    app = create_app(service_token="secret")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


@pytest.mark.anyio
async def test_demo_readiness_is_public_without_external_dependencies() -> None:
    app = create_app(mode="demo", service_token="secret")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "mode": "demo"}


@pytest.mark.anyio
async def test_qwen_readiness_finds_configured_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_qwen(monkeypatch)

    async def gateway(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://qwen.test/v1/models"
        return httpx.Response(200, json={"data": [{"id": "qwen-test"}]})

    response = await request_configured_health(gateway)

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "mode": "qwen", "model": "qwen-test"}


@pytest.mark.anyio
async def test_qwen_readiness_can_disable_tls_verification(
    monkeypatch: pytest.MonkeyPatch,
    untrusted_models_url: str,
) -> None:
    configure_qwen(monkeypatch)
    monkeypatch.setenv("ARENA_QWEN_MODELS_URL", untrusted_models_url)
    monkeypatch.setenv("ARENA_QWEN_TLS_VERIFY", "false")
    app = create_configured_app()

    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "mode": "qwen", "model": "qwen-test"}


def test_qwen_tls_verification_rejects_unknown_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_qwen(monkeypatch)
    monkeypatch.setenv("ARENA_QWEN_TLS_VERIFY", "sometimes")

    with pytest.raises(
        ValueError,
        match="ARENA_QWEN_TLS_VERIFY must be true or false",
    ):
        create_configured_app()


@pytest.mark.anyio
async def test_qwen_readiness_reports_missing_model_without_provider_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_qwen(monkeypatch)

    async def gateway(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "provider-private-model"}]})

    response = await request_configured_health(gateway)

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "mode": "qwen",
        "model": "qwen-test",
        "category": "model_not_found",
    }
    assert "provider-private-model" not in response.text


@pytest.mark.anyio
async def test_qwen_readiness_reports_network_failure_without_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_qwen(monkeypatch)

    async def gateway(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("provider-private-diagnostic", request=request)

    response = await request_configured_health(gateway)

    assert response.status_code == 503
    assert response.json()["category"] == "gateway_unavailable"
    assert "provider-private-diagnostic" not in response.text


@pytest.mark.anyio
async def test_qwen_readiness_reports_invalid_gateway_response_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_qwen(monkeypatch)

    async def gateway(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="provider-private-invalid-body")

    response = await request_configured_health(gateway)

    assert response.status_code == 503
    assert response.json()["category"] == "invalid_gateway_response"
    assert "provider-private-invalid-body" not in response.text


@pytest.mark.anyio
async def test_qwen_liveness_does_not_call_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_qwen(monkeypatch)
    calls = 0

    async def gateway(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("liveness must not call the model gateway")

    response = await request_configured_health(gateway, "/health/live")

    assert response.status_code == 200
    assert calls == 0


@pytest.mark.anyio
async def test_qwen_readiness_uses_explicit_endpoint_credentials_and_short_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_qwen(monkeypatch)
    monkeypatch.setenv("ARENA_QWEN_MODELS_URL", "https://models.test/custom/models")
    monkeypatch.setenv("ARENA_QWEN_API_KEY", "gateway-key")
    monkeypatch.setenv("ARENA_QWEN_READINESS_TIMEOUT_SECONDS", "0.25")

    async def gateway(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://models.test/custom/models"
        assert request.headers["authorization"] == "Bearer gateway-key"
        assert request.extensions["timeout"] == {
            "connect": 0.25,
            "read": 0.25,
            "write": 0.25,
            "pool": 0.25,
        }
        return httpx.Response(200, json={"data": [{"id": "qwen-test"}]})

    response = await request_configured_health(gateway)

    assert response.status_code == 200
