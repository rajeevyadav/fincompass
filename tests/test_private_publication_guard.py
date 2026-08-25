from __future__ import annotations

from pathlib import Path
import zipfile

from tools.package_source import BLOCKED_PREFIXES, is_public_safe, package


ROOT = Path(__file__).resolve().parents[1]


def test_private_paths_are_classified_as_not_public_safe():
    blocked = [
        "datasets/market-seed/market_seed.db",
        "models/example.joblib",
        "adaptive_models/example.state.json",
        "data/fincompass.db",
        "private_assets/corpus.csv",
        "PRIVATE_ASSET_INVENTORY.json",
    ]
    assert all(not is_public_safe(path) for path in blocked)
    assert is_public_safe("data/.gitkeep")
    assert is_public_safe("services/research_store.py")


def test_public_source_package_contains_no_private_assets(tmp_path):
    output = tmp_path / "public-source.zip"
    package(output)
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        assert "FinCompass/PUBLIC_RELEASE_MANIFEST.sha256" in names
        assert "FinCompass/RELEASE_MANIFEST.sha256" not in names
        relative = [name.removeprefix("FinCompass/") for name in names]
        for rel in relative:
            if rel == "PUBLIC_RELEASE_MANIFEST.sha256":
                continue
            assert is_public_safe(rel), rel
            assert not any(rel.startswith(prefix) for prefix in BLOCKED_PREFIXES if prefix != "data/")


def test_private_notice_exists_and_is_explicit():
    text = (ROOT / "PRIVATE-DATA-NOTICE.md").read_text(encoding="utf-8")
    assert "DO NOT PUBLISH" in text
    assert "GitHub" in text
    assert "package_source.py" in text
    assert "package_private_backup.py" in text
