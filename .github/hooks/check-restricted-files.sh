#!/usr/bin/env bash
# Local restricted-file guard. Protected market data/model assets must never be committed.
set -euo pipefail
bad=0
for f in "$@"; do
  f="${f#./}"
  base="$(basename "$f")"
  [ "$base" = ".env.example" ] && continue
  [ "$f" = "data/.gitkeep" ] && continue
  # Public models ship (only DATA is restricted): fixture, PUBLIC bundled model
  # + evidence, public adaptive fixture, sharing-status README.
  case "$f" in
    models/fixture-reference-*|models/bundled-monthly-*|models/PRIVATE_MODEL_README.md|adaptive_models/balanced-adaptive-*)
      continue ;;
  esac
  case "$f" in
    .env|.env.*|secrets/*|*/secrets/*|*.pem|*.key|*.pfx|*.p12|*.keystore|id_rsa|*/id_rsa|id_ed25519|*/id_ed25519|credentials.json|*/credentials.json|*.credentials)
      ;;
    data/*|datasets/market-seed/*|models/*|adaptive_models/*|private_assets/*|*.db|*.sqlite|*.sqlite3|*.joblib|*.npz|*.tar.gz)
      ;;
    *)
      continue
      ;;
  esac
  echo "ERROR: private/restricted file must not be committed: $f"
  bad=1
done
exit "$bad"
