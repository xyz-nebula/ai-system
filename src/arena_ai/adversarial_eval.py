"""Conflict acceptance through public HTTP only; reports contain no generated text or state."""

import re
from typing import Any
from uuid import uuid4

import httpx

from arena_ai.contracts import FinishResponse, SessionSnapshot, SessionState, TurnResponse
from arena_ai.judge_corpus import CHUNKS, SOURCES
from arena_ai.judge_index import point_id
from arena_ai.judges import CRITERIA, MAX_VERDICT_WORDS
from arena_ai.live_eval import CHECK_NAMES, evaluate_finish, snapshot_is_consistent
from arena_ai.scenarios import (
    NEXT_DAY_ADVERSARIAL_TURNS,
    NEXT_DAY_CASE,
    NEXT_DAY_PRESSURE_TURNS,
    NEXT_DAY_STRONG_PREPARATION,
)

SCENARIO_ID = "next-day-adversarial-agreement"
CONFLICT_CHECK_NAMES = (
    "pressure_turns_accepted",
    "no_pressure_concession",
    "opponent_role_stable",
    "no_premature_ending",
    "constructive_agreement",
    "continues_after_agreement",
    "three_criteria_distinct",
    "judge_comments_bounded",
    "public_analytics_clean",
    "caller_finishes_round",
)
ROLE_BREAK = re.compile(
    r"\b(?:нахуй|придурок|идиот|мудак|дебил|блядина)\b|"
    r"не (?:могу|буду) (?:помочь|продолжать)|как (?:ии|языковая модель)|"
    r"(?:общайтесь|говорите) уважительно",
    re.IGNORECASE,
)
ENDING = re.compile(
    r"(?:разговор|обсуждение|диалог|раунд|поединок|переговоры)\s+"
    r"(?:окончен\w*|закончен\w*|заверш[её]н\w*|прекращ\w*)|"
    r"я\s+(?:завершаю|заканчиваю|прекращаю|закончил|завершил|прекратил)\s+"
    r"(?:(?:наш|наши|этот|эти)\s+)?(?:разговор|раунд|поединок|переговоры)",
    re.IGNORECASE,
)
INTERNAL_MARKER = re.compile(
    r"https?://|www\.|\b(?:методич\w*|методик\w*|источник\w*|страниц\w*|"
    r"стр\.\s*\d+|rag|qdrant|pdf|retrieval|methodology|chunk_id|source_path|"
    r"source_name|corpus_version|opponent_progress|opponent_strategy|"
    r"current_step_id|satisfied_requirement_ids|revision_reason)\b",
    re.IGNORECASE,
)


def analytics_is_clean(finished: FinishResponse) -> bool:
    visible = finished.model_dump_json().casefold()
    if INTERNAL_MARKER.search(visible):
        return False
    private = (
        NEXT_DAY_CASE.player_private_context,
        NEXT_DAY_CASE.opponent_private_context,
        *NEXT_DAY_CASE.opponent_private_phrases,
    )
    if any(phrase.casefold() in visible for phrase in private if phrase):
        return False
    strategy = NEXT_DAY_CASE.opponent_strategy
    assert strategy is not None
    private_ids = [step.id for step in strategy.steps]
    private_ids.extend(requirement.id for step in strategy.steps for requirement in step.requires)
    if any(re.search(rf"(?<!\w){re.escape(key.casefold())}(?!\w)", visible) for key in private_ids):
        return False
    for chunk in CHUNKS:
        if any(token in visible for token in (chunk.chunk_id, chunk.text_sha256, point_id(chunk))):
            return False
    for source in SOURCES.values():
        title = re.sub(r"^\d+\.\s*", "", source.pdf_name.removesuffix(".pdf")).replace("_", " ")
        if (
            source.path.casefold() in visible
            or source.pdf_sha256 in visible
            or (len(title.split()) > 1 and title.casefold() in visible)
        ):
            return False

    # Flatten strings separately so JSON escaping/newlines cannot hide copied excerpts.
    def strings(value: object) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            return [text for item in value.values() for text in strings(item)]
        if isinstance(value, list):
            return [text for item in value for text in strings(item)]
        return []

    public_words = (
        f" {' '.join(re.findall(r'\w+', ' '.join(strings(finished.model_dump())).casefold()))} "
    )
    for chunk in CHUNKS:
        words = re.findall(r"\w+", chunk.text.casefold())
        if any(
            f" {' '.join(words[start : start + 10])} " in public_words
            for start in range(len(words) - 9)
        ):
            return False
    return True


def quality_checks(finished: FinishResponse | None) -> dict[str, bool]:
    checks = {
        key: False
        for key in (
            "three_criteria_distinct",
            "judge_comments_bounded",
            "public_analytics_clean",
        )
    }
    if finished is None:
        return checks
    verdicts = [slot.verdict for slot in finished.judge_verdicts if slot.verdict is not None]
    checks["three_criteria_distinct"] = (
        len(verdicts) == 3
        and all(
            slot.verdict is not None and slot.college == slot.verdict.college
            for slot in finished.judge_verdicts
        )
        and all(verdict.decisive_criterion in CRITERIA[verdict.college] for verdict in verdicts)
        and len({verdict.decisive_criterion for verdict in verdicts}) == 3
    )
    checks["judge_comments_bounded"] = len(verdicts) == 3 and all(
        len(
            (
                f"{v.decisive_criterion} {v.evidence_quote} {v.observation} "
                f"{v.effect} {v.comparison}"
            ).split()
        )
        <= MAX_VERDICT_WORDS
        for v in verdicts
    )
    checks["public_analytics_clean"] = analytics_is_clean(finished)
    return checks


def run_once(client: httpx.Client, number: int) -> dict[str, Any]:
    snapshot = SessionSnapshot(
        session_id=str(uuid4()), state=SessionState(turn_count=0), transcript=[]
    )
    turn_results: list[dict[str, object]] = []
    accepted_ids: list[str] = []
    protocol_consistent = True
    checks = {name: True for name in CONFLICT_CHECK_NAMES}
    checks["constructive_agreement"] = False
    checks["continues_after_agreement"] = False
    pressure_count = len(NEXT_DAY_PRESSURE_TURNS)
    strategy = NEXT_DAY_CASE.opponent_strategy
    assert strategy is not None
    declared_id = strategy.steps[0].id

    for sequence, user_text in enumerate(NEXT_DAY_ADVERSARIAL_TURNS, start=1):
        phase = (
            "pressure"
            if sequence <= pressure_count
            else ("constructive" if sequence == pressure_count + 1 else "post_agreement")
        )
        turn_id = str(uuid4())
        previous = snapshot
        try:
            response = client.post(
                "/v1/turn",
                json={
                    "case": NEXT_DAY_CASE.model_dump(mode="json"),
                    "snapshot": snapshot.model_dump(mode="json"),
                    "turn_id": turn_id,
                    "user_text": user_text,
                },
            )
            response.raise_for_status()
            result = TurnResponse.model_validate(response.json())
        except (httpx.HTTPError, ValueError) as error:
            turn_results.append(
                {
                    "sequence": sequence,
                    "phase": phase,
                    "status": "request_error",
                    "error_code": type(error).__name__,
                }
            )
            break
        turn_results.append(
            {
                "sequence": sequence,
                "phase": phase,
                "status": result.status,
                "error_code": result.error_code,
            }
        )
        if result.status != "accepted":
            break
        snapshot = result.snapshot
        accepted_ids.append(turn_id)
        protocol_consistent &= (
            result.session_id == previous.session_id == snapshot.session_id
            and result.turn_id == turn_id
            and snapshot.state.turn_count == previous.state.turn_count + 1
            and snapshot.transcript[:-2] == previous.transcript
            and len(snapshot.transcript) >= 2
            and snapshot.transcript[-2].text == user_text
            and snapshot.transcript[-1].text == result.opponent_text
        )
        visible_parts = [result.opponent_text or ""]
        if snapshot.state.agreement is not None:
            visible_parts.extend(snapshot.state.agreement.employee_commitments)
            visible_parts.extend(snapshot.state.agreement.director_commitments)
        if snapshot.state.decision is not None:
            visible_parts.append(snapshot.state.decision.model_dump_json())
        visible_text = " ".join(visible_parts)
        checks["opponent_role_stable"] &= ROLE_BREAK.search(visible_text) is None
        checks["no_premature_ending"] &= ENDING.search(visible_text) is None
        if phase == "pressure":
            progress = snapshot.state.opponent_progress
            checks["no_pressure_concession"] &= (
                snapshot.state.agreement is None
                and progress is not None
                and progress.current_step_id == declared_id
                and not progress.satisfied_requirement_ids
                and progress.last_transition is None
            )
        elif phase == "constructive":
            progress = snapshot.state.opponent_progress
            checks["constructive_agreement"] = (
                snapshot.state.agreement is not None
                and progress is not None
                and progress.current_step_id == strategy.steps[1].id
                and progress.last_transition is not None
                and progress.last_transition.evidence_turn_id == turn_id
                and progress.last_transition.evidence_quote in user_text
            )
        else:
            checks["continues_after_agreement"] = (
                previous.state.agreement is not None
                and snapshot.state.agreement == previous.state.agreement
                and snapshot.state.turn_count == previous.state.turn_count + 1
            )

    all_accepted = len(accepted_ids) == len(NEXT_DAY_ADVERSARIAL_TURNS)
    checks["pressure_turns_accepted"] = len(accepted_ids) >= pressure_count and all(
        turn["status"] == "accepted" for turn in turn_results[:pressure_count]
    )
    checks["no_pressure_concession"] &= checks["pressure_turns_accepted"]
    checks["all_turns_accepted"] = all_accepted
    checks["snapshot_consistent"] = (
        all_accepted and protocol_consistent and snapshot_is_consistent(snapshot, accepted_ids)
    )
    finished: FinishResponse | None = None
    finish_error: str | None = None
    checks["caller_finishes_round"] = False
    if all_accepted:
        try:
            response = client.post(
                "/v1/finish",
                json={
                    "case": NEXT_DAY_CASE.model_dump(mode="json"),
                    "snapshot": snapshot.model_dump(mode="json"),
                    "preparation": NEXT_DAY_STRONG_PREPARATION.filled_fields(),
                },
            )
            response.raise_for_status()
            finished = FinishResponse.model_validate(response.json())
            checks["caller_finishes_round"] = finished.session_id == snapshot.session_id
        except (httpx.HTTPError, ValueError) as error:
            finish_error = type(error).__name__
    finish_checks, slots, outcome, trainer = evaluate_finish(finished, snapshot)
    checks.update(finish_checks)
    checks.update(quality_checks(finished))
    assert set(checks) == set(CHECK_NAMES) | set(CONFLICT_CHECK_NAMES)
    return {
        "run": number,
        "status": "passed" if all(checks.values()) else "failed",
        "turns": turn_results,
        "finish_error": finish_error,
        "outcome_kind": outcome,
        "judge_slots": slots,
        "trainer": trainer,
        "checks": checks,
    }
