"""Starter-script tests for BYO-env mode (ADR 0010).

Exercises the *starter logic* of ``start.sh`` (flag parsing, environment
validation, choice persistence) through subprocess calls — without touching
the user environment (BYO-env mode never installs anything) and without
running full document processing (``--version`` exits the tool instantly).

Linux/macOS only: the starter's BYO-env section is POSIX bash; on Windows
the equivalent lives in ``start.bat`` (static review there).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
START_SH = PROJECT_ROOT / "start.sh"
ENV_FILE = PROJECT_ROOT / ".smartinvert_env"
VENV_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"

pytestmark = pytest.mark.skipif(
    os.name != "posix" or not START_SH.is_file(),
    reason="BYO-env starter tests require start.sh (Linux/macOS)",
)


def run_starter(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(START_SH), *args],
        capture_output=True,
        text=True,
        timeout=300,
    )


@pytest.fixture(autouse=True)
def _isolate_env_file():
    """Keep the tests from clobbering (or seeing) a real stored choice."""
    backup = ENV_FILE.with_name(".smartinvert_env.test-backup")
    if ENV_FILE.exists():
        shutil.move(str(ENV_FILE), str(backup))
    yield
    if ENV_FILE.exists():
        ENV_FILE.unlink()
    if backup.exists():
        shutil.move(str(backup), str(ENV_FILE))


def _requires_venv() -> None:
    if not VENV_PYTHON.is_file():
        pytest.skip("project .venv not present")


class TestUseEnvValidation:
    def test_missing_value_fails(self):
        result = run_starter("--use-env")
        assert result.returncode == 1
        assert "--use-env needs a path" in result.stderr

    def test_nonexistent_path_fails(self):
        result = run_starter("--use-env", "/definitely/not/here")
        assert result.returncode == 1
        assert "no usable Python found" in result.stderr

    def test_folder_without_python_fails(self):
        result = run_starter("--use-env", "/tmp")
        assert result.returncode == 1
        assert "no usable Python found" in result.stderr

    def test_env_without_dependencies_fails(self):
        # Look for an interpreter on this machine lacking the tool's deps.
        missing_dep_py = None
        for cand in ("/usr/bin/python3", "/usr/bin/python", "python3"):
            probe = shutil.which(cand)
            if probe is None:
                continue
            if subprocess.run(
                [probe, "-c", "import fitz, cv2, numpy, PIL"],
                capture_output=True,
                timeout=60,
            ).returncode != 0:
                missing_dep_py = probe
                break
        if missing_dep_py is None:
            pytest.skip("no dependency-less interpreter found on this machine")
        result = run_starter("--use-env", missing_dep_py)
        assert result.returncode == 1
        assert "missing the required" in result.stderr
        # nothing may have been written
        assert not ENV_FILE.exists()

    def test_venv_folder_is_accepted(self):
        _requires_venv()
        result = run_starter("--use-env", str(PROJECT_ROOT / ".venv"), "--version")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "using your Python environment" in result.stdout
        assert ENV_FILE.is_file()
        stored = ENV_FILE.read_text().strip()
        assert stored.startswith("PYTHON=")
        # the choice is stored as an absolute path (robust to the caller's CWD)
        assert os.path.isabs(stored[len("PYTHON="):])
        assert stored.endswith(str(VENV_PYTHON))

    def test_direct_python_exe_is_accepted(self):
        _requires_venv()
        result = run_starter("--use-env", str(VENV_PYTHON), "--version")
        assert result.returncode == 0, result.stdout + result.stderr
        assert ENV_FILE.is_file()


class TestStoredChoice:
    def test_stored_env_is_silently_reused(self):
        _requires_venv()
        ENV_FILE.write_text(f"PYTHON={VENV_PYTHON}\n")
        result = run_starter("--version")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "using your stored Python environment" in result.stdout

    def test_stored_env_missing_fails(self):
        ENV_FILE.write_text("PYTHON=/definitely/not/here/bin/python\n")
        result = run_starter("--version")
        assert result.returncode == 1
        assert "no longer exists" in result.stderr

    def test_stored_env_broken_fails(self):
        # An interpreter that exists but lacks the dependencies.
        _requires_venv()
        py = shutil.which("python3")
        if py is None:
            pytest.skip("no system python3 to simulate a broken environment")
        if subprocess.run(
            [py, "-c", "import fitz, cv2, numpy, PIL"],
            capture_output=True,
            timeout=60,
        ).returncode == 0:
            pytest.skip("system python3 unexpectedly has all dependencies")
        ENV_FILE.write_text(f"PYTHON={py}\n")
        result = run_starter("--version")
        assert result.returncode == 1
        assert "stored Python environment is broken" in result.stderr


class TestUseStandard:
    def test_removes_env_file_and_uses_standard_path(self):
        ENV_FILE.write_text("PYTHON=/whatever\n")
        assert ENV_FILE.is_file()
        result = run_starter("--use-standard", "--version")
        assert result.returncode == 0, result.stdout + result.stderr
        assert not ENV_FILE.is_file()
        assert "switched back to the standard isolated environment" in result.stdout

    def test_without_env_file_is_a_noop(self):
        assert not ENV_FILE.exists()
        result = run_starter("--use-standard", "--version")
        assert result.returncode == 0, result.stdout + result.stderr
        assert not ENV_FILE.is_file()
