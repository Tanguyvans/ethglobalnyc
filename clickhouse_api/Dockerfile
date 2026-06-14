FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Build context is the clickhouse_api/ folder (Railway Root Directory = clickhouse_api),
# so all COPY paths are relative to this folder — self-contained service.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8009

# CLICKHOUSE_* and CH_API_* come from Railway env vars (no .env baked into the image).
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8009}"]
