"""Generate the SHA-256 manifest for the distributable FinCompass source tree.

The manifest is deliberately derived from a small, explicit exclusion policy so
new source/manual/handoff files cannot be forgotten during release closure.
Runtime databases, caches, build intermediates, and repository metadata are not
part of the distributable source contract.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Iterable, List

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "RELEASE_MANIFEST.sha256"

EXCLUDED_DIR_NAMES = {
    ".git",
    ".pytest_cache",
    ".venv",
    "__pycache__",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
EXCLUDED_PAPER_BUILD = {
    "paper/main.aux",
    "paper/main.log",
    "paper/main.out",
}


def is_release_file(path: Path) -> bool:
    """Return whether *path* belongs to the distributable source package."""
    if not path.is_file():
        return False
    rel = path.relative_to(ROOT).as_posix()
    if path == MANIFEST:
        return False
    if any(part in EXCLUDED_DIR_NAMES for part in path.relative_to(ROOT).parts):
        return False
    if path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    if rel in EXCLUDED_PAPER_BUILD:
        return False
    # Runtime state is rebuilt in the per-user writable directory. Keep only
    # the placeholder that preserves the source directory itself.
    if rel.startswith("data/") and rel != "data/.gitkeep":
        return False
    # PRIVATE, local-only assets (see PRIVATE-DATA-NOTICE.md and .gitignore) are
    # never part of the PUBLIC distributable source contract. They are present in
    # the private working tree (and bundled into the private exe/Docker image),
    # but must not appear in the public manifest so the manifest verifies on a
    # clean public clone. The public synthetic fixtures under models/ and
    # adaptive_models/ (fixture-reference-* / balanced-adaptive-*) are kept.
    import fnmatch
    _PRIVATE_PREFIXES = (
        "datasets/market-seed/", "handoff/", "development/",
        "private_assets/", "testmodels/",
    )
    if any(rel == p.rstrip("/") or rel.startswith(p) for p in _PRIVATE_PREFIXES):
        return False
    _PRIVATE_GLOBS = ("models/default-*", "models/*-market-*", "adaptive_models/*-live-*")
    if any(fnmatch.fnmatch(rel, g) for g in _PRIVATE_GLOBS):
        return False
    # Editor/OS leftovers are never release inputs.
    if path.name in {".DS_Store", "Thumbs.db"} or path.name.endswith("~"):
        return False
    return True


def release_files() -> List[Path]:
    # The distributable set is exactly the git-tracked files: this excludes all
    # gitignored assets — the PRIVATE local-only data AND build artifacts
    # (dist/, build/, *.spec, caches) that may be present in a working tree but
    # are never part of the public source contract. Fall back to a filesystem
    # walk when git metadata is unavailable (e.g. an extracted source ZIP).
    import subprocess
    paths: List[Path]
    try:
        out = subprocess.check_output(["git", "ls-files", "-z"], cwd=str(ROOT), stderr=subprocess.DEVNULL)
        paths = [ROOT / rel for rel in out.decode("utf-8").split("\0") if rel]
    except Exception:
        paths = list(ROOT.rglob("*"))
    return sorted((p for p in paths if is_release_file(p)), key=lambda p: p.relative_to(ROOT).as_posix())


def manifest_lines(files: Iterable[Path] | None = None) -> List[str]:
    rows = []
    for path in files if files is not None else release_files():
        rel = path.relative_to(ROOT).as_posix()
        digest = sha256(path.read_bytes()).hexdigest()
        rows.append(f"{digest}  ./{rel}")
    return rows


def write_manifest() -> Path:
    MANIFEST.write_text("\n".join(manifest_lines()) + "\n", encoding="utf-8")
    return MANIFEST


def main() -> int:
    path = write_manifest()
    print(f"Wrote {len(release_files())} SHA-256 entries to {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
