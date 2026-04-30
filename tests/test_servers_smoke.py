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


def test_local_strip_thinking(local_module):
    """Проверка, что <think>…</think> обрезается из ответа Ollama."""
    raw = (
        "<think>Долго рассуждаю про падежи и согласование...</think>\n\n"
        "===CORRECTED===\nтекст\n===CHANGES===\n1. Ошибок нет.\n===END==="
    )
    out = local_module._strip_thinking(raw)
    assert "<think>" not in out
    assert "Долго рассуждаю" not in out
    assert out.startswith("===CORRECTED===")


def test_local_strip_thinking_without_tags(local_module):
    """Если модель пишет рассуждения без <think>, но дальше ===CORRECTED===,
    обрезаем всё до маркера."""
    raw = (
        "Пользователь хочет проверку текста. Подумаю над правилами...\n\n"
        "===CORRECTED===\nок\n===CHANGES===\n1. Ошибок нет.\n===END==="
    )
    out = local_module._strip_thinking(raw)
    assert out.startswith("===CORRECTED===")
    assert "Пользователь хочет" not in out


def test_local_drops_idempotent_changes(local_module):
    """Пункт вида «X → X» (before=after) фильтруется из ===CHANGES==="""
    raw = (
        "===CORRECTED===\n"
        "текст\n"
        "===CHANGES===\n"
        "1. «согласно распоряжению» — исправлено на «согласно распоряжению» (дательный падеж)\n"
        "2. «округе» → «округах» (множественное число)\n"
        "3. «отдел подготовил отчётность» — исправлено на «отдел подготовил отчётность» (без изменений)\n"
        "===END==="
    )
    out = local_module._drop_idempotent_changes(raw)
    # Первый и третий пункт должны исчезнуть; остался только содержательный
    assert "«округах»" in out
    assert "«согласно распоряжению»" not in out
    assert "отдел подготовил отчётность" not in out
    # Рамки сохранены
    assert "===CORRECTED===" in out
    assert "===CHANGES===" in out
    assert "===END===" in out


def test_local_drops_idempotent_changes_empty_fallback(local_module):
    """Если после фильтрации пунктов не осталось — подставляем заглушку."""
    raw = (
        "===CORRECTED===\n"
        "текст\n"
        "===CHANGES===\n"
        "1. «фраза» → «фраза»\n"
        "2. «другая» — исправлено на «другая»\n"
        "===END==="
    )
    out = local_module._drop_idempotent_changes(raw)
    assert "Ошибок не найдено" in out
    assert "===END===" in out


def test_local_case_correction_is_preserved(local_module):
    """Правка только регистра (Приказа → приказа) — валидная орфографическая,
    НЕ должна считаться идемпотентной и НЕ должна удаляться из ===CHANGES===."""
    raw = (
        "===CORRECTED===\n"
        "на основании приказа...\n"
        "===CHANGES===\n"
        "1. «Приказа» → «приказа» (слово не является именем собственным)\n"
        "2. «округе» → «округе» (ложная правка — дублирует текст)\n"
        "===END==="
    )
    out = local_module._drop_idempotent_changes(raw)
    # Правка регистра сохранена
    assert "«Приказа» → «приказа»" in out
    # Идемпотентная отфильтрована
    assert "«округе» → «округе»" not in out
    # Заглушка НЕ подставлена (остался содержательный пункт)
    assert "Ошибок не найдено" not in out


def test_local_drops_changes_with_ellipsis_in_quotes(local_module):
    """Пункты с многоточием («...» или «…») в цитатах неприменимы клиентом
    (InStr не найдёт сокращённую цитату в выделении). Сервер их отбрасывает,
    чтобы пользователь не видел «не удалось применить» на каждом запросе.

    Видели на yandex-corrector / Yandex-template моделях — стилистически
    сокращают длинные цитаты. T-lite и qwen2.5 этим почти не страдают."""
    raw = (
        "===CORRECTED===\n"
        "текст\n"
        "===CHANGES===\n"
        "1. «по обеспечению...» → «по обеспечению,...» | пропущенная запятая\n"
        "2. «короткая фраза» → «короткая, фраза» | запятая\n"
        "3. «другой пример…» → «другой, пример…» | unicode-многоточие\n"
        "===END==="
    )
    out = local_module._drop_idempotent_changes(raw)
    # Пункты 1 и 3 (многоточие в цитате) отфильтрованы
    assert "по обеспечению" not in out
    assert "другой пример" not in out
    # Пункт 2 (без многоточия) сохранён
    assert "«короткая фраза» → «короткая, фраза»" in out
    # Заглушка НЕ подставлена (остался содержательный пункт)
    assert "Ошибок не найдено" not in out


def test_local_strip_thinking_preserves_non_thinking(local_module):
    """Если в ответе нет ни <think>, ни ===CORRECTED=== — возвращаем как есть."""
    raw = "ПроизвольныйТекстБезМаркеров"
    out = local_module._strip_thinking(raw)
    assert out == "ПроизвольныйТекстБезМаркеров"


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
