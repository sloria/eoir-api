# Hub image

FROM python:3.15.2-slim-trixie@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS python-base

##### Build #####

FROM python-base AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages/acis-core/pyproject.toml packages/acis-core/
COPY packages/acis-browser/pyproject.toml packages/acis-browser/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-default-groups --no-install-workspace --no-editable
COPY README.md LICENSE ./
COPY packages packages
COPY src src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-default-groups --no-editable

##### Run image #####

FROM python-base AS hub
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system --gid 65532 nonroot \
    && adduser --system --uid 65532 --ingroup nonroot --home /data nonroot
COPY --from=builder /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH \
    EOIR_API_CONFIG=/config/hub.toml \
    HOME=/data \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1
USER nonroot
WORKDIR /data
VOLUME /data
EXPOSE 8001
ENTRYPOINT ["tini", "--", "eoir-api"]
CMD ["hub"]
