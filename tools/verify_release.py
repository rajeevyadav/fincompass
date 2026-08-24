#!/usr/bin/env python3
"""Run deterministic local FinCompass 1.0.0 release checks."""
from __future__ import annotations

from hashlib import sha256
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from forecasting.config import get_profile
from config import APP_VERSION
from realtime import REALTIME_ENGINE_VERSION
from forecasting.dataset import load_dataset_bundle
from forecasting.registry import registry_status as forecast_registry_status
from realtime.adaptive import state_sha256
from realtime.config import PROFILES as RT_PROFILES, RealtimeSettings
from realtime.registry import registry_status as adaptive_registry_status
from tools.audit_forecast_dataset import audit_bundle


def run(label, cmd):
    print(f"[verify] {label}: {' '.join(cmd)}")
    subprocess.run(cmd, cwd=ROOT, check=True)


def frontend_scan():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8").lower()
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    failures = []
    for needle, description in [
        ("<style", "inline <style> block"),
        ("style=", "inline style attribute"),
        ("cdn.jsdelivr", "jsDelivr dependency"),
        ("<script src=\"http", "remote script"),
        ("<script src='http", "remote script"),
    ]:
        if needle in html:
            failures.append(description)
    for required in ["page-live", "realtime-settings-json", "/api/v4/realtime/", "/api/v4/methodology"]:
        if required not in html and required not in js:
            failures.append(f"missing v4 frontend contract: {required}")
    if failures:
        raise SystemExit("Frontend CSP/contract scan failed: " + ", ".join(sorted(set(failures))))
    print("[verify] frontend CSP/dependency/v4 contract scan: OK")


def anchor_fixture_integrity_scan():
    base = ROOT / "datasets" / "fixtures"
    train, validation, test, manifest = load_dataset_bundle(base)
    if not manifest.get("synthetic"):
        raise SystemExit("Bundled anchor fixture must be marked synthetic")
    if not all(len(x) > 0 for x in (train, validation, test)):
        raise SystemExit("Bundled anchor fixture partitions must be non-empty")
    sidecar = base / "dataset_manifest.sha256"
    if not sidecar.exists():
        raise SystemExit("Bundled anchor fixture must include dataset_manifest.sha256")
    manifest_digest = sha256((base / "dataset_manifest.json").read_bytes()).hexdigest()
    if not sidecar.read_text().strip().startswith(manifest_digest):
        raise SystemExit("Anchor fixture manifest sidecar mismatch")
    report = json.loads((base / "validation_report.json").read_text(encoding="utf-8"))
    if report.get("report", {}).get("validation_tier") != "fixture_only":
        raise SystemExit("Bundled anchor fixture validation tier must remain fixture_only")
    if not report.get("report", {}).get("gate", {}).get("passed"):
        raise SystemExit("Bundled anchor fixture should pass the statistical regression gate")
    audit = audit_bundle(base)
    if not audit.get("passed"):
        raise SystemExit("Bundled anchor fixture failed dataset audit")
    print("[verify] anchor fixture hashes / temporal audit / tier / validation report: OK")


def adaptive_fixture_integrity_scan():
    base = ROOT / "datasets" / "realtime-fixtures"
    manifest_path = base / "fixture_manifest.json"
    sidecar = base / "fixture_manifest.sha256"
    stream_path = base / "adaptive_stream_manifest.json"
    report_path = base / "adaptive_validation_report.json"
    for path in [manifest_path, sidecar, stream_path, report_path, base / "warmup.csv", base / "locked_test.csv"]:
        if not path.exists():
            raise SystemExit(f"Missing adaptive fixture file: {path.relative_to(ROOT)}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    digest = sha256(manifest_path.read_bytes()).hexdigest()
    if not sidecar.read_text().strip().startswith(digest):
        raise SystemExit("Adaptive fixture manifest sidecar mismatch")
    if not manifest.get("synthetic") or manifest.get("rows", {}).get("warmup") != 1200 or manifest.get("rows", {}).get("locked_test") != 600:
        raise SystemExit("Adaptive fixture must be the frozen 1200/600 synthetic stream")
    for name, expected in (manifest.get("files") or {}).items():
        path = base / name
        if not path.exists() or sha256(path.read_bytes()).hexdigest() != expected:
            raise SystemExit(f"Adaptive fixture hash mismatch: {name}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not report.get("synthetic") or not report.get("passed"):
        raise SystemExit("Adaptive synthetic regression report must be synthetic and passing")
    stream = json.loads(stream_path.read_text(encoding="utf-8"))
    if stream.get("validation_tier") != "fixture_only":
        raise SystemExit("Bundled adaptive artifact must remain fixture_only")
    print("[verify] adaptive fixture hashes / locked stream / fixture tier: OK")


def model_registry_scan():
    manifests = list((ROOT / "models").glob("*.json"))
    if not manifests:
        raise SystemExit("No bundled anchor model manifest found")
    for manifest_path in manifests:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        model_path = ROOT / "models" / manifest.get("model_file", "")
        if not model_path.exists():
            raise SystemExit(f"Missing anchor model artifact for {manifest_path.name}")
        digest = sha256(model_path.read_bytes()).hexdigest()
        if digest != manifest.get("model_sha256") or manifest.get("model_id") != digest[:16]:
            raise SystemExit(f"Anchor model identity/hash mismatch for {model_path.name}")
    status = forecast_registry_status(ROOT / "models")
    if status.get("usable_models") != 0:
        raise SystemExit("Release package must not ship a live-eligible market anchor without external validation evidence")
    print("[verify] anchor model hashes / no bundled live-eligible anchor: OK")


def adaptive_registry_scan():
    root = ROOT / "adaptive_models"
    manifests = [p for p in root.glob("*.json") if not p.name.endswith(".state.json")]
    if not manifests:
        raise SystemExit("No bundled adaptive artifact manifest found")
    for mp in manifests:
        m = json.loads(mp.read_text(encoding="utf-8"))
        state_path = root / m.get("state_file", "")
        if not state_path.exists():
            raise SystemExit(f"Missing adaptive state for {mp.name}")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state_sha256(state) != m.get("state_sha256"):
            raise SystemExit(f"Adaptive state hash mismatch for {state_path.name}")
        settings = RealtimeSettings(**m.get("settings", {})).validate()
        if settings.fingerprint() != m.get("settings_fingerprint"):
            raise SystemExit(f"Adaptive settings fingerprint mismatch for {mp.name}")
        contract = {k: m.get(k) for k in ["base_model_id", "realtime_engine_version", "settings", "settings_fingerprint", "features", "state_sha256", "validation_tier", "validation"]}
        csha = sha256(json.dumps(contract, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
        if csha != m.get("contract_sha256") or csha[:16] != m.get("adaptive_id"):
            raise SystemExit(f"Adaptive artifact contract/ID mismatch for {mp.name}")
    status = adaptive_registry_status(root)
    if status.get("live_eligible_artifacts") != 0:
        raise SystemExit("Release package must not ship a live-eligible adaptive state without external validation evidence")
    print("[verify] adaptive state/contract hashes / no bundled live-eligible adapter: OK")


def settings_scan():
    for name in ("strict", "standard", "exploratory"):
        path = ROOT / "config" / f"forecast-{name}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload != get_profile(name).to_dict():
            raise SystemExit(f"Forecast configuration profile drift: {path}")
    for name, cfg in RT_PROFILES.items():
        path = ROOT / "config" / f"realtime-{name}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload != cfg.to_dict():
            raise SystemExit(f"Realtime configuration profile drift: {path}")
    print("[verify] forecast + realtime configuration profiles: OK")


def docs_scan():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    realtime = (ROOT / "REALTIME.md").read_text(encoding="utf-8")
    architecture = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    model_card = (ROOT / "MODEL_CARD.md").read_text(encoding="utf-8")
    audit_text = (ROOT / "RELEASE_AUDIT.md").read_text(encoding="utf-8")
    stream = json.loads((ROOT / "datasets/realtime-fixtures/adaptive_stream_manifest.json").read_text(encoding="utf-8"))
    report = json.loads((ROOT / "datasets/realtime-fixtures/adaptive_validation_report.json").read_text(encoding="utf-8"))
    release_info = json.loads((ROOT / "RELEASE_INFO.json").read_text(encoding="utf-8"))
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if version != APP_VERSION or release_info.get("release") != APP_VERSION:
        raise SystemExit(f"Application version mismatch: VERSION={version}, config={APP_VERSION}, RELEASE_INFO={release_info.get('release')}")
    if release_info.get("engines", {}).get("realtime_adaptive") != REALTIME_ENGINE_VERSION:
        raise SystemExit("Realtime engine version mismatch in RELEASE_INFO.json")
    app_token = f"`{APP_VERSION}`"
    for name, text in [("ARCHITECTURE.md", architecture), ("MODEL_CARD.md", model_card), ("RELEASE_AUDIT.md", audit_text)]:
        if app_token not in text:
            raise SystemExit(f"Documentation missing application version {APP_VERSION}: {name}")
    test_token = f"{int(release_info.get('automated_tests_passed', 0))} automated tests"
    required = [stream["adaptive_id"], stream["state_sha256"], stream["contract_sha256"], stream["settings_fingerprint"], test_token, REALTIME_ENGINE_VERSION]
    corpus = readme + realtime + architecture + model_card + audit_text
    if any(x not in corpus for x in required):
        missing = [x for x in required if x not in corpus]
        raise SystemExit("Documentation consistency scan failed: " + ", ".join(missing))
    for value in [report["locked_metrics"]["brier_improvement"], report["locked_metrics"]["log_loss_improvement"]]:
        token = f"{value:.6f}"
        if token not in corpus:
            raise SystemExit(f"Documentation missing frozen adaptive metric {token}")
    print("[verify] documentation/version/artifact consistency: OK")


def docker_scan():
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    required = ["COPY forecasting/ ./forecasting/", "COPY realtime/ ./realtime/", "COPY models/ ./models/", "COPY adaptive_models/ ./adaptive_models/", "USER appuser", "chown -R appuser:appuser /app/data"]
    missing = [x for x in required if x not in docker]
    if missing:
        raise SystemExit("Docker static scan failed: " + ", ".join(missing))
    if "chown -R appuser:appuser /app\n" in docker:
        raise SystemExit("Docker app tree must not be runtime-writable")
    print("[verify] Docker packaging/ownership scan: OK")


def hygiene_scan():
    # Verification itself imports the application and therefore creates local
    # SQLite/audit state. Remove verifier-created runtime residue, then assert
    # that the distributable tree is clean. Python bytecode/test caches are
    # cleaned by the packaging step after this verifier returns.
    for pattern in ["*.db", "*.db-wal", "*.db-shm", "audit.jsonl", "audit.jsonl.1"]:
        for p in (ROOT / "data").glob(pattern):
            if p.is_file():
                p.unlink()
    blockers = []
    for pattern in ["*.db", "*.db-wal", "*.db-shm", "audit.jsonl", "audit.jsonl.1"]:
        for p in (ROOT / "data").glob(pattern):
            if p.is_file():
                blockers.append(str(p.relative_to(ROOT)))
    if blockers:
        raise SystemExit("Runtime residue present: " + ", ".join(blockers))
    print("[verify] runtime residue cleanup/scan: OK")


def main() -> int:
    run("python compile", [sys.executable, "-m", "compileall", "-q", "."])
    run("pytest", [sys.executable, "-m", "pytest", "-q"])
    node = shutil.which("node")
    if node:
        run("javascript syntax", [node, "--check", "static/app.js"])
    else:
        print("[verify] javascript syntax: SKIPPED (node not found)")
    frontend_scan()
    anchor_fixture_integrity_scan()
    adaptive_fixture_integrity_scan()
    model_registry_scan()
    adaptive_registry_scan()
    settings_scan()
    docs_scan()
    docker_scan()
    hygiene_scan()
    print("[verify] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
