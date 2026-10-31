(template-variables)=

# Template variables

Definitions can be parameterized templates. Any string value in a definition may contain `${placeholder}` tokens. Each `$ref` that instantiates the definition supplies concrete values via a sibling `$vars` block. Think of a definition as a function, a `$ref` as a call, and `$vars` as the arguments. This removes the last major source of copy-paste: environment-based names and principals that plain `$ref` overrides couldn't factor out.

```{code-block} yaml
definitions:
  policies:
    domain|grant_read_on_finance:
      name: grant_read_on_${env}_finance
      type: grant
      has_tags:
        finance: '*'
      privileges:
        - read
      to:
        - finance_${env}_analysts
        - finance_${env}_engineers

resources:
  catalogs:
    gold_prod:
      name: gold_prod
      policies:
        - $ref: $defs/policies/domain|grant_read_on_finance
          $vars:
            env: prod

    gold_uat:
      name: gold_uat
      policies:
        - $ref: $defs/policies/domain|grant_read_on_finance
          $vars:
            env: uat
```

## Syntax

`${name}` wraps a bare variable name, written tight (no inner whitespace, so `${env}` is a placeholder but `${ env }` is not and is reported as a malformed placeholder). It is a substitution reference, not a templating engine: no filters or expressions.

A literal `${...}` that is not a variable (for example, a shell-style `${HOME}` in a function body) is escaped by doubling the dollar: `$${HOME}` renders a literal `${HOME}`. A bare `$$` not followed by `{` (for example, a SQL dollar-quote `$$body$$`) is left untouched.

For backward compatibility, the legacy `{{ name }}` delimiter is still supported. See {ref}`deprecations`.

## Defaults and signatures (optional)

A definition may declare its own `$vars` block to give variables default values (`medallion: bronze`) and/or to declare required variables with a null value (`env:`). The effective value of a variable is the definition's default overridden by the `$ref`'s argument (the same deep-merge as any other `$ref` override).

Declaring a `$vars` block is optional. With none, variables are implicit and all required. However, a declared block must be complete: it must list exactly the placeholders the body uses. This makes the block a trustworthy, discoverable signature and catches body typos.

```{code-block} yaml
definitions:
  schemas:
    ingestion|salesforce:
      $vars:
        env: ~              # required: no default
        medallion: bronze   # optional: defaults to bronze
      name: salesforce
      tags:
        environment: ${env}
        quality_tier: ${medallion}
```

## Extending a definition (root `$ref`)

A definition may extend another by making its body a top-level `$ref`: inheriting the base and layering on its own fields. Because that root `$ref` shares its level with the definition's own `$vars` signature, there is nowhere to write an explicit forwarding `$vars` onto it. So an extending definition forwards its own variables into the base by name, for the variables the base accepts. This is the one implicit-forwarding case; nested (non-root) `$ref`s still forward explicitly (via a `${placeholder}` `$vars` value).

A variable may be declared purely to pass through to the base, even if the extending definition's own body never uses it.

```{code-block} yaml
definitions:
  schemas:
    base_policies:
      $vars:
        env: ~
      policies:
        - $ref: $defs/policies/grant_read
          $vars:
            env: ${env}   # explicit forward to a nested $ref

    default:
      $ref: $defs/schemas/base_policies   # extends base_policies
      $vars:
        env: ~                 # declared here; forwarded into base_policies by name
      name: default
      volumes:
        - name: v
          owner: uc_gov_${env}_team    # also used locally
```

## Templated reference targets

A `$ref` / `$defs` target inside a definition may itself contain `${placeholder}` tokens: `$ref: $defs/tables/base_${layer}`. This lets a definition select which definition it references (or extends) from a variable. The placeholder is bound by the enclosing definition's `$vars` and substituted to a concrete target before it is resolved. This works for a root `$ref` (extending a variable-selected base), a nested `$ref`, and a bare inline `$defs/...` string value.

Templated targets let one template pick a layer-specific base (for example, a silver base table that already carries an extra `region` column) without overriding every reference by hand. A templated target under `resources:` is still an error: resources are concrete.

One caveat: a bare inline `$defs/...` string with a placeholder is resolved only after `$ref` override merge, so it isn't merge-aligned into an overriding list (an override list replaces it wholesale). Use the `$ref` dict form when a templated target is also merged into.

```{code-block} yaml
definitions:
  tables:
    base_bronze:
      tags:
        layer: bronze

    base_silver:
      tags:
        layer: silver
      columns:
        - name: region   # silver base adds a column
          type: string

    payments:
      $ref: $defs/tables/base_${layer}   # base chosen by the `layer` variable
      $vars:
        layer: ~
      name: payments
      columns:
        - name: payment_id
          type: long
```

## User-data map keys

Most dict keys are structural (field names, resource identities) and stay literal. However, a tag or identity-attribute name is user data, so `${placeholder}` is allowed in the keys of the user-data maps: `tags`, `has_tags`, `has_any_of_tags`, `has_none_of_tags` (on securables, columns, and policies), the FGAC-policy context-attribute maps (`has_context_attributes`, `has_any_of_context_attributes`, `has_none_of_context_attributes`), and the mask-policy identity-attribute maps (`has_identity_attributes`, `has_any_of_identity_attributes`, `has_none_of_identity_attributes`, `has_identity_attribute_tag_matches`, `has_any_of_identity_attribute_tag_matches`, `has_none_of_identity_attribute_tag_matches`), and the `rls_mapping` of an RLS mapping rule (whose keys are parameter values). These are bound by the enclosing definition's `$vars` just like a value.

A placeholder in any other key is an error.

```{code-block} yaml
definitions:
  schemas:
    ingestion|salesforce:
      $vars:
        env: ~
      name: salesforce
      tags:
        uc_gov_${env}_owner: platform    # tag NAME is templated

  policies:
    domain|grant_read:
      $vars:
        env: ~
      name: grant_read
      type: grant
      has_any_of_tags:
        finance_${env}: '*'               # tag NAME in a policy condition
      privileges: [read]
      to: [analysts]
```

## Limitations and rules

**Limitations:**

- Substitution happens after `$ref` override merge, so a tag key that still holds a placeholder cannot be targeted by an outer-level override (the outer writes a concrete key, which won't align).
- Two templated keys that resolve to the same tag name collapse (last wins).

**Rules:**

- Variable names must be bare identifiers (letters, digits, underscore; not starting with a digit). An identifier-shaped-but-invalid token like `${my-var}` (or a spaced `${ env }`) is rejected as a malformed placeholder.
- Variable values are literal strings. A number/bool is rejected with a hint to quote it; `''` is a real empty string; null means "not supplied"; a value that looks like a `$defs/...` reference is rejected (variables carry values, not references).
- A placeholder is bound by the `$vars` of the enclosing definition: the definition in whose text it appears (whether that's the definition's own body or an override the definition writes onto a child `$ref`). The writer binds it.
- A placeholder may appear only inside a definition: in a value, in a `$ref` / `$defs` reference target (which selects the referenced definition), or in a user-data map key. Never in any other dict key or anywhere under a `resources:` entry (including a `$ref` target there). A resource is the concrete instance layer and must supply literals; a placeholder there is a hard error.
- Because binding is local to the writer, a parent cannot widen a child's variable contract via an override.
- A multi-level template forwards a variable to a child `$ref` by using `${placeholder}` as the child's `$vars` value, except a definition's own body-root `$ref` (an extends), where a variable forwards into the base by name.
- Every placeholder must be bound (by an argument or a default) and every supplied argument must be used. A missing, unused, incomplete-signature, non-string, malformed, or resource-placeholder case fails config validation.
