from dataclasses import replace
from pathlib import Path

import pytest

from arena_ai import judge_corpus
from arena_ai.judge_corpus import (
    ALL_COLLEGES,
    CHUNKS,
    SOURCES,
    chunks_for_college,
    validate_corpus,
)


def test_every_college_has_the_same_core_and_only_its_own_profile() -> None:
    validate_corpus()
    core_ids = {chunk.chunk_id for chunk in CHUNKS if chunk.scope == "core"}
    assert len(core_ids) == 6
    for college in ALL_COLLEGES:
        selected = chunks_for_college(college)
        assert {chunk.chunk_id for chunk in selected if chunk.scope == "core"} == core_ids
        profiles = [chunk for chunk in selected if chunk.scope == "profile"]
        assert len(profiles) == 2
        assert all(profile.colleges == (college,) for profile in profiles)
        assert all(college in chunk.colleges for chunk in selected)


def test_corpus_has_only_reviewed_methodology_and_reproducible_provenance() -> None:
    assert len({chunk.chunk_id for chunk in CHUNKS}) == len(CHUNKS)
    for chunk in CHUNKS:
        payload = chunk.payload()
        assert str(payload["source_path"]).startswith("knowledge-base/methodology/")
        assert payload["purpose"] == "judge"
        assert payload["corpus_version"]
        assert payload["page"] == chunk.page
        assert len(chunk.text_sha256) == 64
        assert chunk.payload() == payload
        assert replace(chunk, text=f"{chunk.text} changed").text_sha256 != chunk.text_sha256
        for forbidden in ("business/", "backend/", "ai-system/", "Риск наставника"):
            assert forbidden not in str(payload)


def _source_fixture(root: Path) -> None:
    for key, source in SOURCES.items():
        pages: dict[int, list[str]] = {}
        for chunk in CHUNKS:
            if chunk.source == key:
                pages.setdefault(chunk.page, []).append(chunk.text)
        text = (
            f"**Источник:** `{source.pdf_name}`\n"
            f"**SHA-256 оригинального PDF:** `{source.pdf_sha256}`\n\n"
        )
        for page, excerpts in sorted(pages.items()):
            text += f"## Страница {page}\n\n```text\n" + "\n\n".join(excerpts) + "\n```\n\n"
        path = root / source.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def test_source_verification_rejects_excerpt_missing_from_its_declared_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _source_fixture(tmp_path)
    validate_corpus(source_root=tmp_path)
    changed = replace(CHUNKS[0], page=3)
    monkeypatch.setattr(judge_corpus, "CHUNKS", (changed, *CHUNKS[1:]))
    with pytest.raises(ValueError, match="excerpt not on source page"):
        validate_corpus(source_root=tmp_path)


def test_source_verification_rejects_changed_origin_hash(tmp_path: Path) -> None:
    _source_fixture(tmp_path)
    source = SOURCES["guide"]
    path = tmp_path / source.path
    path.write_text(path.read_text().replace(source.pdf_sha256, "0" * 64), encoding="utf-8")
    with pytest.raises(ValueError, match="source metadata changed"):
        validate_corpus(source_root=tmp_path)


def test_duplicate_chunk_ids_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(judge_corpus, "CHUNKS", (*CHUNKS, CHUNKS[0]))
    with pytest.raises(ValueError, match="duplicate chunk_id"):
        validate_corpus()


def test_real_methodology_checkout_matches_all_curated_excerpts() -> None:
    root = Path(__file__).resolve().parents[1]
    if not all((root / source.path).is_file() for source in SOURCES.values()):
        pytest.skip("Original methodology checkout absent; use --source-root to verify it")
    validate_corpus(source_root=root)
