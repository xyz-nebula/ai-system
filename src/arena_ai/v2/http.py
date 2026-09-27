"""Opt-in stateless turn route; Backend owns persistence and round commit."""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Request, Security
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError

from arena_ai.judge_retrieval import JudgeRetrieval
from arena_ai.v2.contracts import FinishRequest, TurnRequest, TurnResponse
from arena_ai.v2.finish import analyze_finish
from arena_ai.v2.finish_response import FinishResponse
from arena_ai.v2.judges import judge_finish
from arena_ai.v2.preparation import (
    PreparationReviewRequest,
    PreparationReviewResponse,
    review_preparation,
)
from arena_ai.v2.trainer import train_finish
from arena_ai.v2.turn import QwenTurnPipeline


def install_turn_route(
    app: FastAPI,
    pipeline: QwenTurnPipeline,
    authorize: Callable[[HTTPAuthorizationCredentials | None], Awaitable[None]],
    bearer: HTTPBearer,
    retrieval: JudgeRetrieval,
) -> None:
    def error(status: int, code: str, message: str) -> JSONResponse:
        return JSONResponse(
            status_code=status,
            content={
                "code": code,
                "message": message,
                "retryable": False,
            },
            headers={"WWW-Authenticate": "Bearer"} if status == 401 else None,
        )

    @app.post("/v2/preparation/review", operation_id="ai_post__v2_preparation_review")
    async def preparation_review(
        raw: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)],
    ) -> Response:
        try:
            await authorize(credentials)
        except HTTPException:
            return error(401, "unauthorized", "Unauthorized")
        if raw.headers.get("X-Arena-Contract-Version") != "2.0.0-rc.1":
            return error(409, "contract_version_mismatch", "Unsupported contract version")
        try:
            request = PreparationReviewRequest.model_validate_json(await raw.body())
        except ValueError:
            return error(422, "invalid_request", "Invalid preparation review request")
        result = await review_preparation(request, pipeline.analysis)
        return Response(result.model_dump_json(), media_type="application/json")

    @app.post("/v2/turn", response_model=TurnResponse, operation_id="ai_post__v2_turn")
    async def turn(
        raw: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)],
    ) -> Response:
        try:
            await authorize(credentials)
        except HTTPException:
            return error(401, "unauthorized", "Unauthorized")
        if raw.headers.get("X-Arena-Contract-Version") != "2.0.0-rc.1":
            return error(409, "contract_version_mismatch", "Unsupported contract version")
        try:
            request = TurnRequest.model_validate_json(await raw.body())
        except ValidationError as invalid:
            if any(
                item["loc"] == ()
                and str(item.get("ctx", {}).get("error")) == "Turn requires an open round"
                for item in invalid.errors(include_input=False)
            ):
                return error(409, "round_closed", "Round is not open")
            return error(422, "invalid_request", "Invalid turn request")
        except ValueError:
            return error(422, "invalid_request", "Invalid turn request")
        result = await pipeline.turn(request)
        # Serialize exact Decimal values directly; never use a float JSON round-trip.
        return Response(result.model_dump_json(), media_type="application/json")

    @app.post("/v2/finish", operation_id="ai_post__v2_finish")
    async def finish(
        raw: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)],
    ) -> Response:
        try:
            await authorize(credentials)
        except HTTPException:
            return error(401, "unauthorized", "Unauthorized")
        if raw.headers.get("X-Arena-Contract-Version") != "2.0.0-rc.1":
            return error(409, "contract_version_mismatch", "Unsupported contract version")
        try:
            request = FinishRequest.model_validate_json(await raw.body())
        except ValidationError as invalid:
            if any(
                item["loc"] == ()
                and str(item.get("ctx", {}).get("error")) == "Finish requires a frozen round"
                for item in invalid.errors(include_input=False)
            ):
                return error(409, "round_not_closed", "Round is not frozen")
            return error(422, "invalid_request", "Invalid finish request")
        except ValueError:
            return error(422, "invalid_request", "Invalid finish request")
        result = await analyze_finish(request, pipeline.analysis)
        result["judge_verdicts"] = await judge_finish(
            request, pipeline.judge, retrieval, pipeline.analysis
        )
        result["trainer_feedback"] = (await train_finish(request, pipeline.analysis)).model_dump(
            mode="python"
        )
        response = FinishResponse.model_validate(result)
        return Response(response.model_dump_json(), media_type="application/json")


class ArenaApp(FastAPI):
    """Add exact v2 request schemas without automatic float body parsing."""

    def openapi(self) -> dict[str, Any]:
        schema = super().openapi()
        if "/v2/turn" not in schema["paths"]:
            return schema
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        request_schema = TurnRequest.model_json_schema(
            ref_template="#/components/schemas/V2{model}"
        )
        for name, definition in request_schema.pop("$defs", {}).items():
            components[f"V2{name}"] = definition
        components["V2TurnRequest"] = request_schema
        operation = schema["paths"]["/v2/turn"]["post"]
        operation["requestBody"] = {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/V2TurnRequest"},
                }
            },
        }
        operation["parameters"] = [
            {
                "name": "X-Arena-Contract-Version",
                "in": "header",
                "required": True,
                "schema": {"type": "string", "const": "2.0.0-rc.1"},
            }
        ]
        components["V2ServiceError"] = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "code": {"type": "string", "minLength": 1},
                "message": {"type": "string", "minLength": 1},
                "retryable": {"type": "boolean"},
            },
            "required": ["code", "message", "retryable"],
        }
        for status in (401, 409, 422):
            operation["responses"][str(status)] = {
                "description": "Rejected before model execution",
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/V2ServiceError"}}
                },
            }
        if "/v2/finish" in schema["paths"]:
            finish_schema = FinishRequest.model_json_schema(
                ref_template="#/components/schemas/V2{model}"
            )
            for name, definition in finish_schema.pop("$defs", {}).items():
                components[f"V2{name}"] = definition
            components["V2FinishRequest"] = finish_schema
            finish = schema["paths"]["/v2/finish"]["post"]
            finish["requestBody"] = {
                "required": True,
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/V2FinishRequest"}}
                },
            }
            finish["parameters"] = operation["parameters"]
            response_schema = FinishResponse.model_json_schema(
                ref_template="#/components/schemas/V2{model}"
            )
            for name, definition in response_schema.pop("$defs", {}).items():
                components[f"V2{name}"] = definition
            components["V2FinishResponse"] = response_schema
            finish["responses"]["200"]["content"]["application/json"]["schema"] = {
                "$ref": "#/components/schemas/V2FinishResponse"
            }
            for status in (401, 409, 422):
                finish["responses"][str(status)] = operation["responses"][str(status)]
        if "/v2/preparation/review" in schema["paths"]:
            review = schema["paths"]["/v2/preparation/review"]["post"]
            for model in (PreparationReviewRequest, PreparationReviewResponse):
                definition = model.model_json_schema(ref_template="#/components/schemas/V2{model}")
                for name, child in definition.pop("$defs", {}).items():
                    components[f"V2{name}"] = child
                components[f"V2{model.__name__}"] = definition
            review["requestBody"] = {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/V2PreparationReviewRequest"}
                    }
                },
            }
            review["responses"]["200"]["content"]["application/json"]["schema"] = {
                "$ref": "#/components/schemas/V2PreparationReviewResponse"
            }
            review["parameters"] = operation["parameters"]
            for status in (401, 409, 422):
                review["responses"][str(status)] = operation["responses"][str(status)]
        return schema
