# 1C PostgreSQL Number Index Tools

This project helps administrators create and monitor PostgreSQL expression
indexes that speed up standard 1C document search by number.

1C can generate predicates like:

```sql
WHERE (_Number)::mvarchar LIKE 'PREFIX%'::mvarchar ESCAPE '\'
ORDER BY _Date_Time DESC
LIMIT 50
```

When the `_number` column has type `mchar`, the regular index on `_number` may
not be used. The managed index has this default form:

```sql
CREATE INDEX CONCURRENTLY idx_<table_name>_number_as_mvarchar
ON public.<table_name>
USING btree ((_number::mvarchar));
```

For 1C tables whose names start with an underscore, the generated index name
omits that leading underscore. For example, `_document213` uses:

```text
idx_document213_number_as_mvarchar
```

## Project Layout

```text
/opt/1c-pg-tools/
  README.md
  config.yaml
  requirements.txt
  .pgpass.example
  pg1c_indexes.py
  onec_pg_tools/
    config.py
    index_sql.py
    output.py
    postgres.py
    repository.py
  sql/
    checks.sql
    reports.sql
```

- `pg1c_indexes.py` is the main command-line tool.
- `onec_pg_tools/` contains the internal modules for configuration,
  PostgreSQL access, SQL generation, and report output.
- `config.yaml` stores the PostgreSQL endpoint and the explicit production
  database allowlist.
- `.pgpass.example` shows the recommended password format.
- `requirements.txt` lists Python dependencies.
- `sql/checks.sql` contains manual safety checks.
- `sql/reports.sql` contains the manual usage report query.

## Installation

Recommended directory permissions:

```bash
chown -R root:root /opt/1c-pg-tools
chmod 700 /opt/1c-pg-tools
chmod 600 /opt/1c-pg-tools/config.yaml
```

Install dependencies:

```bash
cd /opt/1c-pg-tools
python3 -m pip install -r requirements.txt
```

## Configuration

The tool connects through the HAProxy write endpoint:

```yaml
postgres:
  host: pg-write.example.internal
  port: 5432
  user: postgres
  connect_db: postgres

defaults:
  min_table_size_gb: 1
  include_document_journals: false
  include_tasks: true
  analyze_after_create: true

databases:
  - name: infobase_prod
    enabled: true
    min_table_size_gb: 1
    include_document_journals: false
    include_tasks: true
```

Only databases with `enabled: true` are processed. The tool never scans every
cluster database automatically.

Candidate tables are selected from `public` when:

- the table has a `_number` column;
- `_number` has type `mchar` or `mvarchar`;
- the table size is at least `min_table_size_gb`;
- a valid `_number::mvarchar` expression index does not already exist;
- the table matches the enabled 1C table rules.

Table rules:

- `_document%` is included by default;
- `_task%` is included when `include_tasks: true`;
- `_documentjournal%` is included only when
  `include_document_journals: true`.

## Password Storage

Do not store the PostgreSQL password in `config.yaml`.

Preferred setup:

```bash
cp /opt/1c-pg-tools/.pgpass.example ~/.pgpass
chmod 600 ~/.pgpass
```

When the tool is run as `root`, the default libpq password file is:

```text
/root/.pgpass
```

The tool does not override `PGPASSFILE`. Password lookup follows standard libpq
behavior, the same as `psql`: use `PGPASSFILE` when it is set, otherwise use
the current user's `~/.pgpass`.

Example `.pgpass` line:

```text
pg-write.example.internal:5432:*:postgres:strong_password_here
```

`PGPASSWORD` also works, but a user-owned `.pgpass` file is preferred.

## Run Modes

List cluster databases:

```bash
cd /opt/1c-pg-tools
python3 pg1c_indexes.py list-databases
```

The `list-databases` mode connects to the configured PostgreSQL endpoint and
shows non-template databases with owner, size, connection availability, encoding,
and whether each database is already present and enabled in `config.yaml`.

Dry run:

```bash
cd /opt/1c-pg-tools
python3 pg1c_indexes.py dry-run
```

The `dry-run` mode reads `config.yaml`, connects through the configured
PostgreSQL write endpoint, checks that the connection points to the primary,
finds candidate tables, and prints SQL statements without creating indexes.

If an index with the target name already exists but does not match the expected
definition, the table is skipped and the existing index definition is written to
the log. The tool does not drop or replace indexes automatically.

Pending index check:

```bash
cd /opt/1c-pg-tools
python3 pg1c_indexes.py pending
```

The `pending` mode is intended for cron jobs and external notification systems.
It uses the same candidate discovery and safety checks as `dry-run`, but never
creates indexes and suppresses regular INFO console logging.

Exit codes:

- `0`: no pending indexes;
- `1`: pending indexes were found;
- `2`: the check failed.

When no indexes are pending, output is short:

```text
No pending indexes.
```

When candidates are found, each line is compact and suitable for notification
messages:

```text
database=torg table=_document206 size=2796 MB sql=CREATE INDEX CONCURRENTLY "idx_document206_number_as_mvarchar" ON public."_document206" USING btree (((_number)::mvarchar));
```

Create missing indexes:

```bash
cd /opt/1c-pg-tools
python3 pg1c_indexes.py run
```

The `run` mode creates indexes one by one with `CREATE INDEX CONCURRENTLY`.
Autocommit is enabled because concurrent index creation cannot run inside a
regular transaction. When `analyze_after_create: true`, the tool runs:

```sql
ANALYZE public.<table_name>;
```

Usage report:

```bash
cd /opt/1c-pg-tools
python3 pg1c_indexes.py report
```

The report shows managed indexes, table size, index size, `idx_scan`,
`idx_tup_read`, `idx_tup_fetch`, and the check timestamp.

Invalid index check:

```bash
cd /opt/1c-pg-tools
python3 pg1c_indexes.py check-invalid
```

This mode shows managed indexes with `indisvalid = false` or
`indisready = false`. Such indexes can remain after a connection loss or
failover during `CREATE INDEX CONCURRENTLY`.

## Logging

Default log directory:

```text
/var/log/1c-pg-tools/
```

Default daily log file:

```text
ensure_indexes_YYYY-MM-DD.log
```

Logs include run timestamp, mode, database, table, table size, generated SQL,
execution result, elapsed creation time, and errors.

If the configured log directory cannot be created or opened, the tool continues
with console logging and writes a warning.

## Cron Monitoring

Example wrapper script:

```bash
#!/bin/bash
set -o pipefail

OUT=$(/usr/bin/python3 /opt/1c-pg-tools/pg1c_indexes.py pending 2>&1)
RC=$?

if [ "$RC" -eq 1 ]; then
    /opt/admin-tools/notify.sh "1C PostgreSQL index candidates found" "$OUT"
elif [ "$RC" -eq 2 ]; then
    /opt/admin-tools/notify.sh "1C PostgreSQL index check failed" "$OUT"
fi
```

Example crontab entry:

```cron
SHELL=/bin/bash
0 2 * * 0 root /opt/1c-pg-tools/check-pending-indexes.sh >> /var/log/1c-pg-tools/check-pending-indexes.log 2>&1
```

The wrapper intentionally checks exit codes instead of parsing logs. Regular
mode logs can still be reviewed under `/var/log/1c-pg-tools/` when detailed
diagnostics are needed.

## PostgreSQL Permissions

Some 1C installations keep application objects under a superuser or owner role
such as `postgres`. The example configuration uses `postgres` as a placeholder,
but a dedicated maintenance role is preferable when ownership and permissions
allow it.

Risk reduction rules:

- keep the password only in `.pgpass`;
- set `.pgpass` permissions to `600`;
- keep the project directory readable only by root or administrators;
- do not store passwords in YAML;
- run the tool only from the administrative machine;
- use only the configured HAProxy or load balancer write endpoint.

For a restricted PostgreSQL user, the user must be able to connect to each
enabled database and create indexes on the target tables. In PostgreSQL this is
usually tied to table ownership or superuser privileges, so changing ownership
or using controlled owner roles may be required.

## Operating Procedure

When moving a new 1C database to PostgreSQL:

1. Run `list-databases` and identify the production database name.
2. Add the database to `config.yaml`.
3. Run `dry-run`.
4. Review candidate tables and generated SQL.
5. Run `run`.
6. Run `report`.
7. Test document search by number in 1C.

Monthly maintenance:

1. Run `report`.
2. Review `idx_scan` for actual index usage.
3. Run `check-invalid`.
4. Review index sizes.

After a 1C configuration update:

1. Run `dry-run`.
2. Check whether new large `_number` tables appeared.
3. Run `run` when new indexes are needed.

## Safety Limits

- Do not enable dev, test, or service databases in `config.yaml`.
- Do not create indexes across all cluster databases automatically.
- Do not store PostgreSQL passwords in `config.yaml`.
- Do not place the script on every Patroni node.
- Do not run `CREATE INDEX CONCURRENTLY` inside a transaction.
- Do not auto-index `_documentjournal%` tables without explicit enablement.
- Do not remove indexes automatically in this project stage.
