"""Pick the 3 most similar solved questions from data/fewshot_bank.jsonl.

The bank must never overlap with eval/questions.jsonl, or the accuracy number is fake.
tests/test_data_integrity.py checks this.
"""
import json
from functools import lru_cache

from .config import settings
from .vectors import nearest

COLLECTION = "fewshot"


@lru_cache
def load_bank() -> dict[str, dict]:
    bank = {}
    with open(settings.fewshot_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                item = json.loads(line)
                bank[item["id"]] = item
    return bank


def pick_examples(question: str, n: int = 3) -> list[dict]:
    """Return [{"question": ..., "sql": ...}, ...] most similar to the question."""
    bank = load_bank()
    # Only the question text is embedded: we match on what is being asked, not on SQL.
    documents = {item_id: item["question"] for item_id, item in bank.items()}
    ids = nearest(COLLECTION, documents, question, n)
    return [{"question": bank[i]["question"], "sql": bank[i]["sql"]} for i in ids]
