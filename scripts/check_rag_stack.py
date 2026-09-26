"""Smoke-test Qwen3 embeddings and Qdrant through their HTTP interfaces."""

import argparse
import os
from uuid import uuid4

import httpx

DOCUMENTS = (
    {
        "text": "BATNA — лучший запасной вариант, если соглашение на переговорах не достигнуто.",
        "topic": "batna",
    },
    {
        "text": "Открытые вопросы помогают выяснить интересы и ограничения другой стороны.",
        "topic": "discovery",
    },
    {
        "text": "Якорь задаёт исходную точку обсуждения цены или других условий сделки.",
        "topic": "anchoring",
    },
)
QUERY = (
    "Instruct: Найди фрагмент базы знаний о резервном варианте на случай провала переговоров.\n"
    "Query: Что такое BATNA?"
)


def url(value: str) -> str:
    return value.rstrip("/")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Проверка полного цикла embeddings → Qdrant → semantic search"
    )
    parser.add_argument(
        "--qdrant-url",
        default=os.environ.get("ARENA_QDRANT_URL", "http://127.0.0.1:6333"),
    )
    parser.add_argument(
        "--embeddings-url",
        default=os.environ.get("ARENA_EMBEDDINGS_URL", "http://127.0.0.1:8081"),
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    qdrant_url = url(args.qdrant_url)
    embeddings_url = url(args.embeddings_url)
    collection = f"arena_rag_smoke_{uuid4().hex[:12]}"

    with httpx.Client(timeout=args.timeout) as client:
        qdrant = client.get(qdrant_url)
        qdrant.raise_for_status()
        embedding_health = client.get(f"{embeddings_url}/health")
        embedding_health.raise_for_status()

        texts = [document["text"] for document in DOCUMENTS]
        response = client.post(
            f"{embeddings_url}/embed",
            json={"inputs": [*texts, QUERY], "truncate": True},
        )
        response.raise_for_status()
        vectors = response.json()
        if not isinstance(vectors, list) or len(vectors) != len(texts) + 1:
            raise RuntimeError("Embedding service returned an unexpected batch")
        dimensions = {len(vector) for vector in vectors if isinstance(vector, list)}
        if len(dimensions) != 1 or len(vectors) not in (4,):
            raise RuntimeError("Embedding vectors have inconsistent dimensions")
        dimension = dimensions.pop()
        if dimension <= 0:
            raise RuntimeError("Embedding vectors are empty")

        try:
            create = client.put(
                f"{qdrant_url}/collections/{collection}",
                json={"vectors": {"size": dimension, "distance": "Cosine"}},
            )
            create.raise_for_status()
            upsert = client.put(
                f"{qdrant_url}/collections/{collection}/points",
                params={"wait": "true"},
                json={
                    "points": [
                        {
                            "id": index,
                            "vector": vectors[index - 1],
                            "payload": {
                                "text": document["text"],
                                "topic": document["topic"],
                                "source": "rag-smoke-test",
                                "section": str(index),
                                "type": "knowledge",
                                "usable_for": ["coach", "opponent", "judge"],
                            },
                        }
                        for index, document in enumerate(DOCUMENTS, start=1)
                    ]
                },
            )
            upsert.raise_for_status()
            query = client.post(
                f"{qdrant_url}/collections/{collection}/points/query",
                json={
                    "query": vectors[-1],
                    "limit": 2,
                    "with_payload": True,
                },
            )
            query.raise_for_status()
            points = query.json().get("result", {}).get("points", [])
            if not points or points[0].get("payload", {}).get("topic") != "batna":
                raise RuntimeError("Semantic search did not rank the BATNA chunk first")
        finally:
            client.delete(f"{qdrant_url}/collections/{collection}")

    print(
        f"RAG stack ready: embedding dimension={dimension}, "
        f"top topic={points[0]['payload']['topic']}"
    )


if __name__ == "__main__":
    main()
