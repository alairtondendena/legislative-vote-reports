# syntax=docker/dockerfile:1

# --- app: the report generator. Standard library only, so nothing to install. ---
FROM python:3.14-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY vote_reports/ vote_reports/
ENTRYPOINT ["python", "-m", "vote_reports"]

# --- check: lint, type-check and test, using the versions pinned in uv.lock. ---
FROM app AS check
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --python /usr/local/bin/python3
COPY data/ data/
COPY output/ output/
COPY tests/ tests/
ENV PATH="/opt/venv/bin:$PATH"
ENTRYPOINT []
CMD ["sh", "-c", "ruff check . && ruff format --check . && mypy && pytest -p no:cacheprovider"]
