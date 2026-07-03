
![CI](https://github.com/Cody215/SQL-Database-Agent/.github/workflows/ci.yml/badge.svg)


A natural-language-to-SQL system: messy CSV → cleaned, normalized Postgres-style
relational database → (coming in Phase 3) a LangChain agent that lets
non-technical users ask questions in plain English and get back real query
results.

**Status: all 4 layers built — ETL (Phase 1), schema (Phase 2), agent (Phase
3), and a Streamlit UI. Phases 1-2 and the UI's wiring are fully tested
end-to-end. Phase 3's orchestration logic is tested with a scripted fake LLM
(see "Testing" below) — actually calling the real Gemini API needs your own
key, which I don't have.**

## Why this project

Three problems show up constantly when non-technical people need data answers:
1. **Garbage in, garbage out** — raw business data is messy, and most
   "ask your data" demos skip this part entirely.
2. **The technical barrier** — business stakeholders can describe what they
   want in English but not in SQL.
3. **LLM fragility** — a text-to-SQL system that breaks on the first
   malformed query or, worse, runs a destructive query, isn't usable.

This project tackles all three: a real ETL pipeline with documented cleaning
decisions, a properly normalized schema, and (in Phase 3) an agent that's
structurally prevented from writing to the database, with a self-correction
loop for query errors.

## Architecture

```
[ Messy CSV ] -> [ Python ETL Pipeline ] -> [ employees.db / Postgres ]
                  (extract, clean,                    ^
                   normalize, load)                   | (SELECT only)
                                                        |
                                              [ LangChain Agent ] <- [ User ]
                                                 (Phase 3, next)
```

## Project structure

```
employee-sql-agent/
├── data/
│   ├── raw/                    # original CSV, never modified
│   └── processed/              # generated SQLite db lives here (gitignored)
├── .github/
│   └── workflows/
│       └── ci.yml               # GitHub Actions: ETL smoke test + pytest on every push
├── sql/
│   ├── 01_schema.sql           # human-readable Postgres reference DDL
│   └── 02_roles.sql            # Postgres role/grant setup (for later)
├── src/
│   ├── clean.py                # pure pandas transform functions (no I/O)
│   ├── schema.py                # SQLAlchemy table defs -- actually executed
│   ├── schema_metadata.py        # builds schema context for the agent
│   ├── pipeline.py              # orchestrates extract -> clean -> load
│   ├── agent.py                  # Phase 3: text-to-SQL agent + retry loop
│   └── db.py                    # connection helper, reads .env
├── tests/
│   ├── test_clean.py            # unit tests for cleaning rules
│   ├── test_schema_metadata.py  # integration test for schema introspection
│   ├── test_agent.py             # agent retry/safety logic (scripted fake LLM)
│   ├── test_app.py               # UI flow via Streamlit's AppTest harness
│   └── eval_questions.py         # answer-quality eval -- run manually, real API
├── main.py                      # CLI entrypoint for the ETL pipeline
├── ask.py                       # CLI entrypoint for the agent
├── app.py                       # Streamlit UI for the agent
├── .env.example
└── requirements.txt
```

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
python main.py
```

That's it for local development — `ETL_DATABASE_URL` in `.env.example` defaults
to a SQLite file at `data/processed/employee.db`, created automatically on
first run. No database server to install or configure.

Run the tests:
```bash
pytest tests/ -v
```

## What the pipeline actually does

The source CSV (1,020 rows, 12 columns) has several real data quality issues,
each handled with an explicit, documented rule rather than a silent guess:

| Issue | Rule applied |
|---|---|
| `Department_Region` combines two dimensions (e.g. `"Cloud Tech-Florida"`) | Split into separate `department_name` / `region_name`, normalized into their own dimension tables |
| `Age` ~21% missing, plus implausible values | Cast to nullable int; values outside 16-80 treated as errors -> NULL (not clipped) |
| `Salary` ~2% missing, occasional negatives | Negative values -> NULL (a salary can't be negative; guessing a "real" value would be worse than admitting it's missing) |
| `Phone` stored as signed integers, 7-10 digits | Sign dropped (carries no meaning); only valid 10-digit numbers are formatted, shorter ones -> NULL rather than padded with invented digits |
| `Join_Date` stored as text | Parsed into a real `DATE` type |
| `Status` / `Performance_Score` casing inconsistencies | Normalized casing; unrecognized values -> NULL rather than silently kept |

Running `main.py` prints a before/after data quality report so you can see
exactly what got cleaned vs. flagged as unrecoverable.

## Schema design

Normalized into a small star schema rather than one flat table:

- `departments`, `regions`, `performance_levels` — dimension tables
- `employees` — fact table, foreign-keyed to all three

This matters for Phase 3: a flat table only supports filters and group-bys,
which a manager could mostly do in Excel anyway. A normalized schema means
the natural-language agent has to generate real joins (e.g. *"average salary
by department, broken down by region"*) — the kind of query a non-technical
user genuinely couldn't write themselves, which is the actual point of the
project.

`performance_levels.rank` gives the four performance labels a stable numeric
ordering (Poor=1 ... Excellent=4), so the agent can answer comparative
questions ("better than average") with `WHERE rank >= 2` instead of fragile
string matching.

## The read-only safeguard

The agent (Phase 3) will only ever connect using `AGENT_DATABASE_URL`, never
`ETL_DATABASE_URL`. This was tested directly: a `DELETE` issued over the
agent's connection is rejected by the database connection itself —

```
DELETE correctly blocked: OperationalError - attempt to write a readonly database
```

The principle: query safety shouldn't depend on trusting the LLM to behave or
on prompt engineering catching every bad case. It should be enforced at the
database/connection layer, where it can't be talked around.

- **Now (SQLite):** `AGENT_DATABASE_URL` opens the same file with a read-only
  connection mode (`mode=ro`). This is a development-time safeguard — a
  separate process could still open the file directly without that flag, so
  it's not a hard guarantee.
- **Later (Postgres):** `sql/02_roles.sql` creates a real `agent_readonly`
  database role with only `SELECT` grants. That's enforced by Postgres
  itself regardless of how the connection is opened — the actual safeguard
  this project is designed around.

## Phase 2: schema context for the agent

Column names and types alone are a weak signal for text-to-SQL -- knowing
`status` is a TEXT column doesn't tell an LLM it only ever contains
`'Active'/'Inactive'/'Pending'`, and knowing `performance_levels.rank` is a
number doesn't tell it that's the column to sort by for "top performers"
rather than `label`.

`src/schema_metadata.py` builds the context block that solves this, combining
two different kinds of information:

- **Structure**, introspected live from whatever database is actually
  connected (via SQLAlchemy's inspector) -- table/column names, types, and
  foreign keys. Never hand-maintained, so it can't drift out of sync with
  reality, and stays correct automatically after a Postgres migration.
- **Semantics**, curated by hand in the same file -- what each table means,
  which columns are enums and what their valid values are, which column to
  use for ordinal comparisons. This is the part introspection alone can
  never give you, and it's where text-to-SQL accuracy is actually won or lost.

Run it directly to see exactly what Phase 3's agent will be given as context:

```bash
python -c "
from src.db import get_engine
from src.schema_metadata import build_agent_context
print(build_agent_context(get_engine('AGENT_DATABASE_URL')))
"
```

## CI

GitHub Actions runs on every push and pull request:

```
push / PR -> install deps -> python main.py (ETL) -> pytest (25 tests)
```

The ETL pipeline runs first because `test_schema_metadata.py` and
`test_app.py` use an in-memory SQLite database seeded by the test fixture
itself, but need the schema module to be importable and the pipeline to have
run at least once to confirm the full path works end-to-end. `main.py`
doubles as a smoke test for the ETL itself — if cleaning or loading breaks,
CI fails before pytest even starts.

`tests/eval_questions.py` is excluded from CI: it calls the real Gemini API
and would need a `GOOGLE_API_KEY` secret set in the repo. The automated
suite (`test_agent.py`, `test_app.py`) already covers the same orchestration
logic with a scripted fake LLM, so there's no coverage gap from excluding it.
If you do want to run the real-API eval in CI later, add the key as a GitHub
secret and change the `--ignore` flag to `--ignore=tests/eval_questions.py`
only on branches where the secret isn't available.

Once you push to GitHub: replace `YOUR_USERNAME` in the badge URL at the top
of this README with your actual GitHub username and the badge will go green.

## The UI

```bash
streamlit run app.py
```

`app.py` is a thin wrapper, not a separate implementation — it calls the
exact same `ask()` function `ask.py` does. A chat interface rather than a
plain form, since that matches the mental model most people already have
("ask a question, get an answer") more than a traditional form would. The
sidebar has a few example questions as one-click buttons, since a
non-technical user's first problem is usually "I don't know what I'm allowed
to ask" — and an empty text box doesn't answer that.

One efficiency fix made while building this: `ask()` now accepts an optional
pre-built `schema_context`, so a session asking multiple questions in a row
computes the schema context once and reuses it, instead of re-querying the
database before every single question (`ask.py` still doesn't bother — it's
one question per process invocation, so there's nothing to reuse).

Every result shows an expandable "How it got this answer" section with the
actual SQL used — including every attempt if it self-corrected — so a
curious user can see *why* it returned what it did without needing to read
SQL to trust the table above it.

`tests/test_app.py` uses Streamlit's official `AppTest` harness, which runs
the real script (clicking buttons, populating session state, rendering
results) without a browser. Combined with the same scripted-fake-LLM
approach as `test_agent.py`, this proves the full click -> generate -> render
flow works, and that a failed query shows a clean error instead of crashing
the app — without needing a real API key for the test suite itself.

## Migrating to Postgres later

`src/schema.py` defines tables with SQLAlchemy Core rather than raw SQL, so
the exact same code creates correct tables on whichever database the
connection string points at. To migrate:

1. Stand up Postgres (e.g. via Docker).
2. Run `sql/02_roles.sql` against it to create `etl_writer` / `agent_readonly`.
3. Update `ETL_DATABASE_URL` / `AGENT_DATABASE_URL` in `.env` to the Postgres
   connection strings (commented examples already in `.env.example`).
4. Run `python main.py` again — no code changes needed.

## Phase 3: the agent

`src/agent.py` implements the self-correction loop directly (generate SQL ->
execute -> on error, send the error back to the LLM -> retry), rather than
using LangChain's `create_sql_agent` black box. That keeps every step
inspectable: you can print the exact SQL at each retry, see exactly what
error triggered a repair, and see exactly what changed between attempts.

### Setup

1. Get a free key at https://aistudio.google.com/apikey (no billing required
   for the Flash / Flash-Lite models this defaults to).
2. Put it in `.env` as `GOOGLE_API_KEY=...`.
3. `python ask.py "How many active employees work remotely?"`, or just
   `python ask.py` for an interactive prompt.

The agent connects using `AGENT_DATABASE_URL` — the same read-only connection
tested in Phase 1 — never `ETL_DATABASE_URL`. There's also a second,
code-level check (`_is_select_only` in `src/agent.py`) that refuses to
execute anything that isn't a `SELECT`, so a destructive query is blocked
twice over: once by application logic, once by the database connection
itself if the first check were ever bypassed.

### Testing — and a real limitation, stated plainly

`tests/test_agent.py` proves the *machinery* works: 10 tests using a scripted
fake LLM (no API key needed, $0 cost) confirm the retry loop actually retries,
a destructive query never executes even if the LLM generates one, and
malformed LLM output (markdown fences, etc.) gets cleaned up correctly.

What that suite can't tell you is whether the *real* Gemini model generates
*correct* SQL for a *real* question — that needs an actual model. I wasn't
able to test that myself: my sandbox's network access doesn't extend to
Google's Gemini API endpoint, only to package registries like PyPI. So
`tests/eval_questions.py` — six questions with answers computed directly
from the real dataset (e.g. "how many active employees" -> 352) — is written
and ready, but **you'll need to be the one to run it** once your API key is
in place:

```bash
python -m tests.eval_questions
```

It's a script, not a pytest file, deliberately — it costs a few real API
calls each run, so it shouldn't fire automatically every time you run
`pytest`. If anything fails, the printed SQL for each question makes it easy
to see whether the issue is the schema context, the prompt, or a genuine
model limitation.

## Next steps

- Run `tests/eval_questions.py` yourself and see what passes
- If accuracy on harder questions is shaky, the highest-leverage fix is
  usually expanding `src/schema_metadata.py`'s curated notes, not the prompt
  in `agent.py` — text-to-SQL accuracy is won mostly on schema context
- Consider a basic UI (Streamlit/Gradio) once the agent's accuracy is solid
  on the eval set — that's the piece needed to make this usable by the
  non-technical manager persona, not just from the command line
