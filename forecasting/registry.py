"""Validated forecast model registry with explicit activation.

A validated model is a candidate, not automatically the live anchor.  The live
anchor is selected only by an explicit atomic activation pointer.  This avoids
"newest file wins" behavior and makes activation auditable and reversible.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib

from forecasting import FORECAST_ENGINE_VERSION

MODEL_ROOT = Path(os.getenv("FINCOMPASS_MODELS_DIR") or (Path(__file__).resolve().parents[1] / "models"))
ACTIVE_MODEL_FILENAME = "active_model.json"
# Live-eligible tiers: only these may be explicitly activated as the Live anchor.
_USABLE_TIERS = {"validated_research", "validated_market"}
# Forecast-eligible tiers: the Bayesian reference baseline is loadable for guided
# forecasts (it is a hard-valid model) but is deliberately NOT live-activatable and
# must never be presented as demonstrated alpha.
_FORECAST_TIERS = {"bayesian_baseline", "validated_research", "validated_market"}
_TIER_RANK = {"rejected": 0, "fixture_only": 0, "bayesian_baseline": 1,
              "validated_research": 2, "validated_market": 3}


def _manifest_content_hash(manifest: Dict[str, Any]) -> str:
    return sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _active_path(root: Path) -> Path:
    return root / ACTIVE_MODEL_FILENAME


def save_model(
    model,
    validation_report: Dict[str, Any],
    dataset_manifest: Dict[str, Any],
    profile_name: str = "default",
    root: Path = MODEL_ROOT,
    lineage: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    created = datetime.now(timezone.utc).isoformat()
    base = {
        "forecast_engine_version": FORECAST_ENGINE_VERSION,
        "profile_name": profile_name,
        "validation_tier": validation_report["validation_tier"],
        "created_at": created,
        "dataset_schema_version": dataset_manifest.get("schema_version"),
        "dataset_manifest_content_sha256": _manifest_content_hash(dataset_manifest),
        "dataset_files": dataset_manifest.get("files"),
        "dataset_split": dataset_manifest.get("split"),
        "dataset_provenance": dataset_manifest.get("provenance"),
        "target": dataset_manifest.get("target"),
        "data_quality": dataset_manifest.get("data_quality"),
        "settings": model.settings,
        "features": model.feature_names,
        "validation": validation_report,
    }
    # Retrain lineage: a candidate is a NEW artifact; it records its predecessor
    # and never overwrites it.
    if lineage:
        base["lineage"] = dict(lineage)
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
    out: List[Dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        if path.name == ACTIVE_MODEL_FILENAME:
            continue
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(item, dict) or not item.get("model_id") or not item.get("model_file"):
                continue
            item["manifest_file"] = path.name
            out.append(item)
        except Exception:
            continue
    return sorted(out, key=lambda x: x.get("created_at", ""), reverse=True)


def _find_manifest(model_id: str, root: Path) -> Optional[Dict[str, Any]]:
    wanted = str(model_id or "").strip()
    if not wanted:
        return None
    return next((m for m in list_model_manifests(root) if m.get("model_id") == wanted), None)


def _verified_model_path(manifest: Dict[str, Any], root: Path) -> Optional[Path]:
    file_name = str(manifest.get("model_file") or "")
    if not file_name or Path(file_name).name != file_name:
        return None
    path = root / file_name
    if not path.is_file():
        return None
    expected = str(manifest.get("model_sha256") or "")
    if not expected or sha256(path.read_bytes()).hexdigest() != expected:
        return None
    return path


def get_active_pointer(root: Path = MODEL_ROOT) -> Optional[Dict[str, Any]]:
    path = _active_path(root)
    if not path.is_file():
        return None
    try:
        pointer = json.loads(path.read_text(encoding="utf-8"))
        return pointer if isinstance(pointer, dict) else None
    except Exception:
        return None


def get_active_manifest(root: Path = MODEL_ROOT) -> Optional[Dict[str, Any]]:
    pointer = get_active_pointer(root)
    if not pointer:
        return None
    manifest = _find_manifest(str(pointer.get("model_id") or ""), root)
    if not manifest:
        return None
    if manifest.get("validation_tier") not in _USABLE_TIERS:
        return None
    if _verified_model_path(manifest, root) is None:
        return None
    if pointer.get("model_sha256") != manifest.get("model_sha256"):
        return None
    if pointer.get("manifest_content_sha256") != _manifest_content_hash(
        {k: v for k, v in manifest.items() if k != "manifest_file"}
    ):
        return None
    return manifest


def set_active_model(
    model_id: str,
    *,
    experiment_id: Optional[str] = None,
    activated_by: str = "local_user",
    root: Path = MODEL_ROOT,
) -> Dict[str, Any]:
    """Explicitly activate one validated, live-eligible model artifact."""
    root.mkdir(parents=True, exist_ok=True)
    manifest = _find_manifest(model_id, root)
    if not manifest:
        raise ValueError(f"model not found: {model_id}")
    if manifest.get("validation_tier") not in _USABLE_TIERS:
        raise ValueError("only validated_research or validated_market models can be activated")
    provenance = manifest.get("dataset_provenance") or {}
    if provenance.get("live_eligible_target") is False:
        raise ValueError("this recipe is research-only and cannot be activated for live forecasts")
    if _verified_model_path(manifest, root) is None:
        raise ValueError("model artifact is missing or its SHA-256 does not match the manifest")

    previous = get_active_pointer(root)
    previous_model_id = previous.get("model_id") if previous else None

    clean_manifest = {k: v for k, v in manifest.items() if k != "manifest_file"}
    activated_at = datetime.now(timezone.utc).isoformat()
    pointer = {
        "schema_version": "1.0.0-active-model1",
        "model_id": manifest["model_id"],
        "model_sha256": manifest["model_sha256"],
        "manifest_content_sha256": _manifest_content_hash(clean_manifest),
        "validation_tier": manifest["validation_tier"],
        "profile_name": manifest.get("profile_name"),
        "experiment_id": experiment_id,
        "previous_model_id": previous_model_id,
        "activated_at": activated_at,
        "activated_by": str(activated_by or "local_user"),
    }
    path = _active_path(root)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(pointer, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    # Append an auditable activation-history entry (previous -> new, explicit action).
    _append_activation_history(root, {
        "previous_model_id": previous_model_id,
        "new_model_id": manifest["model_id"],
        "activated_at": activated_at,
        "activated_by": str(activated_by or "local_user"),
        "experiment_id": experiment_id,
    })
    return pointer


ACTIVATION_HISTORY_FILENAME = "activation_history.json"


def _append_activation_history(root: Path, entry: Dict[str, Any]) -> None:
    path = root / ACTIVATION_HISTORY_FILENAME
    try:
        history = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
        if not isinstance(history, list):
            history = []
    except Exception:
        history = []
    history.append(entry)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(history, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def get_activation_history(root: Path = MODEL_ROOT) -> List[Dict[str, Any]]:
    path = root / ACTIVATION_HISTORY_FILENAME
    try:
        history = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
        return history if isinstance(history, list) else []
    except Exception:
        return []


def clear_active_model(root: Path = MODEL_ROOT) -> bool:
    path = _active_path(root)
    if path.exists():
        path.unlink()
        return True
    return False


def load_model(
    model_id: Optional[str] = None,
    profile_name: Optional[str] = None,
    minimum_tier: str = "validated_research",
    root: Path = MODEL_ROOT,
):
    """Load an explicit model ID, or the explicitly activated live anchor.

    Omitting ``model_id`` never falls back to "newest usable".  That behavior
    made model activation implicit and is intentionally removed.
    """
    required = _TIER_RANK.get(minimum_tier, 1)
    if model_id:
        manifest = _find_manifest(model_id, root)
    else:
        manifest = get_active_manifest(root)
    if not manifest:
        return None, None
    if profile_name and manifest.get("profile_name") != profile_name:
        return None, None
    if _TIER_RANK.get(manifest.get("validation_tier"), 0) < required:
        return None, None
    path = _verified_model_path(manifest, root)
    if path is None:
        return None, None
    return joblib.load(path), manifest


def load_best_forecast_model(*, profile_name: Optional[str] = None,
                             horizon_months: Optional[int] = None,
                             root: Path = MODEL_ROOT):
    """Load the strongest forecast-eligible artifact without activating it.

    Selection is deterministic by exact requested horizon, evidence tier and
    creation time. This is for one-shot Guided Forecast only; it never changes
    the explicit Live anchor. The Bayesian baseline participates here (it is
    forecast-eligible) but remains ineligible for Live activation.
    """
    manifests = [m for m in list_model_manifests(root)
                 if m.get("validation_tier") in _FORECAST_TIERS
                 and m.get("guided_eligible", True) is not False]
    if profile_name:
        manifests = [m for m in manifests if m.get("profile_name") == profile_name]
    if horizon_months is not None:
        h = int(horizon_months)

        def mh(m):
            t = m.get("target") or {}
            if t.get("horizon_months") is not None:
                return int(t.get("horizon_months"))
            return int(round(float(t.get("horizon_trading_days") or 0) / 21.0))

        manifests = [m for m in manifests if mh(m) == h]
    manifests.sort(key=lambda m: (_TIER_RANK.get(m.get("validation_tier"), 0), m.get("created_at", "")),
                   reverse=True)
    for manifest in manifests:
        path = _verified_model_path(manifest, root)
        if path is not None:
            return joblib.load(path), manifest
    return None, None


def registry_status(root: Path = MODEL_ROOT) -> Dict[str, Any]:
    manifests = list_model_manifests(root)
    usable = [m for m in manifests if m.get("validation_tier") in _USABLE_TIERS]
    market = [m for m in usable if m.get("validation_tier") == "validated_market"]
    baseline = [m for m in manifests if m.get("validation_tier") == "bayesian_baseline"]
    pointer = get_active_pointer(root)
    active = get_active_manifest(root)
    pointer_valid = bool(pointer and active)
    return {
        "forecast_engine_version": FORECAST_ENGINE_VERSION,
        "models_total": len(manifests),
        "usable_models": len(usable),
        "market_validated_models": len(market),
        "bayesian_baseline_models": len(baseline),
        "live_eligible_models": sum(
            1 for m in usable if (m.get("dataset_provenance") or {}).get("live_eligible_target") is not False
        ),
        "active_model": active.get("model_id") if active else None,
        "active_tier": active.get("validation_tier") if active else None,
        "activation_pointer_present": bool(pointer),
        "activation_pointer_valid": pointer_valid,
        "models": [
            {
                **{k: m.get(k) for k in ["model_id", "profile_name", "validation_tier", "created_at", "target", "data_quality"]},
                "live_eligible_target": (m.get("dataset_provenance") or {}).get("live_eligible_target", True),
                "is_active": bool(active and m.get("model_id") == active.get("model_id")),
            }
            for m in manifests[:20]
        ],
    }
