"""
Integration test for src/schema_metadata.py. Unlike test_clean.py, this
needs a real (if temporary) database -- it's testing that introspection
correctly reflects what's actually in the schema, not a pure transform.
Uses an in-memory SQLite engine so it's still fast and needs no setup.
"""

from datetime import date

from sqlalchemy import create_engine

from src.schema import departments, employees, metadata, performance_levels, regions
from src.schema_metadata import build_agent_context, get_live_schema_summary


def _seeded_engine():
    """An in-memory SQLite DB with the real schema and a couple of rows."""
    engine = create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(departments.insert(), [{"department_id": 1, "department_name": "HR"}])
        conn.execute(regions.insert(), [{"region_id": 1, "region_name": "Texas"}])
        conn.execute(
            performance_levels.insert(),
            [{"performance_id": 1, "label": "Good", "rank": 3}],
        )
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


def test_live_schema_summary_includes_all_tables_and_fk_notes():
    engine = _seeded_engine()
    summary = get_live_schema_summary(engine)
    for table in ["employees", "departments", "regions", "performance_levels"]:
        assert table in summary
    # The hand-curated FK/enum notes should be attached to the right columns
    assert "FK to departments.department_id" in summary
    assert "Only ever 'Active', 'Inactive', or 'Pending'" in summary


def test_agent_context_includes_sample_values_from_seeded_data():
    engine = _seeded_engine()
    context = build_agent_context(engine)
    assert "HR" in context
    assert "Texas" in context
    assert "Good" in context
    assert "Active" in context
