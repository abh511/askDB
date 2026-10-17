"""Groq chat model at temperature 0, plus code-fence stripping."""
import re
from functools import lru_cache

from langchain_groq import ChatGroq

from .config import settings


@lru_cache
def _model() -> ChatGroq:
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not set (add it to .env)")
    # temperature 0 -> the same prompt gives (almost always) the same SQL, so eval runs
    # are repeatable. max_retries lets the Groq client wait and retry on rate limits.
    return ChatGroq(model=settings.groq_model, api_key=settings.groq_api_key,
                    temperature=0, max_retries=6)


def complete(prompt: str) -> str:
    """Send the prompt to Groq and return the reply text."""
    return str(_model().invoke(prompt).content)


def strip_code_fences(text: str) -> str:
    """Remove ```sql ... ``` wrappers from an LLM reply."""
    match = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    return (match.group(1) if match else text).strip()
