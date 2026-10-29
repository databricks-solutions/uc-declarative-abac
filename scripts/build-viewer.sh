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
#
# Usage: build-viewer.sh [<target-schema> <repo-slug> <repo-ref> <config-path-prefix>]
#
# The bundle passes its variables, and the artifact gets an app.yml with the app's
# command and settings, so a redeploy from the app's Deploy button (which deploys the
# uploaded source alone) starts the app the same way as `databricks bundle run`.
# Without arguments (a local build), no app.yml is written.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ $# -ne 0 && $# -ne 4 ]]; then
  echo "usage: $0 [<target-schema> <repo-slug> <repo-ref> <config-path-prefix>]" >&2
  exit 2
fi

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

# A YAML double-quoted string, escaping backslashes and double quotes.
yaml_string() {
  local value="${1//\\/\\\\}"
  printf '"%s"' "${value//\"/\\\"}"
}

if [[ $# -eq 4 ]]; then
  cat > .build/app.yml <<APP_YML
command:
  - sh
  - -c
  - uvicorn abac_viewer.backend.app:app --host 0.0.0.0 --port \${DATABRICKS_APP_PORT:-8000} --workers 1
env:
  - name: ABAC_VIEWER_TARGET_SCHEMA
    value: $(yaml_string "$1")
  - name: ABAC_VIEWER_WAREHOUSE_ID
    valueFrom: sql-warehouse
  - name: ABAC_VIEWER_REPO_SLUG
    value: $(yaml_string "$2")
  - name: ABAC_VIEWER_REPO_REF
    value: $(yaml_string "$3")
  - name: ABAC_VIEWER_CONFIG_PATH_PREFIX
    value: $(yaml_string "$4")
APP_YML
fi

echo "build-viewer: $(find .build -name '*.py' | wc -l | tr -d ' ') modules," \
  "$(wc -l < .build/requirements.txt | tr -d ' ') requirements, version ${version}+g${commit}"
