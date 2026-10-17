"""Guards for the eval set itself: right size, right tiers, and no leakage into the few-shot bank."""
import json
import re
from collections import Counter

from askdb.config import ROOT

EVAL = [json.loads(l) for l in (ROOT / "eval" / "questions.jsonl").read_text().splitlines() if l.strip()]
BANK = [json.loads(l) for l in (ROOT / "data" / "fewshot_bank.jsonl").read_text().splitlines() if l.strip()]


def words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", text.lower()))


def jaccard(a: str, b: str) -> float:
    wa, wb = words(a), words(b)
    return len(wa & wb) / len(wa | wb)


def test_eval_set_shape():
    assert len(EVAL) == 100
    assert Counter(q["difficulty"] for q in EVAL) == {"easy": 33, "medium": 40, "hard": 27}
    assert len({q["id"] for q in EVAL}) == 100
    for q in EVAL:
        assert set(q) == {"id", "question", "gold_sql", "difficulty", "ordered"}


def test_fewshot_bank_size():
    assert 25 <= len(BANK) <= 40
    assert len({b["id"] for b in BANK}) == len(BANK)


def test_no_eval_question_in_fewshot_bank():
    for q in EVAL:
        for b in BANK:
            assert jaccard(q["question"], b["question"]) < 0.6, (q["id"], b["id"])


def test_no_gold_sql_in_fewshot_bank():
    normalize = lambda s: " ".join(s.lower().replace(";", "").split())
    gold = {normalize(q["gold_sql"]) for q in EVAL}
    for b in BANK:
        assert normalize(b["sql"]) not in gold, b["id"]
