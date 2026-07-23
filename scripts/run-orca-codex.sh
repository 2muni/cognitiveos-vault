#!/usr/bin/env bash
set -euo pipefail

# Require an explicit model and reasoning effort for every Orca worker.  This
# prevents Codex's client default (currently Terra/low) from silently
# overriding the tier selected by the orchestrator.
if [[ $# -lt 2 ]]; then
  echo "usage: $0 <model-id> <reasoning-effort> [codex-args...]" >&2
  echo "example: $0 gpt-5.6-terra high" >&2
  exit 64
fi

model_id="$1"
reasoning_effort="$2"
shift 2

case "$model_id" in
  # This repository is operated through Codex with a ChatGPT account.  The
  # account currently supports Terra, but rejects gpt-5.6 and preview IDs.
  gpt-5.6-terra) ;;
  *)
    echo "unsupported model id for this Codex account: $model_id (use gpt-5.6-terra)" >&2
    exit 64
    ;;
esac

case "$reasoning_effort" in
  none|minimal|low|medium|high|xhigh|max|ultra) ;;
  *)
    echo "unsupported reasoning effort: $reasoning_effort" >&2
    exit 64
    ;;
esac

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if ! "$script_dir/verify-github-agent-auth.sh"; then
  echo "Codex was not started: agent-runtime GitHub authentication preflight failed." >&2
  exit 1
fi

exec codex --model "$model_id" \
  -c "model_reasoning_effort=\"$reasoning_effort\"" \
  "$@"
