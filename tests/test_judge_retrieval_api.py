"""Public finish tests over the real retrieval adapter and deterministic HTTP doubles."""

import json
from dataclasses import replace

import httpx
import pytest
from test_judges_api import FINISH_PAYLOAD, RecordingJudge

from arena_ai.app import create_app, create_configured_app
from arena_ai.contracts import JudgeCollege, JudgeContext
from arena_ai.judge_corpus import CHUNKS, CORPUS_ID, CORPUS_VERSION, SOURCES, chunks_for_college
from arena_ai.judge_index import point_id
from arena_ai.judge_retrieval import QUERIES, QdrantJudgeRetrieval, RetrievalSettings


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class RetrievalGateway:
    """Implements filtered scroll pagination and vector query; never contacts a server."""

    def __init__(self, fault: str | None = None) -> None:
        self.fault = fault
        self.requests: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        assert request.extensions["timeout"]["read"] == 2
        if request.url.path == "/embed":
            assert body["truncate"] is False
            assert len(body["inputs"]) == 1
            query = body["inputs"][0]
            assert query.startswith("Instruct: ")
            assert query.split("\nQuery: ", 1)[1] in QUERIES.values()
            if QUERIES["hiring"] in query:
                if self.fault == "embedding_http":
                    return httpx.Response(503, text="retrieval-private-diagnostic")
                if self.fault == "embedding_timeout":
                    raise httpx.ReadTimeout("retrieval-private-diagnostic", request=request)
                if self.fault == "embedding_invalid":
                    return httpx.Response(200, json=[[0, 0, 0]])
            return httpx.Response(200, json=[[1, 0.5, 0.25]])

        assert request.url.path.endswith(("/points/scroll", "/points/query"))
        assert body["with_payload"] is True
        assert body["with_vector"] is False
        conditions = {item["key"]: item["match"] for item in body["filter"]["must"]}
        assert conditions["purpose"] == {"value": "judge"}
        assert conditions["corpus_id"] == {"value": CORPUS_ID}
        assert conditions["corpus_version"] == {"value": CORPUS_VERSION}
        college = conditions["colleges"]["value"]
        scroll = request.url.path.endswith("/scroll")
        scopes = conditions["scope"]["any"]
        assert scopes == (["core", "profile"] if scroll else ["technique"])
        if not scroll:
            assert body["query"] == [1, 0.5, 0.25]
            assert body["limit"] == 2
        broken = college == "hiring"
        if broken and self.fault == "qdrant_http":
            return httpx.Response(503, text="retrieval-private-diagnostic")
        if broken and self.fault == "invalid_json":
            return httpx.Response(200, text="retrieval-private-diagnostic")
        if broken and self.fault == "invalid_envelope":
            return httpx.Response(200, json={"result": []})
        if broken and self.fault == "empty_pages" and scroll:
            return httpx.Response(
                200,
                json={
                    "result": {
                        "points": [],
                        "next_page_offset": body.get("offset", 0) + 1,
                    }
                },
            )

        selected = [chunk for chunk in chunks_for_college(college) if chunk.scope in scopes]
        if broken and self.fault == "missing_core" and scroll:
            selected = [chunk for chunk in selected if chunk.chunk_id != CHUNKS[0].chunk_id]
        if broken and self.fault == "missing_profile" and scroll:
            selected = [chunk for chunk in selected if chunk.scope != "profile"]
        if broken and self.fault == "empty_themes" and not scroll:
            selected = []
        start = next(
            (i for i, chunk in enumerate(selected) if point_id(chunk) == body.get("offset")), 0
        )
        end = start + (4 if scroll else body["limit"])
        points = [
            {"id": point_id(chunk), "payload": chunk.payload()} for chunk in selected[start:end]
        ]
        offset = point_id(selected[end]) if end < len(selected) else None
        if broken and scroll and points:
            if self.fault == "foreign_profile":
                foreign = next(
                    chunk
                    for chunk in CHUNKS
                    if chunk.scope == "profile" and "ownership" in chunk.colleges
                )
                points[0] = {"id": point_id(foreign), "payload": foreign.payload()}
            elif self.fault == "unknown_id":
                points[0]["id"] = "unapproved-document-id"
            elif self.fault == "duplicate":
                points.append(points[0])
            elif self.fault == "duplicate_page" and body.get("offset"):
                points.append({"id": point_id(selected[0]), "payload": selected[0].payload()})
            elif self.fault in ("text", "text_sha256", "corpus_version", "source_path"):
                payload = points[0]["payload"]
                assert isinstance(payload, dict)
                payload[self.fault] = "unreviewed-private-material"
            elif self.fault == "extra_payload":
                payload = points[0]["payload"]
                assert isinstance(payload, dict)
                payload["private_case"] = "unreviewed-private-material"
            elif self.fault == "invalid_offset":
                offset = True
            elif self.fault == "repeated_offset":
                offset = point_id(selected[0])
        return httpx.Response(
            200,
            json={
                "result": {
                    "points": points,
                    "next_page_offset": offset,
                }
            },
        )


async def finish_with_gateway(gateway: RetrievalGateway, judge: RecordingJudge) -> httpx.Response:
    async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as retrieval_http:
        retrieval = QdrantJudgeRetrieval(
            retrieval_http,
            RetrievalSettings(
                qdrant_url="http://qdrant.test",
                embeddings_url="http://tei.test",
                timeout_seconds=2,
            ),
        )
        app = create_app(judge=judge, judge_retrieval=retrieval, model_attempts=2)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await client.post(
                "/v1/finish",
                json={
                    **FINISH_PAYLOAD,
                    "preparation": {
                        "strategic_goal": "private-preparation-marker",
                        "arguments": ["private-argument-marker"],
                    },
                },
            )


@pytest.mark.anyio
async def test_finish_retrieves_required_core_and_only_own_college_profile() -> None:
    gateway = RetrievalGateway()
    judge = RecordingJudge()
    response = await finish_with_gateway(gateway, judge)
    assert response.status_code == 200
    assert all(slot["status"] == "ready" for slot in response.json()["judge_verdicts"])
    assert response.json()["outcome"]["kind"] == "no_agreement"
    assert response.json()["trainer_feedback"]["status"] == "ready"
    assert len(judge.contexts) == 3
    assert len(gateway.requests) == 12  # Two mandatory pages, one embedding, one query per college.
    retrieval_requests = json.dumps(gateway.requests, ensure_ascii=False)
    for marker in (
        "manager-only-marker",
        "director-only-marker",
        "private-target-step",
        "private-preparation-marker",
        "private-argument-marker",
        "judged-duel",
        "Готов компенсировать пропуск",
        "Что вы предлагаете?",
    ):
        assert marker not in retrieval_requests
    for context in judge.contexts:
        expected = chunks_for_college(context.college)
        assert context.methodology.core == [c.text for c in expected if c.scope == "core"]
        assert context.methodology.profile == [c.text for c in expected if c.scope == "profile"]
        assert context.methodology.techniques == [
            c.text for c in expected if c.scope == "technique"
        ]
        internal = context.model_dump_json()
        for key in (
            "chunk_id",
            "source_path",
            "source_name",
            "text_sha256",
            "page",
            "corpus_version",
        ):
            assert f'"{key}"' not in internal
        for chunk in CHUNKS:
            assert chunk.chunk_id not in internal
            assert chunk.chunk_id not in response.text
            assert chunk.text not in response.text
        for source in SOURCES.values():
            assert source.path not in response.text
            assert source.pdf_name not in response.text
    assert "methodology" not in json.dumps(create_app().openapi())


@pytest.mark.anyio
@pytest.mark.parametrize(
    "fault",
    [
        "qdrant_http",
        "embedding_http",
        "embedding_timeout",
        "embedding_invalid",
        "invalid_json",
        "invalid_envelope",
        "missing_core",
        "missing_profile",
        "empty_themes",
        "foreign_profile",
        "unknown_id",
        "duplicate",
        "duplicate_page",
        "text",
        "text_sha256",
        "corpus_version",
        "source_path",
        "extra_payload",
        "invalid_offset",
        "repeated_offset",
        "empty_pages",
    ],
)
async def test_retrieval_failure_skips_only_affected_judge_without_fallback(fault: str) -> None:
    gateway = RetrievalGateway(fault)
    judge = RecordingJudge()
    response = await finish_with_gateway(gateway, judge)
    assert response.status_code == 200
    slots = response.json()["judge_verdicts"]
    unavailable = fault in ("qdrant_http", "embedding_http", "embedding_timeout")
    assert slots[0] == {
        "college": "hiring",
        "status": "failed",
        "verdict": None,
        "error_code": "judge_retrieval_unavailable" if unavailable else "invalid_judge_retrieval",
    }
    assert all(slot["status"] == "ready" for slot in slots[1:])
    assert [context.college for context in judge.contexts] == ["negotiation", "ownership"]
    assert "retrieval-private-diagnostic" not in response.text
    assert "unreviewed-private-material" not in response.text
    assert len(gateway.requests) < 25  # Invalid pagination is bounded, including empty pages.


class LeakingJudge(RecordingJudge):
    def __init__(self, leak: str) -> None:
        super().__init__()
        self.leak = leak

    async def verdict(self, context: JudgeContext) -> object:
        raw = await super().verdict(context)
        assert isinstance(raw, dict)
        if context.college == "hiring":
            if self.leak == "method_quote":
                raw["evidence_quote"] = context.methodology.core[0]
            else:
                raw["observation"] = {
                    "excerpt": context.methodology.core[0],
                    "id": CHUNKS[0].chunk_id,
                    "uuid": point_id(CHUNKS[0]),
                    "hash": CHUNKS[0].text_sha256,
                    "path": SOURCES["guide"].path,
                    "pdf_hash": SOURCES["guide"].pdf_sha256,
                    "title": "Подготовка к переговорам",
                }[self.leak]
        return raw


@pytest.mark.anyio
@pytest.mark.parametrize(
    "leak", ["excerpt", "id", "uuid", "hash", "path", "pdf_hash", "title", "method_quote"]
)
async def test_methodology_leaks_or_method_quote_as_evidence_never_become_public(leak: str) -> None:
    judge = LeakingJudge(leak)
    response = await finish_with_gateway(RetrievalGateway(), judge)
    slots = response.json()["judge_verdicts"]
    assert slots[0]["status"] == "failed"
    assert slots[0]["error_code"] == "invalid_judge_output"
    assert slots[0]["verdict"] is None
    assert all(slot["status"] == "ready" for slot in slots[1:])
    assert [c.college for c in judge.contexts].count("hiring") == 2


class BrokenRetrieval:
    def __init__(self, invalid: bool) -> None:
        self.invalid = invalid

    async def retrieve(self, college: JudgeCollege) -> object:
        if self.invalid:
            approved = chunks_for_college(college)
            return (replace(approved[0], text="unapproved-private-document"), *approved[1:])
        raise RuntimeError("retrieval-private-diagnostic")


@pytest.mark.anyio
@pytest.mark.parametrize("invalid", [False, True])
async def test_judge_boundary_validates_injected_retrievers_and_hides_exceptions(
    invalid: bool,
) -> None:
    judge = RecordingJudge()
    app = create_app(judge=judge, judge_retrieval=BrokenRetrieval(invalid))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/v1/finish", json=FINISH_PAYLOAD)
    assert response.status_code == 200
    assert judge.contexts == []
    assert {slot["error_code"] for slot in response.json()["judge_verdicts"]} == {
        "invalid_judge_retrieval" if invalid else "judge_retrieval_unavailable",
    }
    assert "retrieval-private-diagnostic" not in response.text
    assert "unapproved-private-document" not in response.text


@pytest.mark.anyio
async def test_configured_qwen_runtime_requires_retrieval_and_does_not_close_borrowed_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARENA_MODEL_MODE", "qwen")
    monkeypatch.setenv("ARENA_QWEN_CHAT_URL", "http://model.test/v1/chat/completions")
    monkeypatch.setenv("ARENA_QWEN_MODEL", "test-model")
    monkeypatch.delenv("ARENA_SERVICE_TOKEN", raising=False)
    model_calls: list[str] = []

    def model_gateway(request: httpx.Request) -> httpx.Response:
        system = json.loads(request.content)["messages"][0]["content"]
        model_calls.append(system)
        assert system.startswith("[ARENA_TRAINER]")  # Judges never called without retrieval.
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    def unavailable(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="retrieval-private-diagnostic")

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(model_gateway)) as model_http,
        httpx.AsyncClient(transport=httpx.MockTransport(unavailable)) as retrieval_http,
    ):
        app = create_configured_app(model_http, retrieval_http)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client,
        ):
            response = await client.post("/v1/finish", json=FINISH_PAYLOAD)
        assert not model_http.is_closed
        assert not retrieval_http.is_closed
    assert response.status_code == 200
    assert len(model_calls) > 0
    assert all(
        slot["status"] == "failed" and slot["error_code"] == "judge_retrieval_unavailable"
        for slot in response.json()["judge_verdicts"]
    )


@pytest.mark.anyio
async def test_qwen_app_without_retrieval_cannot_use_demo_corpus_as_fallback() -> None:
    judge = RecordingJudge()
    app = create_app(mode="qwen", judge=judge)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/v1/finish", json=FINISH_PAYLOAD)
    assert judge.contexts == []
    assert all(
        slot["error_code"] == "judge_retrieval_unavailable"
        for slot in response.json()["judge_verdicts"]
    )


@pytest.mark.anyio
async def test_app_closes_both_owned_clients_on_shutdown() -> None:
    async with httpx.AsyncClient() as model_http, httpx.AsyncClient() as retrieval_http:
        app = create_app(owned_model_http=model_http, owned_retrieval_http=retrieval_http)
        async with app.router.lifespan_context(app):
            assert not model_http.is_closed and not retrieval_http.is_closed
        assert model_http.is_closed and retrieval_http.is_closed


@pytest.mark.parametrize(
    "kwargs",
    [
        {"qdrant_url": "file:///tmp/qdrant"},
        {"embeddings_url": "http://tei.test?bad=1"},
        {"collection": "other-project"},
        {"timeout_seconds": 0},
        {"timeout_seconds": float("inf")},
    ],
)
def test_retrieval_settings_reject_invalid_configuration(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        RetrievalSettings(**kwargs)
