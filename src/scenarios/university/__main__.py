"""Module execution entrypoint for `python -m scenarios.university`."""

from __future__ import annotations

import sys

try:
    from .cli import main
except ImportError:
    from scenarios.university.cli import main  # type: ignore

if __name__ == "__main__":
    sys.exit(main())
