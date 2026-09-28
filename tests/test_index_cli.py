import httpx
from test_judge_index import EMBEDDINGS_URL, QDRANT_URL, MemoryRag

from arena_ai.index_corpus import main
from arena_ai.judge_corpus import CHUNKS


def run(fake: MemoryRag, *arguments: str) -> None:
    with httpx.Client(transport=httpx.MockTransport(fake)) as client:
        main(
            ["--qdrant-url", QDRANT_URL, "--embeddings-url", EMBEDDINGS_URL, *arguments],
            client=client,
        )


def test_fresh_clone_indexes_the_excerpts_from_code(monkeypatch, tmp_path, capsys):
    # The methodology PDFs are not published; the curated excerpts in code are enough.
    monkeypatch.chdir(tmp_path)
    fake = MemoryRag()
    run(fake)
    assert len(fake.points) == len(CHUNKS)
    assert f"Indexed {len(CHUNKS)} judge excerpts" in capsys.readouterr().out
    run(fake, "--check-index")
    assert "Verified indexed judge corpus" in capsys.readouterr().out
