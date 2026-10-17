"""Engine for the read-only user, with a 5 s statement timeout on every connection."""
from functools import lru_cache

from sqlalchemy import Engine, create_engine

from .config import settings


@lru_cache
def get_engine() -> Engine:
    # The askdb_reader role already has a 5 s timeout and only SELECT grants. Setting the
    # timeout and a read-only transaction here too means the app stays safe even if it is
    # pointed at a database where the role was set up differently.
    options = (f"-c statement_timeout={settings.statement_timeout_ms} "
               "-c default_transaction_read_only=on")
    return create_engine(settings.database_url, pool_pre_ping=True,
                         connect_args={"options": options})
