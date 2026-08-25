"""Create a public-safe FinCompass source ZIP.

The private delivery tree can contain local research data and model artifacts.
This exporter validates the full release manifest first, then deliberately omits
protected payloads and writes a separate PUBLIC_RELEASE_MANIFEST.sha256 inside
the ZIP. The private RELEASE_MANIFEST.sha256 is not copied into the public ZIP.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "RELEASE_MANIFEST.sha256"
PUBLIC_MANIFEST_NAME = "PUBLIC_RELEASE_MANIFEST.sha256"

BLOCKED_PREFIXES = (
    "data/",
    "datasets/market-seed/",
    "models/",
    "adaptive_models/",
    "private_assets/",
    "development/",
    "handoff/",
)
BLOCKED_FILES = {
    "PRIVATE_ASSET_INVENTORY.json",
    "RELEASE_MANIFEST.sha256",
}
BLOCKED_SUFFIXES = (
    ".db",
    ".sqlite",
    ".sqlite3",
    ".joblib",
    ".npz",
    ".tar.gz",
)


def is_public_safe(rel: str) -> bool:
    rel = rel.replace("\\", "/").lstrip("./")
    if rel in BLOCKED_FILES:
        return False
    if rel == "data/.gitkeep":
        return True
    if any(rel.startswith(prefix) for prefix in BLOCKED_PREFIXES):
        return False
    if rel.lower().endswith(BLOCKED_SUFFIXES):
        return False
    return True


def _manifest_entries() -> list[tuple[str, str]]:
    if not MANIFEST.is_file():
        raise FileNotFoundError("RELEASE_MANIFEST.sha256 is missing")
    rows: list[tuple[str, str]] = []
    for raw in MANIFEST.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        expected, rel = raw.split(None, 1)
        rel = rel.strip().lstrip("*")
        if rel.startswith("./"):
            rel = rel[2:]
        path = ROOT / rel
        if not path.is_file():
            raise FileNotFoundError(f"manifest path is missing: {rel}")
        actual = sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"manifest hash mismatch before packaging: {rel}")
        rows.append((expected, rel))
    return rows


def package(output: Path, root_name: str = "FinCompass") -> tuple[Path, str, int, int]:
    rows = _manifest_entries()
    safe_rows = [(digest, rel) for digest, rel in rows if is_public_safe(rel)]
    omitted = len(rows) - len(safe_rows)
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    public_manifest = "".join(f"{digest}  ./{rel}\n" for digest, rel in safe_rows)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for _digest, rel in safe_rows:
            archive.write(ROOT / rel, f"{root_name}/{rel}")
        archive.writestr(f"{root_name}/{PUBLIC_MANIFEST_NAME}", public_manifest)

    digest = sha256(output.read_bytes()).hexdigest()
    return output, digest, len(safe_rows) + 1, omitted


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a public-safe FinCompass source ZIP")
    parser.add_argument("--output", required=True, help="ZIP path to create")
    parser.add_argument("--root-name", default="FinCompass", help="top-level directory name inside the ZIP")
    args = parser.parse_args()
    path, digest, count, omitted = package(Path(args.output), args.root_name)
    print(f"Created PUBLIC-SAFE {path} with {count} files; omitted {omitted} protected files")
    print(f"SHA-256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
