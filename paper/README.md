# FinCompass — Technical Manuscript

**Title:** FinCompass: Bayesian Probabilistic Forecasting with Evidence-Tiered Validation and Governed Live Adaptation

**Author:** Rajeev Yadav, Ph.D.

## Files

- `main.tex` — canonical manuscript source
- `refs.bib` — bibliography database
- `figures/` — figure image sources
- `FinCompass-Technical-Manuscript.pdf` — compiled manuscript
- `arxiv/` — self-contained arXiv submission package derived from the same source
  (`main.tex`, `refs.bib`, `figures/`)

## Build

With a full TeX installation:

```bash
pdflatex main.tex
bibtex main
pdflatex main.tex
pdflatex main.tex
```

## Scope boundary

The numerical results reported in the paper are deterministic synthetic
regression-fixture results from the FinCompass validation pipeline. They verify
statistical and software behavior and are not presented as evidence of market
alpha or live forecasting skill. The bundled real historical bootstrap exists
only to exercise offline Model Lab operation; it is research-only and is not used
to claim market forecasting skill.
