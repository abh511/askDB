"""SQL safety checks with sqlglot (not regex).

sqlglot parses the SQL into a tree, so the checks look at what the query *is*, not at
what its text looks like. A regex for "DELETE" would block a column named
deleted_at and miss a DELETE hidden inside a CTE; the tree catches both correctly.
"""
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError


class GuardError(ValueError):
    """Raised when a query is not allowed; the message explains why."""


@dataclass
class GuardResult:
    sql: str            # possibly rewritten (LIMIT added)
    tables: list[str]


# Node types that write, change the schema, change settings or take locks. They are
# rejected anywhere in the tree, e.g. "WITH d AS (DELETE ... RETURNING *) SELECT ..."
# parses as a SELECT at the top but has a DELETE inside.
FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge,          # write data
    exp.Drop, exp.Alter, exp.Create, exp.TruncateTable,     # change schema
    exp.Grant, exp.Revoke,                                  # change permissions
    exp.Copy, exp.Set, exp.Command,                         # files, settings, unknown commands
    exp.Into,                                               # SELECT ... INTO creates a table
    exp.Lock,                                               # SELECT ... FOR UPDATE takes locks
)


def check_sql(sql: str, allowed_tables: set[str], row_limit: int = 500) -> GuardResult:
    """
    - exactly one statement
    - it is a SELECT (no INSERT/UPDATE/DELETE/DROP/ALTER/...)
    - every table is in allowed_tables
    - add LIMIT row_limit if missing (and lower a bigger literal LIMIT)
    """
    if not sql or not sql.strip():
        raise GuardError("The query is empty.")

    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except ParseError as exc:
        raise GuardError(f"The query could not be parsed as PostgreSQL: {str(exc).splitlines()[0]}")

    if len(statements) != 1:
        raise GuardError(f"Exactly one statement is allowed, got {len(statements)}.")
    stmt = statements[0]

    # exp.Query covers SELECT, UNION/INTERSECT/EXCEPT and a bracketed SELECT.
    if not isinstance(stmt, exp.Query):
        raise GuardError(f"Only SELECT queries are allowed, got {stmt.key.upper()}.")

    for node in stmt.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise GuardError(f"{node.key.upper()} is not allowed; only read-only SELECT queries can run.")

    tables = _referenced_tables(stmt)
    allowed = {t.lower() for t in allowed_tables}
    unknown = [t for t in tables if t not in allowed]
    if unknown:
        raise GuardError(f"Unknown table(s): {', '.join(unknown)}. "
                         f"Allowed tables: {', '.join(sorted(allowed))}.")

    new_stmt, changed = _apply_row_limit(stmt, row_limit)
    final_sql = new_stmt.sql(dialect="postgres") if changed else sql.strip().rstrip(";").strip()
    return GuardResult(sql=final_sql, tables=tables)


def _referenced_tables(stmt: exp.Expression) -> list[str]:
    """Real tables the query reads; CTE names and table functions are not tables."""
    cte_names = {cte.alias_or_name.lower() for cte in stmt.find_all(exp.CTE)}
    tables: set[str] = set()
    for table in stmt.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):   # e.g. FROM generate_series(1, 3)
            continue
        name = table.name.lower()
        schema = table.db.lower()
        if schema and schema != "public":                # e.g. pg_catalog.pg_user
            tables.add(f"{schema}.{name}")
        elif name not in cte_names:
            tables.add(name)
    return sorted(tables)


def _apply_row_limit(stmt: exp.Query, row_limit: int) -> tuple[exp.Query, bool]:
    """Add LIMIT row_limit when there is none; lower a literal LIMIT above row_limit."""
    limit = stmt.args.get("limit")
    if limit is None:
        # FETCH FIRST n ROWS is another way to write LIMIT; leave it alone
        # (the executor also stops reading after row_limit rows).
        if stmt.find(exp.Fetch) is not None:
            return stmt, False
        return stmt.limit(row_limit), True
    value = limit.args.get("expression")
    if isinstance(value, exp.Literal) and value.is_int and int(value.name) > row_limit:
        new_stmt = stmt.copy()
        new_stmt.args["limit"].set("expression", exp.Literal.number(row_limit))
        return new_stmt, True
    return stmt, False
