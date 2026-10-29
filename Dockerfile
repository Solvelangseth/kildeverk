# One small image: the Python service, with the website built in from the catalogue.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.6.9 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first, so code changes don't reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY README.md LICENSE ./
COPY src ./src
RUN uv sync --frozen --no-dev && kildeverk site --out /app/site

RUN useradd --create-home --uid 1000 kildeverk && mkdir -p /data && chown kildeverk /data

ENV KILDEVERK_DEPLOYMENT=public \
    KILDEVERK_SITE_DIR=/app/site \
    KILDEVERK_CACHE_PATH=/data/responses.sqlite

EXPOSE 8080
# A mounted volume arrives owned by root, so the container starts as root, hands /data to the
# service's user and runs the service as that user.
CMD ["sh", "-c", "chown kildeverk /data && exec setpriv --reuid=kildeverk --regid=kildeverk --init-groups kildeverk serve --http --host 0.0.0.0 --port 8080"]
