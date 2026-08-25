# FinCompass - Start Here

> **PRIVATE PACKAGE - DO NOT PUBLISH THIS ZIP.**
>
> This delivery contains local research data and model artifacts. Read
> `PRIVATE-DATA-NOTICE.md` before copying files into any repository or shared
> location.

This repository contains:

- The **FinCompass** application at the repository root (a self-hostable FastAPI + vanilla-JavaScript research workbench). See `README.md`.
- The open-access **manuscript** under `paper/` (`main.tex` / `main.pdf`).
- `TECHNICAL-REVIEW.md` - technical review and application findings.
- `PRIVATE_ASSET_INVENTORY.json` - inventory of the protected local data/model asset classes in this full private package.

**Run it (Windows):** double-click `run.bat`.
**Run it (macOS / Linux):** `./run.sh`.

Both scripts create a virtual environment, install dependencies, and start the local server at http://127.0.0.1:8000.

Model Lab ships with a small real historical research-only starter corpus so a fresh installation can exercise offline training immediately. Broader market histories are acquired with **Update local data**, cached locally, and then reused/incrementally extended; training itself never performs a network fetch.

## Sharing source safely

Do not share this complete ZIP. If you need a source-only archive for public review, create it with:

`python tools/package_source.py --output FinCompass-public-source.zip`

That exporter validates the reviewed source manifest and omits protected data/model assets. It writes `PUBLIC_RELEASE_MANIFEST.sha256` into the public-safe ZIP.

The application has no analytics, telemetry, data-upload, or model-upload feature.

Manuscript author metadata is set to Rajeev Yadav, Ph.D. (rajeevyadav@gmail.com).
