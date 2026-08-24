# FinCompass — Coding Standards

Applies to all Selora-authored source in this repository (Python app,
frontend JS/CSS, tooling). Ported from the same standard used across the
author's projects, for consistency.

## Naming

- **Descriptive, intention-revealing names.** A name states what the thing
  *is* or *does* in this domain, specifically enough that a reader outside the
  original context understands it.
- **Forbidden generic names** for anything non-trivial: `data`, `temp`, `tmp`,
  `result`, `res`, `val`, `obj`, `item`, `helper`, `process`, `handle`,
  `do_it`, `stuff`, `foo`. Name for the actual concept (`normalized_features`,
  `anchor_probability`, `matured_labels`, `prequential_window`).
- Functions are verbs/verb-phrases; booleans read as predicates
  (`is_live_eligible`, `has_matured_label`).
- Consistent casing: `snake_case` for Python identifiers, `CONSTANT_CASE` for
  module constants, `PascalCase` for classes.

## Documentation

- Module and non-trivial function/class get a docstring: what it does, the
  meaning of key parameters, and any domain assumption (horizon, benchmark,
  data semantics) a reader could get wrong.
- Comments explain *why*, not *what*. Don't restate the code.
- Spell out domain abbreviations on first use; don't rely on context that only
  existed in a chat conversation the reader wasn't part of.

## Correctness and safety

- Type hints on public functions.
- Validate inputs at boundaries (API handlers, dataset loaders); fail loud on
  malformed financial data rather than silently producing a number.
- No secrets, keys, or real provider data in code or fixtures (see
  `GOVERNANCE.md` §2). Configuration comes from the environment
  (`.env.example` documents the variables).
- Keep the analytical layers separated as designed: evidence engine, validated
  forecast anchor, and adaptive live layer must not leak un-validated state
  into a validated artifact.

## No AI / tool references

No AI/LLM/tool name appears in code, comments, docstrings, commit messages, or
file metadata (see `GOVERNANCE.md` §1). Tool-generated file fingerprints
(e.g. `python-docx`, `openpyxl`, `PptxGenJS`) must be scrubbed before commit.
