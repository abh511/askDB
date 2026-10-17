"""Execution accuracy: do two result sets contain the same rows?

- compare as multisets of rows (duplicates count), ignoring column names
- round decimals to 2 places (and treat 3 and 3.0 as equal)
- ignore column order inside a row (category, revenue) == (revenue, category)
- respect row order only when the question asks for a ranking (ordered=True)

Comparing results instead of SQL text matters because two different queries can both
be correct.
"""
import datetime as dt
from collections import Counter


def normalize_value(value: object) -> object:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return round(float(value), 2) + 0.0     # + 0.0 turns -0.0 into 0.0
    if isinstance(value, str):
        value = value.strip()
        # a midnight timestamp and a date are the same day: '2018-01-01T00:00:00' == '2018-01-01'
        if len(value) > 10 and value[10] == "T":
            try:
                parsed = dt.datetime.fromisoformat(value)
                if parsed.time() == dt.time(0):
                    return parsed.date().isoformat()
            except ValueError:
                pass
        return value
    return value


def normalize_row(row: list) -> tuple:
    """Round numbers, then sort the values so column order does not matter."""
    values = [normalize_value(v) for v in row]
    # sort by (type name, value) so mixed types and None can be ordered
    return tuple(sorted(values, key=lambda v: (type(v).__name__, "" if v is None else v)))


def results_match(gold_rows: list[list], pred_rows: list[list], ordered: bool = False) -> bool:
    gold = [normalize_row(r) for r in gold_rows]
    pred = [normalize_row(r) for r in pred_rows]
    if ordered:
        return gold == pred
    return Counter(gold) == Counter(pred)
