"""Enforce the durable-comment policy: production source and user-facing copy
carry no engineering-process residue (cycle labels, phase/slice/track markers).

Runtime identifiers that a machine checks (API v4, schema/feature/training
contract versions, recipe_id, action_policy_v1, model_id, horizon_months) are
allowed. History lives in CHANGELOG.md and dated archives, which are exempt.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Process labels that must not appear in production comments or Guided strings.
KILL_LIST = re.compile(
    r"\bTrack [AB]\b|\bPhase [1-4]\b|\bSlice [12]\b|\bD-00[0-9]\b|\bR-[0-9]{3}\b"
    r"|\bDIRECTIVE-[0-9]{3}\b|director cycle|source drop|integration phase|temporary staging"
)

# Persona/audience labels that must not appear in production CODE (py/js) or the
# copy it renders. The product targets accessibility but never labels the user.
# Scanned only over code files so prose documentation is not falsely flagged.
PERSONA_KILL_LIST = re.compile(
    r"\bcitizen[- ]?safe\b|\bcitizen\b|\bbeginner\b|\bmathematician\b|\bnovice\b",
    re.IGNORECASE,
)

# Files/trees exempt from the scan.
EXEMPT_PREFIXES = (
    "static/vendor/",   # third-party bundles
    "tests/",           # this scanner and fixtures may name the terms
    "local-notes/",     # gitignored working notes (not shipped)
)
EXEMPT_NAMES = {"CHANGELOG.md"}


def _tracked_source_files(patterns=("*.py", "*.js", "*.md")):
    out = subprocess.check_output(["git", "ls-files", *patterns], cwd=str(ROOT))
    for rel in out.decode("utf-8").splitlines():
        rel = rel.strip()
        if not rel or rel in EXEMPT_NAMES or rel.startswith(EXEMPT_PREFIXES):
            continue
        yield rel


def test_no_process_labels_in_production_sources():
    offenders = []
    for rel in _tracked_source_files():
        path = ROOT / rel
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if KILL_LIST.search(line):
                offenders.append(f"{rel}:{i}: {line.strip()}")
    assert not offenders, (
        "Engineering-process labels found in production sources. Rewrite them as "
        "a durable invariant or move history to CHANGELOG.md:\n" + "\n".join(offenders)
    )


def test_no_persona_labels_in_production_code():
    offenders = []
    for rel in _tracked_source_files(patterns=("*.py", "*.js")):
        path = ROOT / rel
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if PERSONA_KILL_LIST.search(line):
                offenders.append(f"{rel}:{i}: {line.strip()}")
    assert not offenders, (
        "Persona/audience labels found in production code. The product targets "
        "accessibility but must not label the user; use durable descriptions "
        "(guided interpretation, plain-language summary, research rationale):\n"
        + "\n".join(offenders)
    )
