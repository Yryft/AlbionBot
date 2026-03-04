from __future__ import annotations

from types import SimpleNamespace

from albionbot.storage.bank_db import BankDB
import albionbot.storage.bank_db as bank_db_module


class FakeOperationalError(Exception):
    pass


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        self.conn.execute_calls += 1
        if self.conn.fail_next:
            self.conn.fail_next = False
            raise FakeOperationalError("consuming input failed: SSL error: unexpected eof while reading")

    def fetchone(self):
        return {"value_json": "{}"}


class FakeConn:
    def __init__(self, fail_next=False):
        self.fail_next = fail_next
        self.execute_calls = 0
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def close(self):
        self.closed = True


def test_postgres_fetchone_retries_once_after_operational_error(monkeypatch):
    db = BankDB.__new__(BankDB)
    db.kind = "postgres"
    db._pg_url = "postgres://example"
    first = FakeConn(fail_next=True)
    second = FakeConn(fail_next=False)
    db._pg_conn = first

    monkeypatch.setattr(bank_db_module, "psycopg", SimpleNamespace(
        OperationalError=FakeOperationalError,
        InterfaceError=FakeOperationalError,
    ))
    db._connect_postgres = lambda: second

    row = db._fetchone("SELECT value_json FROM bot_state WHERE key = %s", ("k",))

    assert row == {"value_json": "{}"}
    assert first.closed is True
    assert second.execute_calls == 1


def test_postgres_fetchone_does_not_retry_non_retryable_error(monkeypatch):
    class NonRetryable(Exception):
        pass

    class BadCursor(FakeCursor):
        def execute(self, sql, params):
            raise NonRetryable("boom")

    class BadConn(FakeConn):
        def cursor(self):
            return BadCursor(self)

    db = BankDB.__new__(BankDB)
    db.kind = "postgres"
    db._pg_url = "postgres://example"
    db._pg_conn = BadConn()

    monkeypatch.setattr(bank_db_module, "psycopg", SimpleNamespace(
        OperationalError=FakeOperationalError,
        InterfaceError=FakeOperationalError,
    ))

    try:
        db._fetchone("SELECT 1", ())
        raised = False
    except NonRetryable:
        raised = True

    assert raised is True
