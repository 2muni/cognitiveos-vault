#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if ! command -v uv >/dev/null 2>&1; then
  echo "Orca worktree setup requires uv: https://docs.astral.sh/uv/" >&2
  exit 1
fi

python_version="${COGNITIVEOS_ORCA_PYTHON:-$(tr -d '[:space:]' < .python-version)}"

if [[ ! -x .venv/bin/python ]]; then
  uv venv --python "$python_version" .venv
fi

uv pip install --python .venv/bin/python '.[dev,mcp]'

cat <<'EOF'

CognitiveOS Orca worktree is ready.

The setup created only the default development runtime. It did not build an
index, download an embedding model, synchronize private notes, or enable
writeback. Run the Tests and Vault status tabs when the task requires them.
EOF
