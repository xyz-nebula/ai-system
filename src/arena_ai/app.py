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
)
from arena_ai.judges import DemoJudge, Judge, judge_duel
from arena_ai.model_recovery import validated_model_call
from arena_ai.outcome import determine_outcome
from arena_ai.privacy import contains_private_phrase, public_transcript
from arena_ai.trainer import DemoTrainer, Trainer, train_duel

SERVICE_BEARER = HTTPBearer(auto_error=False)


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
    return None


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
    visible_text = " ".join(
        [
            proposal.text,
            *(resolution.employee_commitments if isinstance(resolution, AgreementResolution) else []),
            *(resolution.director_commitments if isinstance(resolution, AgreementResolution) else []),
            *(
                resolution.commitments
                if isinstance(resolution, PartialDecision)
                else []
            ),
            *(
                resolution.open_points
                if isinstance(resolution, PartialDecision)
                else []
            ),
            *(
                [resolution.reason, resolution.next_step]
                if isinstance(resolution, DeferredDecision)
                else []
            ),
        ]
    )
    if contains_private_phrase(visible_text, case):
        return False
    if isinstance(resolution, PartialDecision):
        explicit_partial_signal = any(word in player_text for word in ("соглас", "предлага")) or (
            "готов" in player_text
            and any(
                word in player_text
                for word in ("отдельн", "открыт", "остал", "пока", "обсудим")
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
    prior_offer = any(
        entry.speaker == "opponent"
        and entry.status == "accepted"
        and str(terms.kpi_percent) in entry.text
        and "недел" in entry.text.casefold()
        for entry in transcript
    )
    return (
        not re.search(r"\bне\s+(?:готов|согласен|принимаю)\b|\bотказываюсь\b", player_text)
        and (
            (str(terms.kpi_percent) in player_text and "недел" in player_text)
            or ("согласен" in player_text and prior_offer)
        )
        and rules.min_control_weeks <= terms.control_weeks <= rules.max_control_weeks
        and rules.min_kpi_percent <= terms.kpi_percent <= rules.max_kpi_percent
        and (terms.automatic_raise or not rules.require_automatic_raise)
        and not re.search(
            r"\bне\s+(?:согласен|принимаю|принят\w*|согласован\w*)\b",
            text,
        )
        and not re.search(r"\bсогласен\s+(?:обсудить|рассмотреть|вернуться)\b", text)
        and not re.search(r"повышен\w*.{0,40}(?:не\s+обеща|не\s+гарантир|не\s+подтвержд)", text)
        and any(
            word in text
            for word in ("согласен", "договорились", "принимаю", "принят", "согласован")
        )
        and str(terms.kpi_percent) in text
        and "недел" in text
        and "повышен" in text
        and (not terms.automatic_raise or "автоматич" in text or "без повторного" in text)
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
    safe_text = "Давайте вернёмся к условиям работы и повышения. Что вы предлагаете?"
    snapshot = SessionSnapshot(
        session_id=request.snapshot.session_id,
        state=SessionState(turn_count=request.snapshot.state.turn_count + 1),
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
) -> FastAPI:
    if not 1 <= model_attempts <= 3:
        raise ValueError("model_attempts must be between 1 and 3")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if owned_model_http is not None:
                await owned_model_http.aclose()

    app = FastAPI(title="Arena AI", version="0.1.0", lifespan=lifespan)
    active_opponent = opponent if opponent is not None else DemoOpponent()
    active_judge = judge if judge is not None else DemoJudge()
    active_trainer = trainer if trainer is not None else DemoTrainer()

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
        if request.snapshot.state.stage != "negotiating":
            raise HTTPException(status_code=409, detail="Duel already has a decision")
        blocked_reason = guard_reason(request.user_text)
        if blocked_reason is not None:
            return blocked_turn_response(request, blocked_reason)
        if guard is not None:
            guard_context = GuardContext(
                shared_context=request.case.shared_context,
                player_role=request.case.player_role,
                opponent_role=request.case.opponent_role,
                state=request.snapshot.state,
                transcript=public_transcript(request.snapshot.transcript),
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
        context = OpponentContext(
            shared_context=request.case.shared_context,
            opponent_private_context=request.case.opponent_private_context,
            agreement_rules=request.case.agreement_rules,
            player_role=request.case.player_role,
            opponent_role=request.case.opponent_role,
            state=request.snapshot.state,
            transcript=public_transcript(request.snapshot.transcript),
            user_text=request.user_text,
        )
        def validated_proposal(raw: object) -> OpponentProposal | None:
            try:
                proposal = OpponentProposal.model_validate(raw)
            except ValueError:
                return None
            return (
                proposal
                if valid_proposal(
                    proposal,
                    request.case,
                    request.user_text,
                    request.snapshot.transcript,
                )
                else None
            )

        proposal_result = await validated_model_call(
            lambda: active_opponent.respond(context),
            validated_proposal,
            attempts=model_attempts,
        )
        if proposal_result.value is None:
            return model_failure_response(
                request,
                (
                    "opponent_unavailable"
                    if proposal_result.failure == "unavailable"
                    else "invalid_opponent_output"
                ),
            )
        proposal = proposal_result.value
        if validator is not None:
            validation_context = ValidationContext(
                case=request.case,
                state=request.snapshot.state,
                transcript=public_transcript(request.snapshot.transcript),
                user_text=request.user_text,
                proposal=proposal,
            )
            def validated_validation(raw: object) -> ValidationDecision | None:
                try:
                    return ValidationDecision.model_validate(raw)
                except ValueError:
                    return None

            validation_result = await validated_model_call(
                lambda: validator.assess(validation_context),
                validated_validation,
                attempts=model_attempts,
            )
            if validation_result.value is None:
                return model_failure_response(
                    request,
                    (
                        "validator_unavailable"
                        if validation_result.failure == "unavailable"
                        else "invalid_validator_output"
                    ),
                )
            validation = validation_result.value
            if validation.decision == "uncertain":
                return model_failure_response(request, "validator_uncertain")
            if validation.decision == "reject":
                return model_failure_response(request, "invalid_opponent_output")
        resolution = proposal.resolution
        agreement = (
            resolution.as_deal_terms()
            if isinstance(resolution, AgreementResolution)
            else None
        )
        decision = (
            resolution if isinstance(resolution, (PartialDecision, DeferredDecision)) else None
        )
        snapshot = SessionSnapshot(
            session_id=request.snapshot.session_id,
            state=SessionState(
                turn_count=request.snapshot.state.turn_count + 1,
                stage=(
                    "agreed"
                    if agreement is not None
                    else decision.kind
                    if decision is not None
                    else "negotiating"
                ),
                agreement=agreement,
                decision=decision,
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


def create_configured_app(model_http: httpx.AsyncClient | None = None) -> FastAPI:
    mode = os.environ.get("ARENA_MODEL_MODE", "demo")
    service_token = os.environ.get("ARENA_SERVICE_TOKEN") or None
    if mode == "demo":
        return create_app(service_token=service_token)
    if mode != "qwen":
        raise ValueError("ARENA_MODEL_MODE must be demo or qwen")

    from arena_ai.runtime import build_qwen_runtime

    runtime = build_qwen_runtime(model_http)
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
    )


app = create_configured_app()
