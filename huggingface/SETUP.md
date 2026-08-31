# FinCompass on Hugging Face Spaces — free hosted demo

Hugging Face Spaces run this app on a **free CPU tier with no credit card and no
billing**, so it can never cost you anything no matter how many people use it.
The Space stays tiny: its Dockerfile clones the public FinCompass repository at
build time and runs it.

The two files this Space needs are in this folder:

- `README.md` — the Space page + required Hugging Face metadata (`sdk: docker`,
  `app_port: 7860`).
- `Dockerfile` — clones the repo and launches the app in open, hosted-demo mode
  (no login, nothing persisted per user, all scratch under ephemeral `/tmp`).

## One-time setup (about 10 minutes, all in the browser)

1. Create a free account at <https://huggingface.co/join>.
2. Go to <https://huggingface.co/new-space>:
   - **Owner**: you. **Space name**: e.g. `fincompass`.
   - **License**: MIT.
   - **Select the SDK**: **Docker** → **Blank**.
   - **Hardware**: **CPU basic** (free).
   - **Visibility**: Public.
   - Click **Create Space**.
3. The new Space is an empty git repo with a starter `README.md`. Add the two
   files from this folder. Easiest path — the Space's web editor:
   - Open the **Files** tab → click `README.md` → **Edit** → replace its contents
     with `huggingface/README.md` from this repo → **Commit**.
   - **Add file → Create a new file** → name it `Dockerfile` → paste
     `huggingface/Dockerfile` from this repo → **Commit**.
   - (Or clone the Space repo locally, copy both files in, and `git push`.)
4. The Space builds automatically — watch the **Logs** tab. First build takes a
   few minutes (it clones the repo and installs scikit-learn/scipy).
5. When it finishes, the app is live at
   `https://<your-username>-fincompass.hf.space` and embedded on the Space page.

## Keeping it updated

The Dockerfile clones the default branch, so to pull new code just open the Space
→ **Settings → Factory rebuild**. To pin the demo to a fixed release instead, set
the build arg in the Dockerfile: change `ARG FINCOMPASS_REF=main` to
`ARG FINCOMPASS_REF=v2.0.0`.

## Options

- **Require sign-in** (instead of the open demo): in the Space, **Settings →
  Variables and secrets**, add `FINCOMPASS_AUTH_MODE=required`, then add the
  Firebase values as secrets (`FIREBASE_API_KEY`, `FIREBASE_PROJECT_ID`,
  `FIREBASE_AUTH_DOMAIN`) — see `cloudrun/SETUP.md` for creating those. On the
  free CPU tier there is no billing, so the open demo is usually fine.
- **Sleep**: free Spaces pause after a period of inactivity and wake on the next
  visit (a few seconds). This is normal and costs nothing.

## What the demo does and does not do

- Works: Forecast, analytics, DCF/reverse DCF, options, bonds, portfolio, risk,
  glossary — from the bundled models and public market data.
- Not in the hosted demo: Model Lab and any durable per-user storage. For the
  full experience, users download the free desktop app from the GitHub releases.
