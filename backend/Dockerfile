
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system appuser && \
    useradd --system --gid appuser appuser

COPY requirements.txt .

# Official PyPI by default. Override with --build-arg PIP_INDEX_URL=... only for a mirror you trust.
ARG PIP_INDEX_URL=https://pypi.org/simple

RUN python -m pip install \
    --no-cache-dir \
    --index-url "${PIP_INDEX_URL}" \
    --timeout 120 \
    --retries 5 \
    -r requirements.txt

COPY . .

RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["uvicorn", "server:app", \
    "--host", "0.0.0.0", \
    "--port", "8000", \
    "--no-proxy-headers", \
    "--no-access-log"]
