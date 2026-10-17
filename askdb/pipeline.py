"""ask(question, config) -> result. The API, the UI and the eval script all call this."""
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from . import llm
from .charts import choose_chart
from .executor import ExecResult, run_query
from .fewshot import pick_examples
from .guard import GuardError, check_sql
from .prompts import build_answer_prompt, build_sql_prompt
from .schema_index import all_tables, describe_tables, retrieve_tables
from .config import settings


@dataclass
class PipelineConfig:
    use_schema_retrieval: bool = True
    use_fewshot: bool = True
    max_retries: int = 2
    top_k_tables: int = 4
    n_examples: int = 3
    write_answer: bool = True   # the eval turns this off: it only scores the SQL


@dataclass
class AskResult:
    question: str
    sql: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    chart: dict = field(default_factory=lambda: {"type": "table"})
    answer: str | None = None
    attempts: int = 0
    latency_ms: int = 0
    status: str = "ok"          # "ok" | "blocked" | "failed"
    reason: str | None = None


def ask(question: str, config: PipelineConfig | None = None,
        complete: Callable[[str], str] | None = None,
        run: Callable[[str], ExecResult] = run_query) -> AskResult:
    """
    1. schema   = retrieve top-k tables (or full schema if retrieval is off)
    2. examples = pick few-shot examples (or none)
    3. prompt   -> LLM -> strip fences -> guard
       - guard fails  -> status "blocked" with the reason
    4. execute
       - error and retries left -> add the error to the prompt, go to 3
       - error and no retries   -> status "failed", return error + failed SQL
    5. answer sentence (LLM) + chart (rules)

    `complete` and `run` can be swapped for fakes in tests (no Groq, no database).
    """
    config = config or PipelineConfig()
    complete = complete or llm.complete
    start = time.perf_counter()
    result = AskResult(question=question)

    def finish(status: str, reason: str | None = None) -> AskResult:
        result.status, result.reason = status, reason
        result.latency_ms = int((time.perf_counter() - start) * 1000)
        return result

    try:
        # 1-2. context for the prompt
        tables = (retrieve_tables(question, config.top_k_tables)
                  if config.use_schema_retrieval else all_tables())
        schema = describe_tables(tables)
        examples = pick_examples(question, config.n_examples) if config.use_fewshot else []

        # 3-4. write SQL, check it, run it; on a database error, retry with the error
        previous_sql, error = None, None
        for attempt in range(1, config.max_retries + 2):
            result.attempts = attempt
            prompt = build_sql_prompt(question, schema, examples, previous_sql, error)
            sql = llm.strip_code_fences(complete(prompt))
            result.sql = sql
            try:
                # Any real table is allowed, not only the retrieved ones: if the model
                # needs a 5th table it should be able to use it.
                guarded = check_sql(sql, set(all_tables()), settings.row_limit)
            except GuardError as exc:
                return finish("blocked", str(exc))
            result.sql = guarded.sql

            executed = run(guarded.sql)
            if executed.ok:
                result.columns, result.rows = executed.columns, executed.rows
                break
            previous_sql, error = guarded.sql, executed.error
        else:
            return finish("failed", f"Query failed after {result.attempts} attempt(s): {error}")

        # 5. one-sentence answer + chart
        result.chart = choose_chart(result.columns, result.rows)
        if config.write_answer:
            result.answer = complete(build_answer_prompt(question, result.columns, result.rows)).strip()
        return finish("ok")
    except Exception as exc:  # LLM/network/config problems become a failed result, not a crash
        return finish("failed", f"{type(exc).__name__}: {exc}")
