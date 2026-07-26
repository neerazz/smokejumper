# syntax=docker/dockerfile:1

FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.9.18 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
# --frozen fails rather than re-resolving, so the image can only ever contain
# what uv.lock says. --no-dev keeps ruff/pyright/pytest out. --no-editable
# installs the package into the virtualenv, so the runtime stage carries no
# source tree and there is exactly one copy of the code in the image.
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim
# The app writes nothing inside its image; running as root would only widen a
# container escape.
RUN useradd --system --create-home --uid 10001 smokejumper
WORKDIR /app
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1
COPY --from=build /app/.venv /app/.venv
COPY alembic.ini ./
COPY migrations ./migrations
# `config/` is data the settings object reads, not code. It has to be copied
# explicitly because --no-editable installs the package into the virtualenv,
# where the package-relative default would resolve inside site-packages.
COPY config ./config
ENV SMOKEJUMPER_CONFIG_DIR=/app/config
USER smokejumper
EXPOSE 8000
# v1 is a single instance (SPEC 1), so the app container is the only writer and
# migrate-then-serve is ordered by construction. Replicas would need migrations
# hoisted into a separate step ahead of the rollout.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn --factory smokejumper.app:app_from_env --host 0.0.0.0 --port 8000"]
