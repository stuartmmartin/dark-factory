#!/bin/sh
# Runs once on a fresh volume. Creates the platform roles; service databases are created by
# each service's migrate step (sb_db.database.ensure_database) so this file never changes.
# sb_migrator has BYPASSRLS so migrations/backfills see every tenant's rows; sb_app never does.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-SQL
  CREATE ROLE sb_migrator LOGIN CREATEDB BYPASSRLS PASSWORD '${SB_MIGRATOR_PASSWORD}';
  CREATE ROLE sb_app LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '${SB_APP_PASSWORD}';
  CREATE ROLE sb_readonly LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '${SB_READONLY_PASSWORD}';
SQL
