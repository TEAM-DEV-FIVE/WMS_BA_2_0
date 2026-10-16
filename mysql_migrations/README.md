# MySQL migration and runtime

Local deployment: **MYSQL_ACTIVE** on 2026-10-16, database `wms_mysql`.
See [verified cutover evidence](../07_Kiem_tra/mysql/STATUS.md). PostgreSQL and its
backup remain available for recovery.

`001_schema.staging.json` contains native MySQL 8.0 table DDL, primary/unique
indexes, generated columns for partial uniqueness, CHECK constraints and foreign
keys. It is generated from the reviewed PostgreSQL schema inventory by
`scripts/build_mysql_schema.py`. The existing PostgreSQL migrations are unchanged.

A database copied by the staging tool is **not ready for application use** until
preparation, reconciliation and runtime checks pass. The `STAGING_ONLY` label in
the schema asset describes that intermediate DDL stage, not the active deployment.
Bootstrap refuses existing unmanaged databases.

`002_guards.staging.json` contains native business triggers and the reversal
validation procedure; `003_seed.json` contains only migration seed data;
`004_runtime.json` defines transaction locks, publication locks and the document
number allocator and imported-outbox archive. Readiness checks the checksums of these assets and the typed
column metadata. Existing PostgreSQL migrations and connection support remain.

MySQL has no deferred constraint triggers. Reversal validation therefore runs
through the application's connection commit protocol before committing a command.
Direct SQL writers must not bypass that protocol. This differs from PostgreSQL's
database-enforced deferred trigger and requires dedicated rollback/race tests.
Transaction advisory locks use InnoDB rows; shared transaction callers are
conservatively serialized. Storage publication fences retain shared/exclusive
session semantics. Number allocation uses InnoDB AUTO_INCREMENT and does not
reuse rolled-back allocations.

## Data transfer

`scripts/stage_mysql_data.py` accepts a source environment file, a private target
credentials file, an empty `wms_mysql` or `kws_mysql` database, and a private report
path. It refuses nonempty destinations and insufficient free disk space.

- Read the PostgreSQL source in a repeatable-read, read-only transaction.
- Verify source table names, column order, types and nullability.
- Preserve UUIDs, exact DECIMAL values, JSON, dates and UTC microseconds.
- Load rows in one target data transaction; do not disable foreign-key checks.
- Add and validate foreign keys after loading, including cyclic relationships.
- Compare per-table counts and SHA-256 digests in primary-key order.
- Record document sequence state; final transfer requires stopped source writers
  because PostgreSQL sequences are outside the repeatable-read snapshot.
- Never change application connections or start workers.

MySQL DDL commits separately from the data transaction. A failed stage may leave
empty tables or partially validated DDL; inspect the private report and use a new
empty staging database. The tool never drops an existing database automatically.

Indexing unbounded PostgreSQL text requires reviewed bounds for five protocol
identity fields, listed in `bounded_text`. Transfer rejects values outside these
bounds rather than truncating them. Original PostgreSQL and backups remain the
recovery source.

For KWS, do not discard historical stock movements merely because a screen was
removed. Activation also requires a separate review of active sessions, queued
jobs and outbox messages to prevent replaying WMS activity in the new app.

## Tool environment

Use an isolated Python environment with `requirements-mysql-migration.txt`.
Run the offline checks from the repository root:

```sh
python -m pytest tests/mysql_migration -q
```

These checks validate the staging tools only, not application behavior on MySQL.
Run API/transaction tests with `python scripts/check_mysql.py <pytest arguments>`.
The runner starts a private socket-only MySQL instance, removes operational
database URLs from its environment and deletes its temporary data on exit.

Load the MySQL timezone tables from the host's zoneinfo database before using
named business timezones. Connections reject a missing configured timezone;
report age uses calendar-day differences after conversion from UTC. The private
test runner loads its own timezone tables.

`scripts/build_mysql_reconciliation.py` generates the native read-only checks in
`02_CSDL/mysql/`. Run all 25 result sets in a consistent read-only transaction;
each must be empty. These check stock/ledger equality, reservations, serial
positions, ownership, fulfillment, transfers, reversals and posting evidence.

## Preparing a verified stage

`scripts/prepare_mysql_stage.py` requires a fresh staging report with schema DDL
hashes, per-table data hashes and the captured document sequence. It rechecks
all evidence before installing native triggers, runtime tables and readiness
metadata. On this host `--sudo-local-admin` uses the already authorized local
MySQL administrator for DDL; it does not grant SUPER to the migration account.
An incomplete preparation remains unavailable to application startup.

For `kws_mysql`, preparation preserves documents, reservations, ledger and balances.
It records copied outbox events in an immutable archive, without marking them
processed or manufacturing consumer ACKs. Workers exclude archived events.
Copied login sessions and recovery codes are revoked; temporary authentication
challenges and delivery tokens expire. Users sign in again to the new application.
The preparation report records these changes separately from the exact-copy proof.

Neither script changes application connection settings. Activation requires
quiesced source writers, a current backup, a fresh transfer, successful native
reconciliation and application verification. Keep the PostgreSQL deployment and
backup available for recovery; never replay writes on both databases.

Worker claims on MySQL use the matching ordered queue index with `SKIP LOCKED`.
This prevents a filesort plan from locking every scanned queue row before LIMIT.
See [InnoDB statement locking](https://dev.mysql.com/doc/refman/8.0/en/innodb-locks-set.html).
Parallel-worker tests verify that another worker can claim the next unlocked row.
