(volumes)=

# Volumes

Volumes are defined under `definitions: volumes:`. Key convention: `<catalog_name>|<schema_name>|<volume_name>`.

```{code-block} yaml
:caption: definitions/platform/schemas/landing/volumes/raw_events.yaml

definitions:
  volumes:
    platform|landing|raw_events:
      name: raw_events
      comment: Landing volume for raw event files
      owner: data_platform_team
      tags:
        landing: ~
```

## External volumes

To create an external volume, set the `location` field with a URI to external object storage:

```{code-block} yaml
:caption: definitions/platform/schemas/landing/volumes/external_data.yaml

definitions:
  volumes:
    platform|landing|external_data:
      name: external_data
      comment: External volume pointing to S3
      owner: data_platform_team
      location: s3://my-bucket/path
```

When you reference a volume definition from a resource, use the `catalog_name` and `schema_name` fields:

```{code-block} yaml
:caption: resources/catalogs/platform_prod/schemas/landing/volumes/raw_events.yaml

resources:
  volumes:
    platform_prod|landing|raw_events:
      $ref: $defs/volumes/platform|landing|raw_events
      catalog_name: platform_prod
      schema_name: landing
```

Volume creation is gated by `--securable-creation-scopes`; see {ref}`feature-scopes`.
