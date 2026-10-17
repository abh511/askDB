"""The LLM and the database are replaced by fakes: no Groq calls, no Postgres."""
from askdb.executor import ExecResult
from askdb.pipeline import PipelineConfig, ask

# full schema + no few-shot keeps the test free of ChromaDB and the embedding model
CONFIG = PipelineConfig(use_schema_retrieval=False, use_fewshot=False, max_retries=2)


class FakeLLM:
    """Returns the given replies in order and records every prompt."""

    def __init__(self, *replies: str):
        self.replies = list(replies)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.replies.pop(0)


class FakeDB:
    """Fails for SQL containing 'bad_column', succeeds otherwise."""

    def __init__(self):
        self.queries: list[str] = []

    def __call__(self, sql: str) -> ExecResult:
        self.queries.append(sql)
        if "bad_column" in sql:
            return ExecResult(ok=False, error='column "bad_column" does not exist')
        return ExecResult(ok=True, columns=["n"], rows=[[42]])


def test_happy_path_one_attempt():
    llm = FakeLLM("```sql\nSELECT COUNT(*) AS n FROM orders\n```", "There are 42 orders.")
    result = ask("How many orders?", CONFIG, complete=llm, run=FakeDB())
    assert result.status == "ok"
    assert result.attempts == 1
    assert result.rows == [[42]]
    assert result.answer == "There are 42 orders."
    assert result.sql == "SELECT COUNT(*) AS n FROM orders LIMIT 500"


def test_retry_fixes_error_with_mocked_llm():
    llm = FakeLLM("SELECT bad_column FROM orders", "SELECT COUNT(*) AS n FROM orders", "42 orders.")
    db = FakeDB()
    result = ask("How many orders?", CONFIG, complete=llm, run=db)
    assert result.status == "ok"
    assert result.attempts == 2
    assert len(db.queries) == 2
    # the second prompt must contain the failed SQL and the database error
    assert "bad_column" in llm.prompts[1]
    assert 'column "bad_column" does not exist' in llm.prompts[1]
    assert "Previous SQL" not in llm.prompts[0]


def test_stops_after_max_retries():
    llm = FakeLLM(*["SELECT bad_column FROM orders"] * 3)
    db = FakeDB()
    result = ask("How many orders?", CONFIG, complete=llm, run=db)
    assert result.status == "failed"
    assert result.attempts == 3          # 1 try + 2 retries
    assert len(db.queries) == 3
    assert "does not exist" in result.reason
    assert result.sql is not None        # the failed SQL is returned


def test_zero_retries_means_one_attempt():
    llm = FakeLLM("SELECT bad_column FROM orders")
    cfg = PipelineConfig(use_schema_retrieval=False, use_fewshot=False, max_retries=0)
    result = ask("How many orders?", cfg, complete=llm, run=FakeDB())
    assert result.status == "failed"
    assert result.attempts == 1


def test_blocked_query_returns_reason():
    db = FakeDB()
    result = ask("Delete everything", CONFIG, complete=FakeLLM("DELETE FROM orders"), run=db)
    assert result.status == "blocked"
    assert "Only SELECT" in result.reason
    assert db.queries == []              # nothing reached the database


def test_llm_error_becomes_failed_result():
    def broken_llm(prompt: str) -> str:
        raise RuntimeError("GROQ_API_KEY is not set")

    result = ask("How many orders?", CONFIG, complete=broken_llm, run=FakeDB())
    assert result.status == "failed"
    assert "GROQ_API_KEY" in result.reason


def test_answer_skipped_when_disabled():
    cfg = PipelineConfig(use_schema_retrieval=False, use_fewshot=False, write_answer=False)
    llm = FakeLLM("SELECT COUNT(*) AS n FROM orders")
    result = ask("How many orders?", cfg, complete=llm, run=FakeDB())
    assert result.answer is None
    assert len(llm.prompts) == 1


def test_full_schema_prompt_contains_all_tables_and_traps():
    llm = FakeLLM("SELECT COUNT(*) AS n FROM orders", "ok")
    ask("How many orders?", CONFIG, complete=llm, run=FakeDB())
    prompt = llm.prompts[0]
    for table in ["orders", "order_items", "customers", "geolocation", "category_translation"]:
        assert f"TABLE {table}" in prompt
    assert "customer_unique_id" in prompt
    assert "How many orders?" in prompt
