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




def non_public_model_files() -> set[str]:
    """Return model-tree paths that must never enter the public source ZIP.

    A trained artifact is not assumed redistributable merely because raw rows
    are absent.  Explicit RESTRICTED/REVIEW_REQUIRED manifests bind the model,
    manifest and same-ID evidence/summary files as private handover material.
    """
    blocked: set[str] = set()
    models = ROOT / "models"
    if not models.is_dir():
        return blocked
    import json
    for manifest_path in models.glob("*.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(manifest, dict) or not manifest.get("model_id") or not manifest.get("model_file"):
            continue
        sharing = str((manifest.get("dataset_provenance") or {}).get("sharing_status") or "").upper()
        if sharing not in {"RESTRICTED", "REVIEW_REQUIRED"}:
            continue
        blocked.add(manifest_path.relative_to(ROOT).as_posix())
        blocked.add((models / str(manifest["model_file"])).relative_to(ROOT).as_posix())
        model_id = str(manifest["model_id"])
        profile = str(manifest.get("profile_name") or "")
        for sibling in models.glob(f"{profile}-{model_id}-*"):
            if sibling.is_file():
                blocked.add(sibling.relative_to(ROOT).as_posix())
    return blocked

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
    if rel in non_public_model_files():
        return False
    # Runtime state is rebuilt in the per-user writable directory. Keep only
    # the placeholder that preserves the source directory itself.
    if rel.startswith("data/") and rel != "data/.gitkeep":
        return False
    # Private-handover envelope metadata is verified separately and must not
    # become part of the public-source file contract.
    if rel in {"PRIVATE_MODEL_MANIFEST.sha256", "PRIVATE_MODEL_NOTICE.txt"}:
        return False
    # Editor/OS leftovers are never release inputs.
    if path.name in {".DS_Store", "Thumbs.db"} or path.name.endswith("~"):
        return False
    return True


def release_files() -> List[Path]:
    # The distributable set is exactly the git-tracked files: this excludes all
    # gitignored assets — PRIVATE local-only data/models AND build artifacts
    # (dist/, build/, *.spec, caches) — so the manifest verifies on a clean
    # public clone. Fall back to a filesystem walk when git metadata is
    # unavailable (e.g. an extracted source ZIP).
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
