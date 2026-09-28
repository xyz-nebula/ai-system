"""Reviewed methodology excerpts for the three judge colleges, quoted from unpublished manuals."""

import hashlib
import re
from dataclasses import dataclass
from typing import Literal

from arena_ai.contracts import JudgeCollege

CORPUS_ID = "arena-judge-methodology"
CORPUS_VERSION = "2026-09-29.2"
ALL_COLLEGES: tuple[JudgeCollege, ...] = ("hiring", "negotiation", "ownership")
type ChunkScope = Literal["core", "profile", "technique"]


# Keys of the manuals the excerpts are quoted from; the manuals are not published.
SOURCES = frozenset({"guide", "preparation", "argumentation", "social_roles"})


@dataclass(frozen=True, slots=True)
class CorpusChunk:
    chunk_id: str
    source: str
    page: int
    section: str
    scope: ChunkScope
    colleges: tuple[JudgeCollege, ...]
    text: str

    @property
    def text_sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    def payload(self) -> dict[str, object]:
        return {
            "corpus_id": CORPUS_ID,
            "corpus_version": CORPUS_VERSION,
            "purpose": "judge",
            "chunk_id": self.chunk_id,
            "scope": self.scope,
            "colleges": list(self.colleges),
            "source": self.source,
            "page": self.page,
            "section": self.section,
            "text": self.text,
            "text_sha256": self.text_sha256,
        }


CHUNKS: tuple[CorpusChunk, ...] = (
    CorpusChunk(
        "guide-principle-p02",
        "guide",
        2,
        "Главный принцип судейства",
        "core",
        ALL_COLLEGES,
        "Судья не определяет, кто красивее говорил, был увереннее или больше\n"
        "понравился. Он отвечает на практический вопрос своей коллегии: кому из\n"
        "двух игроков я готов доверить соответствующую управленческую\n"
        "функцию?",
    ),
    CorpusChunk(
        "guide-three-perspectives-p03",
        "guide",
        3,
        "Три коллегии",
        "core",
        ALL_COLLEGES,
        "  Важно: судейские критерии не конкурируют между собой.\n"
        "  Один и тот же эпизод может выглядеть сильным для одной коллегии и слабым для\n"
        "  другой. Поэтому судья всегда удерживает собственную роль.",
    ),
    CorpusChunk(
        "guide-action-consequence-p07",
        "guide",
        7,
        "Действие и последствия",
        "core",
        ALL_COLLEGES,
        "   Ключ к экспертному судейству:\n"
        "   не просто замечать действия игроков, а связывать их с изменением ситуации и\n"
        "   будущими последствиями.",
    ),
    CorpusChunk(
        "guide-comparative-choice-p09",
        "guide",
        9,
        "Принятие решения",
        "core",
        ALL_COLLEGES,
        "     Не ищите идеального игрока.\n"
        "     Судейство — сравнительная оценка двух конкретных участников в конкретном\n"
        "     поединке.",
    ),
    CorpusChunk(
        "guide-one-minute-p10",
        "guide",
        10,
        "Сильный судейский комментарий",
        "core",
        ALL_COLLEGES,
        "Оптимальный комментарий занимает около минуты. Его задача — объяснить\n"
        "голос, а не пересказать весь поединок.",
    ),
    CorpusChunk(
        "guide-judge-not-trainer-p11",
        "guide",
        11,
        "Границы роли",
        "core",
        ALL_COLLEGES,
        "Судейский комментарий может быть развивающим, но его основная функция —\n"
        "объяснить решение. Полноценное наставление лучше отделять.",
    ),
    CorpusChunk(
        "guide-judge-errors-p12",
        "guide",
        12,
        "Типичные ошибки судьи",
        "core",
        ALL_COLLEGES,
        "Типичные ошибки судьи — что делать вместо этого:\n"
        "«Он мне больше понравился» — вернуться к роли своей коллегии и назвать конкретное\n"
        "управленческое основание.\n"
        "Голос за уверенность — проверить, стоит ли за уверенностью твёрдая позиция и\n"
        "изменяет ли она ситуацию.\n"
        "Голос за красноречие — смотреть на влияние речи: к чему она привела и что\n"
        "изменилось у второй стороны.\n"
        "Судить не из своей коллегии — начать с практического вопроса: «Я бы нанялся /\n"
        "отправил / доверил?»\n"
        "Судить только финальный результат — учитывать цену результата и последствия после\n"
        "завершения разговора.\n"
        "Считать количество приёмов — оценивать эффект каждого действия, а не количество\n"
        "техник.\n"
        "Пересказывать поединок — выбрать 1–2 эпизода, которые объясняют ваш голос.\n"
        "Комментировать личность — описывать наблюдаемое действие и его последствия.\n"
        "Давать вердикт без доказательства — связать выбор с конкретной репликой, эффектом\n"
        "и критерием коллегии.",
    ),
    CorpusChunk(
        "guide-judge-checklist-p13",
        "guide",
        13,
        "Памятка судьи",
        "core",
        ALL_COLLEGES,
        "Во время поединка: слежу за целью игроков; замечаю смену управления и социальных\n"
        "ролей; фиксирую конкретные реплики и действия; отмечаю, что именно изменилось\n"
        "после действий игроков; смотрю на отношения и будущие последствия; оцениваю\n"
        "происходящее именно через свою коллегию.\n"
        "Перед голосованием: кого я реально выберу из своей роли? Какой эпизод сильнее\n"
        "всего повлиял на мой голос? Какой критерий моей коллегии за ним стоит? Могу ли я\n"
        "объяснить решение без слов «понравился», «уверенный», «красиво говорил»?",
    ),
    CorpusChunk(
        "guide-pocket-version-p14",
        "guide",
        14,
        "Карманная версия",
        "core",
        ALL_COLLEGES,
        "Посмотри на управление: кто держал цель? Кто задавал рамку? Кто влиял на картину\n"
        "мира? Кто принимал решения?\n"
        "Посмотри на цену: что игрок получил — и чем заплатил? Сохранились ли отношения,\n"
        "ресурсы, доверие и будущее взаимодействие?\n"
        "Найди один решающий эпизод: какая реплика или действие лучше всего объясняет\n"
        "твой выбор?\n"
        "Сравни: в чём именно второй игрок оказался слабее по критериям твоей коллегии?",
    ),
    CorpusChunk(
        "guide-hiring-p04",
        "guide",
        4,
        "Нанимающиеся на работу",
        "profile",
        ("hiring",),
        "      Главный вопрос: к кому из этих двух руководителей я бы пошёл\n"
        "      работать?\n\n"
        "      Не «кто приятнее», а под чьим управлением я хотел бы оказаться в реальной\n"
        "      организации.",
    ),
    CorpusChunk(
        "guide-hiring-responsibility-p04",
        "guide",
        4,
        "Уважение и ответственность руководителя",
        "profile",
        ("hiring",),
        "                                              Образ сильного игрока\n"
        "                                              «С ним можно работать. Он уважает\n"
        "                                              людей, но способен принимать\n"
        "                                              решения и отвечать за результат».",
    ),
    CorpusChunk(
        "guide-negotiation-p05",
        "guide",
        5,
        "Отправляющие на переговоры",
        "profile",
        ("negotiation",),
        "Отправляющие на переговоры\n\n"
        "   Главный вопрос: кого из двух игроков я отправлю вместо себя на\n"
        "   сложные переговоры?",
    ),
    CorpusChunk(
        "guide-ownership-p06",
        "guide",
        6,
        "Доверяющие собственность",
        "profile",
        ("ownership",),
        "Доверяющие собственность\n\n"
        "    Главный вопрос: кому из двух игроков я готов доверить свои\n"
        "    деньги, компанию или другой значимый ресурс?",
    ),
    CorpusChunk(
        "guide-ownership-risk-p06",
        "guide",
        6,
        "Механизм решения и риски ресурса",
        "profile",
        ("ownership",),
        "   Образ сильного игрока\n"
        "   «Я понимаю, что он будет делать с моим ресурсом, зачем он это делает, какие\n"
        "   риски существуют и каким образом он ими управляет».",
    ),
    CorpusChunk(
        "guide-effect-p05",
        "guide",
        5,
        "Эффект приёма",
        "profile",
        ("negotiation",),
        "  Не считайте приёмы механически.\n"
        "  Судье важен не сам факт использования техники, а её эффект: что изменилось в\n"
        "  поведении партнёра, распределении ролей, картине мира или вероятности\n"
        "  договорённости?",
    ),
    CorpusChunk(
        "preparation-metaposition-p04",
        "preparation",
        4,
        "Метапозиция",
        "technique",
        ("hiring", "ownership"),
        "Метапозиция — способ восприятия ситуации с точки зрения\n"
        "стороннего беспристрастного наблюдателя. Взгляд сверху —\n"
        "“над схваткой”. Без принятия позиции одной из сторон\n"
        "конфликта.",
    ),
    CorpusChunk(
        "argumentation-purpose-p02",
        "argumentation",
        2,
        "Цель аргументации",
        "technique",
        ("negotiation",),
        "Аргументация — это процесс обоснования\n"
        "своей позиции с помощью убедительных\n"
        "доводов\n\n"
        "Её задача — не просто высказать мнение, а\n"
        "сделать так, чтобы оппонент или аудитория\n"
        "приняли вашу точку зрения как обоснованную",
    ),
    CorpusChunk(
        "social-role-definition-p08",
        "social_roles",
        8,
        "Определение социальной роли",
        "technique",
        ("hiring", "negotiation"),
        "Что такое социальная роль?\n"
        "– это набор ожидаемых форм поведения, обязанностей и норм,\n"
        "которые люди принимают в зависимости от своего положения\n"
        "в определенной группе, обществе или сообществе",
    ),
)


def chunks_for_college(college: JudgeCollege) -> tuple[CorpusChunk, ...]:
    """Return the mandatory common core, this college's profile and allowed techniques."""

    return tuple(chunk for chunk in CHUNKS if college in chunk.colleges)


def corpus_filter(college: JudgeCollege | None = None) -> dict[str, object]:
    conditions = [
        {"key": "purpose", "match": {"value": "judge"}},
        {"key": "corpus_id", "match": {"value": CORPUS_ID}},
    ]
    if college is not None:
        conditions.append({"key": "colleges", "match": {"value": college}})
    return {"must": conditions}


def validate_corpus() -> None:
    """Fail closed on invalid corpus metadata."""

    ids: set[str] = set()
    for chunk in CHUNKS:
        if chunk.chunk_id in ids or re.fullmatch(r"[a-z0-9-]+", chunk.chunk_id) is None:
            raise ValueError(f"invalid or duplicate chunk_id: {chunk.chunk_id}")
        ids.add(chunk.chunk_id)
        if chunk.source not in SOURCES or not chunk.text.strip() or chunk.page < 1:
            raise ValueError(f"invalid corpus chunk: {chunk.chunk_id}")
        if chunk.scope == "core" and (chunk.source != "guide" or chunk.colleges != ALL_COLLEGES):
            raise ValueError(f"invalid judge core: {chunk.chunk_id}")
        if chunk.scope == "profile" and (chunk.source != "guide" or len(chunk.colleges) != 1):
            raise ValueError(f"invalid college profile: {chunk.chunk_id}")
        if not chunk.colleges or any(college not in ALL_COLLEGES for college in chunk.colleges):
            raise ValueError(f"invalid college filter: {chunk.chunk_id}")

    for college in ALL_COLLEGES:
        selected = chunks_for_college(college)
        if not any(chunk.scope == "core" for chunk in selected):
            raise ValueError(f"missing judge core: {college}")
        if not any(chunk.scope == "profile" for chunk in selected):
            raise ValueError(f"missing college profile: {college}")
