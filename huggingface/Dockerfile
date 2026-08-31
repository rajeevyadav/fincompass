# Hugging Face Space image for the hosted FinCompass demo.
#
# The Space stays tiny: this Dockerfile clones the public FinCompass repository
# at build time and runs it. Rebuild the Space to pick up new releases. Hugging
# Face's free CPU tier has no billing attached, so this can never incur a charge.
FROM python:3.12-slim

# git to fetch the app; curl for the health check.
RUN apt-get update && apt-get install -y --no-install-recommends git curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Pull the application. Pin to a tag for a stable demo, or use the default branch
# for the latest. Change the ref below to a tag (e.g. v2.0.0) to freeze it.
ARG FINCOMPASS_REF=main
RUN git clone --depth 1 --branch "${FINCOMPASS_REF}" https://github.com/rajeevyadav/fincompass.git . \
    && pip install --no-cache-dir -r requirements.txt

# Hosted-demo runtime: open access (no login), nothing persisted per user, all
# scratch/cache under the instance's ephemeral /tmp. Set FINCOMPASS_AUTH_MODE to
# "required" and add the Firebase secrets to require sign-in instead.
ENV FINCOMPASS_HOSTED_MODE=1 \
    FINCOMPASS_AUTH_MODE=off \
    FINCOMPASS_DATA_DIR=/tmp/fincompass \
    RATE_LIMIT_BACKEND=memory \
    AUDIT_IP_MODE=none \
    AUDIT_LOG_ENABLED=0 \
    PORT=7860
# Allow Hugging Face to embed the app in its Space iframe (Cloud Run stays strict).
# Bare keywords are quoted by the app, so no single quotes are needed here.
ENV FINCOMPASS_FRAME_ANCESTORS="self https://huggingface.co https://*.hf.space"

# Hugging Face serves the Space on port 7860 and runs the container as a non-root
# user; keep all writable state under world-writable /tmp.
RUN mkdir -p /tmp/fincompass && chmod 1777 /tmp/fincompass

EXPOSE 7860

CMD ["sh", "-c", "python -m uvicorn api:app --host 0.0.0.0 --port ${PORT:-7860}"]
