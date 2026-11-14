"""CLI tests: batch processing, same-name outputs, input immutability, debug."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

from smartboard_invert import cli

import synth

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def run_cli(*args: str, cwd: "Path | None" = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "smartboard_invert", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd is not None else None,
        timeout=300,
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_two_pdf_dir(directory: Path) -> list:
    (directory / "a.pdf").unlink(missing_ok=True)
    (directory / "b.pdf").unlink(missing_ok=True)
    synth.make_pdf(directory / "a.pdf", [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)}])
    synth.make_pdf(directory / "b.pdf", [{"kind": "blank", "marks": [(100, 100, 20, 40)]}])
    return sorted(directory.glob("*.pdf"))


class TestDirectoryBatch:
    def test_batch_same_name_output_and_input_untouched(self, tmp_path):
        ind = tmp_path / "inputs"
        ind.mkdir()
        files = make_two_pdf_dir(ind)
        before = {p.name: sha256(p) for p in files}
        outd = tmp_path / "outputs"
        result = run_cli("--input", str(ind), "--output", str(outd))
        assert result.returncode == 0, result.stderr + result.stdout
        assert (outd / "a.pdf").is_file()
        assert (outd / "b.pdf").is_file()
        # inputs are byte-identical
        for p in files:
            assert sha256(p) == before[p.name]

    def test_default_dirs_inputs_outputs(self, tmp_path):
        ind = tmp_path / "inputs"
        ind.mkdir()
        synth.make_pdf(ind / "x.pdf", [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)}])
        result = run_cli(cwd=tmp_path)  # no arguments: inputs/ -> outputs/
        assert result.returncode == 0, result.stderr + result.stdout
        assert (tmp_path / "outputs" / "x.pdf").is_file()

    def test_empty_input_dir_fails(self, tmp_path):
        ind = tmp_path / "inputs"
        ind.mkdir()
        result = run_cli("--input", str(ind))
        assert result.returncode != 0
        assert "no pdf files" in (result.stderr + result.stdout).lower()

    def test_missing_input_fails(self, tmp_path):
        result = run_cli("--input", str(tmp_path / "does-not-exist"))
        assert result.returncode != 0
        assert "not found" in (result.stderr + result.stdout).lower()

    def test_corrupt_pdf_does_not_stop_batch(self, tmp_path):
        ind = tmp_path / "inputs"
        ind.mkdir()
        synth.make_pdf(ind / "good.pdf", [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)}])
        (ind / "broken.pdf").write_bytes(b"this is not a pdf")
        outd = tmp_path / "outputs"
        result = run_cli("--input", str(ind), "--output", str(outd), "-v")
        assert result.returncode == 1  # one file failed
        assert (outd / "good.pdf").is_file()  # the good one was processed
        assert "failed" in (result.stderr + result.stdout).lower()


class TestSingleFile:
    def test_file_to_directory_same_name(self, tmp_path):
        src = tmp_path / "board.pdf"
        synth.make_pdf(src, [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)}])
        outd = tmp_path / "out"
        result = run_cli("--input", str(src), "--output", str(outd))
        assert result.returncode == 0, result.stderr + result.stdout
        assert (outd / "board.pdf").is_file()

    def test_file_to_file(self, tmp_path):
        src = tmp_path / "board.pdf"
        synth.make_pdf(src, [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)}])
        dst = tmp_path / "renamed.pdf"
        result = run_cli("--input", str(src), "--output", str(dst))
        assert result.returncode == 0, result.stderr + result.stdout
        assert dst.is_file()

    def test_refuse_overwrite_input(self, tmp_path):
        src = tmp_path / "board.pdf"
        synth.make_pdf(src, [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)}])
        before = sha256(src)
        result = run_cli("--input", str(src), "--output", str(src))
        assert result.returncode != 0
        assert sha256(src) == before
        assert "overwrite" in (result.stderr + result.stdout).lower()


class TestDebugFlag:
    def test_debug_writes_composites(self, tmp_path):
        ind = tmp_path / "inputs"
        ind.mkdir()
        synth.make_pdf(
            ind / "dbg.pdf",
            [
                {"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)},
                {"kind": "blank", "marks": [(100, 100, 20, 40)]},
            ],
        )
        outd = tmp_path / "outputs"
        result = run_cli("--input", str(ind), "--output", str(outd), "--debug")
        assert result.returncode == 0, result.stderr + result.stdout
        debug_files = sorted((outd / "debug").glob("*_debug.png"))
        assert len(debug_files) == 2  # one per page
        for f in debug_files:
            assert f.stat().st_size > 1000


class TestConfigAndVersion:
    def test_version(self, tmp_path):
        result = run_cli("--version")
        assert result.returncode == 0
        assert "0.2.0" in result.stdout

    def test_config_file_defaults(self, tmp_path):
        ind = tmp_path / "inputs"
        ind.mkdir()
        synth.make_pdf(ind / "cfg.pdf", [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)}])
        cfg = tmp_path / "config.json"
        cfg.write_text('{"output": "' + str(tmp_path / "cfgout") + '", "dpi": 100}')
        result = run_cli("--input", str(ind), "--config", str(cfg))
        assert result.returncode == 0, result.stderr + result.stdout
        assert (tmp_path / "cfgout" / "cfg.pdf").is_file()

    def test_config_file_missing_fails(self, tmp_path):
        result = run_cli("--config", str(tmp_path / "nope.json"))
        assert result.returncode != 0


class TestCliInProcess:
    """Directly invoke cli.main() (no subprocess) for fast, coverage-enabled
    tests of the argument planning and batch control flow."""

    def test_main_directory_batch(self, tmp_path, caplog):
        import logging

        ind = tmp_path / "inputs"
        ind.mkdir()
        make_two_pdf_dir(ind)
        outd = tmp_path / "outputs"
        with caplog.at_level(logging.INFO):
            rc = cli.main(["--input", str(ind), "--output", str(outd), "-v"])
        assert rc == 0
        assert (outd / "a.pdf").is_file()
        assert (outd / "b.pdf").is_file()
        assert any("Done:" in r.message for r in caplog.records)

    def test_main_single_file_to_directory(self, tmp_path):
        src = tmp_path / "board.pdf"
        synth.make_pdf(src, [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)}])
        outd = tmp_path / "out"
        rc = cli.main(["--input", str(src), "--output", str(outd)])
        assert rc == 0
        assert (outd / "board.pdf").is_file()

    def test_main_single_file_default_output_name(self, tmp_path):
        """Without --output a single file goes to <stem>_inverted.pdf (legacy)."""
        src = tmp_path / "board.pdf"
        synth.make_pdf(src, [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)}])
        rc = cli.main(["--input", str(src)])
        assert rc == 0
        assert (tmp_path / "board_inverted.pdf").is_file()

    def test_main_missing_input(self, tmp_path):
        rc = cli.main(["--input", str(tmp_path / "nope")])
        assert rc == 1

    def test_main_empty_directory(self, tmp_path):
        ind = tmp_path / "inputs"
        ind.mkdir()
        rc = cli.main(["--input", str(ind)])
        assert rc == 1

    def test_main_refuse_overwrite_input(self, tmp_path):
        src = tmp_path / "board.pdf"
        synth.make_pdf(src, [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)}])
        rc = cli.main(["--input", str(src), "--output", str(src)])
        assert rc == 1

    def test_main_corrupt_file_returns_failure_but_batch_continues(self, tmp_path):
        ind = tmp_path / "inputs"
        ind.mkdir()
        synth.make_pdf(ind / "good.pdf", [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)}])
        (ind / "broken.pdf").write_bytes(b"not a pdf")
        outd = tmp_path / "outputs"
        rc = cli.main(["--input", str(ind), "--output", str(outd)])
        assert rc == 1
        assert (outd / "good.pdf").is_file()

    def test_main_debug_flag(self, tmp_path):
        ind = tmp_path / "inputs"
        ind.mkdir()
        synth.make_pdf(
            ind / "d.pdf",
            [
                {"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)},
                {"kind": "blank", "marks": []},
            ],
        )
        outd = tmp_path / "outputs"
        rc = cli.main(["--input", str(ind), "--output", str(outd), "--debug"])
        assert rc == 0
        assert len(list((outd / "debug").glob("*_debug.png"))) == 2

    def test_main_config_takes_precedence_over_defaults(self, tmp_path):
        ind = tmp_path / "inputs"
        ind.mkdir()
        synth.make_pdf(ind / "c.pdf", [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)}])
        cfg = tmp_path / "c.json"
        outd = tmp_path / "viaconfig"
        cfg.write_text('{"output": "' + str(outd) + '"}')
        rc = cli.main(["--input", str(ind), "--config", str(cfg)])
        assert rc == 0
        assert (outd / "c.pdf").is_file()

    def test_main_config_overridden_by_cli(self, tmp_path):
        """An explicit CLI flag beats the config file value."""
        ind = tmp_path / "inputs"
        ind.mkdir()
        synth.make_pdf(ind / "c.pdf", [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)}])
        cfg = tmp_path / "c.json"
        cfg.write_text('{"output": "' + str(tmp_path / "fromconfig") + '"}')
        cli_out = tmp_path / "fromcli"
        rc = cli.main(["--input", str(ind), "--output", str(cli_out), "--config", str(cfg)])
        assert rc == 0
        assert (cli_out / "c.pdf").is_file()
        assert not (tmp_path / "fromconfig" / "c.pdf").exists()

    def test_main_missing_config_file_fails(self, tmp_path):
        rc = cli.main(["--config", str(tmp_path / "nope.json")])
        assert rc == 1

    def test_main_invalid_config_json_fails(self, tmp_path):
        cfg = tmp_path / "bad.json"
        cfg.write_text("{ not json")
        rc = cli.main(["--config", str(cfg)])
        assert rc == 1

    def test_version_flag_exits(self):
        with pytest.raises(SystemExit) as exc:
            cli.main(["--version"])
        assert exc.value.code == 0
