"""AST-backed write policy for the hidden snow-kit v1.1 write path."""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass

from .sql import normalize_object_name, qualify_name

_ALLOWED = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "MERGE",
    "TRUNCATE",
    "CREATE TABLE",
    "CREATE VIEW",
    "CREATE STAGE",
    "CREATE FILE FORMAT",
    "CREATE SEQUENCE",
    "CREATE FUNCTION",
    "CREATE PIPE",
    "CREATE SCHEMA",
    "DROP TABLE",
}
_SCRATCH_SCHEMA_HINTS = ("SCRATCH", "WORKSPACE", "TMP", "TEMP")


@dataclass(frozen=True)
class WritePlan:
    operation: str
    targets: tuple[str, ...]
    required_privilege: str


class SqlPolicyError(ValueError):
    """Raised when write SQL is outside snow-kit's allowed vocabulary."""


def classify_write(
    sql: str,
    *,
    current_database: str,
    current_schema: str | None,
    schema_patterns: tuple[str, ...] = (),
) -> WritePlan:
    """Parse one Snowflake statement and return the allowed operation/targets."""
    import sqlglot

    statements = sqlglot.parse(sql, read="snowflake")
    statements = [stmt for stmt in statements if stmt is not None]
    if len(statements) != 1:
        raise SqlPolicyError("Exactly one SQL statement is required for query.execute_write.")
    expr = statements[0]
    operation = _operation(expr, sql)
    if operation not in _ALLOWED:
        raise SqlPolicyError(f"Statement {operation!r} is not allowed by snow-kit write policy.")
    if "CREATE OR REPLACE" in sql.upper():
        raise SqlPolicyError("CREATE OR REPLACE is not allowed.")
    targets = tuple(
        qualify_name(target, database=current_database, schema=current_schema)
        for target in _targets(expr, operation)
    )
    if not targets:
        raise SqlPolicyError("Could not resolve a target object for write preflight.")
    if schema_patterns and not all(_matches_any_schema_pattern(t, schema_patterns) for t in targets):
        raise SqlPolicyError("Target is outside SNOW_KIT_WRITE_SCHEMA_PATTERNS.")
    if operation == "DROP TABLE" and not all(_scratch_biased(t) for t in targets):
        raise SqlPolicyError("DROP TABLE is allowed only for scratch/workspace-like schemas.")
    return WritePlan(operation=operation, targets=targets, required_privilege=_required_privilege(operation))


def _operation(expr: object, sql: str) -> str:
    name = expr.__class__.__name__.upper()
    upper = sql.strip().upper()
    if name == "INSERT":
        return "INSERT"
    if name == "UPDATE":
        return "UPDATE"
    if name == "DELETE":
        return "DELETE"
    if name == "MERGE":
        return "MERGE"
    if upper.startswith("TRUNCATE"):
        return "TRUNCATE"
    if upper.startswith("DROP TABLE"):
        return "DROP TABLE"
    if upper.startswith("CREATE "):
        words = upper.split()
        return " ".join(words[:3]) if len(words) >= 3 and words[1] == "FILE" else " ".join(words[:2])
    return upper.split()[0] if upper else "EMPTY"


def _targets(expr: object, operation: str) -> list[str]:
    sql = expr.sql(dialect="snowflake")
    words = sql.replace("(", " ").split()
    if operation in {"INSERT", "MERGE"} and "INTO" in [w.upper() for w in words]:
        return [_word_after(words, "INTO")]
    if operation in {"UPDATE", "DELETE"}:
        keyword = "UPDATE" if operation == "UPDATE" else "FROM"
        return [_word_after(words, keyword)]
    if operation == "TRUNCATE":
        return [words[-1]]
    if operation.startswith("CREATE"):
        skip = 3 if operation == "CREATE FILE FORMAT" else 2
        while skip < len(words) and words[skip].upper() in {"IF", "OR", "NOT", "EXISTS"}:
            skip += 1
        if skip >= len(words):
            raise SqlPolicyError("Could not resolve target for CREATE statement.")
        return [words[skip]]
    if operation == "DROP TABLE":
        return [words[-1]]
    return []


def _word_after(words: list[str], keyword: str) -> str:
    for idx, word in enumerate(words):
        if word.upper() == keyword and idx + 1 < len(words):
            return words[idx + 1]
    raise SqlPolicyError(f"Could not resolve target after {keyword}.")


def _required_privilege(operation: str) -> str:
    if operation in {"INSERT", "UPDATE", "DELETE", "TRUNCATE"}:
        return operation if operation != "TRUNCATE" else "DELETE"
    if operation == "MERGE":
        return "INSERT"
    if operation == "DROP TABLE":
        return "OWNERSHIP"
    return operation


def _matches_any_schema_pattern(target: str, patterns: tuple[str, ...]) -> bool:
    parts = normalize_object_name(target).split(".")
    schema_name = ".".join(parts[:2]) if len(parts) >= 2 else target.upper()
    return any(fnmatch.fnmatch(schema_name, pattern.upper()) for pattern in patterns)


def _scratch_biased(target: str) -> bool:
    parts = normalize_object_name(target).split(".")
    schema = parts[-2] if len(parts) >= 2 else ""
    upper = schema.upper()
    for hint in _SCRATCH_SCHEMA_HINTS:
        if upper == hint:
            return True
        if upper.endswith(f"_{hint}") or upper.startswith(f"{hint}_"):
            return True
        if f"_{hint}_" in upper:
            return True
    return False
