# FinCompass 4.0 — free evidence + validation-gated forecasting + adaptive research API
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY VERSION config.py api.py ./
COPY services/ ./services/
COPY forecasting/ ./forecasting/
COPY realtime/ ./realtime/
COPY models/ ./models/
COPY adaptive_models/ ./adaptive_models/
COPY static/ ./static/
COPY legal/ ./legal/
COPY docs/ ./docs/
COPY ARCHITECTURE.md MODEL_CARD.md FORECASTING.md REALTIME.md SETTINGS.md VALIDATION_PROTOCOL.md README.md DEVELOPER_GUIDE.md CONTRIBUTING.md PRIVACY.md SECURITY.md ASVS_CHECKLIST.md CHANGELOG.md TODO.md ./

# Runtime state (cache, audit, SEC cache when configured) is kept outside the
# immutable application/model files.
RUN mkdir -p /app/data && useradd -m -u 10001 appuser \
    && chown -R appuser:appuser /app/data
USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/api/v1/health || exit 1

CMD ["python", "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
