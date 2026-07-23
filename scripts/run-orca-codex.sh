#!/bin/bash -p
set -euo pipefail

# This executable is a security control: launch it directly, never through a
# caller-selected `bash`.  Privileged mode prevents BASH_ENV, ENV, and
# imported functions from changing path resolution before this gate runs.
#
# Require the reviewed model and effort explicitly. This keeps Codex's client
# default (currently Terra/low) from silently weakening this control.
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

if [[ "$reasoning_effort" != "high" ]]; then
  echo "security launcher requires reasoning effort high (received: $reasoning_effort)" >&2
  exit 64
fi

# Do not resolve any executable through the caller's PATH. These are the same
# host-managed locations used by the GitHub authentication preflight.
trusted_bash="/bin/bash"
trusted_env="/usr/bin/env"
trusted_readlink="/usr/bin/readlink"
trusted_host_path="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
trusted_host_roots="/opt/homebrew:/usr/local:/usr/bin:/usr/sbin:/bin:/sbin"
if [[ ! -x "$trusted_bash" || ! -x "$trusted_env" || ! -x "$trusted_readlink" ]]; then
  echo "Codex was not started: trusted host shell utilities are unavailable." >&2
  exit 1
fi

canonicalize_path() {
  local path="$1"
  local link
  local directory
  local filename
  local link_count=0

  if [[ "$path" != /* ]]; then
    path="$(builtin pwd -P)/$path"
  fi

  # Resolve the launcher itself rather than trusting the directory containing
  # a symlink supplied by the caller. Keep the same bounded-link behavior as
  # the authentication preflight's binary resolver.
  while [[ -L "$path" ]]; do
    if (( link_count >= 40 )); then
      return 1
    fi
    ((link_count += 1))
    link="$("$trusted_readlink" "$path")" || return 1
    if [[ "$link" == /* ]]; then
      path="$link"
    else
      directory="${path%/*}"
      if [[ "$directory" == "$path" ]]; then
        directory="."
      fi
      directory="$(builtin cd -P -- "$directory" && builtin pwd -P)" || return 1
      path="$directory/$link"
    fi
  done

  [[ -f "$path" ]] || return 1
  directory="${path%/*}"
  filename="${path##*/}"
  if [[ "$directory" == "$path" ]]; then
    directory="."
  fi
  directory="$(builtin cd -P -- "$directory" && builtin pwd -P)" || return 1
  printf '%s/%s\n' "$directory" "$filename"
}

is_trusted_host_binary() {
  local binary="$1"
  local root
  local IFS=:

  for root in $trusted_host_roots; do
    if [[ "$binary" == "$root/"* ]]; then
      return 0
    fi
  done
  return 1
}

resolve_trusted_host_binary() {
  local name="$1"
  local binary

  binary="$(PATH="$trusted_host_path" builtin type -P -- "$name" 2>/dev/null || true)"
  if [[ "$binary" != /* ]]; then
    return 1
  fi
  binary="$(canonicalize_path "$binary")" || return 1
  [[ -x "$binary" ]] || return 1
  is_trusted_host_binary "$binary" || return 1
  printf '%s\n' "$binary"
}

if ! launcher_path="$(canonicalize_path "${BASH_SOURCE[0]}")"; then
  echo "Codex was not started: unable to resolve the launcher path safely." >&2
  exit 1
fi
script_dir="${launcher_path%/*}"
preflight_path="$script_dir/verify-github-agent-auth.sh"
if [[ ! -f "$preflight_path" || ! -x "$preflight_path" ]]; then
  echo "Codex was not started: sibling GitHub authentication preflight is unavailable." >&2
  exit 1
fi

# The preflight must not inherit a caller-selected interpreter or Bash startup
# hooks. Keep GitHub and Git credential environment variables intact; only
# shell initialization and imported-function variables are removed.
preflight_environment=("$trusted_env" -u BASH_ENV -u ENV)
while IFS='=' read -r environment_name _; do
  case "$environment_name" in
    BASH_FUNC_*%%) preflight_environment+=(-u "$environment_name") ;;
  esac
done < <("$trusted_env")

if ! "${preflight_environment[@]}" "$trusted_bash" --noprofile --norc \
  "$preflight_path"; then
  echo "Codex was not started: agent-runtime GitHub authentication preflight failed." >&2
  exit 1
fi

if ! codex_bin="$(resolve_trusted_host_binary codex)"; then
  echo "Codex was not started: a trusted host Codex executable is unavailable." >&2
  exit 1
fi

exec "$codex_bin" --model "$model_id" \
  -c "model_reasoning_effort=\"$reasoning_effort\"" \
  "$@"
