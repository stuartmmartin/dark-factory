# syntax=docker/dockerfile:1.7-labs@sha256:b99fecfe00268a8b556fad7d9c37ee25d716ae08a5d7320e6d51c4dd83246894
# Build context is the repository root: docker build -f services/ledger/Dockerfile --target prod .
# Stages: base -> deps (third-party dependencies only, cached)
#   -> dev  (no source: compose bind-mounts it; hot reload)
#   -> prod (source copied, installed non-editable, non-root)
# (1.7-labs for `COPY --parents`.) The syntax frontend and the base images are pinned by digest;
# bump tag and digest together (resolve with `docker buildx imagetools inspect <image>:<tag>`).
ARG PYTHON_IMAGE=python:3.13.15-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.19@sha256:04d046b13e60d6bcec73cbc5e1cad25d680dea90c8573340950a0ac2d1aef424
FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_IMAGE} AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy UV_COMPILE_BYTECODE=0 \
    UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH
COPY --from=uv /uv /uvx /bin/
WORKDIR /repo

FROM base AS deps
ARG SERVICE=ledger
# Only the lock and every workspace member's manifest (uv --locked checks the whole workspace):
# this layer changes only when dependencies change. No source, and no tools/ source ever.
COPY pyproject.toml uv.lock ./
COPY --parents libs/py/*/pyproject.toml tools/*/pyproject.toml services/*/pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --package ${SERVICE} --no-install-workspace --no-dev

FROM deps AS dev
ARG SERVICE=ledger
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --package ${SERVICE} --no-install-workspace
# Source is NOT copied: compose bind-mounts services/<svc>/src and libs/py so edits reload
# without an image rebuild. The workspace packages are installed editable at container start.
COPY compose/dev-entrypoint.sh /usr/local/bin/dev-entrypoint
ENV SERVICE=${SERVICE}
ENTRYPOINT ["dev-entrypoint"]

FROM deps AS prod
ARG SERVICE=ledger
# The service and the platform libraries it installs (ledger needs no tools/ package at runtime).
COPY libs/py/ libs/py/
COPY services/${SERVICE}/ services/${SERVICE}/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --package ${SERVICE} --no-dev --no-editable \
 && useradd --system --uid 10001 app
USER 10001
ENV SERVICE=${SERVICE}
ENTRYPOINT ["python", "-m"]
# ledger.main runs uvicorn with log_config=None (D19); never the bare uvicorn CLI.
CMD ["ledger.main"]
