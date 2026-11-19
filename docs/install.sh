#!/bin/sh
# ifseen installer for macOS and Linux.
#
#   curl -fsSL https://krishj.com/ifseen/install.sh | sh
#
# Downloads the standalone binary for this machine from the latest GitHub release, checks it
# against SHA256SUMS and installs it to ~/.local/bin. Never uses sudo.
#
#   IFSEEN_VERSION=0.1.0        install a specific version (default: latest release)
#   IFSEEN_INSTALL_DIR=~/bin    install somewhere else (default: ~/.local/bin)
set -eu

REPO="KrishJoshi/ifseen"
INSTALL_DIR="${IFSEEN_INSTALL_DIR:-${HOME}/.local/bin}"
VERSION="${IFSEEN_VERSION:-}"

say() { printf '%s\n' "$*"; }
die() {
    printf 'ifseen install: %s\n' "$*" >&2
    exit 1
}

# fetch URL DEST
fetch() {
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL --retry 3 --proto '=https' --tlsv1.2 -o "$2" "$1"
    elif command -v wget >/dev/null 2>&1; then
        wget -q --https-only -O "$2" "$1"
    else
        die "needs curl or wget"
    fi
}

sha256() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    else
        die "needs sha256sum or shasum to verify the download"
    fi
}

# -- platform ---------------------------------------------------------------------------------
os="$(uname -s)"
arch="$(uname -m)"
case "$os" in
    Darwin) os=macos ;;
    Linux) os=linux ;;
    MINGW* | MSYS* | CYGWIN*) die "on Windows, run in PowerShell: irm https://krishj.com/ifseen/install.ps1 | iex" ;;
    *) die "no prebuilt binary for $os - install with pipx instead: pipx install \"ifseen[all]\"" ;;
esac
case "$arch" in
    x86_64 | amd64) arch=x86_64 ;;
    arm64 | aarch64) arch=arm64 ;;
    *) die "no prebuilt binary for $arch - install with pipx instead: pipx install \"ifseen[all]\"" ;;
esac
# A shell running under Rosetta reports x86_64 on Apple Silicon: use the native build.
if [ "$os" = macos ] && [ "$arch" = x86_64 ] && [ "$(sysctl -n sysctl.proc_translated 2>/dev/null || echo 0)" = 1 ]; then
    arch=arm64
fi
if [ "$os" = linux ] && ldd --version 2>&1 | grep -qi musl; then
    die "the Linux binaries need glibc (Alpine/musl isn't supported) - use pipx or the Docker image instead"
fi

# -- version ----------------------------------------------------------------------------------
tmp="$(mktemp -d 2>/dev/null || mktemp -d -t ifseen)"
trap 'rm -rf "$tmp"' EXIT INT TERM

if [ -z "$VERSION" ]; then
    if ! fetch "https://api.github.com/repos/${REPO}/releases/latest" "$tmp/latest.json" 2>/dev/null; then
        die "couldn't find a published ifseen release (none yet, or the GitHub API rate limit was hit).
See https://github.com/${REPO}/releases, set IFSEEN_VERSION=x.y.z, or install with: pipx install \"ifseen[all]\""
    fi
    VERSION="$(sed -n 's/.*"tag_name":[[:space:]]*"\([^"]*\)".*/\1/p' "$tmp/latest.json" | head -n 1)"
    [ -n "$VERSION" ] || die "couldn't read the latest release version from the GitHub API"
fi
VERSION="${VERSION#v}"

asset="ifseen-${VERSION}-${os}-${arch}"
base="https://github.com/${REPO}/releases/download/v${VERSION}"

# -- download and verify ----------------------------------------------------------------------
say "Downloading ifseen ${VERSION} for ${os} ${arch}..."
fetch "${base}/SHA256SUMS" "$tmp/SHA256SUMS" \
    || die "release v${VERSION} not found at https://github.com/${REPO}/releases (or it has no SHA256SUMS)"
fetch "${base}/${asset}" "$tmp/ifseen" \
    || die "release v${VERSION} has no ${asset} binary - see https://github.com/${REPO}/releases"

expected="$(awk -v f="$asset" '$2 == f || $2 == "*" f {print $1; exit}' "$tmp/SHA256SUMS")"
[ -n "$expected" ] || die "${asset} is not listed in SHA256SUMS"
actual="$(sha256 "$tmp/ifseen")"
if [ "$(printf '%s' "$expected" | tr 'A-F' 'a-f')" != "$actual" ]; then
    die "checksum mismatch for ${asset} (expected ${expected}, got ${actual}) - not installing"
fi

# -- install ----------------------------------------------------------------------------------
mkdir -p "$INSTALL_DIR" || die "can't create ${INSTALL_DIR} (set IFSEEN_INSTALL_DIR to a folder you own)"
chmod +x "$tmp/ifseen"
if [ "$os" = macos ]; then
    # Unsigned binary: drop the quarantine flag so Gatekeeper doesn't block the first run.
    xattr -d com.apple.quarantine "$tmp/ifseen" 2>/dev/null || true
fi
mv -f "$tmp/ifseen" "$INSTALL_DIR/ifseen" || die "can't write to ${INSTALL_DIR} (set IFSEEN_INSTALL_DIR to a folder you own)"

say "Installed $("$INSTALL_DIR/ifseen" --version) to ${INSTALL_DIR}/ifseen"

case ":${PATH}:" in
    *":${INSTALL_DIR}:"*) ;;
    *)
        case "${SHELL:-}" in
            */zsh) rc="$HOME/.zshrc" ;;
            */bash) rc="$HOME/.bashrc" ;;
            */fish) rc="$HOME/.config/fish/config.fish" ;;
            *) rc="your shell's startup file" ;;
        esac
        say ""
        say "${INSTALL_DIR} is not on your PATH. Add it (e.g. in ${rc}):"
        say "  export PATH=\"${INSTALL_DIR}:\$PATH\""
        ;;
esac

if [ "$os" = linux ] && ! ldconfig -p 2>/dev/null | grep -q libportaudio; then
    say ""
    say "For the microphone, install PortAudio: sudo apt install libportaudio2 (or your distro's equivalent)."
fi

say ""
say "Next: export GEMINI_API_KEY=...   (free at https://aistudio.google.com/apikey)"
say "      ifseen doctor"
