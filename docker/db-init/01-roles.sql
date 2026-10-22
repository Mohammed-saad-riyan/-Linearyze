-- Runs once when the volume is created. ems_owner (POSTGRES_USER) owns every table;
-- ems_app is what the API logs in as.
CREATE ROLE ems_app LOGIN PASSWORD 'ems_app' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
