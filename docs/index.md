# UC Declarative ABAC

**Declare governance in YAML. Version it. Deploy it.**

UC Declarative ABAC lets you define your Databricks Unity Catalog Attribute-Based Access Control
(ABAC) governance model in **declarative YAML files**. You describe the tags, grants, masking and
filtering policies, groups, and UC objects you want; the engine reads the current state of Unity
Catalog, computes the difference, and applies only the changes needed to bring UC in line with
your configs. Run it from the `uc-abac` CLI or as a GitHub Action from the repository that holds
your YAML.

## Where to start

- New to the project? Read the {ref}`overview`, then follow the {ref}`quickstart`.
- Writing configs? The concepts pages explain {ref}`definitions-and-resources`,
  {ref}`references-and-overrides`, and {ref}`template-variables`; the configuration reference
  documents every object you can declare, starting with {ref}`catalogs`.
- Running it in CI? See {ref}`feature-scopes`, {ref}`authentication`, and {ref}`github-actions`.
- Looking up a flag? See the {ref}`cli`.

```{note}
UC Declarative ABAC is not an official Databricks product. Databricks and Unity Catalog are
trademarks of Databricks, Inc.
```

```{toctree}
:caption: Getting started
:maxdepth: 2
:hidden:

getting-started/overview
getting-started/installation
getting-started/quickstart
```

```{toctree}
:caption: Concepts
:maxdepth: 2
:hidden:

concepts/definitions-and-resources
concepts/references-and-overrides
concepts/template-variables
concepts/principals
concepts/file-organization
```

```{toctree}
:caption: Configuration reference
:maxdepth: 2
:hidden:

configuration/common-fields
configuration/catalogs
configuration/schemas
configuration/tables
configuration/volumes
configuration/functions
configuration/policies/index
configuration/groups
configuration/governed-tags
configuration/domains
```

```{toctree}
:caption: Deploying
:maxdepth: 2
:hidden:

deploying/feature-scopes
deploying/deployment-semantics
deploying/authentication
deploying/settings
deploying/github-actions
deploying/dumping-state
```

```{toctree}
:caption: Reference
:maxdepth: 2
:hidden:

reference/cli
reference/deprecations
glossary
```

```{toctree}
:caption: Project
:maxdepth: 1
:hidden:

project/examples
project/contributing
```
