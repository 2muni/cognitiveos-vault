"""Contract tests for the explicit qualified-Linux CI evidence gate."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
GATE_SCRIPT = ROOT / "scripts" / "run-qualified-linux-evidence.sh"


class QualifiedLinuxEvidenceGateTests(unittest.TestCase):
    def test_ci_defines_a_separate_python_312_evidence_job_and_always_uploads_it(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("  qualified-linux-evidence:\n", workflow)
        self.assertIn("name: Qualified Linux evidence / CPython 3.12", workflow)
        self.assertIn("runs-on: ubuntu-24.04", workflow)
        self.assertIn('python-version: "3.12"', workflow)
        self.assertIn("bash scripts/run-qualified-linux-evidence.sh", workflow)
        self.assertIn("name: qualified-linux-evidence", workflow)
        self.assertIn("if: always()", workflow)

    def test_gate_records_required_evidence_and_uses_the_focused_suite(self) -> None:
        script = GATE_SCRIPT.read_text(encoding="utf-8")

        self.assertIn('readonly QUALIFIED_SUITE="tests/test_qualified_linux_control_plane.py"', script)
        self.assertIn("status=QUALIFIED", script)
        self.assertIn("status=BLOCKED", script)
        self.assertIn("status=FAILED", script)
        self.assertIn("qualified_suite_did_not_run_tests", script)
        self.assertIn("commit_sha=", script)
        self.assertIn("uname=", script)
        self.assertIn("uid=", script)
        self.assertIn("python_version=", script)
        self.assertIn("filesystem_mount=", script)
        self.assertIn("mount_namespace=", script)
        self.assertIn("exact_command=PYTHONPATH=src", script)
        self.assertIn("suite_output_begin", script)
        self.assertNotIn("unittest discover -s tests -v", script)

    def test_non_qualifying_host_produces_a_durable_blocked_result(self) -> None:
        if (
            sys.platform == "linux"
            and sys.implementation.name == "cpython"
            and sys.version_info[:2] == (3, 12)
            and os.geteuid() != 0
        ):
            self.skipTest("this test exercises the deterministic non-qualifying-host branch")

        with tempfile.TemporaryDirectory() as temporary:
            evidence_dir = Path(temporary) / "evidence"
            completed = subprocess.run(
                ["bash", os.fspath(GATE_SCRIPT)],
                cwd=ROOT,
                env={
                    **os.environ,
                    "PYTHON_BIN": sys.executable,
                    "QUALIFIED_LINUX_EVIDENCE_DIR": os.fspath(evidence_dir),
                    "GITHUB_SHA": subprocess.check_output(
                        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                    ).strip(),
                },
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
            evidence = (evidence_dir / "qualified-linux-evidence.txt").read_text(encoding="utf-8")
            output = (evidence_dir / "qualified-linux-suite-output.txt").read_text(encoding="utf-8")
            self.assertIn("status=BLOCKED", evidence)
            self.assertIn("blocked_reason=", evidence)
            self.assertIn("commit_sha=", evidence)
            self.assertIn("uname=", evidence)
            self.assertIn("uid=", evidence)
            self.assertIn("python_version=", evidence)
            self.assertIn("filesystem_mount=", evidence)
            self.assertIn("mount_namespace=", evidence)
            self.assertIn("exact_command=", evidence)
            self.assertIn("suite_output_begin", evidence)
            self.assertTrue(output.startswith("BLOCKED:"), output)

    @unittest.skipUnless(
        sys.platform == "linux" and Path("/proc/self/ns/mnt").exists(),
        "requires Linux mount-namespace support to reach the suite-presence guard",
    )
    @unittest.skipIf(
        (ROOT / "tests" / "test_qualified_linux_control_plane.py").exists(),
        "requires the pre-PR-85 suite-absent state",
    )
    def test_matching_tuple_without_the_exact_suite_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            shim_dir = temporary_path / "bin"
            shim_dir.mkdir()

            self._write_executable(
                shim_dir / "uname",
                """#!/usr/bin/env bash
case "$1" in
    -a) printf '%s\\n' 'Linux qualified 6.1.0 x86_64' ;;
    -s) printf '%s\\n' Linux ;;
    -r) printf '%s\\n' 6.1.0 ;;
    -m) printf '%s\\n' x86_64 ;;
esac
""",
            )
            self._write_executable(shim_dir / "id", "#!/usr/bin/env bash\nprintf '%s\\n' 1000\n")
            self._write_executable(shim_dir / "readlink", "#!/usr/bin/env bash\nprintf '%s\\n' 'mnt:[4026531840]'\n")
            self._write_executable(shim_dir / "findmnt", "#!/usr/bin/env bash\nprintf '%s\\n' 'ext4 /dev/vda1 /tmp'\n")
            self._write_executable(
                shim_dir / "python312",
                """#!/usr/bin/env bash
if [[ "$1" == "--version" ]]; then
    printf '%s\\n' 'Python 3.12.0'
fi
exit 0
""",
            )

            evidence_dir = temporary_path / "evidence"
            completed = subprocess.run(
                ["bash", os.fspath(GATE_SCRIPT)],
                cwd=ROOT,
                env={
                    **os.environ,
                    "PATH": os.pathsep.join((os.fspath(shim_dir), os.environ["PATH"])),
                    "PYTHON_BIN": os.fspath(shim_dir / "python312"),
                    "QUALIFIED_LINUX_EVIDENCE_DIR": os.fspath(evidence_dir),
                    "GITHUB_SHA": subprocess.check_output(
                        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                    ).strip(),
                },
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
            evidence = (evidence_dir / "qualified-linux-evidence.txt").read_text(encoding="utf-8")
            output = (evidence_dir / "qualified-linux-suite-output.txt").read_text(encoding="utf-8")
            self.assertIn("status=FAILED", evidence)
            self.assertIn("failure_reason=qualified_suite_is_absent", evidence)
            self.assertIn("tests/test_qualified_linux_control_plane.py", output)

    @staticmethod
    def _write_executable(path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")
        path.chmod(0o700)


if __name__ == "__main__":
    unittest.main()
