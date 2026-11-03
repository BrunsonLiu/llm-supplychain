# Multi-stage build: install the package once, then copy the installed tree.
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.11-slim

WORKDIR /app

COPY --from=builder /install /usr/local

COPY app/ ./app/
COPY config/ ./config/
COPY data/ ./data/
COPY scripts/ ./scripts/

RUN mkdir -p logs cache output

ENV PYTHONPATH=/app/src:/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
