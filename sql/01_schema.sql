-- Normalized employee schema
-- Run as the privileged/writer role (e.g. etl_writer or a superuser during setup).

DROP TABLE IF EXISTS employees CASCADE;
DROP TABLE IF EXISTS departments CASCADE;
DROP TABLE IF EXISTS regions CASCADE;
DROP TABLE IF EXISTS performance_levels CASCADE;

CREATE TABLE departments (
    department_id   SERIAL PRIMARY KEY,
    department_name TEXT NOT NULL UNIQUE
);

CREATE TABLE regions (
    region_id   SERIAL PRIMARY KEY,
    region_name TEXT NOT NULL UNIQUE
);

-- rank gives a numeric ordering for "better/worse than" comparisons in SQL
-- (e.g. ORDER BY rank, or WHERE rank >= 3) without string-matching on label.
CREATE TABLE performance_levels (
    performance_id SERIAL PRIMARY KEY,
    label          TEXT NOT NULL UNIQUE,
    rank           SMALLINT NOT NULL UNIQUE
);

CREATE TABLE employees (
    employee_id     TEXT PRIMARY KEY,
    first_name      TEXT NOT NULL,
    last_name       TEXT NOT NULL,
    age             SMALLINT,                 -- nullable: ~21% missing in source data
    email           TEXT NOT NULL,
    phone           TEXT,                     -- nullable: invalid/unparseable numbers become NULL
    join_date       DATE NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('Active', 'Inactive', 'Pending')),
    remote_work     BOOLEAN NOT NULL,
    salary          NUMERIC(12, 2),           -- nullable: ~2% missing in source data
    department_id   INTEGER REFERENCES departments(department_id),
    region_id       INTEGER REFERENCES regions(region_id),
    performance_id  INTEGER REFERENCES performance_levels(performance_id)
);

CREATE INDEX idx_employees_department ON employees(department_id);
CREATE INDEX idx_employees_region ON employees(region_id);
CREATE INDEX idx_employees_performance ON employees(performance_id);
CREATE INDEX idx_employees_status ON employees(status);
