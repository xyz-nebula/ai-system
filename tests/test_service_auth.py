import httpx
import pytest

from arena_ai.app import create_app, create_configured_app


def turn_request() -> dict[str, object]:
    return {
        "case": {
            "id": "next-day",
            "title": "На следующий день...",
            "shared_context": "Разговор о повышении после пропущенного дня.",
            "player_role": "Менеджер",
            "opponent_role": "Генеральный директор",
            "player_private_context": "Сохранить договорённость о повышении.",
            "opponent_private_context": "Проверить ответственность менеджера.",
        },
        "snapshot": {
            "session_id": "service-auth",
            "state": {"turn_count": 0},
            "transcript": [],
        },
        "turn_id": "turn-1",
        "user_text": "Как восстановить ваше доверие?",
    }


def finish_request() -> dict[str, object]:
    request = turn_request()
    return {"case": request["case"], "snapshot": request["snapshot"]}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("path", "payload"),
    [
        pytest.param("/v1/turn", turn_request(), id="turn"),
        pytest.param("/v1/finish", finish_request(), id="finish"),
    ],
)
async def test_configured_service_token_rejects_missing_and_wrong_credentials(
    path: str,
    payload: dict[str, object],
) -> None:
    app = create_app(service_token="correct-token")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        missing = await client.post(path, json=payload)
        wrong = await client.post(
            path,
            json=payload,
            headers={"Authorization": "Bearer wrong-token"},
        )

    assert (missing.status_code, missing.json()) == (401, {"detail": "Unauthorized"})
    assert (wrong.status_code, wrong.json()) == (401, {"detail": "Unauthorized"})


@pytest.mark.anyio
async def test_environment_service_token_protects_configured_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARENA_MODEL_MODE", "demo")
    monkeypatch.setenv("ARENA_SERVICE_TOKEN", "environment-token")
    app = create_configured_app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        missing = await client.post("/v1/turn", json=turn_request())
        authorized = await client.post(
            "/v1/turn",
            json=turn_request(),
            headers={"Authorization": "Bearer environment-token"},
        )

    assert missing.status_code == 401
    assert authorized.status_code == 200


@pytest.mark.anyio
async def test_configured_service_token_permits_authorized_turn_and_finish() -> None:
    app = create_app(service_token="correct-token")
    headers = {"Authorization": "Bearer correct-token"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        turn = await client.post("/v1/turn", json=turn_request(), headers=headers)
        finish = await client.post(
            "/v1/finish",
            json={"case": turn_request()["case"], "snapshot": turn.json()["snapshot"]},
            headers=headers,
        )

    assert turn.status_code == 200
    assert finish.status_code == 200


@pytest.mark.anyio
async def test_unconfigured_service_token_keeps_local_operations_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ARENA_SERVICE_TOKEN", raising=False)
    app = create_configured_app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/v1/turn", json=turn_request())

    assert response.status_code == 200


@pytest.mark.anyio
async def test_service_metadata_stays_public_and_does_not_expose_token() -> None:
    service_token = "must-not-appear"
    app = create_app(service_token=service_token)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        info = await client.get("/v1/info")
        openapi = await client.get("/openapi.json")

    assert info.status_code == 200
    assert openapi.status_code == 200
    assert service_token not in info.text
    assert service_token not in openapi.text


def test_openapi_documents_bearer_auth_for_duel_operations() -> None:
    schema = create_app(service_token="must-not-appear").openapi()

    assert schema["components"]["securitySchemes"] == {
        "HTTPBearer": {"type": "http", "scheme": "bearer"}
    }
    assert schema["paths"]["/v1/turn"]["post"]["security"] == [{"HTTPBearer": []}]
    assert schema["paths"]["/v1/finish"]["post"]["security"] == [{"HTTPBearer": []}]
