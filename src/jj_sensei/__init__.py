"""jj-sensei tooling for Jujutsu repositories."""

import sys

__version__ = "0.1.0"


def use_utf8_output() -> None:
    """Emit UTF-8 regardless of the caller's locale.

    The helpers draw rules and status marks with non-ASCII characters. Under a
    C/POSIX locale Python picks an ASCII stdout and printing a summary raises
    UnicodeEncodeError, so a working resolution reports itself as a crash.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
