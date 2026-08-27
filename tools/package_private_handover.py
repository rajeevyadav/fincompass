"""Create a private FinCompass handover ZIP including non-public trained models.

This is deliberately separate from package_source.py.  The public-source path
continues to exclude RESTRICTED/REVIEW_REQUIRED model artifacts.  The private
handover may include them for the owner's local evaluation/use and writes an
in-archive SHA-256 manifest for those private model files.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path
import zipfile

from tools.generate_release_manifest import MANIFEST, ROOT, non_public_model_files, release_files


def package(output: Path, root_name: str = "FinCompass") -> tuple[Path, str, int]:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    public = release_files()
    private_rel = sorted(non_public_model_files())
    private_paths = [ROOT / rel for rel in private_rel]
    for path in private_paths:
        if not path.is_file():
            raise FileNotFoundError(f"private model handover file missing: {path}")

    private_manifest_lines = [
        f"{sha256(path.read_bytes()).hexdigest()}  ./{path.relative_to(ROOT).as_posix()}"
        for path in private_paths
    ]
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in public:
            rel = path.relative_to(ROOT).as_posix()
            archive.write(path, f"{root_name}/{rel}")
        if MANIFEST.is_file():
            archive.write(MANIFEST, f"{root_name}/{MANIFEST.name}")
        for path in private_paths:
            rel = path.relative_to(ROOT).as_posix()
            archive.write(path, f"{root_name}/{rel}")
        archive.writestr(
            f"{root_name}/PRIVATE_MODEL_MANIFEST.sha256",
            "\n".join(private_manifest_lines) + ("\n" if private_manifest_lines else ""),
        )
        archive.writestr(
            f"{root_name}/PRIVATE_MODEL_NOTICE.txt",
            "PRIVATE HANDOVER ONLY\n"
            "Trained model artifacts marked RESTRICTED or REVIEW_REQUIRED are included for local owner use/evaluation.\n"
            "Do not publish these files until their sharing status is explicitly changed to PUBLIC after rights/provenance review.\n",
        )
    digest = sha256(output.read_bytes()).hexdigest()
    return output, digest, len(public) + len(private_paths) + (1 if MANIFEST.is_file() else 0) + 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Create private FinCompass handover ZIP with guarded trained models")
    parser.add_argument("--output", required=True)
    parser.add_argument("--root-name", default="FinCompass")
    args = parser.parse_args()
    path, digest, count = package(Path(args.output), args.root_name)
    print(f"Created {path} with {count} archive entries")
    print(f"SHA-256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
