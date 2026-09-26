"""HTTP adapter for text turns and duel completion."""

import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from secrets import compare_digest
from typing import Annotated, Literal, Protocol

import httpx
from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from arena_ai.contracts import (
    AgreementResolution,
    CaseConfig,
    DeferredDecision,
    FinishRequest,
    FinishResponse,
    GuardContext,
    GuardDecision,
    GuardReason,
    LivenessResponse,
    ModelErrorCode,
    OpponentContext,
    OpponentPositionProgress,
    OpponentProposal,
    PartialDecision,
    ReadinessFailureCategory,
    ReadinessResponse,
    ServiceInfo,
    SessionSnapshot,
    SessionState,
    TranscriptEntry,
    TurnRequest,
    TurnResponse,
    ValidationContext,
    ValidationDecision,
    ValidatorRejectReason,
)
from arena_ai.judge_retrieval import DemoJudgeRetrieval, JudgeRetrieval, UnavailableJudgeRetrieval
from arena_ai.judges import DemoJudge, Judge, judge_duel
from arena_ai.model_recovery import validated_model_call
from arena_ai.opponent_position import (
    IncompleteTransitionEvidenceError,
    UnearnedConcessionError,
    apply_position_transition,
    mentions_deal_terms,
    restore_position_progress,
    stated_automatic_raise,
)
from arena_ai.outcome import determine_outcome
from arena_ai.privacy import (
    contains_private_phrase,
    public_duel_view,
    public_transcript,
    visible_proposal_text,
)
from arena_ai.trainer import DemoTrainer, Trainer, train_duel

SERVICE_BEARER = HTTPBearer(auto_error=False)
VALIDATION_ERROR_CODES: dict[ValidatorRejectReason, ModelErrorCode] = {
    "role_break": "opponent_role_break",
    "premature_ending": "opponent_premature_ending",
    "unearned_concession": "opponent_unearned_concession",
    "private_data_leak": "invalid_opponent_output",
    "factual_conflict": "invalid_opponent_output",
}


class Opponent(Protocol):
    async def respond(self, context: OpponentContext) -> object: ...


class Guard(Protocol):
    async def assess(self, context: GuardContext) -> object: ...


class ProposalValidator(Protocol):
    async def assess(self, context: ValidationContext) -> object: ...


class ReadinessProbe(Protocol):
    async def check(self) -> ReadinessFailureCategory | None: ...


class DemoOpponent:
    async def respond(self, context: OpponentContext) -> object:
        if context.state.turn_count == 0:
            return {
                "text": "Вчера мы говорили о большей ответственности. Как вы объясните сегодняшний пропуск?"
            }
        return {
            "text": "Мне нужны понятные условия, которые восстановят доверие. Что вы предлагаете?"
        }


def guard_reason(text: str) -> GuardReason | None:
    lowered = text.casefold()
    if re.search(r"(?:игнорируй|ignore).{0,80}(?:инструкц|instructions)", lowered):
        return "prompt_override"
    if re.search(r"(?:системн\w*\s+промпт|system\s+prompt)", lowered):
        return "prompt_override"
    if re.search(
        r"(?:скрыт\w*|закрыт\w*|секретн\w*|конфиденциальн\w*).{0,80}"
        r"(?:инструкц|вводн|данн|целе|услов)",
        lowered,
    ):
        return "private_data_request"
    if re.search(r"переговорн\w*\s+минимум", lowered) or "batna" in lowered:
        return "hidden_position_request"
    if contains_unambiguous_physical_threat(lowered):
        return "physical_harm_threat"
    return None


def contains_unambiguous_physical_threat(text: str) -> bool:
    unquoted = re.sub(
        r"«[^»]*»|“[^”]*”|\"[^\"\n]*\"|'[^'\n]*'",
        " ",
        text.casefold(),
    )
    threat_patterns = (
        re.compile(
            r"\b(?P<verb>убью|зарежу|застрелю|изобью|покалечу|ударю)\s+"
            r"(?:тебя|вас|его|её)\b"
        ),
        re.compile(
            r"\b(?:тебя|вас|его|её)(?:\s+\w+){0,3}\s+"
            r"(?P<verb>убью|зарежу|застрелю|изобью|покалечу|ударю)\b"
        ),
        re.compile(
            r"\b(?P<verb>сломаю)\s+(?:тебе|вам|ему|ей)\s+"
            r"(?:ноги|руки|шею)\b"
        ),
        re.compile(
            r"\b(?:тебе|вам|ему|ей)\s+(?:ноги|руки|шею)(?:\s+\w+){0,2}\s+"
            r"(?P<verb>сломаю)\b"
        ),
    )
    for pattern in threat_patterns:
        for match in pattern.finditer(unquoted):
            if match.group("verb") == "ударю" and re.search(
                r"\b(?:результатами|показателями|цифрами|аргументами)\b",
                unquoted[match.start() : match.end() + 32],
            ):
                continue
            prefix = unquoted[max(0, match.start("verb") - 40) : match.start("verb")]
            if not re.search(r"\bне\s*$", prefix):
                return True
    return False


def opponent_role_rejection_reason(text: str) -> ValidatorRejectReason | None:
    lowered = text.casefold()
    if re.search(
        r"(?:разговор|обсуждение|диалог|раунд|поединок|переговоры)\s+"
        r"(?:окончен\w*|закончен\w*|заверш[её]н\w*|прекращ[её]н\w*|прекраща\w*)|"
        r"\bя\s+(?:завершаю|заканчиваю|закончил|завершил|прекращаю|прекратил)\s+"
        r"(?:(?:эти|этот|наш|наши)\s+)?"
        r"(?:разговор|обсуждение|диалог|раунд|поединок|переговоры)\b|"
        r"\bна\s+этом\s+(?:разговор|обсуждение|диалог|раунд|поединок|переговоры)\s+"
        r"(?:завершаю|заканчиваю|закончил|завершил|прекращаю|прекратил)\b|"
        r"\bя\s+больше\s+не\s+буду\s+продолжать\b|"
        r"\bна\s+этом\s+(?:разговор|обсуждение)\s+(?:окончен|закончено)\b",
        lowered,
    ):
        return "premature_ending"
    if re.search(
        r"\b(?:нахуй|пош[её]л\s+на\s+хуй|придурок|идиот|мудак|дебил)\b",
        lowered,
    ):
        return "role_break"
    if re.search(
        r"\bне\s+могу\s+продолжать.{0,50}(?:тоне|оскорб)|"
        r"\b(?:общайтесь|говорите)\s+уважительно\b|"
        r"\bоскорблени\w*\s+(?:недопустим|неприемлем)\w*",
        lowered,
    ):
        return "role_break"
    return None


def standard_kpi_commitment(commitment: str, terms: AgreementResolution) -> bool:
    match = re.fullmatch(
        r"выполнить\s+(?:kpi|кпи)\s+(?P<kpi>\d{1,3})\s*%?"
        r"(?:\s+за\s+(?:(?P<count>одну|один|две|три|четыре|\d+)\s+)?"
        r"недел\w*)?",
        commitment.casefold().strip(),
    )
    if match is None or int(match.group("kpi")) != terms.kpi_percent:
        return False
    count = match.group("count")
    if count is None:
        return True
    weeks = {"одну": 1, "один": 1, "две": 2, "три": 3, "четыре": 4}
    return weeks.get(count, int(count) if count.isdigit() else -1) == terms.control_weeks


def commitment_markers(text: str) -> set[str]:
    stopwords = {"за", "после", "о", "об", "и", "на", "при", "с", "в", "по"}
    return {
        token if token.isdigit() or len(token) < 5 else token[:5]
        for token in re.findall(r"[a-zа-яё]+|\d+", text.casefold())
        if token not in stopwords and token != "не"
    }


def clause_has_refusal(clause: str) -> bool:
    return re.search(r"\bне\b|\bотказ\w*", clause.casefold()) is not None


def clause_has_commitment_act(clause: str, source: Literal["player", "offer", "opponent"]) -> bool:
    lowered = clause.casefold()
    if clause.strip().endswith("?"):
        return False
    if source == "player":
        if re.search(r"\b(?:директор|руководитель|работодатель|он|она|они|вы|ты)\b", lowered):
            return False
        return (
            re.search(
                r"\b(?:обязуюсь|обещаю|готов(?:а)?|беру\s+на\s+себя|"
                r"компенсирую|возмещу|выполню|сообщу|предупрежу|закрою|"
                r"не\s+допущу)\b",
                lowered,
            )
            is not None
        )
    if source == "offer":
        return re.search(r"\b(?:вы|ты|менеджер|сотрудник|предлагаю)\b", lowered) is not None
    return (
        re.search(
            r"\b(?:я|согласен|обязуюсь|обещаю|гарантирую|директор|беру\s+на\s+себя)\b",
            lowered,
        )
        is not None
    )


def commitment_is_grounded(
    commitment: str,
    evidence: str,
    terms: AgreementResolution,
    *,
    source: Literal["player", "offer", "opponent"] = "player",
) -> bool:
    if standard_kpi_commitment(commitment, terms):
        if not mentions_deal_terms(evidence, terms):
            return False
        clauses = re.findall(r"[^.!?;\n]+[.!?;]?", evidence)
        kpi_clauses = [
            clause for clause in clauses if re.search(r"\b(?:kpi|кпи)\b", clause.casefold())
        ]
        if source == "offer":
            return any(
                not clause_has_refusal(clause)
                and not clause.strip().endswith("?")
                and re.search(r"\b(?:вы|ты|сотрудник|менеджер)\b", clause.casefold())
                for clause in kpi_clauses
            )
        if source == "player":
            ambiguous_owner = any(
                clause.strip().endswith("?")
                or re.search(
                    r"\b(?:директор|руководитель|работодатель|он|она|они|вы|ты)\b",
                    clause.casefold(),
                )
                for clause in kpi_clauses
            )
            if ambiguous_owner:
                return False
        return any(
            not clause_has_refusal(clause)
            and (
                clause_has_commitment_act(clause, source)
                or (source == "player" and re.search(r"\bпредлагаю\b", clause.casefold()))
            )
            for clause in kpi_clauses
        )

    required = commitment_markers(commitment)
    required_negation = re.search(r"\bне\b", commitment.casefold()) is not None
    if not required:
        return False
    return any(
        required <= commitment_markers(clause)
        and clause_has_refusal(clause) == required_negation
        and clause_has_commitment_act(clause, source)
        for clause in re.findall(r"[^.!?;\n]+[.!?;]?", evidence)
    )


def commitment_is_contradicted(commitment: str, player_text: str) -> bool:
    required = commitment_markers(commitment)
    required_negation = re.search(r"\bне\b", commitment.casefold()) is not None

    def has_relevant_refusal(clause: str) -> bool:
        # A coordinated prevention promise does not negate the other obligations
        # in its sentence. Only remove this recognised, unrelated promise; keep
        # refusal words and every other negation fail-closed.
        prevention = r"\bне\s+допускать\s+(?:новых\s+)?нарушений\s+дисциплины\b"
        for match in re.finditer(prevention, clause, re.IGNORECASE):
            if not required & commitment_markers(match.group()):
                clause = clause.replace(match.group(), "")
        return clause_has_refusal(clause)

    return any(
        required <= commitment_markers(clause) and has_relevant_refusal(clause) != required_negation
        for clause in re.split(r"[.!?;\n]+", player_text)
    )


def standard_salary_raise_commitment(commitment: str, terms: AgreementResolution) -> bool:
    if stated_automatic_raise(commitment) is True and not terms.automatic_raise:
        return False
    return (
        re.fullmatch(
            r"(?:автоматически\s+)?повысить\s+зарплату"
            r"(?:\s+после\s+(?:выполнения\s+)?(?:условий|kpi|кпи))?",
            commitment.casefold().strip(),
        )
        is not None
    )


def discussion_only_clause(clause: str) -> bool:
    lowered = clause.casefold()
    return (
        re.search(r"\b(?:предлагаю|согласен|готов\w*|принимаю)\b", lowered) is not None
        and re.search(r"\b(?:обсуд\w*|обсужд\w*|рассмотр\w*|уточн\w*|вернут\w*)\b", lowered)
        is not None
    )


def affirmative_deal_utterance(text: str, terms: AgreementResolution) -> bool:
    lowered = text.casefold()
    clauses = re.split(r"[.!?;\n]+", lowered)
    return (
        mentions_deal_terms(lowered, terms)
        and any(
            re.search(r"\b(?:предлагаю|согласен|принимаю|обязуюсь|готов\w*)\b", clause)
            and not discussion_only_clause(clause)
            and "недел" in clause
            and re.search(rf"\b(?:kpi|кпи)\s*[:=]?\s*{terms.kpi_percent}\b", clause)
            for clause in clauses
        )
        and any(
            stated_automatic_raise(clause) is terms.automatic_raise
            and not discussion_only_clause(clause)
            for clause in clauses
        )
        and re.search(
            r"\bне\s+(?:предлага\w*|соглас\w*|принима\w*|обеща\w*|готов\w*)\b|"
            r"\bне\s+говорил\w*.{0,60}\b(?:предлага\w*|соглас\w*|обеща\w*)\b",
            lowered,
        )
        is None
    )


def valid_proposal(
    proposal: OpponentProposal,
    case: CaseConfig,
    user_text: str,
    transcript: list[TranscriptEntry],
) -> bool:
    text = proposal.text.casefold()
    player_text = user_text.casefold()
    if re.search(
        r"(?:мне\s+(?:предписали|велели)|"
        r"мо(?:й|и|я)\s+(?:внутренние\s+инструкции|скрытая\s+цель|целевая\s+позиция|целевой\s+вариант)|"
        r"по\s+моим\s+инструкциям|my\s+instructions|i\s+was\s+instructed)",
        text,
    ):
        return False
    resolution = proposal.resolution
    visible_text = visible_proposal_text(proposal)
    if contains_private_phrase(visible_text, case) or re.search(
        r"\brevision_(?:reason|hint)\b|\bcomplete_transition_quote\b|"
        r"\b(?:opponent_|invalid_opponent_|validator_)\w+\b",
        visible_text,
        re.IGNORECASE,
    ):
        return False
    if isinstance(resolution, PartialDecision):
        explicit_partial_signal = any(word in player_text for word in ("соглас", "предлага")) or (
            "готов" in player_text
            and any(
                word in player_text for word in ("отдельн", "открыт", "остал", "пока", "обсудим")
            )
        )
        return (
            "соглас" in text
            and any(word in text for word in ("открыт", "остал", "пока"))
            and not re.search(r"\bне\s+(?:буду|готов|согласен)\b", player_text)
            and explicit_partial_signal
        )
    if isinstance(resolution, DeferredDecision):
        return (
            any(word in text for word in ("верн", "отлож", "перенес"))
            and not re.search(r"\bне\s+(?:хочу|готов).{0,30}(?:отклад|перенос)", player_text)
            and any(word in player_text for word in ("завтра", "верн", "отлож", "позже", "перенес"))
        )
    if resolution is None:
        return True
    if not isinstance(resolution, AgreementResolution):
        return False
    terms = resolution
    rules = case.agreement_rules
    last_opponent_offer = next(
        (
            entry
            for entry in reversed(transcript)
            if entry.speaker == "opponent" and entry.status == "accepted"
        ),
        None,
    )
    prior_offer = last_opponent_offer is not None and affirmative_deal_utterance(
        last_opponent_offer.text,
        terms,
    )
    player_restates_terms = (
        re.search(
            r"\b(?:kpi|кпи|недел\w*|автоматич\w*|повышен\w*|\d+)\b",
            player_text,
        )
        is not None
    )
    accepted_prior_offer = (
        "согласен" in player_text
        and prior_offer
        and not any(
            discussion_only_clause(clause) for clause in re.split(r"[.!?;\n]+", player_text)
        )
        and (not player_restates_terms or affirmative_deal_utterance(player_text, terms))
    )
    commitment_evidence = (
        last_opponent_offer.text.casefold()
        if accepted_prior_offer and last_opponent_offer is not None
        else player_text
    )
    commitments_are_grounded = all(
        commitment_is_grounded(
            commitment,
            commitment_evidence,
            terms,
            source="offer" if accepted_prior_offer else "player",
        )
        for commitment in terms.employee_commitments
    ) and not any(
        commitment_is_contradicted(commitment, player_text)
        or commitment_is_contradicted(commitment, proposal.text)
        for commitment in terms.employee_commitments
    )
    director_commitments_are_stated = all(
        not (stated_automatic_raise(commitment) is True and not terms.automatic_raise)
        and not commitment_is_contradicted(commitment, proposal.text)
        and (
            standard_salary_raise_commitment(commitment, terms)
            or commitment_is_grounded(commitment, proposal.text, terms, source="opponent")
        )
        for commitment in terms.director_commitments
    )
    return (
        not re.search(r"\bне\s+(?:готов|согласен|принимаю)\b|\bотказываюсь\b", player_text)
        and (affirmative_deal_utterance(player_text, terms) or accepted_prior_offer)
        and commitments_are_grounded
        and director_commitments_are_stated
        and rules.min_control_weeks <= terms.control_weeks <= rules.max_control_weeks
        and rules.min_kpi_percent <= terms.kpi_percent <= rules.max_kpi_percent
        and (terms.automatic_raise or not rules.require_automatic_raise)
        and not re.search(
            r"\bне\s+(?:согласен|принимаю|принят\w*|согласован\w*)\b",
            text,
        )
        and not re.search(r"\bсогласен\s+(?:обсудить|рассмотреть|вернуться)\b", text)
        and not any(discussion_only_clause(clause) for clause in re.split(r"[.!?;\n]+", text))
        and not re.search(r"повышен\w*.{0,40}(?:не\s+обеща|не\s+гарантир|не\s+подтвержд)", text)
        and any(
            word in text
            for word in ("согласен", "договорились", "принимаю", "принят", "согласован")
        )
        and str(terms.kpi_percent) in text
        and "недел" in text
        and "повышен" in text
        and stated_automatic_raise(text) is terms.automatic_raise
    )


def model_failure_response(request: TurnRequest, code: ModelErrorCode) -> TurnResponse:
    return TurnResponse(
        session_id=request.snapshot.session_id,
        turn_id=request.turn_id,
        status="model_error",
        opponent_text="Сейчас не могу продолжить разговор. Попробуйте повторить ход.",
        snapshot=request.snapshot,
        error_code=code,
    )


def blocked_turn_response(request: TurnRequest, reason: GuardReason) -> TurnResponse:
    safe_text = (
        "Угрозы физической расправы недопустимы. Вернитесь к безопасному деловому разговору."
        if reason == "physical_harm_threat"
        else "Давайте вернёмся к условиям работы и повышения. Что вы предлагаете?"
    )
    snapshot = SessionSnapshot(
        session_id=request.snapshot.session_id,
        state=request.snapshot.state.model_copy(
            update={"turn_count": request.snapshot.state.turn_count + 1}
        ),
        transcript=[
            *request.snapshot.transcript,
            TranscriptEntry(
                turn_id=request.turn_id,
                speaker="player",
                status="blocked",
                text=request.user_text,
                blocked_reason=reason,
            ),
            TranscriptEntry(
                turn_id=request.turn_id,
                speaker="opponent",
                status="safe_reaction",
                text=safe_text,
            ),
        ],
    )
    return TurnResponse(
        session_id=snapshot.session_id,
        turn_id=request.turn_id,
        status="blocked",
        opponent_text=safe_text,
        snapshot=snapshot,
    )


def create_app(
    opponent: Opponent | None = None,
    judge: Judge | None = None,
    trainer: Trainer | None = None,
    guard: Guard | None = None,
    validator: ProposalValidator | None = None,
    owned_model_http: httpx.AsyncClient | None = None,
    mode: Literal["demo", "qwen"] = "demo",
    model_id: str | None = None,
    service_token: str | None = None,
    readiness_probe: ReadinessProbe | None = None,
    model_attempts: int = 1,
    judge_retrieval: JudgeRetrieval | None = None,
    owned_retrieval_http: httpx.AsyncClient | None = None,
) -> FastAPI:
    if not 1 <= model_attempts <= 3:
        raise ValueError("model_attempts must be between 1 and 3")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            for owned in (owned_model_http, owned_retrieval_http):
                if owned is not None:
                    await owned.aclose()

    app = FastAPI(title="Arena AI", version="0.1.0", lifespan=lifespan)
    active_opponent = opponent if opponent is not None else DemoOpponent()
    active_judge = judge if judge is not None else DemoJudge()
    active_trainer = trainer if trainer is not None else DemoTrainer()
    active_retrieval = (
        judge_retrieval
        if judge_retrieval is not None
        else (DemoJudgeRetrieval() if mode == "demo" else UnavailableJudgeRetrieval())
    )

    async def require_service_token(
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Security(SERVICE_BEARER),
        ],
    ) -> None:
        if service_token is None:
            return
        if credentials is None or not compare_digest(credentials.credentials, service_token):
            raise HTTPException(
                status_code=401,
                detail="Unauthorized",
                headers={"WWW-Authenticate": "Bearer"},
            )

    @app.get("/v1/info", response_model=ServiceInfo)
    async def service_info() -> ServiceInfo:
        return ServiceInfo(mode=mode, model=model_id)

    @app.get("/health/live", response_model=LivenessResponse)
    async def liveness() -> LivenessResponse:
        return LivenessResponse()

    @app.get(
        "/health/ready",
        response_model=ReadinessResponse,
        response_model_exclude_none=True,
        responses={503: {"model": ReadinessResponse}},
    )
    async def readiness() -> ReadinessResponse | JSONResponse:
        if mode == "demo":
            return ReadinessResponse(status="ready", mode="demo")
        category = (
            await readiness_probe.check() if readiness_probe is not None else "gateway_unavailable"
        )
        result = ReadinessResponse(
            status="ready" if category is None else "not_ready",
            mode="qwen",
            model=model_id,
            category=category,
        )
        if category is not None:
            return JSONResponse(
                status_code=503,
                content=result.model_dump(exclude_none=True),
            )
        return result

    @app.post(
        "/v1/turn",
        response_model=TurnResponse,
        response_model_exclude_none=True,
        dependencies=[Depends(require_service_token)],
    )
    async def take_turn(request: TurnRequest) -> TurnResponse:
        blocked_reason = guard_reason(request.user_text)
        if blocked_reason is not None:
            return blocked_turn_response(request, blocked_reason)
        if guard is not None:
            public_view = public_duel_view(request.snapshot)
            guard_context = GuardContext(
                shared_context=request.case.shared_context,
                player_role=request.case.player_role,
                opponent_role=request.case.opponent_role,
                state=public_view.state,
                transcript=public_view.transcript,
                user_text=request.user_text,
            )

            def validated_guard(raw: object) -> GuardDecision | None:
                try:
                    return GuardDecision.model_validate(raw)
                except ValueError:
                    return None

            guard_result = await validated_model_call(
                lambda: guard.assess(guard_context),
                validated_guard,
                attempts=model_attempts,
            )
            if guard_result.value is None:
                return model_failure_response(
                    request,
                    (
                        "guard_unavailable"
                        if guard_result.failure == "unavailable"
                        else "invalid_guard_output"
                    ),
                )
            guard_decision = guard_result.value
            if guard_decision.decision == "uncertain":
                return model_failure_response(request, "guard_uncertain")
            if guard_decision.decision == "block":
                assert guard_decision.reason is not None
                return blocked_turn_response(request, guard_decision.reason)
        position_progress = restore_position_progress(
            strategy=request.case.opponent_strategy,
            current=request.snapshot.state.opponent_progress,
            agreement=request.snapshot.state.agreement,
        )
        opponent_state = request.snapshot.state.model_copy(
            update={"opponent_progress": position_progress}
        )
        context = OpponentContext(
            shared_context=request.case.shared_context,
            opponent_private_context=request.case.opponent_private_context,
            agreement_rules=request.case.agreement_rules,
            opponent_strategy=request.case.opponent_strategy,
            player_role=request.case.player_role,
            opponent_role=request.case.opponent_role,
            state=opponent_state,
            transcript=public_transcript(request.snapshot.transcript),
            user_text=request.user_text,
        )
        last_proposal_error: ModelErrorCode = "invalid_opponent_output"
        last_proposal_hint: Literal["complete_transition_quote"] | None = None

        def validated_proposal(
            raw: object,
        ) -> tuple[OpponentProposal, OpponentPositionProgress | None] | None:
            nonlocal last_proposal_error, last_proposal_hint
            last_proposal_hint = None
            try:
                proposal = OpponentProposal.model_validate(raw)
            except ValueError:
                last_proposal_error = "invalid_opponent_output"
                return None
            role_reason = opponent_role_rejection_reason(visible_proposal_text(proposal))
            if role_reason is not None:
                last_proposal_error = VALIDATION_ERROR_CODES[role_reason]
                return None
            if request.snapshot.state.agreement is not None and isinstance(
                proposal.resolution,
                (PartialDecision, DeferredDecision),
            ):
                last_proposal_error = "invalid_opponent_output"
                return None
            if not valid_proposal(
                proposal,
                request.case,
                request.user_text,
                request.snapshot.transcript,
            ):
                last_proposal_error = "invalid_opponent_output"
                return None
            try:
                opponent_progress = apply_position_transition(
                    strategy=request.case.opponent_strategy,
                    current=position_progress,
                    proposal=proposal,
                    user_text=request.user_text,
                    turn_id=request.turn_id,
                    transcript=request.snapshot.transcript,
                    stored_agreement=request.snapshot.state.agreement,
                )
            except IncompleteTransitionEvidenceError:
                last_proposal_error = "opponent_unearned_concession"
                last_proposal_hint = "complete_transition_quote"
                return None
            except UnearnedConcessionError:
                last_proposal_error = "opponent_unearned_concession"
                return None
            except ValueError:
                last_proposal_error = "invalid_opponent_output"
                return None
            return proposal, opponent_progress

        def validated_validation(raw: object) -> ValidationDecision | None:
            try:
                return ValidationDecision.model_validate(raw)
            except ValueError:
                return None

        proposal: OpponentProposal | None = None
        opponent_progress: OpponentPositionProgress | None = None
        attempt_error: ModelErrorCode = "invalid_opponent_output"
        for attempt_index in range(model_attempts):
            if attempt_index > 0:
                context = context.model_copy(
                    update={
                        "revision_reason": attempt_error,
                        "revision_hint": last_proposal_hint
                        if attempt_error == "opponent_unearned_concession"
                        else None,
                    }
                )
            proposal_result = await validated_model_call(
                lambda context=context: active_opponent.respond(context),
                validated_proposal,
                attempts=1,
            )
            if proposal_result.value is None:
                attempt_error = (
                    "opponent_unavailable"
                    if proposal_result.failure == "unavailable"
                    else last_proposal_error
                )
                continue

            candidate, candidate_progress = proposal_result.value
            if validator is not None:
                validation_context = ValidationContext(
                    case=request.case,
                    state=opponent_state,
                    transcript=public_transcript(request.snapshot.transcript),
                    user_text=request.user_text,
                    proposal=candidate,
                )
                validation_result = await validated_model_call(
                    lambda validation_context=validation_context: validator.assess(
                        validation_context
                    ),
                    validated_validation,
                    attempts=1,
                )
                if validation_result.value is None:
                    attempt_error = (
                        "validator_unavailable"
                        if validation_result.failure == "unavailable"
                        else "invalid_validator_output"
                    )
                    continue
                validation = validation_result.value
                if validation.decision == "uncertain":
                    attempt_error = "validator_uncertain"
                    continue
                if validation.decision == "reject":
                    assert validation.reason is not None
                    attempt_error = VALIDATION_ERROR_CODES[validation.reason]
                    continue

            proposal = candidate
            opponent_progress = candidate_progress
            break

        if proposal is None:
            return model_failure_response(request, attempt_error)
        resolution = proposal.resolution
        proposed_agreement = (
            resolution.as_deal_terms() if isinstance(resolution, AgreementResolution) else None
        )
        proposed_decision = (
            resolution if isinstance(resolution, (PartialDecision, DeferredDecision)) else None
        )
        if proposed_agreement is not None:
            agreement = proposed_agreement
            decision = None
            stage = "agreed"
        elif request.snapshot.state.agreement is not None:
            agreement = request.snapshot.state.agreement
            decision = None
            stage = "agreed"
        elif proposed_decision is not None:
            agreement = None
            decision = proposed_decision
            stage = proposed_decision.kind
        else:
            agreement = None
            decision = request.snapshot.state.decision
            stage = request.snapshot.state.stage
        snapshot = SessionSnapshot(
            session_id=request.snapshot.session_id,
            state=SessionState(
                turn_count=request.snapshot.state.turn_count + 1,
                stage=stage,
                agreement=agreement,
                decision=decision,
                opponent_progress=opponent_progress,
            ),
            transcript=[
                *request.snapshot.transcript,
                TranscriptEntry(
                    turn_id=request.turn_id,
                    speaker="player",
                    status="accepted",
                    text=request.user_text,
                ),
                TranscriptEntry(
                    turn_id=request.turn_id,
                    speaker="opponent",
                    status="accepted",
                    text=proposal.text,
                ),
            ],
        )
        return TurnResponse(
            session_id=snapshot.session_id,
            turn_id=request.turn_id,
            status="accepted",
            opponent_text=proposal.text,
            snapshot=snapshot,
        )

    @app.post(
        "/v1/finish",
        response_model=FinishResponse,
        dependencies=[Depends(require_service_token)],
    )
    async def finish_duel(request: FinishRequest) -> FinishResponse:
        if not any(entry.status == "accepted" for entry in request.snapshot.transcript):
            raise HTTPException(status_code=409, detail="Duel has no accepted turns")
        outcome = determine_outcome(request.snapshot)
        return FinishResponse(
            session_id=request.snapshot.session_id,
            outcome=outcome,
            judge_verdicts=await judge_duel(
                request.case,
                request.snapshot,
                outcome,
                active_judge,
                active_retrieval,
                model_attempts,
            ),
            trainer_feedback=await train_duel(
                request.case,
                request.snapshot,
                outcome,
                active_trainer,
                request.preparation,
                model_attempts,
            ),
        )

    return app


def create_configured_app(
    model_http: httpx.AsyncClient | None = None,
    retrieval_http: httpx.AsyncClient | None = None,
) -> FastAPI:
    mode = os.environ.get("ARENA_MODEL_MODE", "demo")
    service_token = os.environ.get("ARENA_SERVICE_TOKEN") or None
    if mode == "demo":
        return create_app(service_token=service_token)
    if mode != "qwen":
        raise ValueError("ARENA_MODEL_MODE must be demo or qwen")

    from arena_ai.runtime import build_qwen_runtime

    runtime = build_qwen_runtime(model_http, retrieval_http)
    return create_app(
        opponent=runtime.opponent,
        guard=runtime.guard,
        validator=runtime.validator,
        judge=runtime.judge,
        trainer=runtime.trainer,
        owned_model_http=runtime.owned_http,
        mode="qwen",
        model_id=runtime.model_id,
        service_token=service_token,
        readiness_probe=runtime.readiness,
        model_attempts=runtime.model_attempts,
        judge_retrieval=runtime.retrieval,
        owned_retrieval_http=runtime.owned_retrieval_http,
    )


app = create_configured_app()
