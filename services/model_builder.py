"""Offline-first FinCompass Model Lab training orchestration.

Model builds never acquire market data.  Acquisition is a separate Model Lab
operation that populates the durable research store.  A build consumes only
that local corpus, writes a unique evidence bundle, persists the experiment
outcome, and never activates a model implicitly.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import uuid4

from config import DATA_DIR
from forecasting.recipes import get_recipe
from services.cache import cache
from services.research_store import research_store

logger = logging.getLogger(__name__)

BUILD_OUTPUT_DIR = DATA_DIR / "forecast-build"
VALID_PROFILES = ("strict", "standard", "exploratory")
DEFAULT_RECIPE_ID = "core-us-6m"
RECIPE_SETTING_OVERRIDE_ALLOWLIST = {"sample_step_trading_days", "embargo_trading_days"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_experiment_id(recipe_id: str) -> str:
    entropy = f"{recipe_id}|{_utc_now()}|{uuid4().hex}"
    return sha256(entropy.encode("utf-8")).hexdigest()[:20]


def _dataset_digest(manifest: Dict[str, Any]) -> str:
    return sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _failed_gates(report: Dict[str, Any]) -> List[str]:
    checks = ((report.get("gate") or {}).get("checks") or {})
    return sorted(str(name) for name, passed in checks.items() if not bool(passed))


def _load_local_market_data(symbols: Sequence[str], benchmark: str) -> Tuple[Dict[str, Any], Any, List[str]]:
    """Load a recipe's inputs strictly from the durable research store."""
    benchmark_frame = research_store.read_price_history(benchmark)
    prices: Dict[str, Any] = {}
    missing: List[str] = []
    for symbol in symbols:
        ticker = str(symbol).strip().upper()
        if not ticker or ticker == benchmark.upper():
            continue
        frame = research_store.read_price_history(ticker)
        if frame is None or frame.empty:
            missing.append(ticker)
        else:
            prices[ticker] = frame
    return prices, benchmark_frame, missing


def _register(
    experiment_id: str,
    recipe: Dict[str, Any],
    *,
    status: str,
    profile: str,
    message: str,
    model_id: Optional[str] = None,
    validation_tier: Optional[str] = None,
    dataset_hash: Optional[str] = None,
    artifact_hash: Optional[str] = None,
    failed_gates: Optional[List[str]] = None,
    metrics: Optional[Dict[str, Any]] = None,
    lineage_extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    lineage = {
        "recipe_id": recipe["recipe_id"],
        "recipe_settings_hash": recipe["settings_hash"],
        "profile": profile,
        "live_eligible_target": bool(recipe.get("live_eligible_target", True)),
        "feature_contract": recipe.get("feature_contract"),
        "benchmark": recipe.get("benchmark"),
        "horizon_trading_days": recipe.get("horizon_trading_days"),
        "settings_overrides": dict(recipe.get("settings_overrides") or {}),
        "bundled_seed": bool(recipe.get("bundled_seed", False)),
    }
    lineage.update(dict(lineage_extra or {}))
    return research_store.register_experiment({
        "experiment_id": experiment_id,
        "recipe_id": recipe["recipe_id"],
        "status": status,
        "model_id": model_id,
        "validation_tier": validation_tier,
        "settings_hash": recipe["settings_hash"],
        "dataset_hash": dataset_hash,
        "artifact_hash": artifact_hash,
        "failed_gates": failed_gates or [],
        "metrics": metrics or {},
        "lineage": lineage,
        "message": message,
    })


def _worker(
    recipe_id: str,
    profile_override: Optional[str],
    tickers_override: Optional[List[str]],
    output_root: Path,
    experiment_id: str,
) -> None:
    # Heavy scientific imports are deferred so API startup stays light.
    from forecasting.config import settings_from_dict
    from forecasting.dataset import build_universe_dataset, load_dataset_bundle, write_dataset_bundle
    from forecasting.model import train_validate_ensemble
    from forecasting.registry import save_model

    recipe: Dict[str, Any] = {"recipe_id": recipe_id, "settings_hash": "unknown"}
    profile = profile_override or "unknown"
    try:
        recipe = get_recipe(recipe_id)
        if profile_override is None:
            profile = str(recipe.get("profile") or "exploratory")
        elif profile_override in VALID_PROFILES:
            profile = profile_override
        else:
            profile = "strict"

        recipe_overrides = dict(recipe.get("settings_overrides") or {})
        unsupported_overrides = sorted(set(recipe_overrides) - RECIPE_SETTING_OVERRIDE_ALLOWLIST)
        if unsupported_overrides:
            raise ValueError(
                "recipe contains unsupported training-setting override(s): " + ", ".join(unsupported_overrides)
            )
        settings_payload = {
            "horizon_trading_days": int(recipe["horizon_trading_days"]),
            "benchmark": str(recipe["benchmark"]).upper(),
            **recipe_overrides,
        }
        settings = settings_from_dict(settings_payload, base=profile)
        symbols = [str(x).strip().upper() for x in (tickers_override or recipe["tickers"]) if str(x).strip()]
        symbols = list(dict.fromkeys(symbols))
        total = len(symbols)
        experiment_dir = output_root / experiment_id
        experiment_dir.mkdir(parents=True, exist_ok=False)

        _register(
            experiment_id,
            recipe,
            status="training",
            profile=profile,
            message="Loading recipe inputs from the durable local research store.",
            lineage_extra={"experiment_dir": str(experiment_dir), "symbols_requested": symbols},
        )
        cache.update_model_build(
            phase="load_local",
            recipe_id=recipe["recipe_id"],
            experiment_id=experiment_id,
            profile=profile,
            total=total,
            message=f"Loading {recipe['name']} inputs from local research data",
        )

        prices, benchmark, missing = _load_local_market_data(symbols, settings.benchmark)
        if benchmark is None or benchmark.empty:
            message = (
                f"Local research data do not contain benchmark {settings.benchmark}. "
                "Run Model Lab data update/import first; training does not download data automatically."
            )
            _register(
                experiment_id, recipe, status="failed", profile=profile, message=message,
                lineage_extra={"symbols_requested": symbols, "missing_symbols": missing, "experiment_dir": str(experiment_dir)},
            )
            cache.update_model_build(status="failed", phase="failed", failures=len(missing), message=message)
            return
        if len(prices) < 1:
            message = (
                "No locally retained target price series are available for this recipe. "
                "Run Model Lab data update/import first; no network fetch is performed by training."
            )
            _register(
                experiment_id, recipe, status="failed", profile=profile, message=message,
                lineage_extra={"symbols_requested": symbols, "symbols_loaded": sorted(prices), "missing_symbols": missing, "experiment_dir": str(experiment_dir)},
            )
            cache.update_model_build(status="failed", phase="failed", failures=len(missing), message=message)
            return

        cache.update_model_build(
            phase="build_dataset", completed=len(prices), failures=len(missing),
            message=f"Building dataset from {len(prices)} locally retained target series",
        )
        dataset = build_universe_dataset(prices, benchmark, settings)
        coverage = research_store.coverage([settings.benchmark, *sorted(prices)])
        adjusted = bool(coverage) and all(
            str(row.get("price_basis") or "").lower() == "adjusted"
            for row in coverage if int(row.get("rows") or 0) > 0
        )
        manifest = write_dataset_bundle(
            dataset,
            experiment_dir,
            settings,
            synthetic=False,
            provenance={
                "price_sources": "FinCompass durable local research store",
                "research_store_schema": research_store.audit([settings.benchmark, *sorted(prices)]).get("schema_version"),
                "recipe_id": recipe["recipe_id"],
                "recipe_settings_hash": recipe["settings_hash"],
                "feature_contract": recipe.get("feature_contract"),
                "live_eligible_target": bool(recipe.get("live_eligible_target", True)),
                "symbols_requested": symbols,
                "symbols_loaded": sorted(prices),
                "missing_symbols": missing,
                "benchmark": settings.benchmark,
                "built_by": "FinCompass Model Lab offline trainer",
            },
            data_quality={
                "point_in_time_features": True,
                "survivorship_control": False,
                "delistings_included": False,
                "corporate_action_adjusted": adjusted,
                "note": (
                    "Current catalog/recipe construction does not claim historical-universe survivorship control or delisting completeness. "
                    "This caps a passing model at validated_research unless independent controls are supplied."
                ),
            },
        )
        dataset_hash = _dataset_digest(manifest)
        _register(
            experiment_id, recipe, status="candidate", profile=profile,
            message="Dataset frozen; training/calibration/locked-test validation started.",
            dataset_hash=dataset_hash,
            lineage_extra={
                "experiment_dir": str(experiment_dir), "symbols_requested": symbols,
                "symbols_loaded": sorted(prices), "missing_symbols": missing,
            },
        )

        cache.update_model_build(
            phase="train", completed=len(prices), failures=len(missing),
            message="Training, calibrating and running the locked-test validation protocol",
        )
        train, validation, test, frozen_manifest = load_dataset_bundle(experiment_dir)
        model, report, predictions = train_validate_ensemble(train, validation, test, frozen_manifest, settings)
        predictions.to_csv(experiment_dir / "locked_test_predictions.csv", index=False)
        (experiment_dir / "validation_report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
        )

        tier = str(report.get("validation_tier") or "rejected")
        gate_passed = bool((report.get("gate") or {}).get("passed"))
        failed = _failed_gates(report)
        usable = gate_passed and tier in {"validated_research", "validated_market"}
        saved: Optional[Dict[str, Any]] = None
        if usable:
            saved = save_model(model, report, frozen_manifest, profile_name=recipe["recipe_id"])
            status = "validated"
            message = (
                f"Validation passed at {tier.replace('_', ' ')} tier. Candidate retained but NOT active; "
                "explicit Model Lab activation is required."
            )
        else:
            status = "rejected"
            message = (
                "Validation completed but the candidate failed one or more locked-test gates. "
                "Evidence is retained; no model artifact was installed and no activation occurred."
            )

        model_id = saved.get("model_id") if saved else None
        artifact_hash = saved.get("model_sha256") if saved else None
        metrics = {
            "locked_test_metrics": report.get("locked_test_metrics") or {},
            "gate": report.get("gate") or {},
            "walk_forward": report.get("walk_forward") or {},
            "validation_protocol": report.get("validation_protocol") or {},
            "rows": {"train": len(train), "validation": len(validation), "test": len(test)},
        }
        _register(
            experiment_id, recipe, status=status, profile=profile, message=message,
            model_id=model_id, validation_tier=tier, dataset_hash=dataset_hash,
            artifact_hash=artifact_hash, failed_gates=failed, metrics=metrics,
            lineage_extra={
                "experiment_dir": str(experiment_dir), "symbols_requested": symbols,
                "symbols_loaded": sorted(prices), "missing_symbols": missing,
                "model_saved": bool(saved),
            },
        )
        cache.update_model_build(
            status="complete", phase="complete", completed=total, failures=len(missing),
            recipe_id=recipe["recipe_id"], experiment_id=experiment_id,
            model_id=model_id, validation_tier=tier, gate_passed=gate_passed,
            usable=usable, failed_gates=failed, message=message,
        )
    except Exception as exc:
        logger.exception("Model Lab build failed")
        message = f"Build failed: {type(exc).__name__}: {exc}"
        try:
            if recipe.get("settings_hash"):
                _register(
                    experiment_id, recipe, status="failed", profile=profile,
                    message=message, lineage_extra={"exception_type": type(exc).__name__},
                )
        except Exception:
            logger.exception("Could not persist failed Model Lab experiment")
        cache.update_model_build(
            status="failed", phase="failed", experiment_id=experiment_id,
            recipe_id=recipe_id, message=message,
        )


def start_model_build(
    profile: Optional[str] = None,
    tickers: Optional[List[str]] = None,
    *,
    recipe_id: str = DEFAULT_RECIPE_ID,
) -> Dict[str, Any]:
    """Claim the single build slot and launch an offline-only recipe build."""
    try:
        recipe = get_recipe(recipe_id)
    except KeyError as exc:
        raise ValueError(str(exc)) from exc
    resolved_profile = profile if profile is not None else str(recipe.get("profile") or "exploratory")
    if resolved_profile not in VALID_PROFILES:
        resolved_profile = "strict"
    symbols = [str(t).strip().upper() for t in (tickers or recipe["tickers"]) if str(t).strip()]
    symbols = list(dict.fromkeys(symbols))
    if not symbols:
        raise ValueError("recipe has no target symbols")

    claimed, state = cache.claim_model_build(len(symbols))
    if not claimed:
        return {**state, "started": False}

    reclaimed_experiment_id = state.get("reclaimed_experiment_id")
    if reclaimed_experiment_id:
        research_store.mark_experiment_interrupted(
            str(reclaimed_experiment_id),
            "Build was interrupted before completion; the stale build slot was reclaimed. Existing evidence was retained.",
        )

    experiment_id = _new_experiment_id(recipe["recipe_id"])
    BUILD_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cache.update_model_build(
        profile=resolved_profile,
        recipe_id=recipe["recipe_id"],
        experiment_id=experiment_id,
        phase="queued",
        message=f"Queued offline Model Lab recipe: {recipe['name']}",
    )
    thread = threading.Thread(
        target=_worker,
        args=(recipe["recipe_id"], resolved_profile, tickers, BUILD_OUTPUT_DIR, experiment_id),
        name="fincompass-model-build",
        daemon=True,
    )
    thread.start()
    return {**cache.get_model_build(), "started": True}


def get_model_build_status() -> Dict[str, Any]:
    return cache.get_model_build()
