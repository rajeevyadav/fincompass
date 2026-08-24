"""Validated forecast model registry."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import joblib

from forecasting import FORECAST_ENGINE_VERSION

# The registry root defaults to the bundled ./models directory (writable when
# run from source). Frozen/packaged builds ship a read-only bundle, so the
# in-app model builder points FINCOMPASS_MODELS_DIR at a writable location
# (e.g. %LOCALAPPDATA%\FinCompass\models) so newly trained models can be saved
# and then read back through the same registry.
MODEL_ROOT = Path(os.getenv("FINCOMPASS_MODELS_DIR") or (Path(__file__).resolve().parents[1] / "models"))


def save_model(model, validation_report: Dict[str, Any], dataset_manifest: Dict[str, Any], profile_name: str = "default", root: Path = MODEL_ROOT) -> Dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    created = datetime.now(timezone.utc).isoformat()
    base = {
        "forecast_engine_version": FORECAST_ENGINE_VERSION,
        "profile_name": profile_name,
        "validation_tier": validation_report["validation_tier"],
        "created_at": created,
        "dataset_schema_version": dataset_manifest.get("schema_version"),
        "dataset_manifest_content_sha256": sha256(json.dumps(dataset_manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
        "dataset_files": dataset_manifest.get("files"),
        "dataset_split": dataset_manifest.get("split"),
        "dataset_provenance": dataset_manifest.get("provenance"),
        "target": dataset_manifest.get("target"),
        "data_quality": dataset_manifest.get("data_quality"),
        "settings": model.settings,
        "features": model.feature_names,
        "validation": validation_report,
    }
    # Bind the public model ID directly to the serialized artifact hash. This
    # makes an ID independently checkable instead of deriving it from a timestamp.
    tmp_path = root / f".{profile_name}.tmp.joblib"
    joblib.dump(model, tmp_path, compress=3)
    model_digest = sha256(tmp_path.read_bytes()).hexdigest()
    model_id = model_digest[:16]
    model_path = root / f"{profile_name}-{model_id}.joblib"
    tmp_path.replace(model_path)
    manifest_path = root / f"{profile_name}-{model_id}.json"
    base["model_id"] = model_id
    base["model_file"] = model_path.name
    base["model_sha256"] = model_digest
    manifest_path.write_text(json.dumps(base, indent=2, sort_keys=True), encoding="utf-8")
    return base


def list_model_manifests(root: Path = MODEL_ROOT) -> List[Dict[str, Any]]:
    root.mkdir(parents=True, exist_ok=True)
    out = []
    for path in sorted(root.glob("*.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            item["manifest_file"] = path.name
            out.append(item)
        except Exception:
            continue
    return sorted(out, key=lambda x: x.get("created_at", ""), reverse=True)


def load_model(model_id: Optional[str] = None, profile_name: Optional[str] = None, minimum_tier: str = "validated_research", root: Path = MODEL_ROOT):
    tier_rank = {"rejected": 0, "fixture_only": 0, "validated_research": 1, "validated_market": 2}
    required = tier_rank.get(minimum_tier, 1)
    candidates = list_model_manifests(root)
    for manifest in candidates:
        if model_id and manifest.get("model_id") != model_id:
            continue
        if profile_name and manifest.get("profile_name") != profile_name:
            continue
        if tier_rank.get(manifest.get("validation_tier"), 0) < required:
            continue
        path = root / manifest["model_file"]
        if not path.exists():
            continue
        if sha256(path.read_bytes()).hexdigest() != manifest.get("model_sha256"):
            continue
        return joblib.load(path), manifest
    return None, None


def registry_status(root: Path = MODEL_ROOT) -> Dict[str, Any]:
    manifests = list_model_manifests(root)
    usable = [m for m in manifests if m.get("validation_tier") in {"validated_research", "validated_market"}]
    market = [m for m in usable if m.get("validation_tier") == "validated_market"]
    return {
        "forecast_engine_version": FORECAST_ENGINE_VERSION,
        "models_total": len(manifests),
        "usable_models": len(usable),
        "market_validated_models": len(market),
        "active_model": usable[0].get("model_id") if usable else None,
        "active_tier": usable[0].get("validation_tier") if usable else None,
        "models": [
            {k: m.get(k) for k in ["model_id", "profile_name", "validation_tier", "created_at", "target", "data_quality"]}
            for m in manifests[:20]
        ],
    }
