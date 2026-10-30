FROM python:3.12-slim-bookworm

# rule_passages is copied to /app/lib, not /app/src: compose mounts ./passage-stage/src over /app/src,
# which would hide anything the image put there.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/lib

RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
# `rule_passages` is a second build context, set in docker-compose.yml.
COPY --from=rule_passages . ./lib/rule_passages/
COPY src/ ./src/
CMD ["python", "src/main.py"]
