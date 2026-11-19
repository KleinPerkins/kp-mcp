"""Small Snowflake SQL helpers shared by read and write paths."""
from __future__ import annotations

import re

_IDENT_PART = r'(?:[A-Za-z0-9_]+|"(?:[^"]|"")+")'
_IDENT_RE = re.compile(rf"^{_IDENT_PART}(?:\.{_IDENT_PART})*$")


def strip_comments(sql: str) -> str:
    sql = re.sub(r"--.*?$", "", sql, flags=re.MULTILINE)
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return sql.strip()


def statement_type(sql: str) -> str:
    clean = strip_comments(sql)
    if not clean:
        return "EMPTY"
    return clean.split()[0].upper()


def ensure_read_only(sql: str) -> str:
    """Admit one parsed read statement; never treat an opaque command as a query.

    Snowflake SQL is parsed with the same dependency/dialect as the write policy.
    Session context selection remains supported, but roles cannot be changed here.
    """
    import sqlglot
    from sqlglot import exp

    def refused(detail: str) -> PermissionError:
        return PermissionError(f"query.execute is read-only; {detail}.")

    def parse_one(text: str):
        try:
            statements = [item for item in sqlglot.parse(text, read="snowflake") if item is not None]
        except sqlglot.errors.SqlglotError as exc:
            raise refused("SQL could not be parsed safely") from exc
        if len(statements) != 1:
            raise refused("exactly one SQL statement is required")
        return statements[0]

    root = parse_one(sql)
    # SQLGlot represents Snowflake EXPLAIN as an opaque Command. Parse its body
    # separately rather than admitting all Commands or trusting its leading word.
    if isinstance(root, exp.Command) and str(root.this).upper() == "EXPLAIN":
        body = root.args.get("expression")
        if not isinstance(body, exp.Literal) or not body.is_string:
            raise refused("unsupported EXPLAIN body")
        inner = re.sub(r"^\s*USING\s+(?:TABULAR|JSON|TEXT)\b", "", body.this, count=1, flags=re.I)
        root = parse_one(inner)
        if not isinstance(root, (exp.Select, exp.SetOperation, exp.Subquery)):
            raise refused("EXPLAIN requires a read query")
    elif isinstance(root, exp.Use):
        kind = root.args.get("kind")
        kind = str(getattr(kind, "this", kind) or "").upper()
        if kind not in {"", "DATABASE", "SCHEMA", "WAREHOUSE"}:
            raise refused("USE ROLE and USE SECONDARY ROLES are not allowed")
    elif not isinstance(root, (exp.Select, exp.SetOperation, exp.Subquery, exp.Show, exp.Describe)):
        raise refused(f"statement {type(root).__name__!r} is not allowed")

    for node in root.walk():
        if isinstance(node, (exp.DML, exp.DDL, exp.Command, exp.Into, exp.Lock, exp.NextValueFor)):
            raise refused(f"blocked SQL node {type(node).__name__!r}")
        if isinstance(node, exp.CTE) and not isinstance(node.this, (exp.Select, exp.SetOperation, exp.Subquery)):
            raise refused("a CTE must contain a read query")
        # Sequence advancement and SYSTEM$ administrative calls can have effects
        # even inside SELECT. Database grants still govern user-defined functions.
        if isinstance(node, exp.Column) and node.name.upper() == "NEXTVAL":
            raise refused("sequence advancement is not allowed")
        if isinstance(node, exp.Anonymous) and node.name.upper().startswith("SYSTEM$"):
            raise refused("SYSTEM$ calls are not allowed")
    return statement_type(sql)


def sanitize_identifier(name: str) -> str:
    value = name.strip()
    if not value or not _IDENT_RE.fullmatch(value):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return value


def split_identifier(name: str) -> list[str]:
    """Split a validated identifier without breaking dots inside quoted parts."""
    value = sanitize_identifier(name)
    parts: list[str] = []
    current: list[str] = []
    in_quotes = False
    i = 0
    while i < len(value):
        char = value[i]
        if char == '"':
            current.append(char)
            if in_quotes and i + 1 < len(value) and value[i + 1] == '"':
                current.append('"')
                i += 2
                continue
            in_quotes = not in_quotes
        elif char == "." and not in_quotes:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
        i += 1
    parts.append("".join(current))
    return parts


def identifier_value(part: str) -> str:
    """Return the Snowflake object name represented by one identifier part."""
    parts = split_identifier(part)
    if len(parts) != 1:
        raise ValueError(f"Expected one SQL identifier part, got {part!r}")
    value = parts[0]
    if value.startswith('"'):
        return value[1:-1].replace('""', '"')
    return value.upper()


def quote_sql_string(value: str) -> str:
    """Safely quote a value for SQL syntax that does not support bind parameters."""
    escaped = value.replace("\\", "\\\\").replace("'", "''")
    return f"'{escaped}'"


def sanitize_like_pattern(pattern: str) -> str:
    value = pattern.strip()
    if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"Invalid LIKE pattern: {pattern!r}")
    return value


def normalize_object_name(name: str) -> str:
    return ".".join(identifier_value(part).upper() for part in split_identifier(name))


def qualify_name(name: str, *, database: str, schema: str | None) -> str:
    parts = [identifier_value(part).upper() for part in split_identifier(name)]
    normalized = ".".join(parts)
    if len(parts) == 3:
        return normalized
    if len(parts) == 2:
        return f"{database.upper()}.{normalized}"
    if schema:
        return f"{database.upper()}.{schema.upper()}.{normalized}"
    return normalized
