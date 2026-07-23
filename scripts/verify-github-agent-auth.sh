#!/usr/bin/env bash
set -euo pipefail

# Verify the host-level GitHub state immediately before Codex starts. This is
# intentionally separate from the Orca setup hook: credentials can expire or
# be revoked between setup and task submission.
#
# Test seams accept executable paths. They are not credential inputs and no
# credential material is written to, or read from, the worktree.
gh_bin="${COGNITIVEOS_GH_BIN:-gh}"
git_bin="${COGNITIVEOS_GIT_BIN:-git}"
hostname="github.com"

fail() {
  local category="$1"
  local detail="$2"
  printf 'github-agent-auth-preflight: category=%s hostname=%s account=unknown status=failed\n' \
    "$category" "$hostname" >&2
  printf 'github-agent-auth-preflight: %s\n' "$detail" >&2
  exit 1
}

if ! command -v "$gh_bin" >/dev/null 2>&1; then
  fail "missing-gh" "Install GitHub CLI (gh) on the host, then rerun the terminal launcher."
fi

if ! command -v "$git_bin" >/dev/null 2>&1; then
  fail "missing-git" "Install Git on the host, then rerun the terminal launcher."
fi

if ! "$gh_bin" auth status --hostname "$hostname" >/dev/null 2>&1; then
  fail "auth-status" "Run: gh auth login --hostname $hostname (host-level), then rerun the terminal launcher."
fi

if ! "$gh_bin" auth setup-git >/dev/null 2>&1; then
  fail "credential-helper" "GitHub auth is present but gh auth setup-git failed; repair host Git credential helper configuration."
fi

if ! "$git_bin" ls-remote origin HEAD >/dev/null 2>&1; then
  fail "remote-access" "Authenticated access to origin failed; verify the origin remote and host GitHub authorization."
fi

# GET /user is read-only. Ask gh to return only the login, then whitelist it
# before including it in the safe context line.
account="$("$gh_bin" api --hostname "$hostname" user --jq .login 2>/dev/null || true)"
if [[ -z "$account" ]]; then
  fail "api-read" "Read-only GitHub API verification failed; refresh host authentication with gh auth login."
fi
if [[ ! "$account" =~ ^[A-Za-z0-9-]+$ ]]; then
  fail "api-read" "GitHub returned an invalid account identifier; refresh host authentication with gh auth login."
fi

printf 'github-agent-auth-preflight: hostname=%s account=%s status=authenticated\n' \
  "$hostname" "$account"
