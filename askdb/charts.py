"""Rule-based chart choice (not the LLM).

Rules are predictable, free and testable; asking the LLM would add a call, latency and
a new way to be wrong for a decision three if-statements can make.
"""
import datetime as dt

# Integer columns with these names are time axes too (e.g. "orders per year").
TIME_COLUMN_NAMES = {"year", "month", "quarter", "week", "day"}


def _values(rows: list[list], i: int) -> list:
    return [row[i] for row in rows if row[i] is not None]


def _is_number(values: list) -> bool:
    return bool(values) and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values)


def _is_date(values: list) -> bool:
    if not values or not all(isinstance(v, str) for v in values):
        return False
    try:
        for v in values:
            dt.datetime.fromisoformat(v)
    except ValueError:
        return False
    return True


def _is_text(values: list) -> bool:
    return bool(values) and all(isinstance(v, str) for v in values) and not _is_date(values)


def choose_chart(columns: list[str], rows: list[list]) -> dict:
    """
    date column                     -> {"type": "line", "x": ..., "y": ...}
    one text + one number column    -> {"type": "bar", "x": ..., "y": ...}
    otherwise                       -> {"type": "table"}
    """
    if len(rows) < 2 or len(columns) < 2:
        return {"type": "table"}          # a single number or a single row needs no chart

    kinds = []
    for i, name in enumerate(columns):
        values = _values(rows, i)
        if _is_date(values) or (name.lower() in TIME_COLUMN_NAMES and _is_number(values)):
            kinds.append("date")
        elif _is_number(values):
            kinds.append("number")
        elif _is_text(values):
            kinds.append("text")
        else:
            kinds.append("other")

    if "date" in kinds and "number" in kinds:
        return {"type": "line", "x": columns[kinds.index("date")], "y": columns[kinds.index("number")]}
    if sorted(kinds) == ["number", "text"]:
        return {"type": "bar", "x": columns[kinds.index("text")], "y": columns[kinds.index("number")]}
    return {"type": "table"}
