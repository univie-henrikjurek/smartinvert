"""Open the file manager at the tool's output (ADR 0011, D3).

``reveal_output()`` lets a beginner find the result without navigating by
hand — it opens the platform file manager at the output file (single-file
run, file *marked*) or at the output folder (batch run):

* Windows: ``explorer /select,"<file>"`` (file marked) /
  ``explorer "<folder>"``.
* macOS:   ``open -R <file>`` (file marked) / ``open <folder>``.
* Linux:   ``xdg-open "<folder>"`` — the file's *parent folder*; ``xdg-open``
  has no standard way to mark a single file (ADR 0011, "Bekannte
  Einschränkungen" #1).

The opener is started non-blocking (``subprocess.Popen``).  A missing
opener *binary* (typical on headless systems) produces a log warning and
``False`` — the tool itself never crashes because of it.  (If the opener
binary exists but no desktop session is running, ``Popen`` succeeds and
the file manager simply does not appear — nothing to warn about.)
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


def reveal_argv(target: "str | Path") -> Optional[Tuple[str, List[str]]]:
    """Build the platform-specific opener command for *target*.

    Pure function (no process is spawned) so the platform logic is
    testable without a file manager.  Returns ``(executable, args)`` or
    ``None`` on platforms without a known opener.
    """
    target = Path(target).expanduser().resolve()
    if sys.platform == "win32":
        if target.is_dir():
            return ("explorer", [str(target)])
        # The double quotes are part of the argument on purpose: explorer
        # requires /select,"<path>" (quoting matters for paths with spaces).
        # Windows paths containing quote characters break this (documented
        # pathological case, ADR 0011 "Bekannte Einschränkungen" #2).
        return ("explorer", [f'/select,"{target}"'])
    if sys.platform == "darwin":
        if target.is_dir():
            return ("open", [str(target)])
        return ("open", ["-R", str(target)])
    if sys.platform.startswith("linux"):
        folder = target if target.is_dir() else target.parent
        return ("xdg-open", [str(folder)])
    return None


def reveal_output(target: "str | Path") -> bool:
    """Open the file manager at *target* (non-blocking).

    Returns ``True`` when the opener process was started.  A missing
    opener binary produces a warning and ``False`` — never an exception
    (ADR 0011, D3).
    """
    cmd = reveal_argv(target)
    if cmd is None:
        logger.warning("no file manager opener available on this platform")
        return False
    executable, args = cmd
    try:
        subprocess.Popen(
            [executable, *args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except OSError as e:
        logger.warning("could not open the file manager: %s", e)
        return False
