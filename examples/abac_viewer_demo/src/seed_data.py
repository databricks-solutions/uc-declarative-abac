# Databricks notebook source
# MAGIC %md
# MAGIC # ABAC demo: seed data
# MAGIC
# MAGIC Inserts a small fixed dataset into every fixture table. Requires the
# MAGIC uc-declarative-abac apply step to have created the tables already (this
# MAGIC notebook fails with a clear message if not). Idempotent: `INSERT OVERWRITE`
# MAGIC with literal rows, so a re-run leaves identical content.
# MAGIC
# MAGIC Region values are spread across EMEA / AMER / APAC so the
# MAGIC `filter_sales_region` policy has something to bite on (APAC rows are
# MAGIC visible only to excepted principals).

# COMMAND ----------

dbutils.widgets.text("catalog", "abac_viz_demo")
catalog = dbutils.widgets.get("catalog")

SEEDS: dict[str, str] = {
    "sales.customers": """
        (1, 'Alice Meyer',  'alice.meyer@example.com',  '+49-151-0101', 'EMEA', 'enterprise'),
        (2, 'Ben Okafor',   'ben.okafor@example.com',   '+44-7700-0102','EMEA', 'smb'),
        (3, 'Carla Diaz',   'carla.diaz@example.com',   '+1-555-0103',  'AMER', 'enterprise'),
        (4, 'Dan Whitman',  'dan.whitman@example.com',  '+1-555-0104',  'AMER', 'mid-market'),
        (5, 'Emi Tanaka',   'emi.tanaka@example.com',   '+81-90-0105',  'APAC', 'smb'),
        (6, 'Farid Rahman', 'farid.rahman@example.com', '+61-4-0106',   'APAC', 'enterprise')
    """,
    "sales.orders": """
        (101, 1, 'EMEA', 1200.50, 'shipped',   DATE'2026-05-02'),
        (102, 2, 'EMEA',   89.99, 'open',      DATE'2026-06-11'),
        (103, 1, 'EMEA',  450.00, 'returned',  DATE'2026-06-20'),
        (104, 3, 'AMER', 2300.00, 'shipped',   DATE'2026-05-15'),
        (105, 4, 'AMER',  149.00, 'open',      DATE'2026-07-01'),
        (106, 5, 'APAC',  720.25, 'shipped',   DATE'2026-05-28'),
        (107, 6, 'APAC', 3100.00, 'open',      DATE'2026-06-30'),
        (108, 5, 'APAC',   55.10, 'cancelled', DATE'2026-07-05')
    """,
    "sales.leads": """
        (1, 'Grace Lin',   'grace.lin@example.net',    'APAC', 'webinar'),
        (2, 'Hugo Silva',  'hugo.silva@example.net',   'EMEA', 'event'),
        (3, 'Ines Muller', 'ines.mueller@example.net', 'EMEA', 'referral'),
        (4, 'Jack Ryan',   'jack.ryan@example.net',    'AMER', 'outbound')
    """,
    "sales.trips": """
        (201, 'alice.meyer@example.com', 'EMEA', 'AMER', DATE'2026-08-03'),
        (202, 'ben.okafor@example.com',  'APAC', 'EMEA', DATE'2026-08-07'),
        (203, 'carla.diaz@example.com',  'AMER', 'APAC', DATE'2026-08-12'),
        (204, 'dan.whitman@example.com', 'APAC', 'AMER', DATE'2026-08-16'),
        (205, 'emi.tanaka@example.com',  'APAC', 'APAC', DATE'2026-08-20'),
        (206, 'farid.rahman@example.com','EMEA', 'EMEA', DATE'2026-08-25')
    """,
    "hr.employees": """
        (1, 'Kara Novak',  'kara.novak@corp.example',  '900-12-3456', '1988-04-12', 'Engineering', 'CC-100'),
        (2, 'Liam Chen',   'liam.chen@corp.example',   '900-23-4567', '1991-09-30', 'Sales',       'CC-200'),
        (3, 'Maya Patel',  'maya.patel@corp.example',  '900-34-5678', '1985-01-22', 'HR',          'CC-300'),
        (4, 'Noah Kim',    'noah.kim@corp.example',    '900-45-6789', '1993-07-04', 'Finance',     'CC-400'),
        (5, 'Olga Petrov', 'olga.petrov@corp.example', '900-56-7890', '1979-11-15', 'Engineering', 'CC-100')
    """,
    "hr.salaries": """
        (1, 145000.00, 20000.00, 'USD'),
        (2,  98000.00, 15000.00, 'USD'),
        (3,  88000.00,  8000.00, 'EUR'),
        (4, 112000.00, 12000.00, 'USD'),
        (5, 156000.00, 25000.00, 'EUR')
    """,
    "finance.invoices": """
        (9001, 501, 12500.00, 'USD', 'AMER', 'paid'),
        (9002, 502,  4300.50, 'EUR', 'EMEA', 'open'),
        (9003, 501,   780.00, 'USD', 'AMER', 'open'),
        (9004, 503, 22000.00, 'AUD', 'APAC', 'paid'),
        (9005, 504,  1650.75, 'EUR', 'EMEA', 'overdue'),
        (9006, 502,   990.00, 'EUR', 'EMEA', 'paid')
    """,
    "finance.budgets": """
        (1, 'Engineering', 2026, 1500000.00),
        (2, 'Sales',       2026,  900000.00),
        (3, 'HR',          2026,  400000.00),
        (4, 'Finance',     2026,  650000.00)
    """,
    "finance.vendors": """
        (501, 'Acme Cloud',  'sales@acmecloud.example', 'US'),
        (502, 'Helios GmbH', 'kontakt@helios.example',  'DE'),
        (503, 'Wattle Pty',  'hello@wattle.example',    'AU'),
        (504, 'Nordlys AS',  'post@nordlys.example',    'NO')
    """,
}

# COMMAND ----------

missing = [t for t in SEEDS if not spark.catalog.tableExists(f"{catalog}.{t}")]
if missing:
    raise RuntimeError(
        f"Missing tables {missing} in catalog {catalog!r}. Run the "
        "uc-declarative-abac apply step first (see README.md) — it creates the "
        "catalog, schemas, and tables from configs/."
    )

counts = {}
for table, values in SEEDS.items():
    full = f"{catalog}.{table}"
    spark.sql(f"INSERT OVERWRITE TABLE {full} VALUES {values}")
    counts[full] = spark.table(full).count()

for full, n in counts.items():
    print(f"{full}: {n} rows")
