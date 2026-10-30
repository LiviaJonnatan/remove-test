FROM python:3.12-slim-bookworm

# The same image runs on a laptop (CPU) and as a Vertex AI custom job (the PyPI torch wheel carries
# the CUDA libraries, so a GPU machine uses its GPU with no other change).
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/models

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
# The base model is part of the image, so a job needs no download at start.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')"
COPY configs/ ./configs/
COPY src/ ./src/
ENTRYPOINT ["python", "src/main.py"]
CMD ["train", "--mode", "in"]
