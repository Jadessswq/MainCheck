"""Смоук-тесты FastAPI с моками Ollama/OpenRouter.

Не запускают реальные модели — проверяют структуру эндпоинтов, аудит,
формат ответа /suggest и корректную обработку ошибок.
"""
import importlib
import io
import os
import sys
from pathlib import Path

import httpx
import pytest


ROOT = Path(__file__).resolve().parent.parent


def _load_local_server(monkeypatch, tmp_path):
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("AUDIT_DB", str(tmp_path / "audit.sqlite"))
    monkeypatch.setenv("RAG_ENABLED", "false")
    monkeypatch.setenv("MODEL_NAME", "qwen3:30b-a3b")

    # Чистый импорт: сбрасываем кеш, чтобы env подхватился
    for m in list(sys.modules):
        if m.startswith(("shared", "main")):
            sys.modules.pop(m, None)

    local_dir = ROOT / "Сервер" / "local"
    sys.path.insert(0, str(local_dir))
    module = importlib.import_module("main")
    yield module
    sys.path.remove(str(local_dir))
    for m in list(sys.modules):
        if m.startswith(("shared", "main")):
            sys.modules.pop(m, None)


def _load_cloud_server(monkeypatch, tmp_path):
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("AUDIT_DB", str(tmp_path / "audit.sqlite"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test-key-123456")

    for m in list(sys.modules):
        if m.startswith(("shared", "main")):
            sys.modules.pop(m, None)

    cloud_dir = ROOT / "Сервер" / "cloud"
    sys.path.insert(0, str(cloud_dir))
    module = importlib.import_module("main")
    yield module
    sys.path.remove(str(cloud_dir))
    for m in list(sys.modules):
        if m.startswith(("shared", "main")):
            sys.modules.pop(m, None)


@pytest.fixture
def local_module(monkeypatch, tmp_path):
    yield from _load_local_server(monkeypatch, tmp_path)


@pytest.fixture
def cloud_module(monkeypatch, tmp_path):
    yield from _load_cloud_server(monkeypatch, tmp_path)


def test_local_suggest_with_mocked_ollama(local_module, monkeypatch):
    from fastapi.testclient import TestClient

    async def fake_call_ollama(messages):
        return (
            "===CORRECTED===\n"
            "Согласно приказу №5.\n"
            "===CHANGES===\n"
            "1. «согласно приказа» → «согласно приказу» | предлог требует дательного падежа\n"
            "===END==="
        )

    monkeypatch.setattr(local_module, "call_ollama", fake_call_ollama)
    client = TestClient(local_module.app)
    files = {
        "text": ("t.txt", io.BytesIO("согласно приказа №5".encode("utf-8")), "text/plain"),
        "context": ("c.txt", io.BytesIO(b""), "text/plain"),
    }
    r = client.post("/suggest", files=files)
    assert r.status_code == 200
    body = r.text
    assert "===CORRECTED===" in body
    assert "===CHANGES===" in body
    assert "===END===" in body
    assert "дательного падежа" in body


def test_local_suggest_handles_bad_format(local_module, monkeypatch):
    from fastapi.testclient import TestClient

    async def fake_call_ollama(messages):
        return "Просто текст без маркеров"

    monkeypatch.setattr(local_module, "call_ollama", fake_call_ollama)
    client = TestClient(local_module.app)
    files = {
        "text": ("t.txt", io.BytesIO("проверка".encode("utf-8")), "text/plain"),
        "context": ("c.txt", io.BytesIO(b""), "text/plain"),
    }
    r = client.post("/suggest", files=files)
    assert r.status_code == 200
    assert "===CORRECTED===" in r.text
    assert "не распознан" in r.text


def test_local_metrics(local_module):
    from fastapi.testclient import TestClient
    client = TestClient(local_module.app)
    r = client.get("/metrics")
    assert r.status_code == 200
    data = r.json()
    assert data["server"] == "local"
    assert "audit" in data


def test_local_empty_text_returns_error(local_module):
    from fastapi.testclient import TestClient
    client = TestClient(local_module.app)
    files = {
        "text": ("t.txt", io.BytesIO(b"   "), "text/plain"),
        "context": ("c.txt", io.BytesIO(b""), "text/plain"),
    }
    r = client.post("/suggest", files=files)
    assert r.status_code == 200
    assert r.text.startswith("ОШИБКА")


def test_cloud_suggest_with_mocked_openrouter(cloud_module, monkeypatch):
    from fastapi.testclient import TestClient

    async def fake_call_model(messages, model):
        return (
            "===CORRECTED===\nок\n"
            "===CHANGES===\n"
            "1. Ошибок не найдено.\n"
            "===END==="
        )

    monkeypatch.setattr(cloud_module, "call_model", fake_call_model)
    client = TestClient(cloud_module.app)
    files = {
        "text": ("t.txt", io.BytesIO("пример текста".encode("utf-8")), "text/plain"),
        "context": ("c.txt", io.BytesIO(b""), "text/plain"),
    }
    r = client.post("/suggest", files=files)
    assert r.status_code == 200
    assert "===CORRECTED===" in r.text


def test_cloud_metrics(cloud_module):
    from fastapi.testclient import TestClient
    client = TestClient(cloud_module.app)
    r = client.get("/metrics")
    assert r.status_code == 200
    assert r.json()["server"] == "cloud"


def test_cloud_missing_key(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("AUDIT_DB", str(tmp_path / "audit.sqlite"))

    for m in list(sys.modules):
        if m.startswith(("shared", "main")):
            sys.modules.pop(m, None)

    cloud_dir = ROOT / "Сервер" / "cloud"
    sys.path.insert(0, str(cloud_dir))
    try:
        module = importlib.import_module("main")
        from fastapi.testclient import TestClient
        client = TestClient(module.app)
        files = {
            "text": ("t.txt", io.BytesIO("x".encode("utf-8")), "text/plain"),
            "context": ("c.txt", io.BytesIO(b""), "text/plain"),
        }
        r = client.post("/suggest", files=files)
        assert "ОШИБКА" in r.text and "OPENROUTER_API_KEY" in r.text
    finally:
        sys.path.remove(str(cloud_dir))
