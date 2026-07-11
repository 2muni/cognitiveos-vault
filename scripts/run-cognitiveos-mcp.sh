#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -n "${COGNITIVEOS_PYTHON:-}" && -x "$COGNITIVEOS_PYTHON" ]]; then
  python_bin="$COGNITIVEOS_PYTHON"
elif [[ "${COGNITIVEOS_SEMANTIC_RUNTIME:-off}" == "local" && -x "$repo_root/.venv-embeddings312/bin/python" ]]; then
  python_bin="$repo_root/.venv-embeddings312/bin/python"
elif [[ -x "$repo_root/.venv/bin/python" ]]; then
  python_bin="$repo_root/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  python_bin="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  python_bin="$(command -v python)"
else
  echo "CognitiveOS requires Python 3.11 or newer." >&2
  exit 1
fi

if ! "$python_bin" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "CognitiveOS requires Python 3.11 or newer." >&2
  exit 1
fi

export PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$python_bin" -m cognitiveos.mcp_server --vault-root "$repo_root"
