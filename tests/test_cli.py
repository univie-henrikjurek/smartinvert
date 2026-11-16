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
        from smartboard_invert import __version__

        result = run_cli("--version")
        assert result.returncode == 0
        # track the package version instead of a hardcoded value
        assert __version__ in result.stdout

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

    def test_main_config_bad_type_fails(self, tmp_path):
        """A config value with a wrong type must produce a clean error, not
        an unhandled exception (NFR-5)."""
        cfg = tmp_path / "badtype.json"
        cfg.write_text('{"dpi": "not-a-number", "input": 42}')
        rc = cli.main(["--config", str(cfg)])
        assert rc == 1

    def test_main_config_unknown_key_ignored(self, tmp_path):
        ind = tmp_path / "inputs"
        ind.mkdir()
        outd = tmp_path / "outputs"
        synth.make_pdf(ind / "u.pdf", [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)}])
        cfg = tmp_path / "u.json"
        cfg.write_text('{"some_future_option": true}')
        rc = cli.main(["--input", str(ind), "--output", str(outd), "--config", str(cfg)])
        assert rc == 0
        assert (outd / "u.pdf").is_file()

    def test_main_prints_ok_lines_on_stdout(self, tmp_path, capsys):
        ind = tmp_path / "inputs"
        ind.mkdir()
        outd = tmp_path / "outputs"
        synth.make_pdf(ind / "s.pdf", [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)}])
        rc = cli.main(["--input", str(ind), "--output", str(outd)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "OK" in out and "s.pdf" in out

    def test_version_flag_exits(self):
        with pytest.raises(SystemExit) as exc:
            cli.main(["--version"])
        assert exc.value.code == 0


class TestCropCli:
    """--crop / --no-crop / config 'crop' (ADR 0003, D4; ADR 0006): default
    on since v0.7.1, CLI flags take precedence over the config file."""

    BOARD = (150, 150, 300, 550)  # x, y, w, h in pt

    def _board_pdf(self, tmp_path: Path) -> Path:
        src = tmp_path / "board.pdf"
        synth.make_pdf(src, [{"kind": "image", "rect": self.BOARD, "bg": (0, 0, 0)}])
        return src

    def _first_page_rect(self, pdf: Path):
        from smartboard_invert.processing import fitz

        doc = fitz.open(str(pdf))
        try:
            return doc[0].rect
        finally:
            doc.close()

    def test_crop_flag_crops_to_board_rect(self, tmp_path):
        src = self._board_pdf(tmp_path)
        outd = tmp_path / "out"
        result = run_cli("--input", str(src), "--output", str(outd), "--crop")
        assert result.returncode == 0, result.stderr + result.stdout
        rect = self._first_page_rect(outd / "board.pdf")
        assert rect.width == pytest.approx(self.BOARD[2], abs=0.5)
        assert rect.height == pytest.approx(self.BOARD[3], abs=0.5)

    def test_no_crop_flag_keeps_full_page(self, tmp_path):
        src = self._board_pdf(tmp_path)
        outd = tmp_path / "out"
        result = run_cli("--input", str(src), "--output", str(outd), "--no-crop")
        assert result.returncode == 0, result.stderr + result.stdout
        rect = self._first_page_rect(outd / "board.pdf")
        assert rect.width == pytest.approx(595, abs=0.5)
        assert rect.height == pytest.approx(842, abs=0.5)

    def test_config_crop_true_crops(self, tmp_path):
        src = self._board_pdf(tmp_path)
        outd = tmp_path / "out"
        cfg = tmp_path / "c.json"
        cfg.write_text('{"crop": true}')
        result = run_cli("--input", str(src), "--output", str(outd), "--config", str(cfg))
        assert result.returncode == 0, result.stderr + result.stdout
        rect = self._first_page_rect(outd / "board.pdf")
        assert rect.width == pytest.approx(self.BOARD[2], abs=0.5)
        assert rect.height == pytest.approx(self.BOARD[3], abs=0.5)

    def test_cli_crop_beats_config_no_crop(self, tmp_path):
        """An explicit --crop flag beats {"crop": false} in the config."""
        src = self._board_pdf(tmp_path)
        outd = tmp_path / "out"
        cfg = tmp_path / "c.json"
        cfg.write_text('{"crop": false}')
        result = run_cli("--input", str(src), "--output", str(outd), "--config", str(cfg), "--crop")
        assert result.returncode == 0, result.stderr + result.stdout
        rect = self._first_page_rect(outd / "board.pdf")
        assert rect.width == pytest.approx(self.BOARD[2], abs=0.5)
        assert rect.height == pytest.approx(self.BOARD[3], abs=0.5)

    def test_default_run_crops_to_board_rect(self, tmp_path):
        """ADR 0006: without any crop flag the default run crops to the
        board rect."""
        src = self._board_pdf(tmp_path)
        outd = tmp_path / "out"
        result = run_cli("--input", str(src), "--output", str(outd))
        assert result.returncode == 0, result.stderr + result.stdout
        rect = self._first_page_rect(outd / "board.pdf")
        assert rect.width == pytest.approx(self.BOARD[2], abs=0.5)
        assert rect.height == pytest.approx(self.BOARD[3], abs=0.5)

    def test_resolve_options_default_crop_true(self):
        args = cli.build_parser().parse_args([])
        opts = cli.resolve_options(args, {})
        assert opts["crop"] is True

class TestPhase3Parsers:
    """Phase 3 (P3-D-2 / ADR 0002 D3): the central parsers for
    --bg-target / --keep-colors (single choke point for flag and config)."""

    @pytest.mark.parametrize("text", ["complement", "COMPLEMENT", "  Complement  "])
    def test_parse_bg_target_complement(self, text):
        assert cli.parse_bg_target(text) is None

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("255,255,255", (255, 255, 255)),
            (" 255 , 255 , 255 ", (255, 255, 255)),
            ("0,0,0", (0, 0, 0)),
        ],
    )
    def test_parse_bg_target_rgb(self, text, expected):
        assert cli.parse_bg_target(text) == expected

    @pytest.mark.parametrize(
        "text",
        ["bogus", "255,255", "255,255,256", "-1,0,0", "", "255;255;255", "²,0,0", "②,3,4"],
    )
    def test_parse_bg_target_invalid(self, text):
        # includes Unicode digits ("²", "②"): str.isdigit() is True for them
        # but they must fail cleanly, not with a raw ValueError traceback
        with pytest.raises(cli.SmartboardError):
            cli.parse_bg_target(text)

    @pytest.mark.parametrize("text", ["none", "NONE"])
    def test_parse_keep_colors_none(self, text):
        assert cli.parse_keep_colors(text) == frozenset()

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("red,green", frozenset({"red", "green"})),
            ("RED, Green", frozenset({"red", "green"})),
            ("blue, yellow", frozenset({"blue", "yellow"})),
        ],
    )
    def test_parse_keep_colors_valid(self, text, expected):
        assert cli.parse_keep_colors(text) == expected

    @pytest.mark.parametrize("text", ["magenta", "red,magenta"])
    def test_parse_keep_colors_unknown(self, text):
        with pytest.raises(cli.SmartboardError, match="unknown color"):
            cli.parse_keep_colors(text)

    def test_parse_keep_colors_empty_entries_ignored(self):
        """Tested as implemented: empty entries in the comma list are
        dropped, so "red,,green" parses like "red,green"; an entirely empty
        list parses to the empty set (== "none")."""
        assert cli.parse_keep_colors("red,,green") == frozenset({"red", "green"})
        assert cli.parse_keep_colors("red,") == frozenset({"red"})
        assert cli.parse_keep_colors(",") == frozenset()
        assert cli.parse_keep_colors("") == frozenset()

    def test_real_defaults_parse_to_complement_and_red_green(self):
        """P3-D-1: the new (breaking) real defaults are complement +
        red,green; exact v0.4.1 stays reproducible via complement + none."""
        assert cli.parse_bg_target(cli.REAL_DEFAULTS["bg_target"]) is None
        assert cli.parse_keep_colors(cli.REAL_DEFAULTS["keep_colors"]) == frozenset(
            {"red", "green"}
        )


class TestPhase3CliFlags:
    """Phase 3 (P3-FR-9/10): --bg-target / --keep-colors through the full CLI."""

    def test_bg_target_and_keep_colors_run_end_to_end(self, tmp_path):
        src = tmp_path / "board.pdf"
        synth.make_pdf(src, [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)}])
        outd = tmp_path / "outputs"
        result = run_cli(
            "--input", str(src),
            "--output", str(outd),
            "--bg-target", "255,255,255",
            "--keep-colors", "red",
        )
        assert result.returncode == 0, result.stderr + result.stdout
        assert (outd / "board.pdf").is_file()

    def test_bg_target_bogus_fails_with_error(self, tmp_path):
        src = tmp_path / "board.pdf"
        synth.make_pdf(src, [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)}])
        result = run_cli(
            "--input", str(src),
            "--output", str(tmp_path / "outputs"),
            "--bg-target", "bogus",
        )
        assert result.returncode == 1
        assert "[ERROR]" in result.stderr
        assert "bg-target" in result.stderr

    def test_keep_colors_bogus_fails_with_error(self, tmp_path, capsys):
        ind = tmp_path / "inputs"
        ind.mkdir()
        synth.make_pdf(ind / "b.pdf", [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)}])
        rc = cli.main(
            [
                "--input", str(ind),
                "--output", str(tmp_path / "out"),
                "--keep-colors", "magenta",
            ]
        )
        assert rc == 1
        err = capsys.readouterr().err
        assert "[ERROR]" in err
        assert "keep-colors" in err

    # --- Phase 3 options through the JSON config (P3-D-2) -----------------

    def test_config_file_new_keys_take_effect(self, tmp_path):
        """bg_target/keep_colors work via the JSON config file, not only
        via CLI flags."""
        src = tmp_path / "board.pdf"
        synth.make_pdf(src, [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)}])
        cfg = tmp_path / "c.json"
        cfg.write_text('{"bg_target": "255,255,255", "keep_colors": "red,green"}')
        outd = tmp_path / "outputs"
        result = run_cli(
            "--input", str(src), "--output", str(outd), "--config", str(cfg)
        )
        assert result.returncode == 0, result.stderr + result.stdout
        assert (outd / "board.pdf").is_file()

    def test_config_file_null_falls_back_to_real_defaults(self, tmp_path):
        """null = documented "fall back to default" semantics: complement +
        red,green."""
        src = tmp_path / "board.pdf"
        synth.make_pdf(src, [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)}])
        cfg = tmp_path / "c.json"
        cfg.write_text('{"bg_target": null, "keep_colors": null}')
        result = run_cli(
            "--input", str(src),
            "--output", str(tmp_path / "outputs"),
            "--config", str(cfg),
        )
        assert result.returncode == 0, result.stderr + result.stdout

    def test_config_file_invalid_new_key_fails_cleanly(self, tmp_path, capsys):
        """A bad bg_target in the config must produce the same clean error
        as a bad CLI flag (no traceback, NFR-5)."""
        ind = tmp_path / "inputs"
        ind.mkdir()
        synth.make_pdf(ind / "b.pdf", [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)}])
        cfg = tmp_path / "c.json"
        cfg.write_text('{"bg_target": "255,999,0"}')
        rc = cli.main(
            ["--input", str(ind), "--output", str(tmp_path / "out"), "--config", str(cfg)]
        )
        assert rc == 1
        assert "[ERROR]" in capsys.readouterr().err


class TestKeepHexParser:
    """Phase 3 (P3-FR-11 / ADR 0004 D1): parse_keep_hex – single choke point
    for the --keep-hex flag and the JSON config key."""

    def test_empty_is_off(self):
        assert cli.parse_keep_hex("") == ()
        assert cli.parse_keep_hex("   ") == ()

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            # the user's example: exact red, exact green, whole blue axis
            (
                "FF0000, 00FF00, 000001-0000FF",
                (
                    ((255, 0, 0), (255, 0, 0)),
                    ((0, 255, 0), (0, 255, 0)),
                    ((0, 0, 1), (0, 0, 255)),
                ),
            ),
            ("FF0000", (((255, 0, 0), (255, 0, 0)),)),
            ("#FF0000", (((255, 0, 0), (255, 0, 0)),)),
            ("ff0000", (((255, 0, 0), (255, 0, 0)),)),
            # 3-digit shorthand expands digit-wise
            ("F00", (((255, 0, 0), (255, 0, 0)),)),
            ("0F0", (((0, 255, 0), (0, 255, 0)),)),
            # range with reversed endpoints is normalised to ascending order
            ("0000FF-000001", (((0, 0, 1), (0, 0, 255)),)),
            ("#F00-0F0", (((0, 255, 0), (255, 0, 0)),)),
            # empty entries and whitespace are tolerated
            ("FF0000,,  ,00FF00", (
                ((255, 0, 0), (255, 0, 0)),
                ((0, 255, 0), (0, 255, 0)),
            )),
            ("  FF0000 , 00FF00  ", (
                ((255, 0, 0), (255, 0, 0)),
                ((0, 255, 0), (0, 255, 0)),
            )),
        ],
    )
    def test_valid(self, text, expected):
        assert cli.parse_keep_hex(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "zzz",           # not hex
            "FF000",         # 5 digits
            "1234567",       # 7 digits
            "FF0000-",       # dangling range dash
            "-FF0000",       # leading range dash
            "FF0000-00G0FF", # non-hex digit in range endpoint
            "FF0000-00FF00-00FF00",  # two dashes
            "FF 0000",       # inner space
            "#",             # bare prefix
            "-",             # bare dash
            "0x123456",      # 0x prefix is not allowed
            "\u0661F0000",   # Unicode digit (arabic-indic 1): no isdigit() trap
        ],
    )
    def test_invalid(self, text):
        with pytest.raises(cli.SmartboardError, match="keep-hex"):
            cli.parse_keep_hex(text)

    def test_real_default_is_empty(self):
        assert cli.REAL_DEFAULTS["keep_hex"] == ""
        assert cli.parse_keep_hex(cli.REAL_DEFAULTS["keep_hex"]) == ()

    def test_resolve_options_default_and_override(self):
        args = cli.build_parser().parse_args([])
        assert cli.resolve_options(args, {})["keep_hex"] == ""
        args = cli.build_parser().parse_args(["--keep-hex", "FF0000"])
        assert cli.resolve_options(args, {})["keep_hex"] == "FF0000"
        # config file value is picked up when the flag is absent
        args = cli.build_parser().parse_args([])
        assert cli.resolve_options(args, {"keep_hex": "00FF00"})["keep_hex"] == "00FF00"


class TestKeepHexCliFlags:
    """Phase 3 (P3-FR-11 / P3-D-3): --keep-hex through the full CLI and the
    JSON config file."""

    BOARD = (150, 150, 300, 550)  # x, y, w, h in pt

    def _board_pdf(self, tmp_path: Path) -> Path:
        src = tmp_path / "board.pdf"
        synth.make_pdf(src, [{"kind": "image", "rect": self.BOARD, "bg": (0, 0, 0)}])
        return src

    def test_keep_hex_flag_end_to_end(self, tmp_path):
        src = self._board_pdf(tmp_path)
        outd = tmp_path / "outputs"
        result = run_cli(
            "--input", str(src),
            "--output", str(outd),
            "--keep-hex", "FF0000, 00FF00, 000001-0000FF",
        )
        assert result.returncode == 0, result.stderr + result.stdout
        assert (outd / "board.pdf").is_file()

    def test_keep_hex_empty_flag_is_off(self, tmp_path):
        src = self._board_pdf(tmp_path)
        outd = tmp_path / "outputs"
        result = run_cli(
            "--input", str(src), "--output", str(outd), "--keep-hex", ""
        )
        assert result.returncode == 0, result.stderr + result.stdout
        assert (outd / "board.pdf").is_file()

    def test_keep_hex_bogus_fails_with_error(self, tmp_path, capsys):
        ind = tmp_path / "inputs"
        ind.mkdir()
        synth.make_pdf(ind / "b.pdf", [{"kind": "image", "rect": self.BOARD, "bg": (0, 0, 0)}])
        rc = cli.main(
            [
                "--input", str(ind),
                "--output", str(tmp_path / "out"),
                "--keep-hex", "zzz",
            ]
        )
        assert rc == 1
        err = capsys.readouterr().err
        assert "[ERROR]" in err
        assert "keep-hex" in err

    # --- --keep-hex through the JSON config (P3-D-3) -----------------------

    def test_config_file_keep_hex_takes_effect(self, tmp_path):
        src = self._board_pdf(tmp_path)
        cfg = tmp_path / "c.json"
        cfg.write_text('{"keep_hex": "000001-0000FF"}')
        outd = tmp_path / "outputs"
        result = run_cli(
            "--input", str(src), "--output", str(outd), "--config", str(cfg)
        )
        assert result.returncode == 0, result.stderr + result.stdout
        assert (outd / "board.pdf").is_file()

    def test_config_file_null_keep_hex_falls_back_to_default(self, tmp_path):
        src = self._board_pdf(tmp_path)
        cfg = tmp_path / "c.json"
        cfg.write_text('{"keep_hex": null}')
        outd = tmp_path / "outputs"
        result = run_cli(
            "--input", str(src), "--output", str(outd), "--config", str(cfg)
        )
        assert result.returncode == 0, result.stderr + result.stdout

    def test_cli_keep_hex_beats_config(self, tmp_path):
        """An explicit --keep-hex flag beats the (invalid) config value."""
        src = self._board_pdf(tmp_path)
        cfg = tmp_path / "c.json"
        cfg.write_text('{"keep_hex": "zzz"}')
        outd = tmp_path / "outputs"
        result = run_cli(
            "--input", str(src),
            "--output", str(outd),
            "--config", str(cfg),
            "--keep-hex", "FF0000",
        )
        assert result.returncode == 0, result.stderr + result.stdout
        assert (outd / "board.pdf").is_file()

    def test_config_file_invalid_keep_hex_fails_cleanly(self, tmp_path, capsys):
        """A bad keep_hex in the config must produce the same clean error as
        a bad CLI flag (no traceback, NFR-5)."""
        ind = tmp_path / "inputs"
        ind.mkdir()
        synth.make_pdf(ind / "b.pdf", [{"kind": "image", "rect": self.BOARD, "bg": (0, 0, 0)}])
        cfg = tmp_path / "c.json"
        cfg.write_text('{"keep_hex": "zzz"}')
        rc = cli.main(
            ["--input", str(ind), "--output", str(tmp_path / "out"), "--config", str(cfg)]
        )
        assert rc == 1
        assert "[ERROR]" in capsys.readouterr().err

    def test_config_file_keep_hex_bad_type_fails(self, tmp_path):
        cfg = tmp_path / "badtype.json"
        cfg.write_text('{"keep_hex": 42}')
        rc = cli.main(["--config", str(cfg)])
        assert rc == 1
