import inspect
import sqlite3
from pathlib import Path

import pytest

import jobbot.db as db
from jobbot.db import (
    SCHEMA_VERSION,
    JobStore,
    Migration,
    MigrationError,
    load_migrations,
    migrate,
)
from jobbot.models import Job

# The schema exactly as db._SCHEMA defined it before migrations existed (user_version 1).
LEGACY_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id                 INTEGER PRIMARY KEY,
    platform           TEXT NOT NULL,
    job_key            TEXT NOT NULL,
    url                TEXT,
    title              TEXT NOT NULL DEFAULT '',
    company            TEXT NOT NULL DEFAULT '',
    location           TEXT NOT NULL DEFAULT '',
    description        TEXT,
    description_sha256 TEXT,
    snippet            TEXT,
    salary             TEXT,
    posted_at          TEXT,
    easy_apply         INTEGER,
    remote             INTEGER,
    company_size       TEXT,
    search_name        TEXT,
    status             TEXT NOT NULL DEFAULT 'new',
    decision           TEXT,
    resume_id          TEXT,
    score              INTEGER,
    reason             TEXT,
    decision_json      TEXT,
    error              TEXT,
    first_seen_at      TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    decided_at         TEXT,
    UNIQUE (platform, job_key)
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status);
CREATE INDEX IF NOT EXISTS idx_jobs_desc ON jobs (description_sha256);
"""


def user_version(path: Path) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def schema(path: Path) -> list[tuple[str, str, str, str]]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
    finally:
        conn.close()


def table_names(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def legacy_db(path: Path, version: int, rows: int = 2) -> None:
    """A DB as the pre-migration code (version 1) or older code (version 0) left it."""
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_SCHEMA)
    for i in range(rows):
        conn.execute(
            "INSERT INTO jobs (platform, job_key, title, status, first_seen_at, updated_at) "
            "VALUES ('indeed', ?, 'Java Developer', 'pending_review', 't', 't')",
            (f"k{i}",),
        )
    conn.execute(f"PRAGMA user_version = {version}")
    conn.commit()
    conn.close()


def write_migrations(folder: Path, files: dict[str, str]) -> Path:
    folder.mkdir()
    for name, sql in files.items():
        (folder / name).write_text(sql, encoding="utf-8")
    return folder


# ------------------------------------------------------------------ the real migrations


def test_db_module_has_no_inline_ddl():
    source = inspect.getsource(db).upper()
    assert "CREATE TABLE" not in source
    assert "CREATE INDEX" not in source


def test_schema_version_is_latest_migration():
    migrations = load_migrations()
    assert migrations[0].name == "0001_init.sql"
    assert SCHEMA_VERSION == migrations[-1].version == len(migrations)


def test_init_migration_matches_legacy_schema(tmp_path):
    legacy = tmp_path / "legacy.db"
    legacy_db(legacy, version=1, rows=0)
    JobStore(tmp_path / "new.db").close()
    assert schema(tmp_path / "new.db") == schema(legacy)


def test_fresh_db_gets_schema_and_latest_version(tmp_path):
    path = tmp_path / "jobs.db"
    with JobStore(path) as store:
        assert store.upsert_listing(
            Job(platform="indeed", job_key="a", title="SDE", description=""),
            snippet=None,
            search_name="s",
        )
        assert store.counts() == {"new": 1}
    assert user_version(path) == SCHEMA_VERSION
    names = {row[1] for row in schema(path)}
    assert {"jobs", "idx_jobs_status", "idx_jobs_desc"} <= names


def test_reopen_is_idempotent(tmp_path):
    path = tmp_path / "jobs.db"
    with JobStore(path) as store:
        store.upsert_listing(
            Job(platform="indeed", job_key="a", description=""), snippet=None, search_name="s"
        )
    before = schema(path)
    with JobStore(path) as store:
        assert store.counts() == {"new": 1}
    assert schema(path) == before
    assert user_version(path) == SCHEMA_VERSION


def test_existing_v1_db_keeps_rows_and_is_not_remigrated(tmp_path, monkeypatch):
    path = tmp_path / "jobs.db"
    legacy_db(path, version=1)
    # If migration 1 ran again on this DB, this invalid SQL would raise.
    monkeypatch.setattr(
        db, "load_migrations", lambda: [Migration(1, "0001_boom.sql", "THIS IS NOT SQL")]
    )
    with JobStore(path) as store:
        assert store.counts() == {"pending_review": 2}
        assert store.get_by_key("indeed", "k1")["title"] == "Java Developer"
    assert user_version(path) == 1


def test_existing_v1_db_opens_with_real_migrations(tmp_path):
    path = tmp_path / "jobs.db"
    legacy_db(path, version=1)
    before = schema(path)
    with JobStore(path) as store:
        assert store.counts() == {"pending_review": 2}
    assert schema(path) == before
    assert user_version(path) == SCHEMA_VERSION


def test_pre_versioning_db_opens(tmp_path):
    path = tmp_path / "jobs.db"
    legacy_db(path, version=0)
    with JobStore(path) as store:
        assert store.counts() == {"pending_review": 2}
    assert user_version(path) == SCHEMA_VERSION


def test_newer_db_version_raises(tmp_path):
    path = tmp_path / "jobs.db"
    legacy_db(path, version=SCHEMA_VERSION + 1)
    with pytest.raises(MigrationError, match="newer"):
        JobStore(path)
    assert user_version(path) == SCHEMA_VERSION + 1  # left untouched
    path.unlink()  # the failed JobStore closed its connection, so the file is not locked


# ------------------------------------------------------------------ runner with fake sources


def test_loader_reads_folder_sorted_and_ignores_other_files(tmp_path):
    folder = write_migrations(
        tmp_path / "m",
        {
            "0002_b.sql": "CREATE TABLE b (x);",
            "0001_a.sql": "CREATE TABLE a (x);",
            "README.txt": "not a migration",
            "1_bad_name.sql": "not a migration either",
        },
    )
    migrations = load_migrations(folder)
    assert [(m.version, m.name) for m in migrations] == [(1, "0001_a.sql"), (2, "0002_b.sql")]


def test_migrate_applies_pending_in_order(tmp_path):
    folder = write_migrations(
        tmp_path / "m",
        {
            "0001_a.sql": "CREATE TABLE a (x);",
            "0002_b.sql": "CREATE TABLE b (x); INSERT INTO a VALUES (1);",
        },
    )
    conn = sqlite3.connect(tmp_path / "t.db")
    assert migrate(conn, load_migrations(folder)) == 2
    assert table_names(conn) == {"a", "b"}
    assert conn.execute("SELECT x FROM a").fetchall() == [(1,)]
    assert migrate(conn, load_migrations(folder)) == 2  # nothing pending: no duplicate insert
    assert conn.execute("SELECT COUNT(*) FROM a").fetchone()[0] == 1
    conn.close()


def test_failing_migration_rolls_back_ddl_and_version(tmp_path):
    folder = write_migrations(
        tmp_path / "m",
        {
            "0001_ok.sql": "CREATE TABLE a (x);",
            # The CREATE succeeds, then the INSERT fails: both must be undone.
            "0002_bad.sql": "CREATE TABLE b (x);\nINSERT INTO missing_table VALUES (1);",
        },
    )
    path = tmp_path / "t.db"
    conn = sqlite3.connect(path)
    with pytest.raises(MigrationError, match="0002_bad.sql"):
        migrate(conn, load_migrations(folder))
    assert not conn.in_transaction
    conn.close()

    check = sqlite3.connect(path)  # a fresh connection sees only committed state
    assert table_names(check) == {"a"}
    assert check.execute("PRAGMA user_version").fetchone()[0] == 1
    check.close()


def test_connection_mode_restored_after_failure(tmp_path):
    conn = sqlite3.connect(tmp_path / "t.db")
    mode = conn.autocommit
    bad = [Migration(1, "0001_bad.sql", "CREATE TABLE a (x); SELECT * FROM nope;")]
    with pytest.raises(MigrationError):
        migrate(conn, bad)
    assert conn.autocommit == mode
    assert table_names(conn) == set()
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    conn.close()


def test_failed_migration_in_jobstore_closes_connection(tmp_path, monkeypatch):
    path = tmp_path / "jobs.db"
    monkeypatch.setattr(
        db, "load_migrations", lambda: [Migration(1, "0001_bad.sql", "NOT SQL AT ALL")]
    )
    with pytest.raises(MigrationError, match="0001_bad.sql"):
        JobStore(path)
    assert user_version(path) == 0
    path.unlink()  # would fail on Windows if the connection were left open


def test_gap_in_numbers_raises(tmp_path):
    folder = write_migrations(
        tmp_path / "m", {"0001_a.sql": "SELECT 1;", "0003_c.sql": "SELECT 1;"}
    )
    with pytest.raises(MigrationError, match="contiguous"):
        load_migrations(folder)


def test_not_starting_at_one_raises(tmp_path):
    folder = write_migrations(tmp_path / "m", {"0002_b.sql": "SELECT 1;"})
    with pytest.raises(MigrationError, match="contiguous"):
        load_migrations(folder)


def test_duplicate_numbers_raise(tmp_path):
    folder = write_migrations(
        tmp_path / "m",
        {"0001_a.sql": "SELECT 1;", "0001_b.sql": "SELECT 1;", "0002_c.sql": "SELECT 1;"},
    )
    with pytest.raises(MigrationError, match="Duplicate"):
        load_migrations(folder)


def test_no_migrations_raises(tmp_path):
    folder = write_migrations(tmp_path / "m", {})
    with pytest.raises(MigrationError, match="No schema migrations"):
        load_migrations(folder)


def test_migrate_validates_injected_list(tmp_path):
    conn = sqlite3.connect(tmp_path / "t.db")
    with pytest.raises(MigrationError, match="contiguous"):
        migrate(conn, [Migration(2, "0002_b.sql", "SELECT 1;")])
    conn.close()
