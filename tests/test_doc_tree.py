"""The canonical documentation tree: one manuscript source, one user-guide
source, no duplicate/versioned trees, and no tracked LaTeX build artifacts."""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _tracked(*globs):
    out = subprocess.check_output(["git", "ls-files", *globs], cwd=str(ROOT))
    return [l.strip() for l in out.decode("utf-8").splitlines() if l.strip()]


def test_canonical_files_present():
    for rel in ["paper/main.tex", "paper/refs.bib", "paper/FinCompass-Technical-Manuscript.pdf",
                "paper/arxiv/main.tex", "docs/user-guide/main.tex",
                "docs/FinCompass-User-Guide.pdf", "docs/FinCompass-User-Manual.pdf"]:
        assert (ROOT / rel).exists(), f"missing canonical doc: {rel}"


def test_no_tracked_latex_build_artifacts():
    junk = [f for f in _tracked("paper/*", "docs/*")
            if f.rsplit(".", 1)[-1] in {"aux", "log", "out", "toc", "bcf", "bbl"} or f.endswith(".run.xml")]
    assert not junk, f"tracked LaTeX build artifacts: {junk}"


def test_no_duplicate_or_versioned_doc_trees():
    tracked = _tracked("paper/*", "docs/*")
    bad = [f for f in tracked if any(seg in f.lower() for seg in
           ("/v2/", "progressive", "revised", "arxiv-manuscript-final", "technical-article", "main.pdf"))]
    assert not bad, f"non-canonical doc paths still tracked: {bad}"


def test_titles_have_no_version_numbers():
    manu = (ROOT / "paper" / "main.tex").read_text(encoding="utf-8", errors="ignore")
    assert "Bayesian Probabilistic Forecasting" in manu
    guide = (ROOT / "docs" / "user-guide" / "main.tex").read_text(encoding="utf-8", errors="ignore")
    assert "FinCompass User Guide" in guide
