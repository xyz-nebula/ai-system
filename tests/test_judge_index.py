import json
from typing import Any

import httpx
import pytest

from arena_ai.judge_corpus import ALL_COLLEGES, CHUNKS, CORPUS_ID, chunks_for_college
from arena_ai.judge_index import index_corpus, point_id, verify_index

QDRANT_URL = "http://qdrant.test"
EMBEDDINGS_URL = "http://embeddings.test"


class MemoryRag:
    """HTTP contract double with pagination and Qdrant's array membership filtering."""

    def __init__(self) -> None:
        self.exists = False
        self.dimension = 3
        self.points: dict[str, dict[str, Any]] = {}
        self.indexes: dict[str, dict[str, str]] = {}
        self.requests: list[tuple[str, str, Any]] = []
        self.fail_embeddings = False
        self.fail_upsert = False
        self.foreign_scroll = False
        self.inconsistent_embeddings = False
        self.embedding_calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body: dict[str, Any] = json.loads(request.content) if request.content else {}
        self.requests.append((request.method, request.url.path, body))
        if request.url.host == "embeddings.test":
            assert request.url.path == "/embed"
            assert body["truncate"] is False
            assert len(body["inputs"]) == 1
            self.embedding_calls += 1
            if self.fail_embeddings:
                return httpx.Response(503)
            size = 2 if self.inconsistent_embeddings and self.embedding_calls == 2 else 3
            return httpx.Response(200, json=[[1.0] * size])
        path = request.url.path
        if request.method == "GET":
            if not self.exists:
                return httpx.Response(404)
            return httpx.Response(
                200,
                json={
                    "result": {
                        "config": {
                            "params": {"vectors": {"size": self.dimension, "distance": "Cosine"}}
                        },
                        "payload_schema": self.indexes,
                    }
                },
            )
        if path.endswith("/index"):
            assert request.url.params["wait"] == "true"
            self.indexes[body["field_name"]] = {"data_type": body["field_schema"]}
        elif path.endswith("/points/scroll"):
            conditions = body["filter"]["must"]
            selected = [
                point
                for point in self.points.values()
                if all(
                    condition["match"]["value"] in point["payload"].get(condition["key"], [])
                    if isinstance(point["payload"].get(condition["key"]), list)
                    else point["payload"].get(condition["key"]) == condition["match"]["value"]
                    for condition in conditions
                )
            ]
            if self.foreign_scroll:
                selected.append(
                    {
                        "id": "foreign",
                        "payload": {
                            "chunk_id": "foreign",
                            "purpose": "coach",
                            "corpus_id": "foreign",
                        },
                    }
                )
            selected.sort(key=lambda point: point["id"])
            start = next(
                (
                    index
                    for index, point in enumerate(selected)
                    if point["id"] == body.get("offset")
                ),
                0,
            )
            page = selected[start : start + 4]
            offset = selected[start + 4]["id"] if start + 4 < len(selected) else None
            return httpx.Response(
                200, json={"result": {"points": page, "next_page_offset": offset}}
            )
        elif path.endswith("/points/delete"):
            assert request.url.params["wait"] == "true"
            for identifier in body["points"]:
                del self.points[identifier]
        elif path.endswith("/points"):
            assert request.url.params["wait"] == "true"
            if self.fail_upsert:
                return httpx.Response(503)
            for point in body["points"]:
                self.points[point["id"]] = point
        else:
            assert request.method == "PUT"
            assert body == {"vectors": {"size": 3, "distance": "Cosine"}}
            self.exists = True
        return httpx.Response(200, json={"result": {"status": "completed"}})


def _index(fake: MemoryRag) -> None:
    with httpx.Client(transport=httpx.MockTransport(fake)) as client:
        result = index_corpus(client, qdrant_url=QDRANT_URL, embeddings_url=EMBEDDINGS_URL)
    assert result.indexed == len(CHUNKS)
    assert result.dimension == 3


def test_index_is_idempotent_and_each_college_retrieves_only_its_reviewed_chunks() -> None:
    fake = MemoryRag()
    _index(fake)
    first = dict(fake.points)
    _index(fake)
    assert fake.points == first
    assert set(fake.points) == {point_id(chunk) for chunk in CHUNKS}
    assert set(fake.indexes) == {"purpose", "corpus_id", "scope", "colleges"}
    with httpx.Client(transport=httpx.MockTransport(fake)) as client:
        counts = verify_index(client, qdrant_url=QDRANT_URL)
    assert counts == {college: len(chunks_for_college(college)) for college in ALL_COLLEGES}
    assert not any(path.endswith("/delete") for _, path, _ in fake.requests)


def test_reindex_removes_only_stale_points_owned_by_this_corpus() -> None:
    fake = MemoryRag()
    _index(fake)
    fake.points["stale"] = {
        "id": "stale",
        "payload": {
            "chunk_id": "removed-in-new-version",
            "purpose": "judge",
            "corpus_id": CORPUS_ID,
        },
    }
    fake.points["foreign"] = {
        "id": "foreign",
        "payload": {"chunk_id": "other", "purpose": "coach", "corpus_id": "other"},
    }
    with httpx.Client(transport=httpx.MockTransport(fake)) as client:
        result = index_corpus(client, qdrant_url=QDRANT_URL, embeddings_url=EMBEDDINGS_URL)
    assert result.removed == 1
    assert "stale" not in fake.points
    assert "foreign" in fake.points
    deletes = [body for _, path, body in fake.requests if path.endswith("/points/delete")]
    assert deletes == [{"points": ["stale"]}]


@pytest.mark.parametrize("failure", ["fail_embeddings", "fail_upsert", "inconsistent_embeddings"])
def test_failed_indexing_never_deletes_existing_points(failure: str) -> None:
    fake = MemoryRag()
    _index(fake)
    before = dict(fake.points)
    fake.embedding_calls = 0
    setattr(fake, failure, True)
    with pytest.raises((httpx.HTTPStatusError, ValueError)):
        _index(fake)
    assert fake.points == before
    assert not any(path.endswith("/points/delete") for _, path, _ in fake.requests)


def test_incompatible_collection_vectors_are_not_recreated_or_overwritten() -> None:
    fake = MemoryRag()
    _index(fake)
    fake.dimension = 1024
    fake.requests.clear()
    with pytest.raises(ValueError, match="incompatible vectors"):
        _index(fake)
    assert not any(method != "GET" and "/collections/" in path for method, path, _ in fake.requests)


@pytest.mark.parametrize("reply", [[], [[]], [[0.0, 0.0]], [[True, 1.0]], [["invalid"]]])
def test_invalid_embeddings_fail_before_any_qdrant_mutation(reply: object) -> None:
    fake = MemoryRag()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "embeddings.test":
            return httpx.Response(200, json=reply)
        return fake(request)

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(ValueError),
    ):
        index_corpus(client, qdrant_url=QDRANT_URL, embeddings_url=EMBEDDINGS_URL)
    assert fake.requests == []


def test_incompatible_existing_payload_index_is_not_overwritten() -> None:
    fake = MemoryRag()
    _index(fake)
    fake.indexes["colleges"] = {"data_type": "integer"}
    fake.requests.clear()
    with pytest.raises(ValueError, match="payload index is incompatible"):
        _index(fake)
    assert not any(method != "GET" and "/collections/" in path for method, path, _ in fake.requests)


def test_scroll_outside_ownership_filter_fails_before_cleanup() -> None:
    fake = MemoryRag()
    _index(fake)
    fake.foreign_scroll = True
    with pytest.raises(ValueError, match="outside the managed corpus"):
        _index(fake)
    assert not any(path.endswith("/points/delete") for _, path, _ in fake.requests)


def test_collection_name_guard_rejects_unrelated_targets_before_network_calls() -> None:
    fake = MemoryRag()
    with (
        httpx.Client(transport=httpx.MockTransport(fake)) as client,
        pytest.raises(ValueError, match="must start with arena_judge_"),
    ):
        index_corpus(
            client,
            qdrant_url=QDRANT_URL,
            embeddings_url=EMBEDDINGS_URL,
            collection="production_customer_data",
        )
    assert fake.requests == []


@pytest.mark.parametrize("field", ["text", "source_path", "text_sha256", "corpus_version"])
def test_read_only_check_rejects_changed_text_or_provenance(field: str) -> None:
    fake = MemoryRag()
    _index(fake)
    fake.points[point_id(CHUNKS[0])]["payload"][field] = "unreviewed value"
    fake.requests.clear()
    with (
        httpx.Client(transport=httpx.MockTransport(fake)) as client,
        pytest.raises(ValueError, match="payload differs from reviewed corpus"),
    ):
        verify_index(client, qdrant_url=QDRANT_URL)
    assert all(path.endswith("/points/scroll") for _, path, _ in fake.requests)
