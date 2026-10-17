"""Run a guarded query and turn database errors into data, not exceptions."""
import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

from .config import settings
from .db import get_engine


@dataclass
class ExecResult:
    ok: bool
    columns: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    error: str | None = None


def to_json_value(value: object) -> object:
    """Database values -> plain JSON values (Decimal -> float, dates -> ISO text)."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (dt.date, dt.datetime, dt.time)):
        return value.isoformat()
    return str(value)


def run_query(sql: str, max_rows: int = settings.row_limit) -> ExecResult:
    """Execute on the read-only engine; on failure return ok=False with the error text."""
    try:
        with get_engine().connect() as conn:
            # Use the driver's cursor with no parameters, so characters like % and :
            # in the SQL are sent to Postgres as-is instead of being read as placeholders.
            cur = conn.connection.driver_connection.cursor()
            cur.execute(sql)
            columns = [d.name for d in cur.description or []]
            rows = [[to_json_value(v) for v in row] for row in cur.fetchmany(max_rows)]
            conn.rollback()  # we never write; end the transaction cleanly
        return ExecResult(ok=True, columns=columns, rows=rows)
    except Exception as exc:  # any DB error becomes data the retry loop can use
        message = str(exc).strip() or type(exc).__name__
        return ExecResult(ok=False, error=message)
