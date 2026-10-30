FROM python:3.12-slim-bookworm

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir uv
WORKDIR /app
# The versions in uv.lock, the ones the tests ran on. No pytest or ruff in the image.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src/ ./src/
CMD ["python", "src/main.py"]
