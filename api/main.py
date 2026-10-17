"""FastAPI: POST /ask, GET /health, web UI at /. Docs at /docs."""
import logging
from dataclasses import asdict

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from askdb.config import ROOT
from askdb.executor import run_query
from askdb.pipeline import ask
from askdb.querylog import log_query

logging.basicConfig(level=logging.WARNING)
logging.getLogger("askdb").setLevel(logging.INFO)

app = FastAPI(title="AskDB", description="Ask business questions about the Olist e-commerce data.")


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class AskResponse(BaseModel):
    question: str
    sql: str | None
    columns: list[str]
    rows: list[list]
    chart: dict
    answer: str | None
    attempts: int
    latency_ms: int
    status: str
    reason: str | None = None


@app.get("/health")
def health() -> dict:
    db = run_query("SELECT 1")
    return {"status": "ok" if db.ok else "degraded", "database": "ok" if db.ok else db.error}


# A plain `def` (not async): FastAPI runs it in a thread pool, so a slow LLM call
# doesn't block other requests.
@app.post("/ask", response_model=AskResponse)
def ask_endpoint(req: AskRequest) -> AskResponse:
    result = ask(req.question)
    log_query(result)
    return AskResponse(**asdict(result))


# The web UI (plain HTML/JS in web/) is served at "/". Mounted last, so /ask, /health and
# /docs above take priority.
app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
