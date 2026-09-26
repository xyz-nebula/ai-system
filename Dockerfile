FROM ghcr.io/astral-sh/uv:0.12.14 AS uv
FROM python:3.13-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /opt/arena
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.13-slim AS runtime
ARG ARENA_SOURCE_REVISION=unknown
LABEL org.opencontainers.image.revision=$ARENA_SOURCE_REVISION
WORKDIR /opt/arena
ENV PATH=/opt/arena/.venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY --from=build /opt/arena/.venv ./.venv
COPY docs/api/openapi.json ./docs/api/openapi.json
COPY scripts/check_ai_service.py ./scripts/check_ai_service.py
USER 10001:10001
CMD ["uvicorn", "arena_ai.app:app", "--host", "127.0.0.1", "--port", "8000", "--no-access-log"]
