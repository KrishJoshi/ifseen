"""PyInstaller entry point for the standalone `ifseen` binary (see packaging/ifseen.spec)."""

import sys

from ifseen.cli import main

if __name__ == "__main__":
    sys.exit(main())
