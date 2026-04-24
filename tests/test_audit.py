"""Тесты аудита SQLite."""
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest

from shared.audit import AuditStore, Timer, count_changes


@pytest.fixture
def tmp_audit(tmp_path):
    return AuditStore(
        db_path=str(tmp_path / "audit.sqlite"),
        enabled=True,
        redact=False,
        retention_days=30,
    )


def test_record_and_stats(tmp_audit):
    tmp_audit.record(
        client_ip="10.0.0.1", user_agent="LibreOffice/7.5",
        server="local", model="qwen3:30b-a3b",
        text="Пробный текст.", context="контекст",
        changes_count=2, duration_ms=450, ok=True, error="",
    )
    tmp_audit.record(
        client_ip="10.0.0.2", user_agent="LibreOffice/7.4",
        server="local", model="qwen3:30b-a3b",
        text="ошибочный", context="",
        changes_count=0, duration_ms=50, ok=False, error="timeout",
    )

    stats = tmp_audit.stats(hours=1)
    assert stats["total"] == 2
    assert stats["ok"] == 1
    assert stats["fail"] == 1


def test_redact(tmp_path):
    store = AuditStore(db_path=str(tmp_path / "a.sqlite"),
                       enabled=True, redact=True, retention_days=30)
    store.record(text="Секретный текст", context="c", server="x", model="m")
    with sqlite3.connect(store.db_path) as c:
        row = c.execute("SELECT text_snippet, text_sha1 FROM audit").fetchone()
    assert row[0] == ""   # snippet скрыт
    assert len(row[1]) == 40  # sha1 всё равно сохранён (без самого текста)


def test_disabled(tmp_path):
    store = AuditStore(db_path=str(tmp_path / "a.sqlite"), enabled=False)
    store.record(text="x", context="y", server="s", model="m")  # не падает
    assert store.stats()["enabled"] is False


def test_purge_old(tmp_path):
    db = tmp_path / "old.sqlite"
    store = AuditStore(db_path=str(db), enabled=True, retention_days=30)
    store.record(text="recent", context="", server="x", model="m")
    # Вставляем «старую» запись напрямую
    old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    with sqlite3.connect(db) as c:
        c.execute(
            """INSERT INTO audit (ts, client_ip, server, model, text_len, context_len,
                                  changes_count, duration_ms, ok, error, text_sha1, text_snippet)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (old, "", "x", "m", 10, 0, 0, 10, 1, "", "hash", "old"),
        )
    deleted = store.purge_old()
    assert deleted == 1
    assert store.stats(hours=24 * 90)["total"] == 1


def test_count_changes():
    resp = (
        "===CORRECTED===\nтекст\n"
        "===CHANGES===\n"
        "1. «а» → «б» | причина\n"
        "2. «в» → «г» | причина\n"
        "3. «д» → «е» | причина\n"
        "===END==="
    )
    assert count_changes(resp) == 3


def test_count_changes_ok():
    resp = (
        "===CORRECTED===\nтекст\n"
        "===CHANGES===\n"
        "1. Ошибок не найдено. Текст соответствует нормам.\n"
        "===END==="
    )
    # «Ошибок не найдено» — это 0 реальных исправлений
    assert count_changes(resp) in (0, 1)


def test_timer():
    with Timer() as t:
        time.sleep(0.01)
    assert t.ms >= 10
