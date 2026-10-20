FROM node:22-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim AS app
COPY --from=ghcr.io/astral-sh/uv:0.11.11 /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
COPY src/ ./src/
COPY migrations/ ./migrations/
COPY alembic.ini ./
COPY docker/entrypoint.sh ./docker/entrypoint.sh
RUN uv sync --frozen --no-dev && chmod +x /app/docker/entrypoint.sh
COPY --from=frontend /app/frontend/dist ./frontend/dist
ENV PATH=/app/.venv/bin:$PATH
RUN useradd --create-home --uid 1000 app
USER app
EXPOSE 8000
ENTRYPOINT ["/app/docker/entrypoint.sh"]
