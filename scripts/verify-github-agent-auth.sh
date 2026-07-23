#!/usr/bin/env bash
set -euo pipefail

# Verify the host-level GitHub state immediately before Codex starts. This is
# intentionally separate from the Orca setup hook: credentials can expire or
# be revoked between setup and task submission.
#
# Resolve authentication tooling exclusively from host-managed locations. Do
# not use COGNITIVEOS_GH_BIN, COGNITIVEOS_GIT_BIN, or the caller's PATH here:
# those values can be supplied by a worktree and could turn this gate into a
# successful no-op. Keep this list small and explicit so it remains portable
# across the supported macOS, Linux, and Windows-on-WSL host layouts.
trusted_host_path="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
hostname="github.com"

resolve_host_binary() {
  local name="$1"
  local binary

  binary="$(PATH="$trusted_host_path" command -v "$name" 2>/dev/null || true)"
  if [[ "$binary" != /* || ! -x "$binary" ]]; then
    return 1
  fi
  printf '%s\n' "$binary"
}

fail() {
  local category="$1"
  local detail="$2"
  printf 'github-agent-auth-preflight: category=%s hostname=%s account=unknown status=failed\n' \
    "$category" "$hostname" >&2
  printf 'github-agent-auth-preflight: %s\n' "$detail" >&2
  exit 1
}

main() {
  local gh_bin
  local git_bin
  local account

  if ! gh_bin="$(resolve_host_binary gh)"; then
    fail "missing-gh" "Install GitHub CLI (gh) on the host, then rerun the terminal launcher."
  fi

  if ! git_bin="$(resolve_host_binary git)"; then
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
}

# Keep the executable script free of test configuration. Tests source this
# file and replace resolve_host_binary in their own process; the launcher
# executes it directly, so no worktree-controlled executable can be injected.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
