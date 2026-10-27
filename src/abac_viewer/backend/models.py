from pydantic import BaseModel, Field

from .. import __version__


class VersionOut(BaseModel):
    version: str

    @classmethod
    def from_metadata(cls):
        return cls(version=__version__)


# --- ABAC Policy Explorer API models -----------------------------------------


class WhoAmIOut(BaseModel):
    principal: str
    known: bool  # appears in the config-declared membership graph
    groups: list[str]  # transitive


class PrincipalOut(BaseModel):
    name: str
    kind: str  # user | service_principal | group
    groups: list[str]


class DriftOut(BaseModel):
    """A privilege a grant policy expects that Unity Catalog does not hold."""

    policy_id: str
    policy_name: str
    principal: str  # the grantee the policy names
    securable: str
    securable_type: str  # catalog | schema | table | ...
    privilege: str  # UC spelling, e.g. SELECT or USE SCHEMA


class MetaOut(BaseModel):
    revision: str
    source: str
    securables: int
    tables: int
    principals: int
    policies: int
    warnings: list[str]
    drift: list[DriftOut]
    build_sha: str
    repo_slug: str
    config_path_prefix: str


class ChainNodeOut(BaseModel):
    kind: str  # membership | tag | policy | grant | effect
    label: str
    detail: str = ""
    source: str | None = None


class ChainGroupOut(BaseModel):
    """Deduplicated why-detail group mirroring the graph: shared header +
    the effects under it."""

    membership: ChainNodeOut
    policy: ChainNodeOut
    tag: ChainNodeOut | None
    effects: list[ChainNodeOut]


class ColumnVerdictOut(BaseModel):
    column: str
    data_type: str | None
    masked: bool
    mask_policy_ids: list[str]


class VerdictOut(BaseModel):
    principal: str
    securable: str
    status: str  # full | filtered | partial | no_access
    can_read: bool
    row_filter_targeted: bool
    row_filtered: bool
    row_filter_excepted_by: str | None
    missing: list[str]
    columns: list[ColumnVerdictOut]
    chains: list[list[ChainNodeOut]]
    groups: list[ChainGroupOut]
    sentence: str


class AccessRowOut(BaseModel):
    """One row of the Explorer results table."""

    securable: str
    securable_type: str
    status: str
    masked_columns: list[str]
    row_filtered: bool
    tags: dict[str, str]


class ColumnAccessRowOut(BaseModel):
    """Per-column result row for column-level Explorer questions."""

    table: str
    column: str
    column_full_name: str
    data_type: str | None
    can_read_table: bool
    mask_targeted: bool
    masked: bool
    row_filtered: bool
    row_filter_targeted: bool
    principal: str
    policy_name: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class ColumnPolicyOut(BaseModel):
    column_full_name: str
    mask_policy_count: int = 0
    row_filter_policy_count: int = 0


class ColumnExplanationOut(BaseModel):
    """Mask verdict + deciding policy for one (principal, column)."""

    principal: str
    column_full_name: str
    table_full_name: str
    column: str
    data_type: str | None
    can_read_table: bool
    masked: bool
    row_filtered: bool
    row_filter_targeted: bool
    row_filter_excepted_by: str | None
    policy_name: str | None
    function: str | None
    covered_by: str | None
    excepted_by: str | None
    tag_atoms: dict[str, str]
    policy_attached_to: str | None
    policy_attached_level: str | None
    policy_source: str | None
    arguments: list["PolicyArgumentOut"]
    sentence: str


class PolicyArgumentOut(BaseModel):
    position: int
    kind: str  # alias | constant
    alias: str | None
    constant: bool | int | float | str | None
    constant_type: str | None
    target: bool
    matched_columns: list[str]


class GraphSourceOut(BaseModel):
    securable: str
    securable_type: str
    source: str | None = None
    github_url: str | None = None
    inherited: bool = False


class GraphNodeOut(BaseModel):
    id: str
    kind: (
        str  # user | group | policy | manual | tag | table | schema | catalog | column
    )
    label: str
    source: str | None = None
    github_url: str | None = None
    effect_principal: bool = False
    mask_targeted: bool = False
    masked: bool = False
    row_filter_targeted: bool = False
    row_filtered: bool = False


class GraphEdgeOut(BaseModel):
    source: str
    target: str
    label: str  # member | privilege name | policy name
    kind: str  # membership | to | matches | tagged | grant | manual_grant | drift
    policy_id: str | None = None
    code_sources: list[GraphSourceOut] = Field(default_factory=list)


class GraphOut(BaseModel):
    principal: str
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]


class PrincipalEffectOut(BaseModel):
    principal: str
    principal_kind: str
    mask_targeted: bool = False
    masked: bool
    row_filter_targeted: bool = False
    row_filtered: bool
    masked_columns: list[str] = Field(default_factory=list)
    row_filter_columns: list[str] = Field(default_factory=list)
    mask_policy_columns: list[str] = Field(default_factory=list)
    row_filter_policy_columns: list[str] = Field(default_factory=list)


class InverseGraphOut(GraphOut):
    target: str
    target_type: str
    principal_effects: list[PrincipalEffectOut]


class TreeNodeOut(BaseModel):
    """A node in the UC-style securable tree (catalog → schema → table)."""

    full_name: str
    name: str
    securable_type: str  # catalog | schema | table
    children: list["TreeNodeOut"] = Field(default_factory=list)
    # table-only rollup for the selected principal
    readable: bool | None = None
    row_filtered: bool | None = None
    row_filter_targeted: bool | None = None
    masked_column_count: int | None = None
    mask_policy_column_count: int | None = None
    column_count: int | None = None


class ChainGraphNodeOut(BaseModel):
    id: str
    kind: str  # user | group | policy | tag | securable | column | constant
    label: str
    layer: int
    sublabel: str = ""
    source: str | None = None
    github_url: str | None = None  # deep link to the config at the deployed SHA
    effect_principal: bool = False
    mask_targeted: bool = False
    masked: bool = False
    row_filter_targeted: bool = False
    row_filtered: bool = False


class ChainGraphEdgeOut(BaseModel):
    source: str
    target: str
    label: str
    kind: str  # member | to | matches | tagged | grant | effect | contains | argument
    code_sources: list[GraphSourceOut] = Field(default_factory=list)


class ChainGraphOut(BaseModel):
    principal: str
    securable: str
    nodes: list[ChainGraphNodeOut]
    edges: list[ChainGraphEdgeOut]
