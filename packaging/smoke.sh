#!/usr/bin/env bash
# Smoke-test a built ifseen binary without any API keys.
#   packaging/smoke.sh ./dist/ifseen [image]
# Runs from Git Bash on Windows too. Fails on the first broken check.
set -euo pipefail

bin="${1:?usage: smoke.sh <ifseen binary> [image]}"
image="${2:-js/test/fixtures/red.jpg}"

# No keys, no matter what the runner has set.
unset GEMINI_API_KEY GOOGLE_API_KEY TYPESAFE_API_KEY AZURE_DECISION_ENDPOINT AZURE_DECISION_KEY OPENAI_API_KEY

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

step() { printf '\n== %s\n' "$*"; }

step "--version"
out="$("$bin" --version)"
echo "$out"
case "$out" in "ifseen "*) ;; *) echo "unexpected --version output" >&2; exit 1 ;; esac

step "recipes (bundled YAML data)"
"$bin" recipes | tee "$tmp"/recipes.txt
grep -q doorbell "$tmp"/recipes.txt

step "doctor (no keys)"
"$bin" doctor | tee "$tmp"/doctor.txt
# Bundled extras must be in the binary (doctor prints a pip hint for missing ones).
for label in "screen" "camera/video" " mic"; do
    if grep -E "$label" "$tmp"/doctor.txt | grep -q "pip install"; then
        echo "${label# } is missing from this binary" >&2
        exit 1
    fi
done

step "OpenCV loads (a missing camera, not a missing module)"
set +e
"$bin" "x" --camera 99 --dry-run --max-ticks 1 --plain >"$tmp"/camera.txt 2>&1
set -e
cat "$tmp"/camera.txt
if grep -qiE "pip install|opencv-python-headless|No module" "$tmp"/camera.txt; then
    echo "OpenCV failed to load in this binary" >&2
    exit 1
fi
grep -qi "camera" "$tmp"/camera.txt

step "dry-run one-liner"
"$bin" "the image is mostly red" --file "$image" --dry-run --max-ticks 2 --plain

step "test <recipe> with the mock provider"
out="$("$bin" test doorbell --image "$image" --provider mock --json)"
echo "$out"
case "$out" in *'"probs"'*) ;; *) echo "no probabilities in test output" >&2; exit 1 ;; esac

printf '\nsmoke test passed: %s\n' "$bin"
