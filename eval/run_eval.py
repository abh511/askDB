"""Score one pipeline config on eval/questions.jsonl and log it to MLflow.

    python -m eval.run_eval                                    # baseline: full schema, zero-shot
    python -m eval.run_eval --retrieval --fewshot --retries 2  # everything on
    python -m eval.run_eval --check-gold                       # only validate the gold SQL
"""
import os

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")  # silence an MLflow banner

import argparse
import csv
import json
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import mlflow

from askdb.config import ROOT, settings
from askdb.executor import run_query
from askdb.pipeline import PipelineConfig, ask
from askdb.prompts import PROMPT_VERSION
from eval.compare import results_match

QUESTIONS_PATH = ROOT / "eval" / "questions.jsonl"
RESULTS_DIR = ROOT / "eval" / "results"
DIFFICULTIES = ("easy", "medium", "hard")
GOLD_MAX_ROWS = 10_000  # gold results are read in full (the pipeline itself is capped at 500)
RATE_LIMIT_MARKERS = ("RateLimitError", "rate_limit_exceeded")
MAX_RATE_LIMIT_WAITS = 50


def load_questions(path: Path = QUESTIONS_PATH) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def config_label(cfg: PipelineConfig) -> str:
    parts = ["retrieval" if cfg.use_schema_retrieval else "fullschema",
             "fewshot" if cfg.use_fewshot else "zeroshot",
             f"retries{cfg.max_retries}"]
    return "-".join(parts)


def rate_limit_wait(reason: str | None) -> float | None:
    """Seconds to wait if the failure was a Groq rate limit, else None.

    A rate limit says nothing about the model's SQL, so it must never be scored as a
    wrong answer: the question is retried after waiting instead.
    """
    if not reason or not any(marker in reason for marker in RATE_LIMIT_MARKERS):
        return None
    m = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", reason)
    if not m or not any(m.groups()):
        return 60.0
    hours, minutes, seconds = (float(g) if g else 0.0 for g in m.groups())
    return hours * 3600 + minutes * 60 + seconds + 2


def evaluate_one(question: dict, cfg: PipelineConfig) -> dict:
    gold = run_query(question["gold_sql"], max_rows=GOLD_MAX_ROWS)
    if not gold.ok:
        # A broken gold query is a bug in the eval set, not a model mistake: stop loudly.
        raise RuntimeError(f"gold SQL for {question['id']} failed: {gold.error}")
    for _ in range(MAX_RATE_LIMIT_WAITS):
        pred = ask(question["question"], cfg)
        wait = rate_limit_wait(pred.reason) if pred.status == "failed" else None
        if wait is None:
            break
        print(f"    rate limited on {question['id']}; waiting {wait / 60:.1f} min, then retrying it", flush=True)
        time.sleep(wait)
    else:
        raise RuntimeError(f"still rate limited after {MAX_RATE_LIMIT_WAITS} waits; resume later with --resume")
    correct = pred.status == "ok" and results_match(gold.rows, pred.rows, question["ordered"])
    return {
        "id": question["id"],
        "difficulty": question["difficulty"],
        "correct": int(correct),
        "status": pred.status,
        "attempts": pred.attempts,
        "latency_ms": pred.latency_ms,
        "question": question["question"],
        "gold_sql": question["gold_sql"],
        "pred_sql": pred.sql,
        "reason": pred.reason,
        "gold_rows": len(gold.rows),
        "pred_rows": len(pred.rows),
        "gold_preview": json.dumps(gold.rows[:3], ensure_ascii=False),
        "pred_preview": json.dumps(pred.rows[:3], ensure_ascii=False),
    }


def summarize(records: list[dict]) -> dict[str, float]:
    def accuracy(rows: list[dict]) -> float:
        return round(100 * sum(r["correct"] for r in rows) / len(rows), 1) if rows else 0.0

    metrics = {"accuracy": accuracy(records)}
    for level in DIFFICULTIES:
        metrics[f"accuracy_{level}"] = accuracy([r for r in records if r["difficulty"] == level])
    statuses = Counter(r["status"] for r in records)
    metrics["n_questions"] = len(records)
    metrics["n_correct"] = sum(r["correct"] for r in records)
    metrics["n_blocked"] = statuses["blocked"]
    metrics["n_failed"] = statuses["failed"]
    metrics["n_fixed_by_retry"] = sum(1 for r in records if r["correct"] and r["attempts"] > 1)
    metrics["mean_attempts"] = round(sum(r["attempts"] for r in records) / max(len(records), 1), 2)
    metrics["mean_latency_ms"] = round(sum(r["latency_ms"] for r in records) / max(len(records), 1))
    return metrics


def save_results(records: list[dict], label: str) -> tuple[Path, Path]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    csv_path = RESULTS_DIR / f"{stamp}_{label}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    failures_path = RESULTS_DIR / f"{stamp}_{label}_failures.jsonl"
    with failures_path.open("w", encoding="utf-8") as f:
        for r in records:
            if not r["correct"]:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return csv_path, failures_path


def check_gold(questions: list[dict]) -> int:
    """Run every gold query: it must succeed, return rows, and fit in the 500-row cap."""
    problems = 0
    for q in questions:
        res = run_query(q["gold_sql"], max_rows=GOLD_MAX_ROWS)
        issue = (res.error if not res.ok else
                 "returns no rows" if not res.rows else
                 f"returns {len(res.rows)} rows (> {settings.row_limit})" if len(res.rows) > settings.row_limit else
                 None)
        problems += issue is not None
        print(f"{q['id']} {q['difficulty']:<6} {'FAIL ' + issue if issue else f'ok  {len(res.rows):>3} rows'}")
    print(f"\n{len(questions) - problems}/{len(questions)} gold queries OK")
    return problems


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--retrieval", action="store_true", help="use schema retrieval")
    p.add_argument("--fewshot", action="store_true", help="use few-shot examples")
    p.add_argument("--retries", type=int, default=0, help="error-feedback retries")
    p.add_argument("--limit", type=int, help="only the first N questions (for quick checks)")
    p.add_argument("--ids", help="comma-separated question ids to run")
    p.add_argument("--sleep", type=float, default=0.0, help="seconds to wait between questions (rate limits)")
    p.add_argument("--check-gold", action="store_true", help="only validate the gold SQL, no LLM calls")
    p.add_argument("--resume", action="store_true", help="continue an interrupted run of the same config")
    args = p.parse_args()

    questions = load_questions()
    if args.ids:
        wanted = set(args.ids.split(","))
        questions = [q for q in questions if q["id"] in wanted]
    if args.limit:
        questions = questions[: args.limit]

    if args.check_gold:
        raise SystemExit(1 if check_gold(questions) else 0)

    cfg = PipelineConfig(use_schema_retrieval=args.retrieval, use_fewshot=args.fewshot,
                         max_retries=args.retries, write_answer=False)
    label = config_label(cfg)
    full_run = not (args.ids or args.limit)

    # Progress is saved after every question, so a run stopped by rate limits, a crash or
    # Ctrl+C can continue with --resume. The file name pins config, prompt and model, so a
    # resume never mixes results from a different setup.
    model_tag = re.sub(r"[^a-z0-9]+", "-", settings.groq_model.lower())
    progress_path = RESULTS_DIR / f"{label}_{PROMPT_VERSION}_{model_tag}.partial.jsonl"
    records: list[dict] = []
    if progress_path.exists():
        if not args.resume:
            raise SystemExit(f"An unfinished run exists: {progress_path}\n"
                             "Continue it with --resume, or delete the file to start over.")
        records = [json.loads(line) for line in progress_path.open(encoding="utf-8") if line.strip()]
        print(f"resuming: {len(records)} questions already done")
    done = {r["id"] for r in records}
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    todo = [q for q in questions if q["id"] not in done]
    with progress_path.open("a", encoding="utf-8") as progress:
        for i, q in enumerate(todo, len(done) + 1):
            record = evaluate_one(q, cfg)
            records.append(record)
            progress.write(json.dumps(record, ensure_ascii=False) + "\n")
            progress.flush()
            mark = "PASS" if record["correct"] else record["status"].upper() if record["status"] != "ok" else "WRONG"
            print(f"[{i:>3}/{len(questions)}] {q['id']} {q['difficulty']:<6} {mark:<7} "
                  f"attempts={record['attempts']} {record['latency_ms']:>6} ms", flush=True)
            if args.sleep and q is not todo[-1]:
                time.sleep(args.sleep)

    order = {q["id"]: n for n, q in enumerate(questions)}
    records.sort(key=lambda r: order[r["id"]])
    metrics = summarize(records)
    csv_path, failures_path = save_results(records, label)

    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    mlflow.set_experiment("askdb-eval")
    with mlflow.start_run(run_name=label):
        mlflow.log_params({
            "schema_retrieval": cfg.use_schema_retrieval,
            "fewshot": cfg.use_fewshot,
            "max_retries": cfg.max_retries,
            "top_k_tables": cfg.top_k_tables,
            "n_examples": cfg.n_examples,
            "prompt_version": PROMPT_VERSION,
            "model": settings.groq_model,
            "full_run": full_run,
            "resumed": bool(done),
        })
        mlflow.log_metrics(metrics)
        mlflow.log_artifact(str(csv_path))
        mlflow.log_artifact(str(failures_path))
    progress_path.unlink()  # finished: the CSV and MLflow now hold the results

    print(f"\n{label}  (prompt {PROMPT_VERSION}, {settings.groq_model})")
    print(f"| Easy {metrics['accuracy_easy']}% | Medium {metrics['accuracy_medium']}% "
          f"| Hard {metrics['accuracy_hard']}% | Overall {metrics['accuracy']}% |")
    print(f"blocked={metrics['n_blocked']} failed={metrics['n_failed']} "
          f"fixed_by_retry={metrics['n_fixed_by_retry']}")
    print(f"per-question results: {csv_path}")


if __name__ == "__main__":
    main()
