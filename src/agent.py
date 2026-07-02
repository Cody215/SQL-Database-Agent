"""
Natural language -> SQL agent.

Deliberately NOT using LangChain's create_sql_agent black box. That
abstraction hides exactly the steps that matter for this project: how the
schema gets into the prompt, what happens on a SQL error, and how results get
summarized. Implementing each step explicitly here means every part of the
self-correction loop described in the project's user-flow diagram is visible
and debuggable, rather than living inside a library's internals.

Flow per question:
  1. Pull live schema context (src/schema_metadata.py)
  2. Ask the LLM to generate a SQL SELECT statement
  3. Execute it
  4. On failure: send the error + bad SQL back to the LLM, ask it to fix it,
     retry (up to MAX_RETRIES times)
  5. Return the result rows, or the final error if every attempt failed
"""

import os
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from sqlalchemy import Engine, text

from src.schema_metadata import build_agent_context

MAX_RETRIES = 2

SYSTEM_PROMPT_TEMPLATE = """You are a SQL assistant for an employee database (SQLite now, Postgres-compatible SQL later).

{schema_context}

Rules:
- Write exactly one SQL SELECT query that answers the user's question. Nothing else is allowed:
  never write INSERT, UPDATE, DELETE, DROP, ALTER, or any other statement.
- Use the JOINs implied by the foreign keys above whenever the question needs data from more than one table.
- Use performance_levels.rank (not label) for any ordinal comparison, e.g. "better than", "top performers".
- Some columns are nullable (see notes above) -- decide whether NULLs should be included or filtered based on the question.
- Return ONLY the raw SQL query: no explanation, no markdown code fences, no trailing semicolon commentary.
"""


@dataclass
class QueryResult:
    question: str
    sql: str
    columns: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    attempts: int = 1
    sql_history: list = field(default_factory=list)  # every SQL version tried, in order
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


def get_llm(model: str = "gemini-2.5-flash") -> ChatGoogleGenerativeAI:
    """
    Default model is Gemini 3 Flash -- Google's current recommended free-tier
    model (as of mid-2026): no billing required, rate-limited but the limit
    never expires. If you hit the rate limit during testing, gemini-3.1-flash-lite
    is a lighter/cheaper alternative with a higher requests-per-minute ceiling.
    """
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GOOGLE_API_KEY is not set. Copy .env.example to .env and add a key "
            "from https://aistudio.google.com/apikey (free, no billing required "
            "for Flash/Flash-Lite models)."
        )
    return ChatGoogleGenerativeAI(model=model, google_api_key=api_key, temperature=0)


def _strip_code_fences(sql: str) -> str:
    """LLMs frequently wrap SQL in ```sql ... ``` even when told not to -- strip it defensively."""
    sql = sql.strip()
    if sql.startswith("```"):
        parts = sql.split("```")
        sql = parts[1] if len(parts) > 1 else sql
        if sql.lower().startswith("sql"):
            sql = sql[3:]
    return sql.strip().rstrip(";").strip()


def _is_select_only(sql: str) -> bool:
    """
    A second, code-level safety check behind the read-only DB connection.
    The DB connection (AGENT_DATABASE_URL, opened read-only) is the real
    guarantee; this is a cheap first check that fails fast with a clear
    message instead of relying solely on the DB rejecting the statement.
    """
    return sql.strip().lower().startswith("select")


def generate_sql(llm, question: str, schema_context: str) -> str:
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(schema_context=schema_context)
    response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=question)])
    return _strip_code_fences(response.content)


def fix_sql(llm, question: str, schema_context: str, bad_sql: str, db_error: str) -> str:
    """The self-correction step: hand the LLM its own failed query plus the real DB error."""
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(schema_context=schema_context)
    repair_prompt = (
        f"Original question: {question}\n\n"
        f"This SQL query was generated but failed:\n{bad_sql}\n\n"
        f"The database returned this error:\n{db_error}\n\n"
        "Fix the query. Return ONLY the corrected SQL, no explanation."
    )
    response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=repair_prompt)])
    return _strip_code_fences(response.content)


def execute_sql(engine: Engine, sql: str):
    """Runs a SELECT and returns (columns, rows). Raises on any non-SELECT or DB error."""
    if not _is_select_only(sql):
        raise ValueError(f"Generated query was not a SELECT statement, refusing to execute:\n{sql}")
    with engine.connect() as conn:
        result = conn.execute(text(sql))
        columns = list(result.keys())
        rows = [list(row) for row in result.fetchall()]
    return columns, rows


def ask(engine: Engine, question: str, llm=None, schema_context: str | None = None) -> QueryResult:
    """
    The full pipeline for one question: generate -> execute -> retry on error.
    `engine` should be the read-only AGENT_DATABASE_URL connection -- never
    the writer engine -- so a destructive query is rejected by the database
    itself even if it somehow got past the SELECT-only check above.
    """
    llm = llm or get_llm()
    schema_context = schema_context or build_agent_context(engine)

    sql = generate_sql(llm, question, schema_context)
    sql_history = [sql]
    last_error = None

    for attempt in range(1, MAX_RETRIES + 2):  # initial attempt + MAX_RETRIES retries
        try:
            columns, rows = execute_sql(engine, sql)
            return QueryResult(
                question=question, sql=sql, columns=columns, rows=rows,
                attempts=attempt, sql_history=sql_history,
            )
        except Exception as e:
            last_error = str(e)
            if attempt <= MAX_RETRIES:
                sql = fix_sql(llm, question, schema_context, sql, last_error)
                sql_history.append(sql)

    return QueryResult(
        question=question, sql=sql, attempts=MAX_RETRIES + 1,
        sql_history=sql_history, error=last_error,
    )


def format_as_markdown(columns: list, rows: list) -> str:
    """
    Deterministic string formatting -- not an LLM call. There's no ambiguity
    in turning rows into a table, so there's no reason to spend a token (or
    risk a hallucinated number) on something plain code does perfectly.
    """
    if not rows:
        return "_No results._"
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join(["---"] * len(columns)) + " |"
    body_lines = ["| " + " | ".join(str(v) for v in row) + " |" for row in rows]
    return "\n".join([header, separator] + body_lines)
