# ABAC Policy Explorer demo

A small, disposable governance model to explore with the
[ABAC Policy Explorer](https://uc-declarative-abac.readthedocs.io/en/latest/deploying/policy-explorer.html):

- catalog `abac_viz_demo` with three schemas (`sales`, `hr`, `finance`), nine tables, and seeded rows
- ten demo service principals (`principals.yaml`) nested across eight account groups
- governed tags, grant policies, column masks, and row filters
- out-of-band changes (`drift.sql`) that make the deployed access diverge from the config

Every account object uses the `abac_demo_` prefix.

## Prerequisites

- A sandbox workspace and an account admin login for it (the demo creates account groups and
  service principals and sets group membership)
- The Databricks CLI, authenticated with a profile for the workspace
- `uv`, [`apx`](https://github.com/databricks-solutions/apx), and Bun, to build the app
- A target schema for the dump tables outside `abac_viz_demo`, for example
  `abac_viz_demo_state.uc_abac_state` (its catalog must exist)

## Deploy

```bash
./deploy_demo.sh <profile> <catalog>.<schema> [warehouse-id]
```

The script runs, in order:

1. deploys this bundle and runs `abac_demo_setup_principals`, which creates the service principals
2. runs `uc-abac deploy` on `configs/` (a dry run first), creating the groups with their members,
   the catalog and tables, tags, policies, and grants
3. runs `abac_demo_seed_data`, which fills the tables
4. applies `drift.sql` (see below)
5. runs `uc-abac dump` into the target schema
6. deploys the ABAC Policy Explorer app, grants its service principal read access to the dump
   tables, and starts it

Each step is idempotent, so the script is safe to rerun: step 2 reverts the `drift.sql` changes
and step 4 applies them again. After changing `configs/`, rerun it to redeploy, dump, and restart
the app.

## Divergence from the config

`drift.sql` changes privileges by hand after the deployment, as happens in real workspaces, so the
explorer has divergence to show:

- **Manual grant**: `abac_demo_analysts_amer` is granted `USE SCHEMA` on `hr` and `SELECT` on
  `hr.salaries` outside the config. The explorer shows AMER analysts as able to read salaries
  through a manual grant (no grant policy), with the amounts still masked.
- **Drift**: `SELECT` on `sales.orders` is revoked from `abac_demo_analysts`, although
  `grant_gold_analysts` declares it. The explorer reports the missing privilege as drift and shows
  analysts as unable to read orders.

To explore the declared state alone, run `uc-abac deploy` and `uc-abac dump` again without
`drift.sql`, then refresh the app.

## Personas

| Service principal | Groups | Sees |
| --- | --- | --- |
| `abac_demo_sp_ana_emea_1`, `abac_demo_sp_ana_emea_2` | `abac_demo_analysts_emea` | Gold sales tables except orders (drift), EMEA rows only, contact PII masked |
| `abac_demo_sp_ana_amer_1` | `abac_demo_analysts_amer` | Gold sales tables except orders (drift), AMER rows only; HR salaries with amounts masked (manual grant) |
| `abac_demo_sp_lead_1` | `abac_demo_analysts` | Gold sales tables except orders (drift), but no rows of the region-filtered tables |
| `abac_demo_sp_eng_1` | `abac_demo_engineers`, `abac_demo_finance_readers` | Platform zones and finance, unmasked |
| `abac_demo_sp_hr_1` | `abac_demo_hr` | Employees with strict PII redacted, not salaries |
| `abac_demo_sp_hr_admin_1` | `abac_demo_hr_admins` | Employees and salaries, unmasked |
| `abac_demo_sp_fin_1` | `abac_demo_finance_readers` | Finance tables |
| `abac_demo_sp_multi_1` | `abac_demo_analysts_emea`, `abac_demo_finance_readers` | Both analyst (without orders) and finance access |
