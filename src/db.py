"""
Database connection helper.

Deliberately the only place in the codebase that reads connection strings.
The ETL pipeline (writer role) and the future LangChain agent (read-only role)
both go through this module, but each calls get_engine() with a different
env var name -- see .env.example.
"""

import os

from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine

load_dotenv()


def get_engine(env_var: str = "ETL_DATABASE_URL") -> Engine:
    """
    Build a SQLAlchemy engine from a connection string stored in the named
    environment variable.

    Phase 1 (this pipeline) should call get_engine("ETL_DATABASE_URL") -- on
    Postgres this resolves to the etl_writer role (CREATE/INSERT rights to
    build and load the schema); on SQLite it's just the path to the .db file.

    Phase 3 (the agent, later) will call get_engine("AGENT_DATABASE_URL").
    On Postgres this resolves to the agent_readonly role, so the agent is
    structurally incapable of writing no matter what SQL the LLM generates.
    SQLite has no role system, so the equivalent there is opening the same
    file with a read-only connection mode -- see AGENT_DATABASE_URL in
    .env.example for the exact URI. It's a weaker guarantee than a real DB
    role (a local script could still open the file directly and write to it),
    so treat it as a development-time stand-in, not the real safeguard --
    the real safeguard is the Postgres role grants in sql/02_roles.sql,
    applied when this moves off SQLite.
    """
    url = os.environ.get(env_var)
    if not url:
        raise RuntimeError(
            f"{env_var} is not set. Copy .env.example to .env and fill in a "
            "database connection string."
        )
    return create_engine(url)
