"""Three isolated judge calls over the same public duel view."""

import re
from functools import partial
from typing import Protocol

from arena_ai.contracts import (
    CaseConfig,
    JudgeCollege,
    JudgeContext,
    JudgeSlot,
    JudgeVerdict,
    OutcomeResult,
    SessionSnapshot,
)
from arena_ai.judge_corpus import CHUNKS, SOURCES
from arena_ai.judge_index import point_id
from arena_ai.judge_retrieval import InvalidRetrievalError, JudgeRetrieval, methodology_for_college
from arena_ai.model_recovery import validated_model_call
from arena_ai.privacy import contains_private_phrase, public_duel_view

COLLEGES: tuple[JudgeCollege, ...] = ("hiring", "negotiation", "ownership")
RUBRICS: dict[JudgeCollege, str] = {
    "hiring": (
        "Нанимающиеся на работу: к кому из участников я бы пошёл работать? "
        "Оцени надёжность, отношение к людям, управленческую твёрдость, заботу о команде "
        "и долгосрочные последствия управления."
    ),
    "negotiation": (
        "Отправляющие на переговоры: кого я отправлю вместо себя на сложные переговоры? "
        "Оцени движение к цели, управление другой стороной, работу с картиной мира, "
        "управление ролями и сохранение отношений."
    ),
    "ownership": (
        "Доверяющие собственность: кому я доверю деньги, компанию или другой значимый ресурс? "
        "Оцени качество решений, компетентность, ответственность, риски и последствия для ресурсов."
    ),
}
CRITERIA: dict[JudgeCollege, tuple[str, ...]] = {
    "hiring": (
        "Надёжность",
        "Отношение к людям",
        "Управленческая твёрдость",
        "Забота о команде",
        "Долгосрочные последствия управления",
    ),
    "negotiation": (
        "Движение к цели",
        "Управление другой стороной",
        "Работа с картиной мира",
        "Управление ролями",
        "Сохранение отношений",
    ),
    "ownership": (
        "Качество решений",
        "Компетентность",
        "Ответственность",
        "Управление рисками",
        "Последствия для ресурсов",
    ),
}
MAX_VERDICT_WORDS = 120
SOURCE_REFERENCE = re.compile(
    r"https?://|www\.|\b(?:методич\w*|методик\w*|источник\w*|страниц\w*|стр\.\s*\d+|"
    r"rag|qdrant|doi|pdf|methodology|retrieval|source|page|citation)\b",
    re.IGNORECASE,
)
COACHING_LANGUAGE = re.compile(
    r"\b(?:рекоменд\w*|советую|попроб\w*|в следующий раз|"
    r"(?:вам|тебе|ему|ей) стоит)\b",
    re.IGNORECASE,
)
GENERIC_COMMENT = re.compile(
    r"\b(?:нужен вызов (?:реальной )?модели|недостаточно данных для оценки|"
    r"невозможно (?:сделать|дать) вывод|оба участника были уверены|"
    r"был более уверенным|был более красноречивым|хороший ход|"
    r"вс[её] стало лучше|первый лучше второго)\b",
    re.IGNORECASE,
)


class Judge(Protocol):
    async def verdict(self, context: JudgeContext) -> object: ...


class DemoJudge:
    async def verdict(self, context: JudgeContext) -> object:
        evidence = next((entry for entry in context.transcript if entry.status == "accepted"), None)
        if evidence is None:
            raise ValueError("No transcript evidence")
        return {
            "college": context.college,
            "choice": "player" if context.college == "negotiation" else "opponent",
            "decisive_criterion": {
                "hiring": "Надёжность",
                "negotiation": "Движение к цели",
                "ownership": "Управление рисками",
            }[context.college],
            "evidence_turn_id": evidence.turn_id,
            "evidence_quote": evidence.text[:120],
            "observation": "В принятом ходе участник сформулировал свою позицию.",
            "effect": "Реплика стала частью обсуждения между участниками.",
            "comparison": "В деморежиме выбор условный: действия сторон не оценены моделью.",
        }


def verdict_is_grounded(verdict: JudgeVerdict, context: JudgeContext, case: CaseConfig) -> bool:
    if verdict.college != context.college:
        return False
    if verdict.decisive_criterion not in CRITERIA[context.college]:
        return False
    if (
        not verdict.evidence_turn_id.strip()
        or not any(character.isalnum() for character in verdict.evidence_quote)
        or any(
            not text.strip() for text in (verdict.observation, verdict.effect, verdict.comparison)
        )
    ):
        return False
    if not any(
        entry.status == "accepted"
        and entry.turn_id == verdict.evidence_turn_id
        and verdict.evidence_quote in entry.text
        for entry in context.transcript
    ):
        return False
    visible_text = (
        f"{verdict.decisive_criterion} {verdict.evidence_quote} {verdict.observation} "
        f"{verdict.effect} {verdict.comparison}"
    )
    reasoning_text = f"{verdict.observation} {verdict.effect} {verdict.comparison}"
    if len(visible_text.split()) > MAX_VERDICT_WORDS:
        return False
    if (
        SOURCE_REFERENCE.search(visible_text)
        or COACHING_LANGUAGE.search(reasoning_text)
        or GENERIC_COMMENT.search(reasoning_text)
        or contains_internal_support(visible_text, context)
    ):
        return False
    return not contains_private_phrase(visible_text, case)


def contains_internal_support(text: str, context: JudgeContext) -> bool:
    lowered = text.casefold()
    if any(
        token in lowered
        for chunk in CHUNKS
        for token in (chunk.chunk_id, chunk.text_sha256, point_id(chunk))
    ):
        return True
    for source in SOURCES.values():
        title = re.sub(r"^\d+\.\s*", "", source.pdf_name.removesuffix(".pdf")).replace("_", " ")
        if (
            source.path.casefold() in lowered
            or source.pdf_sha256 in lowered
            or (len(title.split()) > 1 and title.casefold() in lowered)
        ):
            return True
    public_words = f" {' '.join(re.findall(r'\w+', lowered))} "
    for excerpt in (
        *context.methodology.core,
        *context.methodology.profile,
        *context.methodology.techniques,
    ):
        words = re.findall(r"\w+", excerpt.casefold())
        if any(
            f" {' '.join(words[start : start + 10])} " in public_words
            for start in range(len(words) - 9)
        ):
            return True
    return False


def validated_judge_verdict(
    raw: object,
    *,
    context: JudgeContext,
    case: CaseConfig,
) -> JudgeVerdict | None:
    try:
        verdict = JudgeVerdict.model_validate(raw)
    except ValueError:
        return None
    return verdict if verdict_is_grounded(verdict, context, case) else None


async def judge_duel(
    case: CaseConfig,
    snapshot: SessionSnapshot,
    outcome: OutcomeResult,
    judge: Judge,
    retrieval: JudgeRetrieval,
    model_attempts: int = 1,
) -> list[JudgeSlot]:
    public_view = public_duel_view(snapshot)
    slots: list[JudgeSlot] = []
    for college in COLLEGES:
        try:
            methodology = methodology_for_college(await retrieval.retrieve(college), college)
        except InvalidRetrievalError:
            slots.append(
                JudgeSlot(college=college, status="failed", error_code="invalid_judge_retrieval")
            )
            continue
        except Exception:  # noqa: BLE001 - isolate retrieval transport per college
            slots.append(
                JudgeSlot(
                    college=college, status="failed", error_code="judge_retrieval_unavailable"
                )
            )
            continue
        context = JudgeContext(
            college=college,
            rubric=RUBRICS[college],
            case_id=case.id,
            case_title=case.title,
            shared_context=case.shared_context,
            player_role=case.player_role,
            opponent_role=case.opponent_role,
            state=public_view.state,
            transcript=public_view.transcript,
            outcome=outcome,
            methodology=methodology,
        )
        verdict_result = await validated_model_call(
            partial(judge.verdict, context),
            partial(validated_judge_verdict, context=context, case=case),
            attempts=model_attempts,
        )
        if verdict_result.value is None:
            slots.append(
                JudgeSlot(
                    college=college,
                    status="failed",
                    error_code=(
                        "judge_unavailable"
                        if verdict_result.failure == "unavailable"
                        else "invalid_judge_output"
                    ),
                )
            )
            continue
        slots.append(JudgeSlot(college=college, status="ready", verdict=verdict_result.value))
    return slots
