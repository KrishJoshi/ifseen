"""Check every place that carries the release version agrees, and print it.

    python packaging/check_versions.py            # all files must match
    python packaging/check_versions.py v0.1.0     # ...and match this tag

Standard library only (runs on a bare CI runner).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent


def _regex(path: str, pattern: str) -> str:
    match = re.search(pattern, (ROOT / path).read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise SystemExit(f"no version found in {path}")
    return match.group(1)


def versions() -> dict[str, str]:
    with open(ROOT / "pyproject.toml", "rb") as f:
        pyproject = tomllib.load(f)["project"]["version"]
    return {
        "pyproject.toml": pyproject,
        "src/ifseen/constants.py": _regex("src/ifseen/constants.py", r'^VERSION = "([^"]+)"'),
        "js/package.json": json.loads((ROOT / "js/package.json").read_text("utf-8"))["version"],
        "homeassistant/ifseen/config.yaml": _regex(
            "homeassistant/ifseen/config.yaml", r'^version:\s*"?([^"\s]+)"?\s*$'
        ),
    }


def main(argv: list[str]) -> int:
    found = versions()
    if argv:
        found["git tag"] = argv[0].removeprefix("refs/tags/").removeprefix("v")
    for where, version in found.items():
        print(f"{version:>12}  {where}", file=sys.stderr)
    if len(set(found.values())) != 1:
        print("error: versions don't match", file=sys.stderr)
        return 1
    print(found["pyproject.toml"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
