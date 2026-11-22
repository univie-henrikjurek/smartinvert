"""Read-only PDF diagnostics for user-facing error messages (ADR 0011, D2).

``diagnose_pdf()`` inspects a PDF file WITHOUT modifying it and returns a
short, user-facing explanation when the file cannot be processed by the
usual pipeline — or ``None`` when the file looks fine:

* password-protected (user password) PDFs,
* files that are not valid PDFs (damaged / not a PDF at all),
* PDFs without pages,
* inputs that do not exist at all.

The same message is used by the CLI (logged) and the GUI (pre-check dialog
and batch failure list), following the project convention of English
message bodies (ADR 0011, D2).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .processing import fitz

#: "cannot read" message, used both when the file cannot be opened at all
#: and when it opens but fails while being inspected.
_CANNOT_READ = (
    "the file is not a valid PDF (it may be damaged or not a PDF at all)"
)


def diagnose_pdf(path: "str | Path") -> Optional[str]:
    """Return a user-facing problem description for *path*, or ``None``.

    The file is opened read-only and never modified.  A file that fitz
    cannot open at all is reported as "not a valid PDF"; a file that opens
    but is password-protected or has no pages gets a specific message.
    Owner-password-only encryption (no user password) keeps the file
    usable and is therefore NOT reported.

    This function never raises: any unexpected inspection problem is
    reported like the open-failure case (the GUI pre-check runs in the
    main thread, where an exception would crash the app).
    """
    p = Path(path)
    name = p.name
    if not p.is_file():
        return f"input PDF not found: {p}"
    try:
        doc = fitz.open(str(p))
    except Exception:
        return f"cannot read '{name}': {_CANNOT_READ}"
    try:
        if doc.needs_pass:
            return (
                f"'{name}' is password-protected (encrypted). Remove the "
                "password first, then run again."
            )
        if doc.page_count == 0:
            return f"'{name}' contains no pages"
        return None
    except Exception:
        # A file that opens but fails while being inspected is as good as
        # unreadable for us — report it like the open-failure case above.
        return f"cannot read '{name}': {_CANNOT_READ}"
    finally:
        try:
            doc.close()
        except Exception:
            pass
