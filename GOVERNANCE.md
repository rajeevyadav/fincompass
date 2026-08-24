# FinCompass — Repository Governance

**Version:** 1.0
**Owner/Maintainer:** Rajeev Yadav
**Applies to:** all source, documentation, the manuscript, and release
artifacts in this repository.

FinCompass is a **private-source** repository with a **public release
surface**: built executables / Docker images are published for download, and
the accompanying manuscript (`paper/`) is intended for open-access
distribution. Governance therefore protects two things at once — the private
working tree (no secrets, no un-reviewed changes to `main`) and the integrity
of what gets published (reproducible, honestly described, no tool/vendor
fingerprints).

## 1. Human authorship — no AI attribution anywhere

1. Only **Rajeev Yadav** appears as author, owner, committer, or approver on
   any file, commit, document, or the manuscript. No other name, handle, tool
   name, or product name is permitted in any authorship or ownership field.
2. AI/automation tools may be used as a drafting aid, but are **never** the
   recorded author, committer, or owner of any output.
3. No commit may carry a `Co-authored-by:` trailer naming an AI/LLM/agent/tool
   (Claude, Copilot, ChatGPT, Gemini, Cursor, Devin, etc.). Enforced by the
   commit-msg hook and reviewed on every PR.
4. This ban covers **file metadata**, not just visible text: document
   properties (`dc:creator`, `cp:lastModifiedBy`, `<Application>`, `<Company>`)
   in any `.docx`/`.pptx`/`.xlsx` — including embedded objects — and PDF
   `/Author` `/Producer` `/Creator`, must show only the authorized name or be
   blank, never a generating tool's name (`PptxGenJS`, `python-docx`,
   `openpyxl`, etc.).

## 2. Secrets and data hygiene

- **Never commit:** `.env` (real), API keys, tokens, private keys
  (`*.pem/.key/.pfx/.p12`), credentials, or runtime data (`data/*.db`, audit
  JSONL). `.env.example` (keys blank) is the only env file that is tracked.
- **Committed on purpose (reproducibility):** the **synthetic** `datasets/`
  fixtures and the `fixture_only` model in `models/` — these are simulated,
  never live-eligible reference artifacts (see `MODEL_CARD.md`,
  `RELEASE_INFO.json`). No real paid-provider (FMP / Alpha Vantage / FRED)
  data is ever committed.
- Enforced by the **Restricted Folder Guard** CI check and the local
  `check-restricted-files` pre-commit hook.

## 3. Branch protection and commit standard

- `main` requires a **pull request** — no direct pushes (including by the
  admin/maintainer). Signed commits, linear history, no force-push/deletion.
- Required status checks: **Restricted Folder Guard** and the release
  verification **CI** (`ci.yml` → `tools/verify_release.py`).
- Commit messages follow `<type>(<scope>): <description>` (conventional
  commits); no "WIP"/"misc"/"fix stuff".

## 4. Coding standards

All Selora-authored code follows `CODING_STANDARDS.md` — descriptive,
intention-revealing names (no bare `data`, `temp`, `result`, `helper`,
`process`), docstrings on non-trivial functions, type hints, secure-coding
practices, and no AI/tool references in code or comments.

## 5. Releases and publishing

- Semantic Versioning (currently `1.0.0`, see `VERSION`). A release bundles a
  built executable / Docker image plus `RELEASE_INFO.json` and the
  `RELEASE_MANIFEST.sha256` integrity manifest.
- The manuscript in `paper/` is the open-access description of the tool; it is
  published as-is and must carry no tool/vendor authorship fingerprints (§1).
- Only release artifacts, the manuscript, the `pages/` download site, and the
  public docs are intended to leave this repository. Everything else stays
  private.


## 7. CI / GitHub Actions discipline (cost and correctness)

Learned from a real incident (account Actions minutes exhausted, 2026-08-24 —
private-repo billing multiplied by double-triggered runs):

1. **One CI run per change.** Workflows trigger on `pull_request` and
   `push: branches: [main]` **only** — never bare `push:` (all branches)
   together with `pull_request:`, which double-fires on every PR push.
2. **Cancel superseded runs.** Every workflow sets
   `concurrency: { group: <name>-${{ github.ref }}, cancel-in-progress: true }`
   so rapid pushes cancel in-flight runs instead of stacking billed minutes.
3. **Keep the matrix lean.** Only the Python versions actually supported;
   don't expand the matrix without cause.
4. **Batch changes; don't push in rapid succession** to an open PR — each push
   re-runs CI. One PR per logical change.
5. **Public where possible.** This repo is MIT-licensed and published, so it is
   **public** — public repos get unlimited free Actions. Private repos bill
   minutes, so the rules above matter most there.
