# FinCompass hosted setup — Cloud Run + Firebase Authentication

This setup creates a real browser-hosted FinCompass service. It is not a public
sample-data demo. Users can create their own Firebase account and use the
application whenever Cloud Run is available.

## Privacy architecture

FinCompass does not create a server-side user profile database. Firebase owns
the authentication identity. The hosted application does not persist a user's
watchlist, portfolio inputs, Forecast history, DCF inputs, option selections, or
research history.

The application still needs temporary computation and cache files while a Cloud
Run instance is alive. `FINCOMPASS_DATA_DIR=/tmp/fincompass` keeps those files on
the instance's ephemeral filesystem. They are not durable storage and are not a
per-user research database.

Browser preferences stay in the user's own `localStorage`. The existing
`/api/prefs` mirror is disabled automatically in hosted mode.

Custom FinCompass audit logging is disabled in hosted mode. Google Cloud may
still produce infrastructure request logs. Do not log request bodies, Firebase
ID tokens, passwords, portfolio payloads, or analytical results.

## Before deployment

1. Create or choose one Google Cloud project.
2. Add Firebase to the same project.
3. In Firebase Authentication, enable **Email/Password**.
4. Register a Firebase Web app and copy its Web API key.
5. Install the Google Cloud CLI locally and authenticate with `gcloud auth login`.
6. A billing account may be required by Google Cloud even when usage remains
   inside the Cloud Run free allowance. Configure budgets/alerts in Google Cloud.

## Code integration (already done)

The hosted-edition code is already integrated into this repository — Firebase
token verification (`services/cloud_auth.py`), the browser auth layer
(`static/cloud_auth.js`/`.css`), the PWA files, the `/api/cloud/*` routes, and a
Cloud-Run-ready root `Dockerfile`. Hosting is off by default and is enabled only
by environment variables, so the desktop and local Docker editions are unchanged.

You do not need to run any patcher. Verify the code with:

```bash
python -m pytest tests/test_cloud_auth.py
```

## Local smoke test

Create a temporary environment file or export:

```bash
export FINCOMPASS_HOSTED_MODE=1
export FINCOMPASS_AUTH_MODE=required
export FINCOMPASS_DATA_DIR=/tmp/fincompass
export RATE_LIMIT_BACKEND=memory
export AUDIT_IP_MODE=none
export AUDIT_LOG_ENABLED=0
export FIREBASE_PROJECT_ID="your-project-id"
export FIREBASE_API_KEY="your-web-api-key"
export FIREBASE_AUTH_DOMAIN="your-project-id.firebaseapp.com"
```

Install the cloud-only dependency and start the application:

```bash
pip install -r cloudrun/requirements-cloud.txt
uvicorn api:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/`. Create a test account and verify that an API call
is rejected when signed out and succeeds when signed in.

## Deploy

From the repository root:

```bash
export GOOGLE_CLOUD_PROJECT="your-project-id"
export FIREBASE_API_KEY="your-web-api-key"
export FIREBASE_PROJECT_ID="$GOOGLE_CLOUD_PROJECT"
./cloudrun/deploy.sh
```

`gcloud run deploy --source .` builds the source and deploys it to Cloud Run.
The service itself is Cloud Run `--allow-unauthenticated` because Firebase
authentication is enforced inside FinCompass; otherwise a normal browser would
be forced through Google Cloud IAM rather than the application's signup flow.

## Firebase authorized domain

After Cloud Run returns the service URL, add its hostname to Firebase
Authentication's authorized domains if Firebase requires it for your selected
sign-in methods.

## What is intentionally disabled or non-durable

- Server-side UI preference persistence.
- Durable per-user watchlists.
- Durable portfolio state.
- Durable Forecast history.
- Durable Live history.
- Durable Model Lab output.
- Persistent application audit logs.

The normal analytical and Forecast paths can use bundled model artifacts and
public market-data providers. Model Lab should remain a local-desktop capability
unless a separate cloud execution policy is deliberately designed.

## Recommended production-hardening before broad sharing

- Keep `FINCOMPASS_AUTH_MODE=required`.
- Add email verification before allowing expensive endpoints if abuse appears.
- Add Firebase App Check or another abuse-control layer if needed.
- Set Cloud Run max instances to a small value while operating inside a free
  budget.
- Configure Google Cloud budgets and alerts.
- Review Cloud Logging retention and exclusions.
- Never place provider secrets in JavaScript or Firebase public configuration.
- Put optional market-data API keys in Secret Manager, not `--set-env-vars`.
- Add a privacy page explaining Firebase identity data versus FinCompass research
  data.
