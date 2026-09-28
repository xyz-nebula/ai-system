"""Index the curated judge excerpts into Qdrant: `arena-ai-index`."""

import argparse
import os
from collections.abc import Sequence

import httpx

from arena_ai.cli_args import positive_timeout
from arena_ai.judge_corpus import validate_corpus
from arena_ai.judge_index import DEFAULT_COLLECTION, index_corpus, verify_index


def main(argv: Sequence[str] | None = None, *, client: httpx.Client | None = None) -> None:
    parser = argparse.ArgumentParser(description="Индексация методологии судей в Qdrant")
    parser.add_argument(
        "--check-index", action="store_true", help="проверить уже заполненный индекс"
    )
    parser.add_argument(
        "--qdrant-url", default=os.getenv("ARENA_QDRANT_URL", "http://127.0.0.1:6333")
    )
    parser.add_argument(
        "--embeddings-url", default=os.getenv("ARENA_EMBEDDINGS_URL", "http://127.0.0.1:8081")
    )
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--timeout", type=positive_timeout, default=180.0)
    args = parser.parse_args(argv)

    validate_corpus()
    if client is None:
        with httpx.Client(timeout=args.timeout) as http:
            run(args, http)
    else:
        run(args, client)


def run(args: argparse.Namespace, http: httpx.Client) -> None:
    if args.check_index:
        counts = verify_index(http, qdrant_url=args.qdrant_url, collection=args.collection)
        print(f"Verified indexed judge corpus: {counts}")
        return
    result = index_corpus(
        http,
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
