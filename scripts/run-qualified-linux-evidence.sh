#!/usr/bin/env bash
# Run the deliberately narrow qualified-Linux suite and preserve its evidence.
#
# A result is QUALIFIED only when every declared tuple condition holds and the
# focused suite completes without skips. Any host mismatch is BLOCKED (exit 2);
# a missing suite or test failure is FAILED (exit 1). Neither state is Linux
# qualification evidence.

set -euo pipefail

readonly QUALIFICATION_SCHEMA="cognitiveos-qualified-linux-evidence-v0.1"
readonly QUALIFIED_SUITE="tests/test_qualified_linux_control_plane.py"
readonly BLOCKED_EXIT=2

python_bin="${PYTHON_BIN:-python}"
evidence_dir="${QUALIFIED_LINUX_EVIDENCE_DIR:-}"
tmp_base="${TMPDIR:-/tmp}"

if [[ -z "$evidence_dir" || "$evidence_dir" != /* ]]; then
    printf '%s\n' "QUALIFIED_LINUX_EVIDENCE_DIR must be an absolute path" >&2
    exit 64
fi

umask 077
mkdir -p "$evidence_dir"
readonly evidence_file="$evidence_dir/qualified-linux-evidence.txt"
readonly suite_output_file="$evidence_dir/qualified-linux-suite-output.txt"

: >"$suite_output_file"

actual_commit_sha="$(git rev-parse HEAD 2>/dev/null || printf 'unavailable')"
expected_pr_head_sha="${EXPECTED_PR_HEAD_SHA:-}"
github_sha="${GITHUB_SHA:-unavailable}"
uname_all="$(uname -a 2>&1 || true)"
uname_system="$(uname -s 2>&1 || true)"
uname_release="$(uname -r 2>&1 || true)"
uname_machine="$(uname -m 2>&1 || true)"
effective_uid="$(id -u 2>&1 || true)"
python_version="$("$python_bin" --version 2>&1 || true)"
python_identity="$("$python_bin" -c 'import platform, sys; print(f"implementation={sys.implementation.name} version={platform.python_version()}")' 2>&1 || true)"
mount_namespace="unavailable"
if [[ -e /proc/self/ns/mnt ]]; then
    mount_namespace="$(readlink /proc/self/ns/mnt 2>&1 || true)"
fi
filesystem_mount="unavailable"
if command -v findmnt >/dev/null 2>&1; then
    filesystem_mount="$(findmnt --target "$tmp_base" --noheadings --output FSTYPE,SOURCE,TARGET 2>&1 || true)"
elif command -v df >/dev/null 2>&1; then
    filesystem_mount="$(df -P "$tmp_base" 2>&1 || true)"
fi

{
    printf 'schema=%s\n' "$QUALIFICATION_SCHEMA"
    printf 'recorded_at_utc=%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    printf 'commit_sha=%s\n' "$github_sha"
    printf 'expected_pr_head_sha=%s\n' "$expected_pr_head_sha"
    printf 'github_sha=%s\n' "$github_sha"
    printf 'checked_out_commit_sha=%s\n' "$actual_commit_sha"
    printf 'uname=%s\n' "$uname_all"
    printf 'uid=%s\n' "$effective_uid"
    printf 'python_version=%s\n' "$python_version"
    printf 'python_identity=%s\n' "$python_identity"
    printf 'mount_namespace=%s\n' "$mount_namespace"
    printf 'filesystem_mount=%s\n' "$filesystem_mount"
    printf 'qualified_suite=%s\n' "$QUALIFIED_SUITE"
    printf 'exact_command=PYTHONPATH=src '
    printf '%q ' "$python_bin" -W error -m unittest discover -s tests -p "$(basename "$QUALIFIED_SUITE")" -v
    printf '\n'
} >"$evidence_file"

append_evidence() {
    printf '%s\n' "$1" >>"$evidence_file"
}

record_output() {
    {
        printf '%s\n' 'suite_output_begin'
        cat "$suite_output_file"
        printf '%s\n' 'suite_output_end'
    } >>"$evidence_file"
}

blocked() {
    append_evidence "status=BLOCKED"
    append_evidence "blocked_reason=$1"
    printf 'BLOCKED: %s\n' "$1" >"$suite_output_file"
    record_output
    exit "$BLOCKED_EXIT"
}

failed() {
    append_evidence "status=FAILED"
    append_evidence "failure_reason=$1"
    record_output
    exit 1
}

if [[ -z "$expected_pr_head_sha" ]]; then
    blocked "expected_pr_head_sha_unavailable"
fi

if [[ "$github_sha" == "unavailable" ]]; then
    blocked "github_sha_unavailable"
fi

if [[ "$actual_commit_sha" == "unavailable" ]]; then
    blocked "checked_out_commit_sha_unavailable"
fi

if [[ "$expected_pr_head_sha" != "$github_sha" ]]; then
    blocked "expected_pr_head_sha_does_not_match_github_sha"
fi

if [[ "$github_sha" != "$actual_commit_sha" ]]; then
    blocked "github_sha_does_not_match_checked_out_commit_sha"
fi

if [[ "$expected_pr_head_sha" != "$actual_commit_sha" ]]; then
    blocked "expected_pr_head_sha_does_not_match_checked_out_commit_sha"
fi

if [[ "$uname_system" != "Linux" ]]; then
    blocked "operating_system_is_not_linux"
fi

kernel_version="${uname_release%%-*}"
IFS=. read -r kernel_major kernel_minor _ <<<"$kernel_version"
if [[ ! "$kernel_major" =~ ^[0-9]+$ || ! "$kernel_minor" =~ ^[0-9]+$ ]] \
    || ((kernel_major < 6 || (kernel_major == 6 && kernel_minor < 1))); then
    blocked "kernel_is_not_linux_gte_6_1"
fi

if [[ "$uname_machine" != "x86_64" ]]; then
    blocked "architecture_is_not_x86_64"
fi

if ! "$python_bin" -c 'import sys; raise SystemExit(not (sys.implementation.name == "cpython" and sys.version_info[:2] == (3, 12)))'; then
    blocked "interpreter_is_not_cpython_3_12"
fi

if [[ "$effective_uid" == "0" ]]; then
    blocked "effective_uid_is_root"
fi

if [[ ! -e /proc/self/ns/mnt ]]; then
    blocked "mount_namespace_is_unavailable"
fi

if [[ -z "$mount_namespace" || "$mount_namespace" == *"No such file"* ]]; then
    blocked "mount_namespace_is_unreadable"
fi

fixture_parent="$(mktemp -d "$tmp_base/cognitiveos-qualified-linux.XXXXXX")"
trap 'rmdir "$fixture_parent" 2>/dev/null || true' EXIT

if ! command -v findmnt >/dev/null 2>&1; then
    blocked "findmnt_is_unavailable"
fi

mount_record="$(findmnt --target "$fixture_parent" --noheadings --output FSTYPE,SOURCE,TARGET 2>&1 || true)"
append_evidence "fixture_filesystem_mount=$mount_record"
filesystem_type="$(awk '{print $1}' <<<"$mount_record")"
filesystem_source="$(awk '{print $2}' <<<"$mount_record")"
if [[ "$filesystem_type" != "ext4" ]]; then
    blocked "fixture_filesystem_is_not_local_ext4"
fi
if [[ "$filesystem_source" != /dev/* ]]; then
    blocked "fixture_mount_source_is_not_local_device"
fi

if [[ ! -f "$QUALIFIED_SUITE" ]]; then
    printf 'FAILED: required qualified suite is absent: %s\n' "$QUALIFIED_SUITE" >"$suite_output_file"
    failed "qualified_suite_is_absent"
fi

set +e
TMPDIR="$fixture_parent" PYTHONPATH=src "$python_bin" -W error -m unittest discover -s tests -p "$(basename "$QUALIFIED_SUITE")" -v >"$suite_output_file" 2>&1
suite_exit=$?
set -e

if [[ $suite_exit -ne 0 ]]; then
    failed "qualified_suite_failed"
fi

if ! grep -Eq '^Ran [1-9][0-9]* tests? in ' "$suite_output_file"; then
    failed "qualified_suite_did_not_run_tests"
fi

if grep -Eq 'skipped=[1-9][0-9]*' "$suite_output_file"; then
    failed "qualified_suite_skipped_after_tuple_guard"
fi

append_evidence "status=QUALIFIED"
append_evidence "suite_exit=$suite_exit"
record_output
