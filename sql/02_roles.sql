-- Role setup for the SQL agent project.
-- Run once, as a superuser (e.g. the default 'postgres' role), against the target database.
--
-- Two roles, two jobs:
--   etl_writer      -> used only by the ETL pipeline (Phase 1) to create/load/update tables.
--   agent_readonly  -> used only by the LangChain agent (Phase 3) to run SELECT queries.
--
-- The agent's .env should ONLY ever contain agent_readonly's credentials. That way,
-- even if the LLM generates a destructive query (DROP, DELETE, UPDATE, ALTER), Postgres
-- itself rejects it at the permissions layer -- the safety doesn't depend on the LLM
-- behaving, or on prompt engineering catching everything.

-- Change these passwords before using outside local development.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'etl_writer') THEN
        CREATE ROLE etl_writer LOGIN PASSWORD 'change_me_writer';
    END IF;

    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'agent_readonly') THEN
        CREATE ROLE agent_readonly LOGIN PASSWORD 'change_me_readonly';
    END IF;
END
$$;

-- etl_writer: full DML/DDL rights on the public schema, so the pipeline can
-- create tables, load data, and re-run idempotently during development.
GRANT ALL PRIVILEGES ON SCHEMA public TO etl_writer;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO etl_writer;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO etl_writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO etl_writer;

-- agent_readonly: SELECT only. No INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE.
GRANT CONNECT ON DATABASE employee_db TO agent_readonly;
GRANT USAGE ON SCHEMA public TO agent_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO agent_readonly;
-- Ensures tables created LATER (e.g. if you add more dimension tables) are
-- automatically readable by the agent without manually re-granting each time.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO agent_readonly;
