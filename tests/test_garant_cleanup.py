"""Тесты очистки документов, выгруженных из Гарант/КонсультантПлюс."""
from shared.garant_cleanup import clean_text, chunk_text


GARANT_SAMPLE = """Система ГАРАНТ: https://garant.ru
© Гарант, 2024

Документ предоставлен КонсультантПлюс

Статья 12. Основные положения

Настоящая статья устанавливает общие принципы орга-
низации делопроизводства в федеральных органах исполнительной
власти.

Информация об изменениях

С 1 января 2025 г. часть 2 статьи 12 излагается в новой редакции.

Согласно пункту 3 настоящей статьи, документы подлежат
регистрации в установленном порядке.

──────────────────────

Страница 1 из 3

КонсультантПлюс надежная правовая поддержка
Дата печати: 15.03.2024

"""


def test_clean_removes_service_headers():
    cleaned, stats = clean_text(GARANT_SAMPLE)
    assert "Система ГАРАНТ" not in cleaned
    assert "КонсультантПлюс" not in cleaned
    assert "Документ предоставлен" not in cleaned
    assert "Дата печати" not in cleaned
    assert "Страница 1 из 3" not in cleaned
    assert "Информация об изменениях" not in cleaned
    assert "──" not in cleaned
    assert stats.removed_service >= 6


def test_clean_joins_soft_hyphen_breaks():
    cleaned, _ = clean_text(GARANT_SAMPLE)
    # «орга-\nнизации» → «организации»
    assert "организации" in cleaned
    assert "орга-" not in cleaned


def test_clean_keeps_real_content():
    cleaned, _ = clean_text(GARANT_SAMPLE)
    assert "Настоящая статья устанавливает" in cleaned
    assert "Согласно пункту 3" in cleaned


def test_clean_nbsp_normalisation():
    raw = "Абзац\u00a0с\u00a0неразрывными\u00a0пробелами."
    cleaned, _ = clean_text(raw)
    assert "\u00a0" not in cleaned
    assert "неразрывными пробелами" in cleaned


def test_clean_formfeed():
    raw = "Глава\fновая\fстраница"
    cleaned, _ = clean_text(raw)
    assert "\f" not in cleaned


def test_chunk_text_preserves_content():
    text = ("Абзац один.\n\n" + "Абзац два. " * 100 + "\n\nАбзац три.")
    chunks = list(chunk_text(text, chunk_chars=400, overlap=80))
    assert len(chunks) >= 2
    joined = " ".join(chunks)
    assert "Абзац один" in joined
    assert "Абзац три" in joined


def test_chunk_text_overlap_defense():
    # overlap не должен быть >= chunk_chars
    list(chunk_text("x" * 500, chunk_chars=100, overlap=500))  # не падает
