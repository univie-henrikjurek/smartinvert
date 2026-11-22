"""Tests for ``smartboard_invert.reveal`` (ADR 0011, D3): the platform
file-manager opener of the "Speicherordner öffnen" button.

``reveal_argv()`` is a pure function (no process is spawned), so the
platform logic is tested by swapping ``sys.platform``; ``reveal_output()``
is tested with a stubbed ``subprocess.Popen`` (no file manager needed).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from smartboard_invert import reveal


class TestRevealArgv:
    """Pure argv construction per platform (ADR 0011, D3)."""

    def test_windows_file_marks_the_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        f = tmp_path / "out.pdf"
        f.write_bytes(b"%PDF-1.4")
        exe, args = reveal.reveal_argv(f)
        assert exe == "explorer"
        assert args == [f'/select,"{f.resolve()}"']

    def test_windows_folder_opens_folder(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        d = tmp_path / "outputs"
        d.mkdir()
        exe, args = reveal.reveal_argv(d)
        assert exe == "explorer"
        assert args == [str(d.resolve())]

    def test_darwin_file_uses_open_dash_R(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        f = tmp_path / "out.pdf"
        f.write_bytes(b"%PDF-1.4")
        exe, args = reveal.reveal_argv(f)
        assert exe == "open"
        assert args == ["-R", str(f.resolve())]

    def test_darwin_folder_uses_plain_open(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        d = tmp_path / "outputs"
        d.mkdir()
        exe, args = reveal.reveal_argv(d)
        assert exe == "open"
        assert args == [str(d.resolve())]

    def test_linux_file_opens_parent_folder(self, tmp_path, monkeypatch):
        """xdg-open cannot mark a single file -> the parent folder is
        opened instead (ADR 0011, 'Bekannte Einschränkungen' #1)."""
        monkeypatch.setattr(sys, "platform", "linux")
        f = tmp_path / "out.pdf"
        f.write_bytes(b"%PDF-1.4")
        exe, args = reveal.reveal_argv(f)
        assert exe == "xdg-open"
        assert args == [str(tmp_path.resolve())]

    def test_linux_folder_opens_folder(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        d = tmp_path / "outputs"
        d.mkdir()
        exe, args = reveal.reveal_argv(d)
        assert exe == "xdg-open"
        assert args == [str(d.resolve())]

    def test_unknown_platform_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "platform", "sunos5")
        assert reveal.reveal_argv(tmp_path / "out.pdf") is None

    def test_accepts_str_targets(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        f = tmp_path / "out.pdf"
        f.write_bytes(b"%PDF-1.4")
        exe, args = reveal.reveal_argv(str(f))
        assert exe == "xdg-open"
        assert args == [str(tmp_path.resolve())]


class TestRevealOutput:
    """The Popen wrapper: non-blocking start, graceful failure."""

    def test_starts_opener_and_returns_true(self, tmp_path, monkeypatch):
        started = []

        def fake_popen(cmd, **kwargs):
            started.append((cmd, kwargs))
            return None

        monkeypatch.setattr(reveal.subprocess, "Popen", fake_popen)
        f = tmp_path / "out.pdf"
        f.write_bytes(b"%PDF-1.4")
        assert reveal.reveal_output(f) is True
        assert started, "Popen must be called"
        cmd, kwargs = started[0]
        # the started command must match the pure argv construction for
        # whatever platform this runs on (no hardcoded opener name)
        expected_exe, expected_args = reveal.reveal_argv(f)
        assert cmd == [expected_exe, *expected_args]
        # the opener must not flood the terminal
        assert kwargs.get("stdout") is not None
        assert kwargs.get("stderr") is not None

    def test_missing_opener_returns_false_without_raising(
        self, tmp_path, monkeypatch, caplog
    ):
        """A missing xdg-open (FileNotFoundError) or any OSError produces
        a warning and False — never an exception (headless SSH sessions,
        ADR 0011, D3)."""

        def boom(cmd, **kwargs):
            raise FileNotFoundError("xdg-open not found")

        monkeypatch.setattr(reveal.subprocess, "Popen", boom)
        f = tmp_path / "out.pdf"
        f.write_bytes(b"%PDF-1.4")
        import logging

        with caplog.at_level(logging.WARNING, logger="smartboard_invert.reveal"):
            assert reveal.reveal_output(f) is False
        assert any("file manager" in r.message for r in caplog.records)

    def test_unknown_platform_returns_false_without_raising(
        self, tmp_path, monkeypatch, caplog
    ):
        monkeypatch.setattr(sys, "platform", "sunos5")
        import logging

        with caplog.at_level(logging.WARNING, logger="smartboard_invert.reveal"):
            assert reveal.reveal_output(tmp_path / "out.pdf") is False
        assert any("no file manager opener" in r.message for r in caplog.records)
