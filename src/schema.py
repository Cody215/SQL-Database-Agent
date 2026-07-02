"""
Schema defined with SQLAlchemy Core (not raw SQL strings). This is what
actually gets executed by the pipeline -- it's dialect-agnostic, so the exact
same code creates valid tables whether ETL_DATABASE_URL points at SQLite
(default, for easy local development) or Postgres (for the "real" deployment
later). No rewrite needed when you migrate, just change the connection string.

sql/01_schema.sql is kept alongside this as the human-readable Postgres
reference -- useful for documentation, and for applying manually with psql
once you're on a real Postgres instance with sql/02_roles.sql.
"""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Table,
)

metadata = MetaData()

departments = Table(
    "departments",
    metadata,
    Column("department_id", Integer, primary_key=True, autoincrement=True),
    Column("department_name", String, nullable=False, unique=True),
)

regions = Table(
    "regions",
    metadata,
    Column("region_id", Integer, primary_key=True, autoincrement=True),
    Column("region_name", String, nullable=False, unique=True),
)

performance_levels = Table(
    "performance_levels",
    metadata,
    Column("performance_id", Integer, primary_key=True, autoincrement=True),
    Column("label", String, nullable=False, unique=True),
    Column("rank", SmallInteger, nullable=False, unique=True),
)

employees = Table(
    "employees",
    metadata,
    Column("employee_id", String, primary_key=True),
    Column("first_name", String, nullable=False),
    Column("last_name", String, nullable=False),
    Column("age", SmallInteger, nullable=True),
    Column("email", String, nullable=False),
    Column("phone", String, nullable=True),
    Column("join_date", Date, nullable=False),
    Column("status", String, nullable=False),
    Column("remote_work", Boolean, nullable=False),
    Column("salary", Numeric(12, 2), nullable=True),
    Column("department_id", Integer, ForeignKey("departments.department_id")),
    Column("region_id", Integer, ForeignKey("regions.region_id")),
    Column("performance_id", Integer, ForeignKey("performance_levels.performance_id")),
    CheckConstraint("status IN ('Active', 'Inactive', 'Pending')", name="status_valid_values"),
)
