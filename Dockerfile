# FinCompass — free evidence + validation-gated forecasting + adaptive research API
FROM python:3.14-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Firebase Admin is only exercised in hosted (Cloud Run) mode for server-side ID
# token verification; installing it here is inert for the local/desktop editions.
RUN pip install --no-cache-dir "firebase-admin>=6.5.0,<8"

COPY VERSION config.py api.py ./
COPY services/ ./services/
COPY forecasting/ ./forecasting/
COPY config/ ./config/
COPY datasets/market-seed/ ./datasets/market-seed/
COPY realtime/ ./realtime/
COPY models/ ./models/
COPY adaptive_models/ ./adaptive_models/
COPY static/ ./static/
COPY resources/ ./resources/
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
  CMD curl -fsS "http://127.0.0.1:${PORT:-8000}/api/health" || exit 1

# Bind the port the platform provides ($PORT on Cloud Run = 8080), defaulting to
# 8000 for local Docker. The same image serves the local and hosted editions;
# hosting is toggled entirely by environment variables at deploy time.
CMD ["sh", "-c", "python -m uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000}"]
