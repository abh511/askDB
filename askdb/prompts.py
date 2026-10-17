"""Prompt templates. Bump PROMPT_VERSION on every change so MLflow can track it."""

PROMPT_VERSION = "v3"  # v2: clear sections + explicit task (v1 examples confused gpt-oss)
                       # v3: answer prompt never claims data was changed

RULES = """\
- Write a single PostgreSQL SELECT query.
- Use only the tables and columns given below.
- Follow every NOTE in the schema; they define business terms such as revenue and customer.
- For any category name in the output, join category_translation and return product_category_name_english.
- Select exactly the columns the question asks for, in the order it mentions them.
- Express percentages on a 0-100 scale.
- Return only SQL, no explanation.
"""

ANSWER_ROWS = 20  # the answer sentence is written from the first 20 rows only


def build_sql_prompt(question: str, schema: str, examples: list[dict],
                     previous_sql: str | None = None, error: str | None = None) -> str:
    """Schema + examples + rules (+ the last error, on a retry)."""
    # Clear sections and an explicit task at the end: without them the model can mistake
    # the real question for one more example and never answer it.
    parts = [
        "You are an expert data analyst writing PostgreSQL for an e-commerce database "
        "(Olist, Brazil, 2016-2018, money in R$).",
        f"## Rules\n{RULES}",
        f"## Schema\n{schema}",
    ]
    if examples:
        shown = "\n\n".join(f"Example {i}\nQuestion: {ex['question']}\nSQL: {ex['sql']}"
                            for i, ex in enumerate(examples, 1))
        parts.append(f"## Examples of solved questions (for reference only)\n{shown}")
    if previous_sql and error:
        parts.append(
            "## Your previous attempt failed\n"
            f"Previous SQL:\n{previous_sql}\n"
            f"Database error:\n{error}\n"
            "Write a corrected query."
        )
    parts.append(f"## Task\nWrite one PostgreSQL SELECT query that answers this question:\n{question}")
    return "\n\n".join(parts)


def build_answer_prompt(question: str, columns: list[str], rows: list[list]) -> str:
    """Ask for one sentence from the first 20 rows."""
    shown = rows[:ANSWER_ROWS]
    table = "\n".join([" | ".join(columns)] + [" | ".join(str(v) for v in row) for row in shown])
    more = f"\n(showing {len(shown)} of {len(rows)} rows)" if len(rows) > len(shown) else ""
    return (
        "Answer the question in ONE short sentence using only the query result below. "
        "Use R$ for money and round numbers sensibly. Do not mention SQL or tables. "
        "This system can only read data: never say that anything was deleted, changed or created. "
        "If the result is empty, say that no matching data was found.\n\n"
        f"Question: {question}\n\nResult:\n{table}{more}\n\nAnswer:"
    )
