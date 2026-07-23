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
                    ["/bin/bash", str(scripts / "run-orca-codex.sh"), "gpt-5.6-terra", "high"],
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
