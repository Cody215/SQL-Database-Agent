"""
Schema context for the Phase 3 agent.

Column names and types alone are a weak signal for text-to-SQL: knowing
`status` is a TEXT column doesn't tell the LLM it only ever contains
'Active'/'Inactive'/'Pending', and knowing `performance_levels.rank` is a
SmallInteger doesn't tell it that's the column to sort by for "best
performers" rather than the `label` column.

This module produces one formatted text block that combines two different
kinds of truth:

1. STRUCTURE, introspected live from whatever database is actually connected
   (via SQLAlchemy's inspector) -- table names, column names/types, and
   foreign key relationships. This is never hand-maintained, so it can't
   drift out of sync with reality, and it stays correct automatically after
   a Postgres migration.

2. SEMANTICS, curated by hand below -- what each table/column *means*, which
   columns are enums and what their valid values are, and which column to
   use for ordinal comparisons. This is the part raw schema introspection
   can never give you, and it's exactly where text-to-SQL accuracy is won
   or lost.

Phase 3 will call build_agent_context(engine) once per query (or cache it)
and inject the result into the agent's system prompt before generating SQL.
"""

from sqlalchemy import Engine, inspect, text

# --- Hand-curated semantics -------------------------------------------------
# This is the part that can't be introspected. Update it if the schema's
# meaning changes, even if the column types don't.

TABLE_DESCRIPTIONS = {
    "employees": (
        "One row per employee. The fact table -- everything else hangs off this."
    ),
    "departments": "Dimension table: the 6 departments employees can belong to.",
    "regions": "Dimension table: the 6 US states employees are based in.",
    "performance_levels": (
        "Dimension table: the 4 performance ratings, with a numeric 'rank' "
        "column for ordinal comparisons (Poor=1, Average=2, Good=3, Excellent=4)."
    ),
}

COLUMN_NOTES = {
    ("employees", "status"): "Enum-like. Only ever 'Active', 'Inactive', or 'Pending'.",
    ("employees", "age"): "Nullable -- about 21% of rows have no recorded age. Don't assume NOT NULL.",
    ("employees", "salary"): "Nullable -- a small fraction of rows have no recorded salary.",
    ("employees", "phone"): (
        "Nullable -- set to NULL during cleaning when the source phone number "
        "was invalid (wrong digit count). Not useful for analytical queries."
    ),
    ("employees", "department_id"): "Foreign key to departments.department_id. Join to get the department name.",
    ("employees", "region_id"): "Foreign key to regions.region_id. Join to get the region name.",
    ("employees", "performance_id"): "Foreign key to performance_levels.performance_id. Join to get the label and rank.",
    ("performance_levels", "rank"): (
        "Use THIS column (not 'label') for any 'better/worse than' or "
        "'top performers' comparison -- it's the ordinal field. Higher is better."
    ),
}


# --- Live introspection ------------------------------------------------------

def get_live_schema_summary(engine: Engine) -> str:
    """
    Introspect the actually-connected database (not src/schema.py) for table
    names, columns, types, and foreign keys. This is the "ground truth" half
    of the context -- if it disagrees with anything hand-written above, the
    database is right and the hand-written notes are stale.
    """
    inspector = inspect(engine)
    lines = []
    for table_name in sorted(inspector.get_table_names()):
        columns = inspector.get_columns(table_name)
        fks = inspector.get_foreign_keys(table_name)
        fk_by_column = {
            fk["constrained_columns"][0]: f"{fk['referred_table']}.{fk['referred_columns'][0]}"
            for fk in fks
            if fk["constrained_columns"]
        }

        lines.append(f"\nTable: {table_name}")
        if table_name in TABLE_DESCRIPTIONS:
            lines.append(f"  Description: {TABLE_DESCRIPTIONS[table_name]}")

        for col in columns:
            col_name = col["name"]
            col_type = str(col["type"])
            nullable = "NULL" if col["nullable"] else "NOT NULL"
            line = f"  - {col_name} ({col_type}, {nullable})"
            if col_name in fk_by_column:
                line += f" -> FK to {fk_by_column[col_name]}"
            note = COLUMN_NOTES.get((table_name, col_name))
            if note:
                line += f"  # {note}"
            lines.append(line)

    return "\n".join(lines)


def get_sample_distinct_values(engine: Engine, table: str, column: str, limit: int = 10) -> list:
    """
    Pull actual distinct values for a column. Most useful for low-cardinality
    text columns -- seeing the literal values ('Active', not 'a status code')
    is often more convincing to the LLM than a prose description.
    """
    with engine.connect() as conn:
        result = conn.execute(
            text(f"SELECT DISTINCT {column} FROM {table} WHERE {column} IS NOT NULL LIMIT :limit"),
            {"limit": limit},
        )
        return [row[0] for row in result]


def build_agent_context(engine: Engine) -> str:
    """
    The single function Phase 3 actually calls. Combines live structure with
    sample values for the categorical columns most likely to matter.
    """
    structure = get_live_schema_summary(engine)

    sample_blocks = []
    for table, column in [
        ("employees", "status"),
        ("departments", "department_name"),
        ("regions", "region_name"),
        ("performance_levels", "label"),
    ]:
        values = get_sample_distinct_values(engine, table, column)
        sample_blocks.append(f"  {table}.{column}: {values}")

    return (
        "=== DATABASE SCHEMA ===" + structure
        + "\n\n=== SAMPLE VALUES (categorical columns) ===\n"
        + "\n".join(sample_blocks)
    )
