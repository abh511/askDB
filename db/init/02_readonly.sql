-- Second layer of safety: the app connects as a user that can only SELECT.
-- Change the password before deploying anywhere public.
CREATE ROLE askdb_reader LOGIN PASSWORD 'reader_pw';

GRANT CONNECT ON DATABASE askdb TO askdb_reader;
GRANT USAGE ON SCHEMA public TO askdb_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO askdb_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO askdb_reader;

-- Every query from this user is killed after 5 seconds.
ALTER ROLE askdb_reader SET statement_timeout = '5s';

-- Check it works (as askdb_reader):  DELETE FROM orders;  -> permission denied
