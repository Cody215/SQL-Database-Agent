"""
ETL orchestration. This module owns the I/O (reading the CSV, writing to
Postgres); src/clean.py owns the actual transform logic. Keeping them separate
means clean.py can be unit tested with no database or filesystem involved.
"""

from pathlib import Path

import pandas as pd
from sqlalchemy import Engine

from src import clean
from src.schema import departments as departments_table
from src.schema import employees as employees_table
from src.schema import metadata
from src.schema import performance_levels as performance_levels_table
from src.schema import regions as regions_table


def extract(csv_path: str | Path) -> pd.DataFrame:
    """Read the raw CSV exactly as-is -- no cleaning happens here."""
    return pd.read_csv(csv_path)


def create_schema(engine: Engine) -> None:
    """
    Create all tables defined in src/schema.py if they don't already exist.
    Dialect-agnostic: generates SQLite-correct SQL now, Postgres-correct SQL
    later, from the same table definitions.
    """
    metadata.create_all(engine)


def data_quality_report(raw: pd.DataFrame, cleaned_employees: pd.DataFrame) -> dict:
    """
    A quick before/after summary -- useful for the README and for sanity-checking
    that cleaning rules behaved as expected (e.g. that 'invalid phone' rows went
    to NULL rather than silently vanishing or getting fabricated).
    """
    return {
        "raw_row_count": len(raw),
        "cleaned_row_count": len(cleaned_employees),
        "missing_age_before": int(raw["Age"].isna().sum()),
        "missing_age_after": int(cleaned_employees["age"].isna().sum()),
        "missing_salary_before": int(raw["Salary"].isna().sum()),
        "missing_salary_after": int(cleaned_employees["salary"].isna().sum()),
        "invalid_phone_after": int(cleaned_employees["phone"].isna().sum()),
        "missing_department_fk": int(cleaned_employees["department_id"].isna().sum()),
        "missing_region_fk": int(cleaned_employees["region_id"].isna().sum()),
        "missing_performance_fk": int(cleaned_employees["performance_id"].isna().sum()),
    }


def load_all(
    engine: Engine,
    departments: pd.DataFrame,
    regions: pd.DataFrame,
    performance_levels: pd.DataFrame,
    employees: pd.DataFrame,
) -> None:
    """
    Load dimension tables first, then the fact table -- order matters because
    employees has foreign keys pointing at the other three. Deletes existing
    rows first (in FK-safe order) so the pipeline is idempotent/re-runnable
    without manually dropping tables between runs.
    """
    with engine.begin() as conn:
        conn.execute(employees_table.delete())
        conn.execute(departments_table.delete())
        conn.execute(regions_table.delete())
        conn.execute(performance_levels_table.delete())

    departments.to_sql("departments", engine, if_exists="append", index=False)
    regions.to_sql("regions", engine, if_exists="append", index=False)
    performance_levels.to_sql("performance_levels", engine, if_exists="append", index=False)
    employees.to_sql("employees", engine, if_exists="append", index=False)


def run(csv_path: str | Path, engine: Engine) -> dict:
    """Full pipeline: extract -> clean -> build dims/fact -> load. Returns a quality report."""
    create_schema(engine)

    raw = extract(csv_path)
    cleaned = clean.run_all_cleaning(raw)

    departments = clean.build_departments_dim(cleaned)
    regions = clean.build_regions_dim(cleaned)
    performance_levels = clean.build_performance_dim()
    employees = clean.build_employees_fact(cleaned, departments, regions, performance_levels)

    load_all(engine, departments, regions, performance_levels, employees)

    return data_quality_report(raw, employees)
