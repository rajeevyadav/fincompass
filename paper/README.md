# FinCompass — arXiv Manuscript Package

## Manuscript

**Title:** Validation-Gated Adaptive Probabilistic Forecasting in Nonstationary Equity Markets

**Author:** Rajeev Yadav, Ph.D.  
**Email:** rajeevyadav@gmail.com

This directory is self-contained for arXiv-style LaTeX submission. Figures are generated directly in LaTeX/TikZ; there are no external image dependencies.

## Files

- `main.tex` - manuscript source
- `main.pdf` - compiled 23-page manuscript
- `refs.bib` - bibliography database
- `main.bbl` - resolved bibliography for submission environments that do not run BibTeX automatically
- `REVISION_NOTES.md` - scope and revision notes

## Build

With a full TeX installation:

```bash
pdflatex main.tex
bibtex main
pdflatex main.tex
pdflatex main.tex
```

If BibTeX is unavailable, the included `main.bbl` permits:

```bash
pdflatex main.tex
pdflatex main.tex
```

## Scope boundary

The numerical results reported in the paper are deterministic synthetic regression-fixture results from the FinCompass validation pipeline. They verify statistical/software behavior and are not presented as evidence of market alpha or live market forecasting skill. The separate real historical GOOG/MSFT bootstrap bundled with the application exists only to exercise offline Model Lab operation; it is research-only, is not a live model dataset, and is not used to claim market forecasting skill.
