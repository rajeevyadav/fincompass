#!/usr/bin/env bash
# Reject AI/tool co-authorship or attribution in commit messages.
# No tool/vendor/AI name in any authorship field (GOVERNANCE.md).
# commit-msg stage; $1 = commit message file path.
set -euo pipefail
msg_file="${1:?commit message file path expected}"
if grep -iqE 'co-authored-by:.*(claude|anthropic|copilot|chatgpt|openai|gpt-|gemini|cursor|devin|codeium|pptxgenjs|python-docx|openpyxl|\bbot\b)|generated (with|by) .*(claude|copilot|ai\b)|as an ai( language)? model' "$msg_file"; then
  echo "ERROR: commit message contains an AI/tool co-author or attribution trailer."
  echo "       Remove it and re-commit (GOVERNANCE.md AI-authorship ban)."
  exit 1
fi
exit 0
