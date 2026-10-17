"""Settings read from environment variables (.env in development)."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
    database_url: str = os.getenv("DATABASE_URL", "")
    database_admin_url: str = os.getenv("DATABASE_ADMIN_URL", "")
    chroma_dir: str = os.getenv("CHROMA_DIR", str(ROOT / ".chroma"))
    mlflow_tracking_uri: str = os.getenv("MLFLOW_TRACKING_URI", "sqlite:///mlflow.db")
    query_log_path: str = os.getenv("QUERY_LOG_PATH", str(ROOT / "logs" / "queries.jsonl"))
    schema_docs_path: str = str(ROOT / "data" / "schema_docs.yaml")
    fewshot_path: str = str(ROOT / "data" / "fewshot_bank.jsonl")
    embedding_model: str = "all-MiniLM-L6-v2"
    row_limit: int = 500
    statement_timeout_ms: int = 5000
    max_retries: int = 2


settings = Settings()
