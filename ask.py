"""
Ask the database a question in plain English.

Usage:
    python ask.py "How many active employees work remotely?"
    python ask.py             # interactive mode, one question per line, blank line to quit
"""

import argparse
import sys

from src.agent import ask, format_as_markdown
from src.db import get_engine


def answer_one(engine, question: str) -> None:
    result = ask(engine, question)

    print(f"\nSQL generated ({result.attempts} attempt(s)):")
    print(f"  {result.sql}")
    if len(result.sql_history) > 1:
        print(f"  (self-corrected {len(result.sql_history) - 1} time(s) after a database error)")

    if not result.succeeded:
        print(f"\nCouldn't get a working query after {result.attempts} attempts.")
        print(f"Last error: {result.error}")
        return

    print("\nResult:")
    print(format_as_markdown(result.columns, result.rows))


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask the employee database a question in plain English.")
    parser.add_argument("question", nargs="?", help="The question to ask. Omit for interactive mode.")
    args = parser.parse_args()

    engine = get_engine("AGENT_DATABASE_URL")

    if args.question:
        answer_one(engine, args.question)
        return

    print("Interactive mode. Type a question and press Enter. Blank line to quit.")
    while True:
        try:
            question = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question:
            break
        answer_one(engine, question)


if __name__ == "__main__":
    sys.exit(main())
