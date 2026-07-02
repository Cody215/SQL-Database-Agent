"""
End-to-end test for app.py using Streamlit's AppTest harness. This runs the
actual script -- clicking sidebar buttons, populating chat history, rendering
results -- in a simulated session, no browser needed. The LLM call inside
ask() is mocked the same way test_agent.py mocks it (a scripted fake LLM),
so this proves the UI wiring works without a real API key or network access.

What this does NOT prove: whether the real Gemini model gives a good answer
in this UI. That's still tests/eval_questions.py's job, run manually against
the real API.
"""

from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from tests.test_agent import FakeLLM


def test_app_loads_without_exception():
    at = AppTest.from_file("app.py").run()
    assert not at.exception
    assert "Employee Data Assistant" in at.title[0].value


def test_app_shows_example_question_buttons_in_sidebar():
    at = AppTest.from_file("app.py").run()
    button_labels = [b.label for b in at.sidebar.button]
    assert "How many active employees work remotely?" in button_labels


def test_clicking_example_question_renders_a_result_table():
    fake_llm = FakeLLM(["SELECT COUNT(*) FROM employees WHERE remote_work = 1 AND status = 'Active'"])
    with patch("src.agent.get_llm", return_value=fake_llm):
        at = AppTest.from_file("app.py").run()
        at.sidebar.button[0].click().run()

    assert not at.exception
    assert len(at.session_state["messages"]) == 2  # one user turn, one assistant turn
    assert len(at.dataframe) == 1  # the result rendered as an actual table, not raw text


def test_failed_query_shows_error_not_a_crash():
    # Every attempt is broken SQL -- the agent exhausts its retries and the UI
    # should show a clear error, not throw an unhandled exception.
    fake_llm = FakeLLM(["SELECT nonexistent_col FROM employees"] * 5)
    with patch("src.agent.get_llm", return_value=fake_llm):
        at = AppTest.from_file("app.py").run()
        at.chat_input[0].set_value("An unanswerable question").run()

    assert not at.exception
    assert len(at.error) == 1
