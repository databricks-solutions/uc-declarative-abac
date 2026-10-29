-- Out-of-band changes that make the deployed access diverge from configs/.
--
-- deploy_demo.sh runs these after uc-abac deploy and before uc-abac dump, so the
-- ABAC Policy Explorer has divergence to show. The next uc-abac deploy reverts them
-- (privilege management grants what the config declares and revokes the rest).

-- Manual grant: AMER analysts can read HR salaries through a manual GRANT that no
-- grant policy produces. The salary amounts mask still applies to them.
GRANT USE SCHEMA ON SCHEMA abac_viz_demo.hr TO `abac_demo_analysts_amer`;
GRANT SELECT ON TABLE abac_viz_demo.hr.salaries TO `abac_demo_analysts_amer`;

-- Drift: grant_gold_analysts declares SELECT on the gold sales tables for
-- abac_demo_analysts, but it has been revoked by hand on orders, so analysts
-- cannot read it.
REVOKE SELECT ON TABLE abac_viz_demo.sales.orders FROM `abac_demo_analysts`;
