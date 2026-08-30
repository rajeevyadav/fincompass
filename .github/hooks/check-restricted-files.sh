#!/usr/bin/env bash
# Local mirror of the Restricted Folder Guard — blocks staging of secrets /
# runtime-data files. pre-commit stage; receives staged paths as arguments.
set -euo pipefail
PATTERN='(^|/)\.env$|(^|/)\.env\.|(^|/)secrets/|\.(pem|key|pfx|p12|keystore)$|(^|/)id_rsa$|(^|/)id_ed25519$|(^|/)credentials\.json$|\.credentials$|(^|/)data/.*\.db($|-)|(^|/)data/audit\.jsonl|\.(sqlite|sqlite3)$'
bad=0
for f in "$@"; do
  [ "$(basename "$f")" = ".env.example" ] && continue
  if echo "$f" | grep -qE "$PATTERN"; then
    echo "ERROR: secret / restricted file must not be committed: $f"
    bad=1
  fi
done
exit "$bad"
