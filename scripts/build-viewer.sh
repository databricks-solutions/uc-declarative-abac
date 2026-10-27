#!/usr/bin/env bash
# Build the ABAC Policy Explorer app artifact into .build/ (bundle artifact step).
#
# The artifact holds the uc_abac and abac_viewer packages as source, plus a
# requirements.txt of their third-party dependencies pinned from uv.lock. Databricks
# Apps replaces the source files on every deploy, but only reinstalls requirements
# when requirements.txt changes, so shipping the code as source (rather than a wheel
# whose name and version don't change between builds) keeps each deploy current.
#
# apx builds the UI into src/abac_viewer/__dist__. Its dependency installs can
# rewrite the lockfiles, package.json, and _metadata.py with the locally configured
# package registry, so those are restored afterwards.
set -euo pipefail
cd "$(dirname "$0")/.."

saved="$(mktemp -d)"
tracked=(package.json bun.lock uv.lock src/abac_viewer/_metadata.py)
tar -cf "$saved/tracked.tar" "${tracked[@]}"
trap 'tar -xf "$saved/tracked.tar" && rm -rf "$saved"' EXIT

UV_FROZEN=1 apx frontend build

rm -rf .build
mkdir -p .build
rsync -a --exclude __pycache__ --exclude ui/ src/uc_abac src/abac_viewer .build/

version="$(sed -n 's/^version = "\(.*\)"$/\1/p' pyproject.toml | head -1)"
commit="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
printf 'version = "%s+g%s"\n' "$version" "$commit" > .build/abac_viewer/_version.py

uv export --frozen --no-hashes --no-dev --extra viewer --no-emit-project \
  --no-header --no-annotate > .build/requirements.txt

echo "build-viewer: $(find .build -name '*.py' | wc -l | tr -d ' ') modules," \
  "$(wc -l < .build/requirements.txt | tr -d ' ') requirements, version ${version}+g${commit}"
