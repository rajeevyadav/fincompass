"""Package the manifest-bound FinCompass source tree into one ZIP.

Only files bound by RELEASE_MANIFEST.sha256 plus the manifest itself are added.
This keeps the reviewed/tested source set identical to the delivered source set
and prevents runtime databases, caches, or build residue from leaking into the
package.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "RELEASE_MANIFEST.sha256"


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


def package(output: Path, root_name: str = "FinCompass") -> tuple[Path, str, int]:
    rows = _manifest_entries()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for _digest, rel in rows:
            archive.write(ROOT / rel, f"{root_name}/{rel}")
        archive.write(MANIFEST, f"{root_name}/{MANIFEST.name}")
    digest = sha256(output.read_bytes()).hexdigest()
    return output, digest, len(rows) + 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the manifest-bound FinCompass source ZIP")
    parser.add_argument("--output", required=True, help="ZIP path to create")
    parser.add_argument("--root-name", default="FinCompass", help="top-level directory name inside the ZIP")
    args = parser.parse_args()
    path, digest, count = package(Path(args.output), args.root_name)
    print(f"Created {path} with {count} files")
    print(f"SHA-256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
