# The API as Cloud Run serves it: the rule index and the tuned linker are inside the image, so the
# service needs no ChromaDB server and starts from nothing but this image. deploy.sh assembles the
# build folder (this file, the API, rule_passages, the index folder and the model folder).
FROM python:3.12-slim-bookworm

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/lib \
    FASTEMBED_CACHE_PATH=/opt/models \
    CHROMA_PATH=/app/index \
    LINKER_MODEL_DIR=/app/linker \
    DATA_DIR=/app/data

RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"
COPY lib/ ./lib/
COPY index/ ./index/
COPY linker/ ./linker/
COPY src/ ./src/
# Cloud Run sets PORT.
CMD ["sh", "-c", "uvicorn main:app --app-dir src --host 0.0.0.0 --port ${PORT:-8080}"]
