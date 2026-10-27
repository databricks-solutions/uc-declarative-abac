#!/usr/bin/env bash
# Deploy the ABAC Policy Explorer demo end to end, in order:
#
#   1. fixture bundle (jobs) and the demo service principals
#   2. uc-abac deploy of configs/ (dry run first): groups, tags, catalog, policies
#   3. seed data
#   4. out-of-band changes from drift.sql, so deployed access diverges from configs/
#   5. uc-abac dump into the target schema
#   6. the ABAC Policy Explorer app, and SELECT on the dump for its service principal
#
# Usage: ./deploy_demo.sh <profile> <target-schema> [warehouse-id]
#   e.g. ./deploy_demo.sh my-sandbox abac_viz_demo_state.uc_abac_state
#
# The target schema must be outside the demo catalog: uc-abac manages privileges on
# abac_viz_demo, so it would revoke the app's access to dump tables kept there.
# Re-running is safe: every step is idempotent, and step 2 reverts the drift.sql
# changes before step 4 re-applies them.
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "usage: $0 <profile> <target-schema> [warehouse-id]" >&2
  exit 2
fi

PROFILE="$1"
TARGET_SCHEMA="$2"
WAREHOUSE_ID="${3:-}"
DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${DEMO_DIR}/../.." && pwd)"
APP_NAME="abac-policy-explorer"

if [[ -z "${WAREHOUSE_ID}" ]]; then
  WAREHOUSE_ID="$(databricks experimental aitools tools get-default-warehouse --profile "${PROFILE}")"
fi

run_sql() {
  databricks experimental aitools tools query "$1" --profile "${PROFILE}" >/dev/null
}

echo "deploy: fixture bundle and service principals"
(cd "${DEMO_DIR}" && databricks bundle deploy -t demo --profile "${PROFILE}" \
  && databricks bundle run abac_demo_setup_principals -t demo --profile "${PROFILE}")

echo "deploy: uc-abac deploy (dry run, then apply)"
UC_ARGS=(
  --config-dir configs
  --warehouse-id "${WAREHOUSE_ID}"
  --profile "${PROFILE}"
  --tag-management-scopes abac_viz_demo
  --privilege-management-scopes abac_viz_demo
  --securable-creation-scopes abac_viz_demo
  --securable-modification-scopes abac_viz_demo
  --group-creation-scopes 'abac_demo_*'
  --group-modification-scopes 'abac_demo_*'
)
# uc-abac runs from the demo directory so the dumped config_file_path values are
# relative to it (the app's config_path_prefix maps them to repository paths).
(cd "${DEMO_DIR}" && UV_FROZEN=1 uv run --project "${REPO_DIR}" uc-abac deploy "${UC_ARGS[@]}" --dry-run \
  && UV_FROZEN=1 uv run --project "${REPO_DIR}" uc-abac deploy "${UC_ARGS[@]}")

echo "deploy: seed data"
(cd "${DEMO_DIR}" && databricks bundle run abac_demo_seed_data -t demo --profile "${PROFILE}")

echo "deploy: out-of-band changes from drift.sql"
# One statement per ';'-terminated chunk, with -- comments removed.
sed -e 's/--.*$//' "${DEMO_DIR}/drift.sql" | tr '\n' ' ' | tr ';' '\n' | while read -r statement; do
  if [[ -n "${statement// /}" ]]; then
    run_sql "${statement}"
  fi
done

echo "deploy: uc-abac dump into ${TARGET_SCHEMA}"
(cd "${DEMO_DIR}" && UV_FROZEN=1 uv run --project "${REPO_DIR}" uc-abac dump \
  --config-dir configs --warehouse-id "${WAREHOUSE_ID}" --profile "${PROFILE}" \
  --target-schema "${TARGET_SCHEMA}")

echo "deploy: ABAC Policy Explorer app"
(cd "${REPO_DIR}" && databricks bundle deploy -t dev --profile "${PROFILE}" \
  --var "target_schema=${TARGET_SCHEMA}" --var "warehouse_id=${WAREHOUSE_ID}" \
  --var "app_name=${APP_NAME}" --var "config_path_prefix=examples/abac_viewer_demo")

APP_SP="$(databricks apps get "${APP_NAME}" --profile "${PROFILE}" -o json | jq -r .service_principal_client_id)"
CATALOG="${TARGET_SCHEMA%%.*}"
echo "deploy: granting ${APP_SP} read access to ${TARGET_SCHEMA}"
run_sql "GRANT USE CATALOG ON CATALOG ${CATALOG} TO \`${APP_SP}\`"
run_sql "GRANT USE SCHEMA, SELECT ON SCHEMA ${TARGET_SCHEMA} TO \`${APP_SP}\`"

(cd "${REPO_DIR}" && databricks bundle run abac_policy_explorer -t dev --profile "${PROFILE}" \
  --var "target_schema=${TARGET_SCHEMA}" --var "warehouse_id=${WAREHOUSE_ID}" \
  --var "app_name=${APP_NAME}" --var "config_path_prefix=examples/abac_viewer_demo")

databricks apps get "${APP_NAME}" --profile "${PROFILE}" -o json | jq -r '"deploy: complete: \(.url)"'
