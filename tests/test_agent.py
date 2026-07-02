"""
Tests for src/agent.py. These exercise the orchestration logic (the retry
loop, SELECT-only enforcement, SQL cleanup, markdown formatting) without ever
calling a real LLM -- a FakeLLM below returns scripted responses in order.
This is the right boundary for an automated test: it can't tell you whether
Gemini generates *correct* SQL for a given question (that's what the eval
harness in tests/eval_questions.py is for, run manually against the real
API), but it can prove the retry/error-handling machinery itself works.
"""

from datetime import date

import pytest
from sqlalchemy import create_engine

from src.agent import (
    QueryResult,
    _is_select_only,
    _strip_code_fences,
    ask,
    execute_sql,
    format_as_markdown,
)
from src.schema import departments, employees, metadata, performance_levels, regions


class FakeLLM:
    """Returns each response in `responses`, in order, one per .invoke() call."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.call_count = 0

    def invoke(self, messages):
        self.call_count += 1
        content = self._responses.pop(0)
        return type("FakeResponse", (), {"content": content})()


def _seeded_engine():
    engine = create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(departments.insert(), [{"department_id": 1, "department_name": "HR"}])
        conn.execute(regions.insert(), [{"region_id": 1, "region_name": "Texas"}])
        conn.execute(performance_levels.insert(), [{"performance_id": 1, "label": "Good", "rank": 3}])
        conn.execute(
            employees.insert(),
            [
                {
                    "employee_id": "EMP0001",
                    "first_name": "Jane",
                    "last_name": "Doe",
                    "age": 30,
                    "email": "jane.doe@example.com",
                    "phone": "(555) 123-4567",
                    "join_date": date(2023, 1, 1),
                    "status": "Active",
                    "remote_work": True,
                    "salary": 75000.00,
                    "department_id": 1,
                    "region_id": 1,
                    "performance_id": 1,
                }
            ],
        )
    return engine


# --- pure helper functions --------------------------------------------------

def test_strip_code_fences_removes_markdown_and_language_tag():
    raw = "```sql\nSELECT * FROM employees\n```"
    assert _strip_code_fences(raw) == "SELECT * FROM employees"


def test_strip_code_fences_handles_plain_sql_unchanged():
    assert _strip_code_fences("SELECT 1") == "SELECT 1"


def test_is_select_only_accepts_select_rejects_writes():
    assert _is_select_only("SELECT * FROM employees")
    assert not _is_select_only("DELETE FROM employees")
    assert not _is_select_only("DROP TABLE employees")
    assert not _is_select_only("UPDATE employees SET salary = 0")


def test_format_as_markdown_empty_rows():
    assert format_as_markdown(["a"], []) == "_No results._"


def test_format_as_markdown_basic_table():
    md = format_as_markdown(["name", "age"], [["Jane", 30]])
    assert "| name | age |" in md
    assert "| Jane | 30 |" in md


def test_execute_sql_rejects_non_select_statement():
    engine = _seeded_engine()
    with pytest.raises(ValueError):
        execute_sql(engine, "DELETE FROM employees")


# --- the self-correction loop ----------------------------------------------

def test_ask_succeeds_on_first_try_with_valid_sql():
    engine = _seeded_engine()
    llm = FakeLLM(["SELECT first_name FROM employees WHERE employee_id = 'EMP0001'"])
    result = ask(engine, "What is the first name of EMP0001?", llm=llm)

    assert result.succeeded
    assert result.attempts == 1
    assert result.rows == [["Jane"]]
    assert llm.call_count == 1  # only the initial generation, no repair call needed


def test_ask_retries_after_db_error_and_then_succeeds():
    engine = _seeded_engine()
    llm = FakeLLM(
        [
            "SELECT first_nam FROM employees",  # typo'd column -> DB error
            "SELECT first_name FROM employees WHERE employee_id = 'EMP0001'",  # corrected
        ]
    )
    result = ask(engine, "What is the first name of EMP0001?", llm=llm)

    assert result.succeeded
    assert result.attempts == 2
    assert len(result.sql_history) == 2
    assert result.rows == [["Jane"]]
    assert llm.call_count == 2  # initial generation + one repair call


def test_ask_returns_error_after_exhausting_retries():
    engine = _seeded_engine()
    # Every attempt is broken -- the agent should give up after MAX_RETRIES and report the error
    llm = FakeLLM(["SELECT nonexistent_col FROM employees"] * 5)
    result = ask(engine, "An unanswerable question", llm=llm)

    assert not result.succeeded
    assert result.error is not None
    assert result.attempts == 3  # 1 initial + 2 retries (MAX_RETRIES)


def test_ask_refuses_destructive_sql_even_if_llm_generates_it():
    engine = _seeded_engine()
    # If the LLM ever generates a write, the agent should refuse and treat it as
    # a failed attempt (triggering the same retry path), never execute it.
    llm = FakeLLM(
        [
            "DELETE FROM employees",
            "SELECT first_name FROM employees WHERE employee_id = 'EMP0001'",
        ]
    )
    result = ask(engine, "Delete the test employee", llm=llm)

    assert result.succeeded  # recovered via the repair call
    assert result.rows == [["Jane"]]
    # and, separately, prove the destructive query never actually ran
    with engine.connect() as conn:
        count = conn.execute(employees.select()).fetchall()
    assert len(count) == 1  # row still present
