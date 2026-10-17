# CLAUDE.md — AskDB

This file guides Claude Code when working in this repository. Read it fully before making changes.

## Project in one paragraph

AskDB is a natural-language analytics agent. A user asks a business question in plain English;
AskDB finds the relevant tables, writes one PostgreSQL query, runs it safely on the Olist
e-commerce database, and answers with the SQL, a result table, a chart and one sentence.
What makes it stand out: **accuracy is measured** on a hand-written eval set, and every
improvement is proven with numbers logged in MLflow.

Owner: Abhishek Bhosale. This is a portfolio/resume project, so the owner must be able to
explain every line in an interview (see "How to work with me" below).

Example:
- Question: "Which 5 product categories earned the most revenue in 2017?"
- SQL: joins `order_items → orders → products → category_translation`, filters
  `order_status = 'delivered'` and year 2017, `SUM(price)`, `ORDER BY revenue DESC LIMIT 5`
- Answer: "Health & beauty led 2017 revenue at about R$5.4 lakh, followed by watches & gifts."

## The four pieces (one repo)

1. **Agent pipeline** — Python package `askdb/` that turns a question into safe SQL, runs it,
   and fixes its own mistakes when the database returns an error.
2. **Evaluation harness** — 100 hand-written questions with gold SQL (`eval/questions.jsonl`);
   `eval/run_eval.py` scores a pipeline config and logs to MLflow.
3. **App** — FastAPI backend (`POST /ask`, `GET /health`) that also serves the web UI
   (`web/`, plain HTML/JS + Plotly.js) at `/`, plus a Streamlit page; both show SQL, table,
   chart and one-line answer.
4. **Deployment** — `docker compose up` locally; deployed to a free host for a live link.

## Commands

```bash
# setup
python -m venv .venv && source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu   # CPU-only torch first (no CUDA)
pip install -r requirements.txt
cp .env.example .env                     # add GROQ_API_KEY

# database (Olist CSVs from Kaggle go in data/raw/)
docker compose up -d postgres            # runs db/init/*.sql on first start
python -m db.load_data                   # CSVs → PostgreSQL (admin user)
docker compose down -v                   # wipe DB volume (re-runs init scripts next start)

# run
uvicorn api.main:app --reload            # web UI + API on :8000, docs at /docs
streamlit run app/streamlit_app.py       # UI on :8501
docker compose up --build                # everything

# evaluate
python -m eval.run_eval --check-gold                     # validate all gold SQL, no LLM calls
python -m eval.run_eval                                  # baseline: full schema, zero-shot
python -m eval.run_eval --retrieval                      # + schema retrieval
python -m eval.run_eval --retrieval --fewshot            # + few-shot
python -m eval.run_eval --retrieval --fewshot --retries 2  # + error-feedback retry
python -m eval.run_eval ... --resume                     # continue an interrupted run (progress saved per question)
# rate limits (Groq free tier) are waited out and retried, never scored as wrong answers
mlflow ui --backend-store-uri sqlite:///mlflow.db        # view runs (MLflow 3 refuses file:./mlruns)

# tests
pytest -q
```

Always run commands from the repo root. Scripts are run as modules (`python -m db.load_data`,
`python -m eval.run_eval`) so the `askdb` package is importable.

## Repository layout

```
askdb/
├── README.md               # problem, demo GIF, architecture, results table
├── docker-compose.yml      # postgres + api + ui
├── Dockerfile
├── requirements.txt
├── .env.example            # GROQ_API_KEY, DATABASE_URL (never commit .env)
├── data/
│   ├── raw/                # Olist CSVs (gitignored)
│   ├── schema_docs.yaml    # plain-English notes on every table and column
│   └── fewshot_bank.jsonl  # ~30 question → SQL pairs for the prompt
├── db/
│   ├── init/01_schema.sql  # CREATE TABLE, keys, indexes
│   ├── init/02_readonly.sql# askdb_reader role, GRANT SELECT, statement_timeout
│   └── load_data.py        # CSVs → PostgreSQL
├── askdb/                  # core package — ALL agent logic lives here
│   ├── config.py           # settings from env vars
│   ├── db.py               # read-only engine, 5 s timeout
│   ├── vectors.py          # ChromaDB helper; rebuilds a collection when its source file changes
│   ├── schema_index.py     # build + query ChromaDB table index; column types parsed from 01_schema.sql
│   ├── fewshot.py          # pick 3 similar examples
│   ├── prompts.py          # templates + PROMPT_VERSION
│   ├── llm.py              # Groq client, temperature 0, strip code fences
│   ├── guard.py            # sqlglot checks, LIMIT injection
│   ├── executor.py         # run query, catch errors
│   ├── charts.py           # rule-based chart choice
│   ├── querylog.py         # append every /ask call to logs/queries.jsonl
│   └── pipeline.py         # ask(question, config) → result; retry loop lives here
├── api/main.py             # FastAPI: POST /ask, GET /health, serves web/ at /
├── web/                    # web UI: index.html, app.js, styles.css (no build step)
├── app/streamlit_app.py    # Streamlit UI (alternative)
├── docs/GUIDE.md           # user guide: flow, worked example, question types
├── eval/
│   ├── questions.jsonl     # 100 questions: id, question, gold_sql, difficulty, ordered
│   ├── compare.py          # result-set comparison
│   ├── run_eval.py         # score one config, log to MLflow
│   └── results/            # CSV of every run, failure examples
├── notebooks/01_explore_olist.ipynb
└── tests/                  # test_guard, test_compare, test_pipeline, test_charts, test_data_integrity
```

**Architecture rule:** agent logic lives only in `askdb/`. The API, the Streamlit app and the
eval script all call the same `askdb.pipeline.ask()`; the web UI only calls the API. Never put
pipeline logic inside `api/`, `app/` or `web/`.

## Pipeline: how a question becomes an answer

```
Streamlit → FastAPI POST /ask → schema retriever (top 4 tables, ChromaDB)
→ few-shot picker (3 similar solved questions) → prompt builder
→ LLM writes one SQL query (gpt-oss-120b on Groq)     [LLM call]
→ SQL guard ── blocked → refuse and explain why
→ run on PostgreSQL (read-only user, 5 s timeout, LIMIT 500)
→ did it run? ── error + retries left (max 2) → add error to prompt → LLM again
              ── error + no retries → return error + failed SQL
→ one-sentence answer (LLM, first 20 rows) + chart type (rules)   [LLM call]
→ response: SQL + table + chart + answer → query log
```

Only two steps call the LLM. Everything else is plain Python — that is where most of the
engineering lives.

### Step-by-step rules

1. **Schema retriever** (`schema_index.py`) — Olist has 9 tables; sending all confuses the
   model. Embed each table's description from `data/schema_docs.yaml` with
   `all-MiniLM-L6-v2` into a persistent ChromaDB collection; return the 4 closest tables.
2. **Few-shot picker** (`fewshot.py`) — bank of ~30 question → SQL pairs in
   `data/fewshot_bank.jsonl`; retrieve the 3 most similar. **The bank must never overlap
   with the eval questions** — otherwise the accuracy number is fake.
3. **Prompt builder** (`prompts.py`) — fixed rules: PostgreSQL dialect; use only the given
   tables; always join `category_translation` for category names; return only SQL.
   Every prompt change bumps `PROMPT_VERSION` so MLflow can track it.
4. **LLM call** (`llm.py`) — Groq, `openai/gpt-oss-120b` (name from `GROQ_MODEL`; check the
   Groq console for the current one). Free tier: 1,000 requests/day, 8,000 tokens/minute. `temperature=0` for repeatable results. Strip code
   fences from the reply before using it.
5. **SQL guard** (`guard.py`) — parse with **sqlglot, never regex**. Allow exactly one
   `SELECT` statement; block INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE, GRANT
   and multiple statements; reject unknown tables; add `LIMIT 500` if missing.
6. **Executor** (`executor.py`) — connect as `askdb_reader` (SELECT-only), with
   `statement_timeout = 5s`. Even if the guard has a bug, the DB can't be damaged — two
   layers of safety. Return errors as data, don't raise.
7. **Self-correction loop** (`pipeline.py`) — if Postgres errors (e.g.
   `column "price" does not exist`), send the failed SQL + error back to the LLM and ask for
   a fix. At most 2 retries. Measure how much this adds.
8. **Answer and chart** — LLM writes one sentence from the first 20 rows. Chart type is
   chosen by **rules, not the LLM** (`charts.py`): date column → line; one text + one number
   column → bar; otherwise table only.

### API contract — `POST /ask` response

```json
{
  "question": "Which 5 product categories earned the most revenue in 2017?",
  "sql": "SELECT t.product_category_name_english AS category, ...",
  "columns": ["category", "revenue"],
  "rows": [["health_beauty", 540000.00], ["watches_gifts", 490000.00]],
  "chart": {"type": "bar", "x": "category", "y": "revenue"},
  "answer": "Health & beauty led 2017 revenue at about R$5.4 lakh.",
  "attempts": 1,
  "latency_ms": 1840,
  "status": "ok",
  "reason": null
}
```

`status` is `"ok"`, `"blocked"` (guard refused; `reason` explains) or `"failed"` (ran out of
retries; return the error and the failed SQL). Keep `askdb.pipeline.AskResult` and
`api.main.AskResponse` in sync with this contract.

## Evaluation (the most important part)

- `eval/questions.jsonl`: 100 questions, each `{id, question, gold_sql, difficulty, ordered}`.
  Tiers: **33 easy** (one table, filters), **40 medium** (joins, GROUP BY, dates),
  **27 hard** (3+ joins, window functions, "repeat customers", cohorts, growth).
  Expanded from 60 to 100 on 2026-10-17 at the owner's request, before any scored run.
- **Execution accuracy**: generated SQL returns the same rows as the gold SQL. In
  `eval/compare.py`: compare results as multisets of rows, round decimals to 2 places,
  ignore column names, care about row order only when `ordered` is true (ranking questions).
  Compare results, not SQL text — two different queries can both be correct.
- `run_eval.py` logs to MLflow: config flags, `PROMPT_VERSION`, model name, accuracy overall
  and per difficulty. Saves per-question CSV and failure examples to `eval/results/`.

Results table to fill (README + resume):

| Configuration                    | Easy | Medium | Hard | Overall |
|----------------------------------|------|--------|------|---------|
| Baseline: full schema, zero-shot | __%  | __%    | __%  | __%     |
| + schema retrieval               | __%  | __%    | __%  | __%     |
| + few-shot examples              | __%  | __%    | __%  | __%     |
| + error-feedback retry           | __%  | __%    | __%  | __%     |

Add **one change at a time** and re-score after each.

### Eval integrity — never break these

- Never edit `gold_sql` or a question to make a score go up. If a gold query looks wrong,
  stop and tell me.
- Never copy eval questions (or near-paraphrases) into `fewshot_bank.jsonl`.
- Never hard-code answers or special-case eval questions in prompts or code.
- Report numbers honestly. If an improvement doesn't help, keep it in the table with a
  one-line explanation (e.g. "few-shot hurt hard questions because examples were too simple").

## The data: Olist Brazilian e-commerce

Free Kaggle dataset, ~100K orders from 2016–2018, 9 tables. Traps that must be documented in
`data/schema_docs.yaml` and respected in any SQL you write:

| Table                  | Contents                          | Trap |
|------------------------|-----------------------------------|------|
| `orders`               | status + 5 timestamps             | Revenue questions usually filter `order_status = 'delivered'` |
| `order_items`          | one row per item, price, freight  | Revenue = `SUM(price)`, not COUNT of orders |
| `order_payments`       | type, installments, value         | One order can have several payment rows |
| `order_reviews`        | score 1–5, comments               | Comments are in Portuguese; `review_id` not unique |
| `customers`            | city, state, zip prefix           | `customer_id` is **per order**; use `customer_unique_id` for repeat customers |
| `products`             | category, size, weight            | Category names in Portuguese; columns spelled `..._lenght` |
| `category_translation` | Portuguese → English names        | Join it for any category output |
| `sellers`              | seller city and state             | — |
| `geolocation`          | lat/long per zip prefix           | Duplicate rows per zip; rarely needed |

Use `order_purchase_timestamp` for "in 2017" style questions. Zip prefixes are TEXT (leading
zeros). Currency is Brazilian real (R$).

## Tech stack (don't swap without asking)

| Layer        | Choice                                   |
|--------------|------------------------------------------|
| Language     | Python 3.11                              |
| Database     | PostgreSQL 16 in Docker                  |
| DB access    | SQLAlchemy 2.x + psycopg                 |
| LLM          | Groq API, `openai/gpt-oss-120b` (free tier), temperature 0 — Llama 70B was retired by Groq; swap approved 2026-10-17 |
| LLM wrapper  | `langchain-groq` — chat-model call only  |
| Embeddings   | sentence-transformers `all-MiniLM-L6-v2` |
| Vector store | ChromaDB (local persistent, `CHROMA_DIR`)|
| SQL safety   | sqlglot                                  |
| API          | FastAPI + Pydantic v2                    |
| Frontend     | Web UI in `web/` (HTML/JS + Plotly.js, served by FastAPI) + Streamlit + Plotly |
| Experiments  | MLflow (local tracking)                  |
| Testing      | pytest                                   |
| Packaging    | Docker + Docker Compose                  |
| Hosting      | Neon or Supabase (Postgres) + Hugging Face Spaces or Render |

LangChain is used **only** for the chat-model call. Do not use LangChain agents, SQL chains,
`SQLDatabaseChain`, `create_sql_agent` or similar — the pipeline logic is hand-written so it
can be explained step by step. If LangChain ends up unused, remove it from requirements.

## Coding conventions

- Type hints everywhere; dataclasses or Pydantic models for structured data.
- Settings only via `askdb/config.py` (env vars / `.env`). No hard-coded keys, URLs or passwords.
- Keep functions small and pure where possible so they can be unit-tested without a DB or LLM.
- Mock the LLM in tests (`tests/test_pipeline.py`); never call Groq from pytest.
- Tests must cover: guard (DROP blocked, multiple statements blocked, unknown table blocked,
  SELECT allowed, LIMIT added), compare (order, rounding, column names), retry loop.
- Log every `/ask` call (question, SQL, status, attempts, latency).
- Bump `PROMPT_VERSION` in `prompts.py` whenever any prompt text changes.

## Safety rules

- The app and eval connect **only** as `askdb_reader`. `DATABASE_ADMIN_URL` is used only by
  `db/load_data.py`.
- Never weaken the guard or the read-only role to make a query pass.
- Never commit `.env`, data CSVs, `.chroma/`, `mlflow.db`, `mlruns/` or `logs/`.
- Change the default passwords in `02_readonly.sql` / compose before any public deploy.

## Build plan (~4 weeks) — update status as we go

**Week 1 · Data** — Done when: I can answer business questions in SQL without help.
- [x] Postgres in Docker Compose; load the 9 CSVs
- [x] Read-only role created; verify `DELETE` fails as `askdb_reader`
- [x] EDA notebook; write `schema_docs.yaml`
- [x] Write 15 SQL queries by hand → first eval questions (all 100 drafted by Claude — owner review pending)

**Week 2 · Baseline** — Done when: baseline score + list of failure types exist.
- [x] `llm.py`, `prompts.py`, `guard.py`, `executor.py`
- [x] Full-schema zero-shot `pipeline.ask()`
- [x] All 100 eval questions; `compare.py`
- [ ] Baseline run logged in MLflow (needs GROQ_API_KEY)

**Week 3 · Improve, one change at a time** — Done when: results table has real numbers.
- [ ] Schema retrieval with ChromaDB → re-score (built, not scored)
- [ ] Few-shot bank + picker → re-score (built, not scored)
- [ ] Error-feedback retry loop → re-score (built, not scored)
- [x] pytest for guard, comparison, retry logic

**Week 4 · Ship** — Done when: a stranger can open the link and ask a question.
- [x] FastAPI `/ask` + web UI (`web/`) + Streamlit UI with Plotly charts
- [ ] Dockerize; deploy; live link (Dockerized; not deployed)
- [ ] README: architecture diagram, results table, demo GIF (diagram done; numbers + GIF pending)
- [ ] Update resume with real numbers

## How to work with me

- This is a learning project. When you implement something in `askdb/` or `eval/`, keep it
  simple and explain the key decisions briefly so I can defend them in an interview.
  Prefer readable code over clever code.
- For the core learning pieces (guard, retry loop, compare, eval runner), propose the
  approach first and confirm before writing a large implementation.
- Work in small steps that match the build plan; don't jump ahead weeks unless I ask.
- After a change, run `pytest -q` (and the relevant eval if pipeline behaviour changed) and
  report the result honestly.
- If something in this file conflicts with what I ask in chat, follow the chat and point out
  the conflict.

## Interview questions this project must answer

- **How do you know it's correct?** Execution accuracy on 100 hand-written questions, split
  by difficulty, every run logged in MLflow.
- **What stops it deleting the database?** sqlglot guard allows only SELECT + DB user has no
  write permission + timeout + row limit.
- **Why not send the whole schema?** Noise and cost; retrieval narrows to relevant tables —
  show before/after numbers.
- **Most common failure?** Read from `eval/results/` (likely wrong joins or
  `customer_id` vs `customer_unique_id`) and how it was fixed.
- **How did you avoid leaking the test set?** Few-shot bank and eval questions written
  separately, no overlap.
- **With more time?** Clarifying questions for vague inputs, caching repeated questions,
  comparing two LLMs on the same eval set.