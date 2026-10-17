from eval.run_eval import rate_limit_wait, summarize


def test_rate_limit_wait_parses_groq_message():
    reason = ("RateLimitError: Error code: 429 - Rate limit reached for model openai/gpt-oss-120b "
              "on tokens per day (TPD): Limit 200000, Used 199500. Please try again in 7m30.5s.")
    assert rate_limit_wait(reason) == 7 * 60 + 30.5 + 2


def test_rate_limit_wait_hours_and_default():
    assert rate_limit_wait("RateLimitError: ... Please try again in 1h2m3s") == 3725
    assert rate_limit_wait("RateLimitError: no time given") == 60


def test_real_errors_are_not_rate_limits():
    # a SQL or auth failure must be scored as wrong, not waited out
    assert rate_limit_wait('Query failed after 1 attempt(s): column "x" does not exist') is None
    assert rate_limit_wait("AuthenticationError: Invalid API Key") is None
    assert rate_limit_wait(None) is None


def test_summarize_per_difficulty():
    records = [
        {"difficulty": "easy", "correct": 1, "status": "ok", "attempts": 1, "latency_ms": 100},
        {"difficulty": "easy", "correct": 0, "status": "ok", "attempts": 1, "latency_ms": 100},
        {"difficulty": "hard", "correct": 1, "status": "ok", "attempts": 2, "latency_ms": 300},
        {"difficulty": "medium", "correct": 0, "status": "blocked", "attempts": 1, "latency_ms": 100},
    ]
    m = summarize(records)
    assert m["accuracy"] == 50.0
    assert m["accuracy_easy"] == 50.0
    assert m["accuracy_medium"] == 0.0
    assert m["accuracy_hard"] == 100.0
    assert m["n_blocked"] == 1
    assert m["n_fixed_by_retry"] == 1
