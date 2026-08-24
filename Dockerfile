FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml LICENSE README.md ./
COPY src ./src
COPY outputs ./outputs
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 echolock
USER echolock

EXPOSE 8000
CMD ["sh", "-c", "python -m uvicorn echolock.webapp:app --host 0.0.0.0 --port ${PORT:-8000}"]
