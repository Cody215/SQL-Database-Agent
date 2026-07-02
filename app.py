"""
Streamlit front-end for the employee data agent.

This is a thin presentation layer only. Every actual decision -- how the
schema gets into the prompt, how SQL gets generated and retried, what's
allowed to execute -- lives in src/agent.py exactly as it does for the CLI
(ask.py). This file's only job is rendering that same ask() call as a chat
interface someone who's never seen SQL can actually use.

Run with:
    streamlit run app.py
"""

import pandas as pd
import streamlit as st

from src.agent import QueryResult, ask
from src.db import get_engine
from src.schema_metadata import build_agent_context

st.set_page_config(page_title="Employee Data Assistant", page_icon="📊", layout="centered")

EXAMPLE_QUESTIONS = [
    "How many active employees work remotely?",
    "What's the average salary by department?",
    "Which region has the most employees?",
    "How many employees have an Excellent performance rating?",
]


@st.cache_resource
def get_cached_engine():
    return get_engine("AGENT_DATABASE_URL")


@st.cache_resource
def get_cached_schema_context(_engine) -> str:
    # Leading underscore tells Streamlit's cache not to try hashing the
    # SQLAlchemy engine object itself -- only the function body changing
    # would invalidate this, which is what we want: the schema doesn't
    # change mid-session, so compute it once and reuse it for every question.
    return build_agent_context(_engine)


def render_assistant_turn(result: QueryResult) -> None:
    if not result.succeeded:
        st.error(
            f"Couldn't get a working answer after {result.attempts} attempt(s). "
            f"Last database error: {result.error}"
        )
        with st.expander("What it tried"):
            for sql in result.sql_history:
                st.code(sql, language="sql")
        return

    if not result.rows:
        st.info("That ran fine, but didn't match any rows.")
    else:
        df = pd.DataFrame(result.rows, columns=result.columns)
        st.dataframe(df, width="stretch", hide_index=True)

    label = "How it got this answer"
    if result.attempts > 1:
        label += f" (self-corrected {result.attempts - 1} time(s) after a database error)"
    with st.expander(label):
        for sql in result.sql_history:
            st.code(sql, language="sql")


def handle_question(engine, schema_context: str, question: str) -> None:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            result = ask(engine, question, schema_context=schema_context)
        render_assistant_turn(result)

    st.session_state.messages.append({"role": "assistant", "content": result})


def main() -> None:
    st.title("📊 Employee Data Assistant")
    st.caption("Ask a question about the employee data in plain English. No SQL required.")

    try:
        engine = get_cached_engine()
        schema_context = get_cached_schema_context(engine)
    except RuntimeError as e:
        st.error(str(e))
        st.stop()

    with st.sidebar:
        st.subheader("Try asking")
        for q in EXAMPLE_QUESTIONS:
            if st.button(q, width="stretch"):
                st.session_state.pending_question = q
        st.divider()
        st.caption(
            "This only ever reads data -- it connects through a read-only "
            "database role, so it can't change or delete anything."
        )

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            if message["role"] == "user":
                st.write(message["content"])
            else:
                render_assistant_turn(message["content"])

    pending_question = st.session_state.pop("pending_question", None)
    typed_question = st.chat_input("Ask about the employee data...")
    question = typed_question or pending_question

    if question:
        handle_question(engine, schema_context, question)


if __name__ == "__main__":
    main()
