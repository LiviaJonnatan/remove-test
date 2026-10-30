FROM python:3.12-slim-bookworm

# rule_passages is copied to /app/lib, not /app/src: compose mounts ./api-service/src over /app/src,
# which would hide anything the image put there.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/lib \
    FASTEMBED_CACHE_PATH=/opt/models

RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
# The embedding model is part of the image, so the container needs no download at run time.
# It must be the model rule-passages embedded with (MODEL_NAME in rule_passages/embedding.py).
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"
# `rule_passages` is a second build context, set in docker-compose.yml.
COPY --from=rule_passages . ./lib/rule_passages/
COPY src/ ./src/
CMD ["uvicorn", "main:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
