"""Open the file manager at the tool's output (ADR 0011, D3).

``reveal_output()`` lets a beginner find the result without navigating by
hand — it opens the platform file manager at the output file (single-file
run, file *marked*) or at the output folder (batch run):

* Windows: ``explorer /select,"<file>"`` (file marked) /
  ``explorer "<folder>"``.  The command is passed to ``Popen`` as a single
  **command-line string** — see the note in :func:`reveal_command` why an
  argv *list* breaks ``/select`` on Windows.
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
from typing import List, Optional, Union

logger = logging.getLogger(__name__)

#: Exactly what is handed to ``subprocess.Popen``: a command-line *string*
#: on Windows (passed verbatim to ``CreateProcess``) or an argv *list* on
#: macOS/Linux (a list is required there — a string would not be split).
Command = Union[str, List[str]]


def reveal_command(target: "str | Path") -> Optional[Command]:
    """Build exactly what to pass to ``subprocess.Popen`` for *target*.

    Pure function (no process is spawned) so the platform logic is
    testable without a file manager:

    * Windows + file    → ``'explorer /select,"<file>"'``  (file marked)
    * Windows + folder  → ``'explorer "<folder>"'``
    * macOS + file      → ``['open', '-R', '<file>']``    (file marked)
    * macOS + folder    → ``['open', '<folder>']``
    * Linux             → ``['xdg-open', '<folder>']``    (parent folder)
    * unknown platform  → ``None``

    The Windows cases return a **string**, not a list: ``Popen`` passes a
    string to ``CreateProcess`` verbatim, whereas a list goes through
    ``subprocess.list2cmdline``, which would wrap the
    ``/select,"<path>"`` argument in extra quotes and backslash-escape its
    inner quotes — a command line explorer cannot parse, so it opens
    "This PC" instead of selecting the file (regression, found on
    Windows; ADR 0011, D3).  On macOS/Linux the arguments contain no
    embedded quotes, so a list (and thus ``list2cmdline``-safe quoting)
    is fine.

    Windows paths containing quote characters remain a documented
    pathological case (ADR 0011, "Bekannte Einschränkungen" #2).
    """
    target = Path(target).expanduser().resolve()
    if sys.platform == "win32":
        if target.is_dir():
            return f'explorer "{target}"'
        return f'explorer /select,"{target}"'
    if sys.platform == "darwin":
        if target.is_dir():
            return ["open", str(target)]
        return ["open", "-R", str(target)]
    if sys.platform.startswith("linux"):
        folder = target if target.is_dir() else target.parent
        return ["xdg-open", str(folder)]
    return None


def reveal_output(target: "str | Path") -> bool:
    """Open the file manager at *target* (non-blocking).

    Returns ``True`` when the opener process was started.  A missing
    opener binary produces a warning and ``False`` — never an exception
    (ADR 0011, D3).
    """
    cmd = reveal_command(target)
    if cmd is None:
        logger.warning("no file manager opener available on this platform")
        return False
    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except OSError as e:
        logger.warning("could not open the file manager: %s", e)
        return False
