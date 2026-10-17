(examples)=

# Examples

## Finance Demo

The [finance_demo](https://github.com/databricks-solutions/uc-declarative-abac/tree/main/examples/finance_demo) is a complete, deployable-from-scratch governance model for a fictional financial-services organisation. Every principal (owner, grant target, tag assigner, group member) is either a group this project creates or a built-in system group. Nothing depends on pre-existing users or service principals.

### What it demonstrates

- **Multi-environment deployment**: one logical catalog definition deployed to both `prod` and `uat` using template variables to customize names and principals per environment
- **Medallion architecture**: bronze, silver, and gold layers across three business subdomains (transactions, customers, shared utilities)
- **Governed tags** with allowed values and role-based assigners
- **Discovery domains**: a parent domain with nested subdomains, each backed by a governed tag
- **Nested group hierarchy**: parent-child group relationships and an expiring group that automatically clears membership
- **Tag-based ABAC policies**:
  - Column masking by sensitivity level and PII type
  - Row filtering by region, plus large-transaction oversight
  - Grants with the `read`, `use`, and `create` abstractions, concrete volume privileges, `use_catalog`/`use_schema` cascading, wildcard tag matches, and expiry dates

It exercises every GA feature of the engine and is a good starting point to copy into your own governance repository.

### Validate it locally

```bash
cd examples/finance_demo
uc-abac validate --config-dir configs
```

### Deploy it

See the [finance_demo README](https://github.com/databricks-solutions/uc-declarative-abac/tree/main/examples/finance_demo#deploy-it) for step-by-step deployment instructions and prerequisites.

### Adapt it for your use case

The README also explains [how to use it as a starting point](https://github.com/databricks-solutions/uc-declarative-abac/tree/main/examples/finance_demo#use-it-as-a-starting-point): copy the entire `finance_demo/` folder into a new repository, delete what you don't need, rename the `uc_abac_finance` catalog and prefixes to yours, configure your warehouse, and iterate locally with `validate`.
