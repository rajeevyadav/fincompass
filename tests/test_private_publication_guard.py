"""The public source package must never contain private local-only assets.

`tools/package_source.package()` zips exactly the RELEASE_MANIFEST entries, which
`tools/generate_release_manifest.py` builds from the git-tracked public set with
private data/models excluded. This test packages the tree and asserts no private
asset (seed, private trained models, research DB, handover envelope, working
notes) leaks into the ZIP, while the core public files are present.
"""
from __future__ import annotations

from pathlib import Path
import zipfile

from tools.package_source import package

ROOT = Path(__file__).resolve().parents[1]

PRIVATE_MARKERS = (
    "datasets/market-seed/",
    "handoff/",
    "development/",
    "private_assets/",
    "data/research/",
    "PRIVATE_MODEL_MANIFEST.sha256",
    "PRIVATE_MODEL_NOTICE.txt",
)


def _zip_rel_names(zip_path: Path) -> list[str]:
    with zipfile.ZipFile(zip_path) as archive:
        # Strip the top-level "<root_name>/" prefix.
        return [name.split("/", 1)[1] if "/" in name else name for name in archive.namelist()]


def test_public_source_package_contains_no_private_assets(tmp_path):
    out, _digest, count = package(tmp_path / "public-source.zip")
    names = _zip_rel_names(out)

    for name in names:
        assert not any(name.startswith(marker) or marker in name for marker in PRIVATE_MARKERS), (
            f"private asset leaked into public package: {name}"
        )

    # Public models ship (the synthetic fixture + the PUBLIC bundled reference
    # model); private/rejected trained artifacts must not.
    leaked_models = [
        n for n in names
        if n.endswith(".joblib") and "fixture-reference" not in n and "bundled-monthly" not in n
    ]
    assert not leaked_models, f"private model artifact leaked: {leaked_models}"

    # Core public source is present.
    assert any(n == "api.py" for n in names)
    assert any(n == "tools/package_source.py" for n in names)
    assert count > 50


def test_manifest_only_lists_present_public_files():
    from tools.package_source import _manifest_entries

    rows = _manifest_entries()  # raises if any manifest path is missing or hash-mismatched
    rels = {rel for _digest, rel in rows}
    assert "api.py" in rels
    # No private markers may appear in the manifest itself.
    for rel in rels:
        assert not any(rel.startswith(m) or m in rel for m in PRIVATE_MARKERS), f"private path in manifest: {rel}"
