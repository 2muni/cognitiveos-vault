#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Warning: this bootstrap is intended for macOS." >&2
fi

if ! command -v git >/dev/null 2>&1; then
  echo "Git is required. On macOS, run: xcode-select --install" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.12+ is required. On an Intel Mac with Homebrew, run: brew install python@3.14" >&2
  exit 1
fi

if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)'; then
  echo "Python 3.12 or newer is required." >&2
  exit 1
fi

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

./.venv/bin/python scripts/verify_environment.py

cat <<'EOF'

Intel Mac bootstrap complete.

Next:
1. Open this vault root in Obsidian and VS Code/Codex.
2. Trust the project when Codex asks.
3. Confirm the cognitiveos MCP server and its nine read-only tools are visible.
4. Keep private note folders synchronized separately from Git.
EOF
