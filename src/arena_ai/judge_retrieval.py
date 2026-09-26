"""Mandatory, college-only retrieval with exact allowlist validation at the model boundary."""

import math
import os
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from arena_ai.contracts import JudgeCollege, JudgeMethodology
from arena_ai.judge_corpus import (
    CHUNKS,
    CORPUS_VERSION,
    CorpusChunk,
    chunks_for_college,
    corpus_filter,
)
from arena_ai.judge_index import DEFAULT_COLLECTION, parse_embedding_response, point_id

QUERIES: dict[JudgeCollege, str] = {
    "hiring": "К кому из двух участников я бы пошёл работать: надёжность, люди и последствия управления?",
    "negotiation": "Кого я отправлю на сложные переговоры: движение к цели, управление и отношения?",
    "ownership": "Кому я доверю ресурс: качество решений, ответственность и управление рисками?",
}
TECHNIQUE_LIMIT = 2


class RetrievalUnavailableError(RuntimeError):
    pass


class InvalidRetrievalError(ValueError):
    pass


class JudgeRetrieval(Protocol):
    async def retrieve(self, college: JudgeCollege) -> object: ...


class DemoJudgeRetrieval:
    async def retrieve(self, college: JudgeCollege) -> object:
        return chunks_for_college(college)


class UnavailableJudgeRetrieval:
    async def retrieve(self, college: JudgeCollege) -> object:
        raise RetrievalUnavailableError("Judge retrieval was not configured")


def methodology_for_college(raw: object, college: JudgeCollege) -> JudgeMethodology:
    if not isinstance(raw, tuple | list) or not raw:
        raise InvalidRetrievalError("Missing judge support")
    allowed = {chunk.chunk_id: chunk for chunk in chunks_for_college(college)}
    seen: set[str] = set()
    selected: list[CorpusChunk] = []
    for chunk in raw:
        if (
            not isinstance(chunk, CorpusChunk)
            or chunk.chunk_id in seen
            or allowed.get(chunk.chunk_id) != chunk
        ):
            raise InvalidRetrievalError("Unreviewed, duplicate or foreign-college support")
        seen.add(chunk.chunk_id)
        selected.append(chunk)
    required = {key for key, chunk in allowed.items() if chunk.scope in ("core", "profile")}
    if not required.issubset(seen):
        raise InvalidRetrievalError("Missing mandatory judge core or college profile")
    techniques = [chunk.text for chunk in selected if chunk.scope == "technique"]
    if not techniques or len(techniques) > TECHNIQUE_LIMIT:
        raise InvalidRetrievalError("Invalid thematic support")
    # Corpus order, not vector score, determines priority of the mandatory guide.
    return JudgeMethodology(
        core=[chunk.text for chunk in CHUNKS if chunk.chunk_id in seen and chunk.scope == "core"],
        profile=[
            chunk.text for chunk in CHUNKS if chunk.chunk_id in seen and chunk.scope == "profile"
        ],
        techniques=techniques,
    )


@dataclass(frozen=True, slots=True)
class RetrievalSettings:
    qdrant_url: str = "http://127.0.0.1:6333"
    embeddings_url: str = "http://127.0.0.1:8081"
    collection: str = DEFAULT_COLLECTION
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        for value in (self.qdrant_url, self.embeddings_url):
            parsed = urlsplit(value)
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.netloc
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("Retrieval URL must be an HTTP base URL")
        if re.fullmatch(r"arena_judge_[a-z0-9_]+", self.collection) is None:
            raise ValueError("Invalid judge retrieval collection")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("Retrieval timeout must be finite and positive")

    @classmethod
    def from_env(cls) -> "RetrievalSettings":
        return cls(
            qdrant_url=os.getenv("ARENA_QDRANT_URL", "http://127.0.0.1:6333"),
            embeddings_url=os.getenv("ARENA_EMBEDDINGS_URL", "http://127.0.0.1:8081"),
            collection=os.getenv("ARENA_JUDGE_COLLECTION", DEFAULT_COLLECTION),
            timeout_seconds=float(os.getenv("ARENA_RETRIEVAL_TIMEOUT_SECONDS", "30")),
        )


def _filter(college: JudgeCollege, scopes: list[str]) -> dict[str, object]:
    base = corpus_filter(college)
    conditions = base["must"]
    assert isinstance(conditions, list)
    return {
        "must": [
            *conditions,
            {"key": "corpus_version", "match": {"value": CORPUS_VERSION}},
            {"key": "scope", "match": {"any": scopes}},
        ]
    }


def _points(
    body: object, college: JudgeCollege, scopes: tuple[str, ...]
) -> tuple[CorpusChunk, ...]:
    if not isinstance(body, dict) or not isinstance(body.get("result"), dict):
        raise InvalidRetrievalError("Invalid Qdrant retrieval envelope")
    points = body["result"].get("points")
    if not isinstance(points, list):
        raise InvalidRetrievalError("Invalid Qdrant retrieval points")
    allowed = {
        point_id(chunk): chunk for chunk in chunks_for_college(college) if chunk.scope in scopes
    }
    selected: list[CorpusChunk] = []
    seen: set[str] = set()
    for point in points:
        if not isinstance(point, dict) or not isinstance(point.get("id"), str):
            raise InvalidRetrievalError("Invalid retrieved point ID")
        chunk = allowed.get(point["id"])
        if chunk is None or chunk.chunk_id in seen or point.get("payload") != chunk.payload():
            raise InvalidRetrievalError("Retrieved point differs from reviewed corpus")
        seen.add(chunk.chunk_id)
        selected.append(chunk)
    return tuple(selected)


class QdrantJudgeRetrieval:
    def __init__(self, client: httpx.AsyncClient, settings: RetrievalSettings) -> None:
        self.client = client
        self.settings = settings
        self.url = f"{settings.qdrant_url.rstrip('/')}/collections/{settings.collection}/points"

    async def _post(self, url: str, body: dict[str, object]) -> object:
        try:
            response = await self.client.post(url, json=body, timeout=self.settings.timeout_seconds)
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise RetrievalUnavailableError("Judge retrieval HTTP unavailable") from error
        try:
            return response.json()
        except ValueError as error:
            raise InvalidRetrievalError("Invalid retrieval JSON") from error

    async def retrieve(self, college: JudgeCollege) -> object:
        mandatory: list[CorpusChunk] = []
        offset: str | int | None = None
        offsets: set[str | int] = set()
        while True:
            request: dict[str, object] = {
                "filter": _filter(college, ["core", "profile"]),
                "with_payload": True,
                "with_vector": False,
                "limit": 100,
            }
            if offset is not None:
                request["offset"] = offset
            body = await self._post(f"{self.url}/scroll", request)
            mandatory.extend(_points(body, college, ("core", "profile")))
            assert isinstance(body, dict)
            offset = body["result"].get("next_page_offset")
            if offset is None:
                break
            if isinstance(offset, bool) or not isinstance(offset, str | int) or offset in offsets:
                raise InvalidRetrievalError("Invalid retrieval scroll pagination")
            offsets.add(offset)
            if len(mandatory) > len(CHUNKS) or len(offsets) > len(CHUNKS):
                raise InvalidRetrievalError("Too many retrieval pages or mandatory chunks")

        required = {
            chunk.chunk_id
            for chunk in chunks_for_college(college)
            if chunk.scope in ("core", "profile")
        }
        if len(mandatory) != len(required) or {chunk.chunk_id for chunk in mandatory} != required:
            raise InvalidRetrievalError("Missing or duplicate mandatory judge support")

        query = (
            "Instruct: Retrieve negotiation methodology relevant to this judge college.\n"
            f"Query: {QUERIES[college]}"
        )
        raw_embedding = await self._post(
            f"{self.settings.embeddings_url.rstrip('/')}/embed",
            {"inputs": [query], "truncate": False},
        )
        try:
            vector = parse_embedding_response(raw_embedding)
        except (ValueError, TypeError) as error:
            raise InvalidRetrievalError("Invalid retrieval embedding") from error
        body = await self._post(
            f"{self.url}/query",
            {
                "query": vector,
                "filter": _filter(college, ["technique"]),
                "limit": TECHNIQUE_LIMIT,
                "with_payload": True,
                "with_vector": False,
            },
        )
        techniques = _points(body, college, ("technique",))
        support = (*mandatory, *techniques)
        methodology_for_college(support, college)
        return support
