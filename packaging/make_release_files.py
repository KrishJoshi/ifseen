"""Generate the Homebrew formula, Scoop manifest and release notes from a SHA256SUMS file.

    python packaging/make_release_files.py --version 0.1.0 --sums dist/SHA256SUMS --out dist

Writes ifseen.rb (for github.com/KrishJoshi/homebrew-tap, Formula/ifseen.rb), ifseen.json
(for github.com/KrishJoshi/scoop-bucket, bucket/ifseen.json) and release-notes.md.
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from string import Template

TEMPLATES = Path(__file__).resolve().parent / "templates"
REPO = "KrishJoshi/ifseen"
# archive used by each package manager, keyed by template placeholder
ARCHIVES = {
    "sha_macos_arm64": "ifseen-{v}-macos-arm64.tar.gz",
    "sha_macos_x86_64": "ifseen-{v}-macos-x86_64.tar.gz",
    "sha_linux_arm64": "ifseen-{v}-linux-arm64.tar.gz",
    "sha_linux_x86_64": "ifseen-{v}-linux-x86_64.tar.gz",
    "sha_windows_x86_64": "ifseen-{v}-windows-x86_64.zip",
}
SUMS_LINE = re.compile(r"^([0-9a-fA-F]{64})\s+\*?(\S+)\s*$")


def read_sums(path: Path) -> dict[str, str]:
    sums = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = SUMS_LINE.match(line)
        if match:
            sums[match.group(2)] = match.group(1).lower()
    return sums


def render(version: str, sums: dict[str, str]) -> dict[str, str]:
    values = {"version": version, "repo": REPO}
    values["base_url"] = f"https://github.com/{REPO}/releases/download/v{version}"
    missing = []
    for key, pattern in ARCHIVES.items():
        name = pattern.format(v=version)
        if name in sums:
            values[key] = sums[name]
        else:
            missing.append(name)
    if missing:
        raise SystemExit(f"SHA256SUMS is missing: {', '.join(missing)}")
    out = {}
    for template, target in (
        ("ifseen.rb.tmpl", "ifseen.rb"),
        ("ifseen.json.tmpl", "ifseen.json"),
        ("release-notes.md.tmpl", "release-notes.md"),
    ):
        text = (TEMPLATES / template).read_text(encoding="utf-8")
        out[target] = Template(text).substitute(values)
    json.loads(out["ifseen.json"])  # fail loudly on a broken manifest
    return out


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--version", required=True)
    p.add_argument("--sums", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, text in render(args.version.removeprefix("v"), read_sums(args.sums)).items():
        (args.out / name).write_text(text, encoding="utf-8")
        print(args.out / name)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
