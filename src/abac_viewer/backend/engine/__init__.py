"""ABAC Policy Explorer evaluation engine.

Loads the tables ``uc-abac dump`` writes into a target schema and derives factored
membership, tag, policy, and securable relations from which verdicts and why-chains are
computed on the fly. Never materializes principal × securable.
"""

from abac_viewer.backend.engine.chain_graph import (
    build_chain_graph,
    build_column_chain_graph,
)
from abac_viewer.backend.engine.dump import (
    DUMP_TABLES,
    DumpReader,
    DumpReadError,
    InMemoryDumpReader,
    load_factored_model_from_dump,
)
from abac_viewer.backend.engine.model import (
    ALL_USERS_GROUP,
    CompiledFgacPolicy,
    CompiledGrantPolicy,
    FactoredModel,
    GrantDrift,
    GrantMatch,
    MembershipEdge,
    Securable,
    TagAssignment,
)
from abac_viewer.backend.engine.runtime import (
    BuildInfo,
    BuildInfoDependency,
    ModelDependency,
    ModelStoreDependency,
    ModelUnavailableError,
)
from abac_viewer.backend.engine.verdict import (
    evaluate,
    evaluate_column,
    explanation_sentence,
    grouped_chains,
    masked_columns_for,
    readable_tables,
    row_filter_state_details_for,
    row_filter_state_for,
)

__all__ = [
    "ALL_USERS_GROUP",
    "DUMP_TABLES",
    "BuildInfo",
    "BuildInfoDependency",
    "CompiledFgacPolicy",
    "CompiledGrantPolicy",
    "DumpReadError",
    "DumpReader",
    "FactoredModel",
    "GrantDrift",
    "GrantMatch",
    "InMemoryDumpReader",
    "MembershipEdge",
    "ModelDependency",
    "ModelStoreDependency",
    "ModelUnavailableError",
    "Securable",
    "TagAssignment",
    "build_chain_graph",
    "build_column_chain_graph",
    "evaluate",
    "evaluate_column",
    "explanation_sentence",
    "grouped_chains",
    "load_factored_model_from_dump",
    "masked_columns_for",
    "readable_tables",
    "row_filter_state_details_for",
    "row_filter_state_for",
]
