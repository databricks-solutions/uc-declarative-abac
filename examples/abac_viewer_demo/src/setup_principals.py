# Databricks notebook source
# MAGIC %md
# MAGIC # ABAC demo: create the demo service principals
# MAGIC
# MAGIC Creates every service principal listed in `principals.yaml` (the
# MAGIC `principals_file` widget, deployed with this bundle) that does not exist yet.
# MAGIC They stand in for demo users. `uc-abac deploy` then creates the account groups
# MAGIC in `configs/resources/groups` with these principals as members, so this job
# MAGIC must run first.
# MAGIC
# MAGIC Idempotent: existing principals are left alone, and nothing is deleted. Only
# MAGIC `abac_demo_`-prefixed principals are ever created.

# COMMAND ----------

import json

import yaml
from databricks.sdk import WorkspaceClient

dbutils.widgets.text("principals_file", "")  # noqa: F821
principals_file = dbutils.widgets.get("principals_file")  # noqa: F821
if not principals_file:
    raise ValueError("principals_file widget is required")

with open(principals_file) as fh:
    names = sorted((yaml.safe_load(fh) or {}).get("service_principals") or {})

for name in names:
    if not name.startswith("abac_demo_"):
        raise ValueError(f"Refusing to create non-abac_demo_ principal: {name!r}")

# COMMAND ----------

w = WorkspaceClient()
created, existing = [], []
for name in names:
    if list(w.service_principals.list(filter=f'displayName eq "{name}"')):
        existing.append(name)
        continue
    # A workspace-level create also registers the principal in the account.
    w.service_principals.create(display_name=name, active=True)
    created.append(name)

summary = {"created": created, "existing": existing}
print(json.dumps(summary, indent=2))
dbutils.notebook.exit(json.dumps(summary))  # noqa: F821
