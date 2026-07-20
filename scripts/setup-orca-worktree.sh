#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if ! command -v uv >/dev/null 2>&1; then
  echo "Orca worktree setup requires uv: https://docs.astral.sh/uv/" >&2
  exit 1
fi

# GitHub credentials are host-level and must not be copied into a worktree.
# Verify them before an agent starts so GitHub operations fail at setup time,
# not after a long implementation run. `gh auth setup-git` only installs the
# approved Git credential helper; it does not create or print a token.
if ! command -v gh >/dev/null 2>&1; then
  echo "Orca worktree setup requires GitHub CLI (gh) for authenticated worktree operations." >&2
  exit 1
fi

if ! gh auth status --hostname github.com >/dev/null 2>&1; then
  echo "GitHub authentication is not available for this Orca worktree." >&2
  echo "Authenticate once at the host level with: gh auth login --hostname github.com" >&2
  echo "Then recreate or rerun the worktree setup hook." >&2
  exit 1
fi

if ! gh auth setup-git >/dev/null 2>&1; then
  echo "GitHub authentication is valid, but Git credential setup failed." >&2
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
writeback. GitHub authentication was verified at setup time and the Git
credential helper was initialized without copying credentials into the
worktree. Run the Tests and Vault status tabs when the task requires them.
EOF
