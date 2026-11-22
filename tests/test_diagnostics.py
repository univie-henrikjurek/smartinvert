"""Tests for ``smartboard_invert.diagnostics`` (ADR 0011, D2): read-only
file-level diagnosis of PDF inputs for clear, user-facing error messages.

The same message is shown by the CLI (on job failure) and the GUI (pre-check
dialog + batch failure list).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from smartboard_invert.diagnostics import diagnose_pdf

import synth


class TestDiagnosePdf:
    def test_valid_pdf_returns_none(self, tmp_path):
        p = tmp_path / "valid.pdf"
        synth.make_pdf(p, [{"kind": "blank"}])
        assert diagnose_pdf(p) is None

    def test_encrypted_pdf_reports_password(self, tmp_path):
        p = synth.make_encrypted_pdf(tmp_path / "secret.pdf")
        msg = diagnose_pdf(p)
        assert msg is not None
        assert "password-protected" in msg
        assert "secret.pdf" in msg
        assert "remove the password" in msg.lower()

    def test_owner_password_only_is_usable_not_reported(self, tmp_path):
        """Owner-password-only encryption (no user password) keeps the file
        usable without interaction and must NOT be reported (ADR 0011, D2)."""
        p = synth.make_encrypted_pdf(tmp_path / "owner.pdf", user_pw="")
        assert diagnose_pdf(p) is None

    def test_corrupt_file_reports_not_a_valid_pdf(self, tmp_path):
        p = tmp_path / "broken.pdf"
        p.write_bytes(b"%PDF-1.4 this is not really a pdf")
        msg = diagnose_pdf(p)
        assert msg is not None
        assert "not a valid PDF" in msg
        assert "broken.pdf" in msg

    def test_completely_non_pdf_bytes_reported(self, tmp_path):
        p = tmp_path / "nonsense.bin"
        p.write_bytes(b"\x00\x01\x02 not a pdf at all")
        msg = diagnose_pdf(p)
        assert msg is not None
        assert "not a valid PDF" in msg

    def test_zero_page_pdf_reports_no_pages(self, tmp_path):
        p = synth.make_zero_page_pdf(tmp_path / "empty.pdf")
        msg = diagnose_pdf(p)
        assert msg is not None
        assert "contains no pages" in msg

    def test_missing_file_reports_not_found(self, tmp_path):
        msg = diagnose_pdf(tmp_path / "missing.pdf")
        assert msg is not None
        assert "not found" in msg

    def test_accepts_str_paths(self, tmp_path):
        p = tmp_path / "valid.pdf"
        synth.make_pdf(p, [{"kind": "blank"}])
        assert diagnose_pdf(str(p)) is None

    def test_never_modifies_the_input(self, tmp_path):
        p = synth.make_encrypted_pdf(tmp_path / "secret.pdf")
        before = hashlib.sha256(p.read_bytes()).hexdigest()
        assert diagnose_pdf(p) is not None  # exercise the diagnosis path
        assert hashlib.sha256(p.read_bytes()).hexdigest() == before
