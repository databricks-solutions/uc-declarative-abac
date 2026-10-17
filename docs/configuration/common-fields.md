(common-fields)=

# Common fields

Most UC objects and resources can carry metadata fields that apply across all types.

## Metadata fields

The following metadata fields are supported on catalogs, schemas, tables, volumes, and functions:

**`name`**: The name of the object. Optional on securable resources (catalogs, schemas, tables, volumes, functions): when omitted, the dictionary key is used as the UC object name. Securable names may not start with `__`, a prefix reserved for internal Databricks-managed objects. Never derived from a key for policies (which are lists, not keyed dicts); policy names must be set explicitly and must be unique among the policies attached to the same securable.

**`owner`**: A principal (user email, group display name, or service principal display name) to set or update as the object's owner. Supported on catalogs, schemas, tables, volumes, and functions.

**`comment`**: A description string to manage on the UC object. Supported on catalogs, schemas, tables, volumes, functions, and columns. Table-level comments are rejected when the table's `table_type` is `VIEW` (set the comment in the view definition instead). {ref}`feature-scopes` gate owner and comment updates.

**`tags`**: A map of tag keys to tag values applied to the object. Use valueless (null / `~`) tags to mark an object without a specific value. Tags are managed under the `--tag-management-scopes` or `--tag-assignment-scopes` feature gates; see {ref}`feature-scopes`.

**`rfa_destinations`**: A list of destinations where access requests are sent for this object (Request For Access notifications). Each entry must be one of: an email address, an `http://` or `https://` URL, or a Databricks notification-destination UUID (a valid RFC 4122 UUID). Omitting this field leaves the object's RFA destinations unmanaged (untouched); an explicit empty list `[]` removes all RFA destinations. Rejected on columns. Gated by `--securable-modification-scopes`; see {ref}`feature-scopes`. Invalid entry kinds raise a config error listing every offender.
