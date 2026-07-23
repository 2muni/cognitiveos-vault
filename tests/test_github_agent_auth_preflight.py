from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = REPO_ROOT / "scripts" / "verify-github-agent-auth.sh"
LAUNCHER = REPO_ROOT / "scripts" / "run-orca-codex.sh"


class GitHubAgentAuthPreflightTests(unittest.TestCase):
    def make_command(self, directory: Path, name: str, body: str) -> Path:
        command = directory / name
        command.write_text("#!/usr/bin/env bash\nset -eu\n" + textwrap.dedent(body), encoding="utf-8")
        command.chmod(command.stat().st_mode | stat.S_IXUSR)
        return command

    def run_preflight(self, gh_body: str | None, git_body: str | None) -> subprocess.CompletedProcess[str]:
        """Run the sourced-only seam; production executable resolution is untouched."""
        with tempfile.TemporaryDirectory() as temp_dir:
            commands = Path(temp_dir)
            gh = self.make_command(commands, "gh", gh_body) if gh_body is not None else None
            git = self.make_command(commands, "git", git_body) if git_body is not None else None
            environment = os.environ | {
                "TEST_GH_BIN": str(gh) if gh is not None else "",
                "TEST_GIT_BIN": str(git) if git is not None else "",
            }
            harness = """
                source "$1"
                resolve_host_binary() {
                  case "$1" in
                    gh) [[ -n "${TEST_GH_BIN:-}" ]] && printf '%s\\n' "$TEST_GH_BIN" ;;
                    git) [[ -n "${TEST_GIT_BIN:-}" ]] && printf '%s\\n' "$TEST_GIT_BIN" ;;
                  esac
                }
                main
            """
            return subprocess.run(
                ["/bin/bash", "-c", textwrap.dedent(harness), "preflight-test", str(PREFLIGHT)],
                cwd=REPO_ROOT,
                env=environment,
                text=True,
                capture_output=True,
            )

    @staticmethod
    def healthy_gh() -> str:
        return """
            if [[ "$1" == "auth" && "$2" == "status" ]]; then exit 0; fi
            if [[ "$1" == "auth" && "$2" == "setup-git" ]]; then exit 0; fi
            if [[ "$1" == "api" ]]; then printf 'octocat\\n'; exit 0; fi
            exit 99
        """

    @staticmethod
    def healthy_git() -> str:
        return """
            if [[ "$1" == "ls-remote" && "$2" == "origin" && "$3" == "HEAD" ]]; then exit 0; fi
            exit 99
        """

    def test_success_prints_only_safe_auth_context(self) -> None:
        result = self.run_preflight(self.healthy_gh(), self.healthy_git())

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            "github-agent-auth-preflight: hostname=github.com account=octocat status=authenticated\n",
        )
        self.assertEqual(result.stderr, "")

    def test_every_failure_category_suppresses_token_like_command_output(self) -> None:
        leaking = "printf 'ghp_SUPER_SECRET_SHOULD_NOT_APPEAR'; printf 'ghp_SUPER_SECRET_SHOULD_NOT_APPEAR' >&2"
        scenarios = {
            "missing-gh": (None, self.healthy_git()),
            "missing-git": (self.healthy_gh(), None),
            "auth-status": (
                f"""
                if [[ "$1" == "auth" && "$2" == "status" ]]; then {leaking}; exit 1; fi
                exit 99
                """,
                self.healthy_git(),
            ),
            "credential-helper": (
                f"""
                if [[ "$1" == "auth" && "$2" == "status" ]]; then exit 0; fi
                if [[ "$1" == "auth" && "$2" == "setup-git" ]]; then {leaking}; exit 1; fi
                exit 99
                """,
                self.healthy_git(),
            ),
            "remote-access": (self.healthy_gh(), f"{leaking}\nexit 1"),
            "api-read": (
                f"""
                if [[ "$1" == "auth" ]]; then exit 0; fi
                if [[ "$1" == "api" ]]; then {leaking}; printf 'ghp_SUPER_SECRET_SHOULD_NOT_APPEAR'; exit 1; fi
                exit 99
                """,
                self.healthy_git(),
            ),
        }

        for category, (gh_body, git_body) in scenarios.items():
            with self.subTest(category=category):
                result = self.run_preflight(gh_body, git_body)

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"category={category}", result.stderr)
                self.assertNotIn("ghp_SUPER_SECRET_SHOULD_NOT_APPEAR", result.stdout)
                self.assertNotIn("ghp_SUPER_SECRET_SHOULD_NOT_APPEAR", result.stderr)

    def test_production_preflight_ignores_override_variables_and_worktree_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            commands = Path(temp_dir)
            marker = commands / "bypass-ran"
            bypass = self.make_command(
                commands,
                "bypass",
                'printf bypass > "$TEST_BYPASS_MARKER"\nexit 0',
            )
            environment = os.environ | {
                "COGNITIVEOS_GH_BIN": str(bypass),
                "COGNITIVEOS_GIT_BIN": str(bypass),
                "PATH": str(commands),
                "TEST_BYPASS_MARKER": str(marker),
            }

            result = subprocess.run(
                ["/bin/bash", str(PREFLIGHT)],
                cwd=REPO_ROOT,
                env=environment,
                text=True,
                capture_output=True,
            )

            self.assertFalse(marker.exists(), result.stdout + result.stderr)
            self.assertNotIn("bypass", result.stdout + result.stderr)

    def test_resolver_ignores_an_imported_git_shell_function(self) -> None:
        marker_name = "TEST_IMPORTED_GIT_FUNCTION_RAN"
        harness = f"""
            source "$1"
            git() {{ printf invoked > "${{{marker_name}}}"; }}
            export -f git
            resolved="$(resolve_host_binary git)"
            [[ "$resolved" == /* && -x "$resolved" ]]
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            marker = Path(temp_dir) / "imported-git-function-ran"
            result = subprocess.run(
                ["/bin/bash", "-c", textwrap.dedent(harness), "preflight-test", str(PREFLIGHT)],
                cwd=REPO_ROOT,
                env=os.environ | {marker_name: str(marker)},
                text=True,
                capture_output=True,
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(marker.exists(), result.stdout + result.stderr)

    def test_resolver_rejects_host_path_symlink_outside_trusted_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            trusted_bin = root / "trusted" / "bin"
            trusted_bin.mkdir(parents=True)
            untrusted = self.make_command(root, "untrusted-git", "exit 0")
            (trusted_bin / "git").symlink_to(untrusted)
            harness = """
                source "$1"
                trusted_host_path="$2"
                trusted_host_roots="$3"
                if resolve_host_binary git; then
                  exit 1
                fi
            """

            result = subprocess.run(
                [
                    "/bin/bash",
                    "-c",
                    textwrap.dedent(harness),
                    "preflight-test",
                    str(PREFLIGHT),
                    str(trusted_bin),
                    str(root / "trusted"),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_launcher_direct_execution_ignores_path_bash_before_preflight(self) -> None:
        """The executable launcher must not select a caller-provided outer Bash."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scripts = root / "scripts"
            scripts.mkdir()
            launcher = scripts / "run-orca-codex.sh"
            shutil.copy2(LAUNCHER, launcher)
            (scripts / "verify-github-agent-auth.sh").write_text(
                "#!/usr/bin/env bash\nexit 17\n",
                encoding="utf-8",
            )
            (scripts / "verify-github-agent-auth.sh").chmod(0o755)
            preflight_interpreter_marker = root / "untrusted-bash-ran"
            codex_marker = root / "codex-ran"
            self.make_command(
                root,
                "bash",
                'printf bypass > "$TEST_PREFLIGHT_INTERPRETER_MARKER"\nexit 0',
            )
            self.make_command(root, "codex", 'printf started > "$TEST_CODEX_MARKER"')
            environment = os.environ | {
                "PATH": f"{root}:{os.environ['PATH']}",
                "TEST_PREFLIGHT_INTERPRETER_MARKER": str(preflight_interpreter_marker),
                "TEST_CODEX_MARKER": str(codex_marker),
            }

            result = subprocess.run(
                [str(launcher), "gpt-5.6-terra", "high"],
                cwd=REPO_ROOT,
                env=environment,
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Codex was not started", result.stderr)
            self.assertFalse(preflight_interpreter_marker.exists(), result.stdout + result.stderr)
            self.assertFalse(codex_marker.exists(), result.stdout + result.stderr)

    def test_launcher_clears_shell_startup_state_but_preserves_github_auth_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scripts = root / "scripts"
            scripts.mkdir()
            launcher = scripts / "run-orca-codex.sh"
            shutil.copy2(LAUNCHER, launcher)
            (scripts / "verify-github-agent-auth.sh").write_text(
                textwrap.dedent(
                    """\
                    #!/bin/bash
                    [[ "${GH_CONFIG_DIR:-}" == "$TEST_GH_CONFIG_DIR" ]]
                    [[ "${GH_TOKEN:-}" == "$TEST_GH_TOKEN" ]]
                    [[ "${GITHUB_TOKEN:-}" == "$TEST_GITHUB_TOKEN" ]]
                    [[ "${SSH_AUTH_SOCK:-}" == "$TEST_SSH_AUTH_SOCK" ]]
                    [[ -z "${BASH_ENV+x}" ]]
                    [[ -z "${ENV+x}" ]]
                    ! declare -F gh >/dev/null
                    exit 17
                    """
                ),
                encoding="utf-8",
            )
            (scripts / "verify-github-agent-auth.sh").chmod(0o755)
            bash_env = root / "bash-env"
            bash_env.write_text(":\n", encoding="utf-8")
            environment = os.environ | {
                "BASH_ENV": str(bash_env),
                "ENV": str(bash_env),
                "BASH_FUNC_gh%%": "() { :; }",
                "GH_CONFIG_DIR": str(root / "gh-config"),
                "GH_TOKEN": "test-gh-token",
                "GITHUB_TOKEN": "test-github-token",
                "SSH_AUTH_SOCK": str(root / "ssh-agent.sock"),
                "TEST_GH_CONFIG_DIR": str(root / "gh-config"),
                "TEST_GH_TOKEN": "test-gh-token",
                "TEST_GITHUB_TOKEN": "test-github-token",
                "TEST_SSH_AUTH_SOCK": str(root / "ssh-agent.sock"),
            }

            result = subprocess.run(
                [str(launcher), "gpt-5.6-terra", "high"],
                cwd=REPO_ROOT,
                env=environment,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Codex was not started", result.stderr)

    def test_launcher_ignores_bash_env_and_imported_functions_before_sibling_resolution(self) -> None:
        """Startup hooks must not redirect a relative launcher to an attacker sibling."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scripts = root / "scripts"
            scripts.mkdir()
            launcher = scripts / "run-orca-codex.sh"
            shutil.copy2(LAUNCHER, launcher)
            trusted_preflight_marker = root / "trusted-preflight-ran"
            bash_env_marker = root / "bash-env-ran"
            imported_function_marker = root / "imported-function-ran"
            codex_marker = root / "codex-ran"
            attacker = root / "attacker"
            (attacker / "scripts").mkdir(parents=True)
            (scripts / "verify-github-agent-auth.sh").write_text(
                'printf trusted > "$TEST_TRUSTED_PREFLIGHT_MARKER"\nexit 17\n',
                encoding="utf-8",
            )
            (scripts / "verify-github-agent-auth.sh").chmod(0o755)
            (attacker / "scripts" / "verify-github-agent-auth.sh").write_text(
                'printf attacker > "$TEST_ATTACKER_PREFLIGHT_MARKER"\nexit 0\n',
                encoding="utf-8",
            )
            (attacker / "scripts" / "verify-github-agent-auth.sh").chmod(0o755)
            bash_env = root / "bash-env"
            bash_env.write_text(
                textwrap.dedent(
                    """\
                    printf startup > "$TEST_BASH_ENV_MARKER"
                    cd "$TEST_ATTACKER_DIR"
                    PATH="$TEST_ATTACKER_DIR:$PATH"
                    """
                ),
                encoding="utf-8",
            )
            self.make_command(root, "bash", 'printf bypass > "$TEST_PATH_BASH_MARKER"\nexit 0')
            self.make_command(root, "codex", 'printf started > "$TEST_CODEX_MARKER"')
            environment = os.environ | {
                "PATH": f"{root}:{os.environ['PATH']}",
                "BASH_ENV": str(bash_env),
                "ENV": str(bash_env),
                "BASH_FUNC_readlink%%": '() { printf imported > "$TEST_IMPORTED_FUNCTION_MARKER"; }',
                "TEST_TRUSTED_PREFLIGHT_MARKER": str(trusted_preflight_marker),
                "TEST_ATTACKER_PREFLIGHT_MARKER": str(root / "attacker-preflight-ran"),
                "TEST_BASH_ENV_MARKER": str(bash_env_marker),
                "TEST_IMPORTED_FUNCTION_MARKER": str(imported_function_marker),
                "TEST_PATH_BASH_MARKER": str(root / "path-bash-ran"),
                "TEST_CODEX_MARKER": str(codex_marker),
                "TEST_ATTACKER_DIR": str(attacker),
            }

            result = subprocess.run(
                [str(launcher), "gpt-5.6-terra", "high"],
                cwd=REPO_ROOT,
                env=environment,
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Codex was not started", result.stderr)
            self.assertTrue(trusted_preflight_marker.exists(), result.stdout + result.stderr)
            self.assertFalse(bash_env_marker.exists(), result.stdout + result.stderr)
            self.assertFalse(imported_function_marker.exists(), result.stdout + result.stderr)
            self.assertFalse((root / "attacker-preflight-ran").exists(), result.stdout + result.stderr)
            self.assertFalse((root / "path-bash-ran").exists(), result.stdout + result.stderr)
            self.assertFalse(codex_marker.exists(), result.stdout + result.stderr)

    def test_launcher_rejects_low_effort_without_running_preflight_or_codex(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scripts = root / "scripts"
            scripts.mkdir()
            launcher = scripts / "run-orca-codex.sh"
            shutil.copy2(LAUNCHER, launcher)
            preflight_marker = root / "preflight-ran"
            codex_marker = root / "codex-ran"
            (scripts / "verify-github-agent-auth.sh").write_text(
                'printf preflight > "$TEST_PREFLIGHT_MARKER"\nexit 0\n',
                encoding="utf-8",
            )
            (scripts / "verify-github-agent-auth.sh").chmod(0o755)
            self.make_command(root, "codex", 'printf started > "$TEST_CODEX_MARKER"')

            result = subprocess.run(
                [str(launcher), "gpt-5.6-terra", "low"],
                cwd=REPO_ROOT,
                env=os.environ | {
                    "PATH": f"{root}:{os.environ['PATH']}",
                    "TEST_PREFLIGHT_MARKER": str(preflight_marker),
                    "TEST_CODEX_MARKER": str(codex_marker),
                },
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 64, result.stdout + result.stderr)
            self.assertIn("requires reasoning effort high", result.stderr)
            self.assertFalse(preflight_marker.exists(), result.stdout + result.stderr)
            self.assertFalse(codex_marker.exists(), result.stdout + result.stderr)

    def test_launcher_rejects_path_codex_after_successful_preflight(self) -> None:
        """Codex must satisfy the same host-path policy as gh and git."""
        trusted_host_path = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        if shutil.which("codex", path=trusted_host_path) is not None:
            self.skipTest("a real trusted-host Codex must not be invoked by this adversarial test")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scripts = root / "scripts"
            scripts.mkdir()
            launcher = scripts / "run-orca-codex.sh"
            shutil.copy2(LAUNCHER, launcher)
            codex_marker = root / "codex-ran"
            (scripts / "verify-github-agent-auth.sh").write_text("exit 0\n", encoding="utf-8")
            (scripts / "verify-github-agent-auth.sh").chmod(0o755)
            self.make_command(root, "codex", 'printf started > "$TEST_CODEX_MARKER"')

            result = subprocess.run(
                [str(launcher), "gpt-5.6-terra", "high"],
                cwd=REPO_ROOT,
                env=os.environ | {
                    "PATH": f"{root}:{os.environ['PATH']}",
                    "TEST_CODEX_MARKER": str(codex_marker),
                },
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("trusted host Codex executable is unavailable", result.stderr)
            self.assertFalse(codex_marker.exists(), result.stdout + result.stderr)

    def test_launcher_never_executes_codex_for_any_preflight_failure(self) -> None:
        scenarios = {
            "missing-gh": (None, self.healthy_git()),
            "missing-git": (self.healthy_gh(), None),
            "auth-status": ("exit 1", self.healthy_git()),
            "credential-helper": (
                """
                if [[ "$1" == "auth" && "$2" == "status" ]]; then exit 0; fi
                exit 1
                """,
                self.healthy_git(),
            ),
            "remote-access": (self.healthy_gh(), "exit 1"),
            "api-read": (
                """
                if [[ "$1" == "auth" ]]; then exit 0; fi
                if [[ "$1" == "api" ]]; then exit 1; fi
                exit 99
                """,
                self.healthy_git(),
            ),
        }

        for category, (gh_body, git_body) in scenarios.items():
            with self.subTest(category=category), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                scripts = root / "scripts"
                scripts.mkdir()
                shutil.copy2(LAUNCHER, scripts / "run-orca-codex.sh")
                gh = self.make_command(root, "gh", gh_body) if gh_body is not None else None
                git = self.make_command(root, "git", git_body) if git_body is not None else None
                marker = root / "codex-ran"
                self.make_command(root, "codex", 'printf started > "$TEST_CODEX_MARKER"')
                (scripts / "verify-github-agent-auth.sh").write_text(
                    textwrap.dedent(
                        """\
                        #!/usr/bin/env bash
                        set -euo pipefail
                        source "$ORIGINAL_PREFLIGHT"
                        resolve_host_binary() {
                          case "$1" in
                            gh) [[ -n "${TEST_GH_BIN:-}" ]] && printf '%s\\n' "$TEST_GH_BIN" ;;
                            git) [[ -n "${TEST_GIT_BIN:-}" ]] && printf '%s\\n' "$TEST_GIT_BIN" ;;
                          esac
                        }
                        main
                        """
                    ),
                    encoding="utf-8",
                )
                (scripts / "verify-github-agent-auth.sh").chmod(0o755)
                environment = os.environ | {
                    "ORIGINAL_PREFLIGHT": str(PREFLIGHT),
                    "TEST_GH_BIN": str(gh) if gh is not None else "",
                    "TEST_GIT_BIN": str(git) if git is not None else "",
                    "TEST_CODEX_MARKER": str(marker),
                    "PATH": f"{root}:{os.environ['PATH']}",
                }

                result = subprocess.run(
                    [str(scripts / "run-orca-codex.sh"), "gpt-5.6-terra", "high"],
                    cwd=REPO_ROOT,
                    env=environment,
                    text=True,
                    capture_output=True,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Codex was not started", result.stderr)
                self.assertFalse(marker.exists(), result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
