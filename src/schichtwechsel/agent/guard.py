"""SQL guard for the analyst agent.

Every query the model writes passes through `check` before it runs. The
rules are an allowlist: one SELECT statement, reading only views in the
mart schema, no table functions, no functions that touch files, the
network or the catalog, and a row limit. The connection the agent uses is
also read-only with external access switched off, so this guard is the
first line, not the only one.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

MAX_ROWS = 200
SCHEMA = "mart"

# statement and clause types that never belong in an analysis query
FORBIDDEN_NODES = tuple(
    getattr(exp, name)
    for name in (
        "Insert",
        "Update",
        "Delete",
        "Merge",
        "Create",
        "Drop",
        "Alter",
        "Command",
        "Copy",
        "Pragma",
        "Set",
        "Use",
        "Transaction",
        "Commit",
        "Rollback",
        "Attach",
        "Detach",
        "Install",
        "Load",
        "Export",
        "Describe",
        "Show",
        "Into",
    )  # fmt: skip
    if hasattr(exp, name)
)

FORBIDDEN_FUNCTION_PREFIXES = ("read_", "duckdb_", "pragma_", "sniff_", "glob", "parquet_")
FORBIDDEN_FUNCTIONS = {
    "query", "query_table", "getenv", "current_setting", "csv_scan", "json_scan",
    "parquet_scan", "iceberg_scan", "delta_scan", "sqlite_scan", "postgres_scan",
    "httpfs", "read_text", "read_blob", "system", "shell", "load_extension",
}  # fmt: skip


class GuardError(ValueError):
    """The query breaks a rule. The message is shown to the model so it can fix the query."""


@dataclass(frozen=True)
class CheckedQuery:
    sql: str
    views: frozenset[str]


def _function_name(node: exp.Expression) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.this).lower()
    return (node.sql_name() if hasattr(node, "sql_name") else node.key).lower()


def check(sql: str, allowed_views: set[str]) -> CheckedQuery:
    try:
        statements = sqlglot.parse(sql, read="duckdb")
    except sqlglot.errors.ParseError as exc:
        raise GuardError(f"could not parse the query: {str(exc).splitlines()[0]}") from exc
    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise GuardError("send exactly one SELECT statement")
    tree = statements[0]
    if not isinstance(tree, exp.Select | exp.Union | exp.Except | exp.Intersect):
        raise GuardError("only SELECT queries are allowed")

    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise GuardError(f"{node.key.upper()} is not allowed")
        if isinstance(node, exp.Func):
            name = _function_name(node)
            if name in FORBIDDEN_FUNCTIONS or name.startswith(FORBIDDEN_FUNCTION_PREFIXES):
                raise GuardError(f"function {name} is not allowed")

    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    views = set()
    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            raise GuardError("table functions are not allowed; select from mart views")
        name, schema = table.name.lower(), table.db.lower()
        if not schema and name in cte_names:
            continue
        if table.catalog:
            raise GuardError("refer to views as mart.<view>")
        if schema != SCHEMA:
            raise GuardError(f"only views in the {SCHEMA} schema can be queried, not {table.sql()}")
        if name not in allowed_views:
            raise GuardError(f"unknown view {SCHEMA}.{name}")
        views.add(name)
    if not views:
        raise GuardError(f"the query must read from at least one {SCHEMA} view")

    limit = tree.args.get("limit")
    if limit is None:
        tree = tree.limit(MAX_ROWS + 1)
    else:
        value = limit.expression
        if not isinstance(value, exp.Literal) or not value.is_int:
            raise GuardError("LIMIT must be a whole number")
        if int(value.this) > MAX_ROWS + 1:
            tree = tree.limit(MAX_ROWS + 1)
    return CheckedQuery(sql=tree.sql(dialect="duckdb"), views=frozenset(views))
