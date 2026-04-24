"""Тесты настройки логгера."""
import logging
import os
from pathlib import Path

from shared.logging_setup import setup_logger


def test_creates_file_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("LOG_RETENTION_DAYS", "7")

    log1 = setup_logger("test_al")
    log1.info("hello")
    log2 = setup_logger("test_al")  # повторный вызов не должен дублировать handler'ы
    log2.warning("warn")
    assert log1 is log2
    # Файл создан
    assert (tmp_path / "test_al.log").exists()
    # Handler'ы не задваиваются
    assert len(log1.handlers) == 2  # file + console
