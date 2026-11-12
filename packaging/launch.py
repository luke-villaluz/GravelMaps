"""Entry point of the packaged Mac app (see GravelMaps.spec): opens the app window."""
import sys

from gravelmaps import paths  # noqa: F401  (first: points numba's cache out of the read-only bundle)
from gravelmaps.__main__ import main

if __name__ == "__main__":
    if len(sys.argv) == 1:  # opened from the Dock or Finder
        sys.argv.append("desktop")
    main()
