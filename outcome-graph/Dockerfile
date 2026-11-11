# Hosted copy of Oversight: API plus the built page, rule bundles baked in. Iris and the coach call
# Claude on Vertex AI and Iris speaks with Cloud Text-to-Speech, both as the Cloud Run service
# account (no API keys). Build it with deploy.sh, which assembles the context.
FROM python:3.12-slim-bookworm
ENV UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 \
    AGENT=0 OUTCOME_DATA_ROOT=/app/data FASTEMBED_CACHE_PATH=/app/models
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
# the embedding model the coach and comment search use, baked in so no request waits on a download
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"
COPY src/ ./src/
COPY web/dist/ ./web/dist/
COPY data/ ./data/
CMD ["sh", "-c", "uvicorn server:app --app-dir src --host 0.0.0.0 --port ${PORT:-8080}"]
