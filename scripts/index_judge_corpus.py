"""Verify and index the reviewed judge corpus without touching LocalAI's port 8080."""

import argparse
import os
from pathlib import Path

import httpx

from arena_ai.cli_args import positive_timeout
from arena_ai.judge_corpus import CHUNKS, validate_corpus
from arena_ai.judge_index import DEFAULT_COLLECTION, index_corpus, verify_index


def main() -> None:
    parser = argparse.ArgumentParser(description="Проверка и индексация судейского корпуса")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify-only", action="store_true")
    mode.add_argument("--check-index", action="store_true")
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--qdrant-url", default=os.getenv("ARENA_QDRANT_URL", "http://127.0.0.1:6333")
    )
    parser.add_argument(
        "--embeddings-url", default=os.getenv("ARENA_EMBEDDINGS_URL", "http://127.0.0.1:8081")
    )
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--timeout", type=positive_timeout, default=180.0)
    args = parser.parse_args()

    validate_corpus(source_root=args.source_root)
    if args.verify_only:
        print(f"Verified {len(CHUNKS)} curated judge excerpts against source pages")
        return
    with httpx.Client(timeout=args.timeout) as client:
        if args.check_index:
            counts = verify_index(client, qdrant_url=args.qdrant_url, collection=args.collection)
            print(f"Verified indexed judge corpus: {counts}")
            return
        result = index_corpus(
            client,
            qdrant_url=args.qdrant_url,
            embeddings_url=args.embeddings_url,
            collection=args.collection,
        )
    print(
        f"Indexed {result.indexed} judge excerpts in {result.collection} "
        f"(dimension={result.dimension}, stale removed={result.removed})"
    )


if __name__ == "__main__":
    main()
