#!/usr/bin/env python3
"""Run deterministic local FinCompass release checks."""
from __future__ import annotations

from hashlib import sha256
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.generate_release_manifest import release_files

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


def market_seed_integrity_scan():
    base = ROOT / "datasets" / "market-seed"
    db = base / "market_seed.db"
    manifest_path = base / "SEED_MANIFEST.json"
    sidecar = base / "SEED_MANIFEST.sha256"
    # The market seed is a PRIVATE, local-only asset (see PRIVATE-DATA-NOTICE.md),
    # absent on a clean public clone / CI. Skip its integrity checks when absent;
    # enforce fully when present (private/local tree, exe/Docker packaging).
    if not db.exists():
        print("[verify] market seed: SKIPPED (private local-only seed absent — public/CI mode)")
        return
    for path in [db, manifest_path, sidecar, base / "README.md"]:
        if not path.exists():
            raise SystemExit(f"Missing bundled market seed file: {path.relative_to(ROOT)}")
    if list(base.glob("market_seed.db-*")):
        raise SystemExit("Bundled market seed must not ship SQLite WAL/SHM sidecars")
    manifest_digest = sha256(manifest_path.read_bytes()).hexdigest()
    if not sidecar.read_text(encoding="utf-8").strip().startswith(manifest_digest):
        raise SystemExit("Market seed manifest sidecar mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("live_eligible") is not False or manifest.get("bootstrap_recipe") != "bootstrap-real-1m":
        raise SystemExit("Bundled market seed must remain research-only and bound to bootstrap-real-1m")
    db_digest = sha256(db.read_bytes()).hexdigest()
    if manifest.get("database_sha256") != db_digest:
        raise SystemExit("Bundled market seed database SHA-256 mismatch")
    for source in manifest.get("sources") or []:
        source_path = base / str(source.get("file") or "")
        license_path = base / str(source.get("license_file") or "")
        if not source_path.is_file() or sha256(source_path.read_bytes()).hexdigest() != source.get("sha256"):
            raise SystemExit(f"Bundled market seed source hash mismatch: {source_path.name}")
        if not license_path.is_file() or sha256(license_path.read_bytes()).hexdigest() != source.get("license_sha256"):
            raise SystemExit(f"Bundled market seed license/metadata hash mismatch: {license_path.name}")
        raw_matches = [x for x in (base / "raw").glob(f"{str(source.get('sha256') or '')[:12]}-*") if x.is_file()]
        if len(raw_matches) != 1 or sha256(raw_matches[0].read_bytes()).hexdigest() != source.get("sha256"):
            raise SystemExit(f"Bundled market seed retained raw source mismatch: {source_path.name}")
    conn = sqlite3.connect(db)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()
        if not integrity or str(integrity[0]).lower() != "ok":
            raise SystemExit(f"Bundled market seed SQLite integrity check failed: {integrity}")
        rows = dict(conn.execute("SELECT symbol,COUNT(*) FROM price_bars GROUP BY symbol").fetchall())
        basis = dict(conn.execute("SELECT symbol,price_basis FROM symbol_contracts WHERE symbol IN ('GOOG','MSFT')").fetchall())
        revisions = conn.execute("SELECT COUNT(*) FROM price_revisions").fetchone()[0]
        experiments = conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
    finally:
        conn.close()
    if rows.get("GOOG") != 1047 or rows.get("MSFT") != 7983:
        raise SystemExit(f"Bundled market seed row counts drifted: {rows}")
    if basis != {"GOOG": "adjusted", "MSFT": "raw"}:
        raise SystemExit(f"Bundled market seed price-basis contracts drifted: {basis}")
    if revisions != 0 or experiments != 0:
        raise SystemExit("Bundled market seed must not contain revisions or experiment history")
    print("[verify] market seed hashes / SQLite integrity / real bootstrap corpus: OK")


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
    manifests = []
    for manifest_path in (ROOT / "models").glob("*.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(manifest, dict) and manifest.get("model_id") and manifest.get("model_file"):
            manifests.append((manifest_path, manifest))
    if not manifests:
        raise SystemExit("No bundled anchor model manifest found")

    public_files = {path.relative_to(ROOT).as_posix() for path in release_files()}
    usable_private = 0
    for manifest_path, manifest in manifests:
        model_path = ROOT / "models" / manifest.get("model_file", "")
        if not model_path.exists():
            raise SystemExit(f"Missing anchor model artifact for {manifest_path.name}")
        digest = sha256(model_path.read_bytes()).hexdigest()
        if digest != manifest.get("model_sha256") or manifest.get("model_id") != digest[:16]:
            raise SystemExit(f"Anchor model identity/hash mismatch for {model_path.name}")

        tier = str(manifest.get("validation_tier") or "")
        sharing = str((manifest.get("dataset_provenance") or {}).get("sharing_status") or "").upper()
        if tier in {"validated_research", "validated_market"}:
            if not manifest.get("validation", {}).get("gate", {}).get("passed"):
                raise SystemExit(f"Usable model lacks a passing gate: {manifest_path.name}")
            if sharing in {"RESTRICTED", "REVIEW_REQUIRED"}:
                usable_private += 1
                rel_manifest = manifest_path.relative_to(ROOT).as_posix()
                rel_model = model_path.relative_to(ROOT).as_posix()
                if rel_manifest in public_files or rel_model in public_files:
                    raise SystemExit(f"Non-public trained model would leak into public source package: {manifest_path.name}")
            elif sharing != "PUBLIC":
                raise SystemExit(f"Usable model must declare PUBLIC, RESTRICTED, or REVIEW_REQUIRED sharing status: {manifest_path.name}")

    if (ROOT / "models" / "active_model.json").exists():
        raise SystemExit("Release tree must not ship a pre-activated forecast model pointer")
    print(f"[verify] anchor model hashes / public-release sharing guard: OK ({usable_private} private usable model(s) excluded)")


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
    required = ["COPY forecasting/ ./forecasting/", "COPY realtime/ ./realtime/", "COPY config/ ./config/", "COPY datasets/market-seed/ ./datasets/market-seed/", "COPY models/ ./models/", "COPY adaptive_models/ ./adaptive_models/", "USER appuser", "chown -R appuser:appuser /app/data"]
    missing = [x for x in required if x not in docker]
    if missing:
        raise SystemExit("Docker static scan failed: " + ", ".join(missing))
    if "chown -R appuser:appuser /app\n" in docker:
        raise SystemExit("Docker app tree must not be runtime-writable")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    if "!datasets/market-seed/**" not in dockerignore or "\nconfig/\n" in "\n" + dockerignore:
        raise SystemExit("Docker context excludes required config or market-seed resources")
    exe = (ROOT / "build_exe.bat").read_text(encoding="utf-8").replace("/", "\\")
    if "datasets\\market-seed;datasets\\market-seed" not in exe:
        raise SystemExit("Windows one-file build does not bundle datasets/market-seed")
    print("[verify] Docker + Windows packaging/ownership/market-seed scan: OK")


def release_manifest_scan():
    manifest_path = ROOT / "RELEASE_MANIFEST.sha256"
    if not manifest_path.is_file():
        raise SystemExit("Missing RELEASE_MANIFEST.sha256")
    entries = {}
    for raw in manifest_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            expected, rel = line.split(None, 1)
        except ValueError as exc:
            raise SystemExit(f"Malformed release manifest line: {raw}") from exc
        rel = rel.strip()
        if rel.startswith("*"):
            rel = rel[1:]
        if rel.startswith("./"):
            rel = rel[2:]
        if rel == "RELEASE_MANIFEST.sha256":
            raise SystemExit("Release manifest must not hash itself")
        path = ROOT / rel
        if not path.is_file():
            raise SystemExit(f"Release manifest references missing file: {rel}")
        actual = sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise SystemExit(f"Release manifest SHA-256 mismatch: {rel}")
        entries[rel] = expected
    # Required PUBLIC source artifacts only. Private local-only assets
    # (market-seed, handoff/, development/, private models) are excluded from the
    # public manifest and therefore not required here (see PRIVATE-DATA-NOTICE.md).
    required = {
        "api.py", "services/model_builder.py", "services/research_store.py",
        "forecasting/model.py", "forecasting/recipes.py", "tools/build_builtin_seed.py",
        "tools/generate_release_manifest.py", "tools/package_source.py", "tools/verify_release.py",
        "docs/USER_MANUAL.md", "docs/FinCompass-User-Manual.pdf",
        "docs/FinCompass-User-Guide.pdf", "docs/user-guide/main.tex",
        "paper/main.tex", "paper/FinCompass-Technical-Manuscript.pdf",
        "paper/arxiv/main.tex",
    }
    missing = sorted(required - set(entries))
    if missing:
        raise SystemExit("Release manifest missing required source artifacts: " + ", ".join(missing))
    expected_files = {path.relative_to(ROOT).as_posix() for path in release_files()}
    manifest_files = set(entries)
    if manifest_files != expected_files:
        unmanifested = sorted(expected_files - manifest_files)
        stale = sorted(manifest_files - expected_files)
        detail = []
        if unmanifested:
            detail.append("unmanifested=" + ", ".join(unmanifested[:20]))
        if stale:
            detail.append("stale=" + ", ".join(stale[:20]))
        raise SystemExit("Release manifest file-set mismatch: " + "; ".join(detail))
    print(f"[verify] release manifest: {len(entries)} files hash-verified and file-set exact")


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
    market_seed_integrity_scan()
    adaptive_fixture_integrity_scan()
    model_registry_scan()
    adaptive_registry_scan()
    settings_scan()
    docs_scan()
    docker_scan()
    release_manifest_scan()
    hygiene_scan()
    print("[verify] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
