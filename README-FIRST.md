# FinCompass — Start Here

This repository contains:

- The **FinCompass** application at the repository root (a self-hostable
  FastAPI + vanilla-JavaScript research workbench). See `README.md`.
- The open-access **manuscript** under `paper/` (`main.tex` / `main.pdf`).
- `TECHNICAL-REVIEW.md` - technical review and application findings.

**Run it (Windows):** double-click `run.bat`.
**Run it (macOS / Linux):** `./run.sh`.

Both scripts create a virtual environment, install dependencies, and start the
local server at http://127.0.0.1:8000.

Model Lab ships with a small real historical research-only starter corpus so a fresh installation can exercise offline training immediately. Broader market histories are acquired with **Update local data**, cached locally, and then reused/incrementally extended; training itself never performs a network fetch.

The application opens in **Guided mode** for a simple update -> train -> inspect -> activate -> forecast workflow. **Research mode** exposes the full recipe, validation, model-comparison, experiment-lineage, and adaptive settings controls for advanced work. Both modes use the same validation gates.

Manuscript author metadata is set to Rajeev Yadav, Ph.D. (rajeevyadav@gmail.com).
