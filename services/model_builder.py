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
from services.training_readiness import evaluate_training_readiness

logger = logging.getLogger(__name__)

# Ordered training stages surfaced to the UI. No fake percentages — the
# stage itself is the progress signal.
TRAINING_STAGES = [
    "checking_data", "building_examples", "training_models",
    "calibrating", "locked_test", "checking_gates", "saving_candidate",
]


def _write_diagnostic(output_root: Path, experiment_id: str, recipe: Dict[str, Any], profile: str,
                      *, final_state: str, readiness: Optional[Dict[str, Any]] = None,
                      manifest: Optional[Dict[str, Any]] = None, report: Optional[Dict[str, Any]] = None,
                      model_id: Optional[str] = None, artifact_hash: Optional[str] = None,
                      dataset_hash: Optional[str] = None, coverage: Optional[List[Dict[str, Any]]] = None,
                      rows: Optional[Dict[str, int]] = None, traceback_str: Optional[str] = None) -> None:
    """Write experiments/<id>/diagnostic.json for every attempted training run."""
    try:
        exp_dir = output_root / experiment_id
        exp_dir.mkdir(parents=True, exist_ok=True)
        diag: Dict[str, Any] = {
            "experiment_id": experiment_id,
            "recipe_id": recipe.get("recipe_id"),
            "recipe_name": recipe.get("name"),
            "profile": profile,
            "benchmark": recipe.get("benchmark"),
            "horizon_trading_days": recipe.get("horizon_trading_days"),
            "feature_contract": recipe.get("feature_contract"),
            "final_state": final_state,
            "requested_universe": (readiness or {}).get("universe", {}).get("requested") or recipe.get("tickers"),
            "usable_universe": (readiness or {}).get("universe", {}).get("usable"),
            "excluded_symbols": (readiness or {}).get("universe", {}).get("excluded"),
            "readiness_gates": (readiness or {}).get("gates"),
            "coverage": coverage,
            "rows_per_symbol": {str(r.get("symbol")): int(r.get("rows") or 0) for r in (coverage or [])},
            "split_rows": rows,
            "dataset_hash": dataset_hash,
            "locked_test_metrics": (report or {}).get("locked_test_metrics"),
            "gate": (report or {}).get("gate"),
            "walk_forward": (report or {}).get("walk_forward"),
            "validation_protocol": (report or {}).get("validation_protocol"),
            "validation_tier": (report or {}).get("validation_tier"),
            "model_id": model_id,
            "artifact_hash": artifact_hash,
            "data_quality": (manifest or {}).get("data_quality"),
            "traceback": traceback_str,
        }
        (exp_dir / "diagnostic.json").write_text(
            json.dumps(diag, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
        )
    except Exception:
        logger.exception("Could not write training diagnostic for %s", experiment_id)

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


def _stamp_training_contract(saved: Dict[str, Any], recipe: Dict[str, Any], trainer_family: str) -> None:
    """Record how a saved model can be retrained, on its own manifest.

    Runtime code retrains strictly from this contract's recipe_id — never from a
    display name — so a model produced here is itself retrainable next time.
    """
    from forecasting.registry import MODEL_ROOT
    horizon_days = int(recipe.get("horizon_trading_days") or 252)
    contract = {
        "trainer_family": trainer_family,
        "recipe_id": recipe.get("recipe_id"),
        "feature_contract": recipe.get("feature_contract"),
        "benchmark_family": (saved.get("applicability_domain") or {}).get("benchmark_family") or "US_LARGE_CAP",
        "horizon_months": int(round(horizon_days / 21.0)),
        "retrain_supported": True,
    }
    saved["training_contract"] = contract
    path = MODEL_ROOT / f"{saved.get('profile_name')}-{saved.get('model_id')}.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["training_contract"] = contract
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        logger.warning("could not stamp training contract on %s", path.name)


def _worker(
    recipe_id: str,
    profile_override: Optional[str],
    tickers_override: Optional[List[str]],
    output_root: Path,
    experiment_id: str,
    parent_model_id: Optional[str] = None,
) -> None:
    # Heavy scientific imports are deferred so API startup stays light.
    from forecasting.config import settings_from_dict
    from forecasting.dataset import build_universe_dataset, load_dataset_bundle, write_dataset_bundle
    from forecasting.baseline import train_validate_bayesian_reference
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
            phase="checking_data",
            recipe_id=recipe["recipe_id"],
            experiment_id=experiment_id,
            profile=profile,
            total=total,
            message=f"Checking {recipe['name']} data in the local research store",
        )

        prices, benchmark, missing = _load_local_market_data(symbols, settings.benchmark)
        if benchmark is None or benchmark.empty:
            message = (
                f"Local research data do not contain benchmark {settings.benchmark}. "
                "Run Model Lab data update/import first; training does not download data automatically."
            )
            _register(
                experiment_id, recipe, status="not_ready", profile=profile, message=message,
                lineage_extra={"symbols_requested": symbols, "missing_symbols": missing, "experiment_dir": str(experiment_dir)},
            )
            cache.update_model_build(status="not_ready", phase="not_ready", failures=len(missing), message=message)
            _write_diagnostic(output_root, experiment_id, recipe, profile, final_state="not_ready",
                              coverage=research_store.coverage([settings.benchmark, *symbols]))
            return
        if len(prices) < 1:
            message = (
                "No locally retained target price series are available for this recipe. "
                "Run Model Lab data update/import first; no network fetch is performed by training."
            )
            _register(
                experiment_id, recipe, status="not_ready", profile=profile, message=message,
                lineage_extra={"symbols_requested": symbols, "symbols_loaded": sorted(prices), "missing_symbols": missing, "experiment_dir": str(experiment_dir)},
            )
            cache.update_model_build(status="not_ready", phase="not_ready", failures=len(missing), message=message)
            _write_diagnostic(output_root, experiment_id, recipe, profile, final_state="not_ready",
                              coverage=research_store.coverage([settings.benchmark, *symbols]))
            return

        cache.update_model_build(
            phase="building_examples", completed=len(prices), failures=len(missing),
            message=f"Building training examples from {len(prices)} locally retained target series",
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
            phase="training_models", completed=len(prices), failures=len(missing),
            message="Training component models, calibrating probabilities and running the locked test",
        )
        train, validation, test, frozen_manifest = load_dataset_bundle(experiment_dir)
        # Dispatch by the recipe's declared trainer. The Bayesian reference is a
        # hard-valid probability model; a passing run that lacks stronger skill is
        # retained as a Limited-evidence (bayesian_baseline) candidate rather than
        # rejected.
        trainer_family = str(recipe.get("trainer_family") or "enhanced_ensemble")
        if trainer_family == "bayesian_reference":
            model, report, predictions = train_validate_bayesian_reference(train, validation, test, frozen_manifest, settings)
        else:
            model, report, predictions = train_validate_ensemble(train, validation, test, frozen_manifest, settings)
        predictions.to_csv(experiment_dir / "locked_test_predictions.csv", index=False)
        (experiment_dir / "validation_report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
        )

        cache.update_model_build(
            phase="checking_gates", completed=len(prices), failures=len(missing),
            message="Evaluating locked-test validation gates",
        )
        tier = str(report.get("validation_tier") or "rejected")
        gate_passed = bool((report.get("gate") or {}).get("passed"))
        failed = _failed_gates(report)
        # A hard-valid Bayesian baseline is a legitimate forecast-eligible candidate
        # even without stronger skill; the validated tiers additionally require a
        # passing locked-test gate.
        savable = tier == "bayesian_baseline" or (gate_passed and tier in {"validated_research", "validated_market"})
        saved: Optional[Dict[str, Any]] = None
        if savable:
            cache.update_model_build(
                phase="saving_candidate", completed=len(prices), failures=len(missing),
                message="Saving candidate (not activated)",
            )
            lineage = None
            if parent_model_id:
                lineage = {"parent_model_id": str(parent_model_id), "update_type": "retrain",
                           "reason": "new_data_and_matured_labels", "created_at": _utc_now()}
            saved = save_model(model, report, frozen_manifest, profile_name=recipe["recipe_id"], lineage=lineage)
            _stamp_training_contract(saved, recipe, trainer_family)
            status = "validated"
            if tier == "bayesian_baseline":
                message = (
                    "Hard-valid Limited-evidence baseline retained. It is forecast-eligible and "
                    "tracking-only for Live; it is not activated and never applies adaptive updates."
                )
            else:
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
        _write_diagnostic(
            output_root, experiment_id, recipe, profile, final_state=status,
            manifest=manifest, report=report, model_id=model_id, artifact_hash=artifact_hash,
            dataset_hash=dataset_hash, coverage=coverage, rows=metrics["rows"],
        )
    except Exception as exc:
        import traceback as _tb
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
        try:
            _write_diagnostic(output_root, experiment_id, recipe, profile,
                              final_state="failed", traceback_str=_tb.format_exc())
        except Exception:
            logger.exception("Could not write failed-build diagnostic")
        cache.update_model_build(
            status="failed", phase="failed", experiment_id=experiment_id,
            recipe_id=recipe_id, message=message,
        )


def start_model_build(
    profile: Optional[str] = None,
    tickers: Optional[List[str]] = None,
    *,
    recipe_id: str = DEFAULT_RECIPE_ID,
    parent_model_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Claim the single build slot and launch an offline-only recipe build.

    ``parent_model_id`` marks the build as a retrain of an existing model; the
    resulting candidate records it as lineage and NEVER replaces the active model
    (activation stays an explicit, separate user action).
    """
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

    # Hard data-readiness gates: training must not start — and the active
    # model must not be disturbed — if a predictable data requirement fails.
    readiness = evaluate_training_readiness(recipe["recipe_id"], tickers, profile=resolved_profile)
    if not readiness["ready"]:
        experiment_id = _new_experiment_id(recipe["recipe_id"])
        actions = "; ".join(dict.fromkeys(g["action"] for g in readiness["gates"] if g.get("action")))
        message = "Data needs attention before training. " + actions
        try:
            _register(experiment_id, recipe, status="not_ready", profile=resolved_profile,
                      message=message, lineage_extra={"readiness": readiness})
        except Exception:
            logger.exception("Could not persist not_ready experiment")
        _write_diagnostic(BUILD_OUTPUT_DIR, experiment_id, recipe, resolved_profile,
                          final_state="not_ready", readiness=readiness)
        return {"started": False, "status": "not_ready", "experiment_id": experiment_id,
                "readiness": readiness, "message": message}

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
        args=(recipe["recipe_id"], resolved_profile, tickers, BUILD_OUTPUT_DIR, experiment_id, parent_model_id),
        name="fincompass-model-build",
        daemon=True,
    )
    thread.start()
    return {**cache.get_model_build(), "started": True}


def get_model_build_status() -> Dict[str, Any]:
    return cache.get_model_build()
