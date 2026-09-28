from dataclasses import replace

import pytest

from arena_ai import judge_corpus
from arena_ai.judge_corpus import (
    ALL_COLLEGES,
    CHUNKS,
    SOURCES,
    chunks_for_college,
    cites_source_title,
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
        assert payload["source"] in SOURCES
        assert not {"source_path", "source_name", "source_pdf_sha256"} & payload.keys()
        assert payload["purpose"] == "judge"
        assert payload["corpus_version"]
        assert payload["page"] == chunk.page
        assert len(chunk.text_sha256) == 64
        assert chunk.payload() == payload
        assert replace(chunk, text=f"{chunk.text} changed").text_sha256 != chunk.text_sha256
        for forbidden in ("business/", "backend/", "ai-system/", "Риск наставника"):
            assert forbidden not in str(payload)


def test_duplicate_chunk_ids_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(judge_corpus, "CHUNKS", (*CHUNKS, CHUNKS[0]))
    with pytest.raises(ValueError, match="duplicate chunk_id"):
        validate_corpus()


@pytest.mark.parametrize(
    ("text", "cited"),
    [
        ("Как сказано в «Подготовке к переговорам»", False),
        ("Согласно пособию «Подготовка к переговорам», это верно", True),
        ("ГАЙД ПО СУДЕЙСТВУ УПРАВЛЕНЧЕСКИХ ПОЕДИНКОВ", True),
        ("Аргументация была слабой", False),
    ],
)
def test_leak_guard_recognises_manual_titles(text: str, cited: bool) -> None:
    assert cites_source_title(text) is cited
