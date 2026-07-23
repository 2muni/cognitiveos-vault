from __future__ import annotations

import os
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

    def run_preflight(self, gh_body: str, git_body: str, *, launcher: bool = False) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            commands = Path(temp_dir)
            gh = self.make_command(commands, "gh", gh_body)
            git = self.make_command(commands, "git", git_body)
            environment = os.environ | {
                "COGNITIVEOS_GH_BIN": str(gh),
                "COGNITIVEOS_GIT_BIN": str(git),
            }
            command = ["bash", str(LAUNCHER), "gpt-5.6-terra", "low"] if launcher else [str(PREFLIGHT)]
            return subprocess.run(command, cwd=REPO_ROOT, env=environment, text=True, capture_output=True)

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

    def test_auth_failure_has_actionable_category_without_command_output(self) -> None:
        result = self.run_preflight(
            """
            if [[ "$1" == "auth" && "$2" == "status" ]]; then
              printf 'token=should-not-appear' >&2
              exit 1
            fi
            exit 99
            """,
            self.healthy_git(),
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("category=auth-status", result.stderr)
        self.assertIn("gh auth login --hostname github.com", result.stderr)
        self.assertNotIn("should-not-appear", result.stderr)

    def test_remote_failure_is_distinguished_after_host_auth_succeeds(self) -> None:
        result = self.run_preflight(self.healthy_gh(), "exit 1")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("category=remote-access", result.stderr)

    def test_launcher_does_not_execute_codex_when_preflight_fails(self) -> None:
        result = self.run_preflight("exit 1", self.healthy_git(), launcher=True)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Codex was not started", result.stderr)


if __name__ == "__main__":
    unittest.main()
