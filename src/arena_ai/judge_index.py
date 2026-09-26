"""Idempotent indexing of the curated judge corpus into a dedicated Qdrant collection."""

import math
import re
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

import httpx

from arena_ai.contracts import JudgeCollege
from arena_ai.judge_corpus import (
    ALL_COLLEGES,
    CHUNKS,
    CORPUS_ID,
    CorpusChunk,
    chunks_for_college,
    corpus_filter,
    validate_corpus,
)

DEFAULT_COLLECTION = "arena_judge_methodology_v1"


@dataclass(frozen=True, slots=True)
class IndexResult:
    collection: str
    indexed: int
    removed: int
    dimension: int


def point_id(chunk: CorpusChunk) -> str:
    return str(uuid5(NAMESPACE_URL, f"{CORPUS_ID}/{chunk.chunk_id}"))


def _embedding(client: httpx.Client, url: str, text: str) -> list[float]:
    response = client.post(
        f"{url.rstrip('/')}/embed",
        json={"inputs": [text], "truncate": False},
    )
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, list) or len(body) != 1 or not isinstance(body[0], list):
        raise ValueError("invalid embeddings response")
    vector = body[0]
    if (
        not vector
        or not any(vector)
        or any(
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
            for value in vector
        )
    ):
        raise ValueError("invalid embedding vector")
    return [float(value) for value in vector]


def _collection_url(base: str, collection: str) -> str:
    if re.fullmatch(r"arena_judge_[a-z0-9_]+", collection) is None:
        raise ValueError("judge collection name must start with arena_judge_")
    return f"{base.rstrip('/')}/collections/{collection}"


def _ensure_collection(client: httpx.Client, url: str, dimension: int) -> None:
    response = client.get(url)
    if response.status_code == 404:
        created = client.put(url, json={"vectors": {"size": dimension, "distance": "Cosine"}})
        created.raise_for_status()
        indexed_fields: set[str] = set()
    else:
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or not isinstance(body.get("result"), dict):
            raise TypeError("invalid Qdrant collection response")
        result = body["result"]
        params = result.get("config", {}).get("params", {})
        vectors = params.get("vectors", {})
        if vectors.get("size") != dimension or vectors.get("distance") != "Cosine":
            raise ValueError("existing judge collection has incompatible vectors")
        schema = result.get("payload_schema", {})
        if not isinstance(schema, dict):
            raise ValueError("invalid judge payload schema")
        for field in ("purpose", "corpus_id", "scope", "colleges"):
            if field in schema and (
                not isinstance(schema[field], dict) or schema[field].get("data_type") != "keyword"
            ):
                raise ValueError("existing judge payload index is incompatible")
        indexed_fields = set(schema)

    for field in ("purpose", "corpus_id", "scope", "colleges"):
        if field not in indexed_fields:
            index = client.put(
                f"{url}/index",
                params={"wait": "true"},
                json={"field_name": field, "field_schema": "keyword"},
            )
            index.raise_for_status()


def _managed_points(
    client: httpx.Client,
    url: str,
    college: JudgeCollege | None = None,
    expected_payloads: dict[str, dict[str, object]] | None = None,
) -> dict[str, str]:
    """Scroll only this corpus, never assuming ownership of other Qdrant points."""

    points: dict[str, str] = {}
    offset: str | int | None = None
    seen_offsets: set[str | int] = set()
    while True:
        body: dict[str, object] = {
            "filter": corpus_filter(college),
            "with_payload": (
                True
                if expected_payloads is not None
                else ["chunk_id", "purpose", "corpus_id", "colleges"]
            ),
            "with_vector": False,
            "limit": 100,
        }
        if offset is not None:
            body["offset"] = offset
        response = client.post(f"{url}/points/scroll", json=body)
        response.raise_for_status()
        envelope = response.json()
        if not isinstance(envelope, dict):
            raise TypeError("invalid Qdrant scroll envelope")
        result = envelope.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("points"), list):
            raise TypeError("invalid Qdrant scroll response")
        for point in result["points"]:
            if not isinstance(point, dict) or not isinstance(point.get("id"), str):
                raise TypeError("invalid managed Qdrant point")
            payload = point.get("payload")
            if not isinstance(payload, dict) or not isinstance(payload.get("chunk_id"), str):
                raise TypeError("invalid managed Qdrant payload")
            if payload.get("purpose") != "judge" or payload.get("corpus_id") != CORPUS_ID:
                raise ValueError("Qdrant returned a point outside the managed corpus")
            if college is not None:
                colleges = payload.get("colleges")
                if not isinstance(colleges, list) or college not in colleges:
                    raise ValueError("Qdrant returned a point outside the college filter")
            if (
                expected_payloads is not None
                and point["id"] in expected_payloads
                and payload != expected_payloads[point["id"]]
            ):
                raise ValueError("indexed judge payload differs from reviewed corpus")
            points[point["id"]] = payload["chunk_id"]
        next_offset = result.get("next_page_offset")
        if next_offset is None:
            return points
        if isinstance(next_offset, bool) or not isinstance(next_offset, str | int):
            raise TypeError("invalid Qdrant scroll offset")
        if next_offset in seen_offsets:
            raise ValueError("invalid Qdrant scroll offset")
        seen_offsets.add(next_offset)
        offset = next_offset


def verify_index(
    client: httpx.Client, *, qdrant_url: str, collection: str = DEFAULT_COLLECTION
) -> dict[JudgeCollege, int]:
    """Read-only verification that each college sees exactly its reviewed corpus."""

    url = _collection_url(qdrant_url, collection)
    counts: dict[JudgeCollege, int] = {}
    for college in ALL_COLLEGES:
        chunks = chunks_for_college(college)
        expected = {point_id(chunk): chunk.chunk_id for chunk in chunks}
        payloads = {point_id(chunk): chunk.payload() for chunk in chunks}
        if _managed_points(client, url, college, payloads) != expected:
            raise ValueError(f"indexed judge corpus differs for college: {college}")
        counts[college] = len(expected)
    return counts


def index_corpus(
    client: httpx.Client,
    *,
    qdrant_url: str,
    embeddings_url: str,
    collection: str = DEFAULT_COLLECTION,
) -> IndexResult:
    """Upsert stable point IDs, then prune only stale points owned by this corpus."""

    validate_corpus()
    url = _collection_url(qdrant_url, collection)
    vectors = [_embedding(client, embeddings_url, chunk.text) for chunk in CHUNKS]
    dimensions = {len(vector) for vector in vectors}
    if len(dimensions) != 1:
        raise ValueError("embedding dimensions differ across corpus chunks")
    dimension = dimensions.pop()
    _ensure_collection(client, url, dimension)

    desired = {point_id(chunk): chunk.chunk_id for chunk in CHUNKS}
    upsert = client.put(
        f"{url}/points",
        params={"wait": "true"},
        json={
            "points": [
                {"id": point_id(chunk), "vector": vector, "payload": chunk.payload()}
                for chunk, vector in zip(CHUNKS, vectors, strict=True)
            ]
        },
    )
    upsert.raise_for_status()

    found = _managed_points(
        client, url, expected_payloads={point_id(chunk): chunk.payload() for chunk in CHUNKS}
    )
    if any(found.get(identifier) != chunk_id for identifier, chunk_id in desired.items()):
        raise ValueError("Qdrant did not persist every judge chunk")
    stale_ids = sorted(set(found) - set(desired))
    if stale_ids:
        deleted = client.post(
            f"{url}/points/delete",
            params={"wait": "true"},
            json={"points": stale_ids},
        )
        deleted.raise_for_status()
    verify_index(client, qdrant_url=qdrant_url, collection=collection)
    return IndexResult(collection, len(CHUNKS), len(stale_ids), dimension)
