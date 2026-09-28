from pathlib import Path

import httpx
import pytest
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


def test_source_verification_runs_only_when_sources_are_given(tmp_path):
    fake = MemoryRag()
    with pytest.raises(FileNotFoundError):
        run(fake, "--source-root", str(tmp_path))
    assert not fake.points


def test_verify_only_checks_excerpts_against_local_sources_without_network():
    sources = Path(__file__).resolve().parents[1]
    if not (sources / "knowledge-base" / "methodology").is_dir():
        pytest.skip("Private methodology sources are not available in this checkout")

    def offline(request):
        raise AssertionError("Verification must not reach Qdrant or embeddings")

    with httpx.Client(transport=httpx.MockTransport(offline)) as client:
        main(["--verify-only", "--source-root", str(sources)], client=client)
