from __future__ import annotations

from dataclasses import dataclass

from uc_abac.types import SecurableType


class OrchestratorError(Exception):
    """Base exception for all orchestrator errors."""


class ResolutionError(OrchestratorError):
    """Raised when a $ref cannot be resolved (missing key, circular ref, etc.)."""


class DuplicateKeyError(OrchestratorError):
    """Raised for a duplicate mapping key in a YAML config.

    Covers a key repeated within a single file (caught at parse time by the strict
    loader, at any nesting depth) as well as duplicate definition keys found across
    files during the definitions/resources merge."""


class DuplicateResourceError(OrchestratorError):
    """Raised when duplicate resource names are detected within the same parent."""


class UnreferencedDefinitionError(OrchestratorError):
    """Raised when definitions exist that are not referenced by any $ref."""


class TemplateVariableError(OrchestratorError):
    """Raised for template-variable (``$vars`` / ``{{ placeholder }}``) errors.

    Covers every failure mode of the template-variables feature: an incomplete
    definition ``$vars`` signature (a body placeholder left undeclared, or a
    declared variable the body never uses), a ``$ref`` that fails to supply a
    required variable (missing) or supplies one the template does not use
    (unused), a non-string ``$vars`` value, and a ``{{ placeholder }}`` in a
    resource value (resources are the concrete instance layer — placeholders are
    bound by the enclosing definition's ``$vars`` and belong inside definitions).
    """


class PrincipalValidationError(OrchestratorError):
    """Raised when one or more principal names cannot be found in the account."""


class UngovernedTagError(OrchestratorError):
    """Raised when a policy references an ungoverned tag key — i.e. a key
    that is not declared as a governed tag in the config's desired governed
    tags nor present in UC's actual governed tags. Only the tag key is
    checked — values are not validated."""


class DisallowedTagValueError(OrchestratorError):
    """Raised when a securable tag assignment uses a governed tag key but the
    assigned value is not in the governed tag's ``allowed_values``. A governed
    tag with empty ``allowed_values`` accepts any value and does not trigger
    this error."""


class DuplicateServicePrincipalError(OrchestratorError):
    """Raised when two service principals share the same display name."""


class InteractiveConfirmationRequiredError(OrchestratorError):
    """Raised when the engine needs an interactive confirmation but no TTY is attached.

    Surfaces as a hard, immediate error (not accumulated via ChangeLogger) because the
    engine cannot safely proceed with a destructive action (e.g. governed-tag deletion)
    without an explicit human confirm. The caller must set ``--force`` in non-interactive
    contexts (CI, scripted runs) to auto-confirm.
    """


class NonexistentSecurableError(OrchestratorError):
    """Raised when a securable declared in config doesn't exist in UC.

    Functions are created by the engine and are excluded from this check; only
    catalogs, schemas, tables, and volumes can trigger this error. One instance
    carries a single (type, full_name) pair. By default the engine logs one error
    per offender and surfaces them together via ``ExecutionBatchError``. With the
    explicit warning mode enabled, out-of-creation-scope offenders are logged as
    non-fatal warnings and their dependent changes are skipped instead.

    An optional ``hint`` string is appended to the stock message — used by the
    table-creation validator to explain why an otherwise-createable table can't
    be created (e.g. missing columns or missing column types).
    """

    def __init__(
        self,
        securable_type: SecurableType,
        full_name: str,
        hint: str | None = None,
    ) -> None:
        self.securable_type = securable_type
        self.full_name = full_name
        self.hint = hint
        base = (
            f"Nonexistent {securable_type.value} {full_name!r} declared in config but "
            f"not found in Unity Catalog."
        )
        if hint:
            # A hint means a downstream validator ran (typically with the
            # creation flag already on) and identified a specific blocker.
            # The hint is the actionable advice; suggesting the flag here
            # would be redundant (the user has already set it).
            message = f"{base} {hint}"
        else:
            message = (
                f"{base} Please add its namespace to --securable-creation-scopes "
                "to have the engine create it, or remove it from config."
            )
        super().__init__(message)


@dataclass(frozen=True)
class ExecutionError:
    """A single error that occurred during SQL execution."""

    context: str
    exception: Exception


class ExecutionBatchError(OrchestratorError):
    """Raised after execution completes when one or more SQL statements failed."""

    def __init__(self, errors: list[ExecutionError]) -> None:
        self.errors = errors
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        lines = [f"{len(self.errors)} SQL statement(s) failed during execution:"]
        for err in self.errors:
            lines.append(f"  - {err.context}: {err.exception}")
        return "\n".join(lines)
