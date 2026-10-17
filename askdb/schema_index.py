"""Embed schema_docs.yaml into ChromaDB and return the top-k relevant tables.

Column types come from db/init/01_schema.sql (parsed with sqlglot), so the prompt always
matches the real database and the descriptions live in one place: schema_docs.yaml.
"""
from functools import lru_cache

import sqlglot
import yaml
from sqlglot import exp

from .config import ROOT, settings
from .vectors import get_collection, nearest

COLLECTION = "tables"


@lru_cache
def load_docs() -> dict[str, dict]:
    with open(settings.schema_docs_path, encoding="utf-8") as f:
        return yaml.safe_load(f)["tables"]


@lru_cache
def column_types() -> dict[str, dict[str, str]]:
    """{table: {column: SQL type}} from the CREATE TABLE statements."""
    sql = (ROOT / "db" / "init" / "01_schema.sql").read_text(encoding="utf-8")
    types: dict[str, dict[str, str]] = {}
    for stmt in sqlglot.parse(sql, read="postgres"):
        if isinstance(stmt, exp.Create) and stmt.kind == "TABLE":
            table = stmt.this.this.name
            types[table] = {col.name: col.args["kind"].sql("postgres")
                            for col in stmt.find_all(exp.ColumnDef)}
    return types


def all_tables() -> list[str]:
    return list(load_docs())


def _embedding_text(table: str, doc: dict) -> str:
    # Short on purpose: all-MiniLM-L6-v2 only reads the first ~256 tokens.
    columns = ", ".join(doc.get("columns") or {})
    return f"{table}: {doc['description'].strip()} Columns: {columns}"


def _documents() -> dict[str, str]:
    return {table: _embedding_text(table, doc) for table, doc in load_docs().items()}


def build_index() -> None:
    """Embed one document per table into a persistent ChromaDB collection."""
    get_collection(COLLECTION, _documents())


def retrieve_tables(question: str, k: int = 4) -> list[str]:
    """Return the names of the k tables closest to the question."""
    return nearest(COLLECTION, _documents(), question, k)


def describe_tables(tables: list[str]) -> str:
    """Return the schema text (columns + notes) for these tables, for the prompt."""
    docs, types = load_docs(), column_types()
    blocks = []
    for table in tables:
        doc = docs[table]
        lines = [f"TABLE {table} -- {' '.join(doc['description'].split())}"]
        column_notes = doc.get("columns") or {}
        for column, sql_type in types[table].items():
            note = column_notes.get(column)
            lines.append(f"  {column} {sql_type}" + (f" -- {note}" if note else ""))
        for note in doc.get("notes") or []:
            lines.append(f"  NOTE: {note}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


if __name__ == "__main__":
    build_index()
    print("indexed tables:", ", ".join(all_tables()))
