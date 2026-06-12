"""Focused tests for runtime Alembic bootstrap behavior."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from app.infra.db.migrations import _alembic_config, _engine_database_url, migrate_database_to_head


def test_engine_database_url_preserves_password_for_alembic_config():
    engine = create_engine("postgresql://stockscanner:secret@localhost/stockscanner")
    database_url = _engine_database_url(engine)
    assert database_url == "postgresql://stockscanner:secret@localhost/stockscanner"
    assert _alembic_config(database_url).get_main_option("sqlalchemy.url") == database_url
    engine.dispose()


def _stub_postgres_engine(calls: list[str]):
    """Engine stub recording advisory lock/unlock alongside migration steps."""

    def _record_execute(statement, params=None):
        sql = str(statement)
        if "pg_advisory_lock" in sql:
            calls.append("lock")
        elif "pg_advisory_unlock" in sql:
            calls.append("unlock")
        return MagicMock()

    conn = MagicMock()
    conn.execute.side_effect = _record_execute
    connect_cm = MagicMock()
    connect_cm.__enter__ = MagicMock(return_value=conn)
    connect_cm.__exit__ = MagicMock(return_value=False)

    engine = SimpleNamespace(
        url=make_url("postgresql://stockscanner:secret@localhost/stockscanner"),
        dialect=SimpleNamespace(name="postgresql"),
        connect=MagicMock(return_value=connect_cm),
    )
    return engine


def test_migrate_database_to_head_reconciles_existing_schema_without_alembic_version():
    calls: list[str] = []
    engine = _stub_postgres_engine(calls)
    config = object()

    with patch("app.infra.db.migrations._has_alembic_version_table", return_value=False), patch(
        "app.infra.db.migrations._has_user_tables", return_value=True
    ), patch("app.infra.db.migrations._alembic_config", return_value=config), patch(
        "app.infra.db.migrations.reconcile_legacy_runtime_schema",
        side_effect=lambda _engine: calls.append("reconcile"),
    ) as reconcile, patch(
        "app.infra.db.migrations.command.stamp",
        side_effect=lambda _config, _revision: calls.append("stamp"),
    ) as stamp, patch(
        "app.infra.db.migrations.command.upgrade",
        side_effect=lambda _config, _revision: calls.append("upgrade"),
    ) as upgrade:
        action = migrate_database_to_head(engine)

    assert action == "reconciled"
    # Advisory lock must bracket the entire reconcile/stamp/upgrade sequence
    # so concurrent uvicorn workers cannot interleave DDL.
    assert calls == ["lock", "reconcile", "stamp", "upgrade", "unlock"]
    reconcile.assert_called_once_with(engine)
    stamp.assert_called_once_with(config, "20260408_0001")
    upgrade.assert_called_once()


def test_migrate_database_to_head_upgrades_new_schema():
    # Non-Postgres dialect (test harness SQLite) skips the advisory lock path.
    engine = SimpleNamespace(
        url="sqlite://",
        dialect=SimpleNamespace(name="sqlite"),
        connect=MagicMock(side_effect=AssertionError("no lock connection expected")),
    )
    with patch("app.infra.db.migrations._has_alembic_version_table", return_value=False), patch(
        "app.infra.db.migrations._has_user_tables", return_value=False
    ), patch("app.infra.db.migrations._alembic_config", return_value=object()), patch(
        "app.infra.db.migrations.command.stamp"
    ) as stamp, patch("app.infra.db.migrations.command.upgrade") as upgrade:
        action = migrate_database_to_head(engine)

    assert action == "upgraded"
    stamp.assert_not_called()
    upgrade.assert_called_once()


def test_migrate_database_to_head_releases_lock_when_upgrade_fails():
    calls: list[str] = []
    engine = _stub_postgres_engine(calls)

    with patch("app.infra.db.migrations._has_alembic_version_table", return_value=True), patch(
        "app.infra.db.migrations._has_user_tables", return_value=True
    ), patch("app.infra.db.migrations._alembic_config", return_value=object()), patch(
        "app.infra.db.migrations.command.upgrade", side_effect=RuntimeError("boom")
    ):
        try:
            migrate_database_to_head(engine)
        except RuntimeError:
            pass
        else:  # pragma: no cover - defensive
            raise AssertionError("expected upgrade failure to propagate")

    assert calls == ["lock", "unlock"]
