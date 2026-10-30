FROM python:3.12-slim-bookworm

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src/ ./src/

# The pinned bge-small tokenizer, checksum verified, so the default run needs no manual step.
COPY fetch_tokenizer.py ./
RUN python fetch_tokenizer.py --out /app/models/bge/tokenizer.json
# The tokenizer is now in the image, so the processor makes no network call at run time.
CMD ["python", "src/main.py"]
