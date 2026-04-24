"""Тесты RAG-хранилища с offline-эмбеддером."""
from pathlib import Path

import pytest

from shared.rag_store import HashingEmbedder, RagStore


@pytest.fixture
def tmp_store(tmp_path):
    return RagStore(tmp_path / "store")


@pytest.fixture
def sample_txt(tmp_path):
    p = tmp_path / "fz44.txt"
    p.write_text(
        "Согласно распоряжению Правительства от 01.01.2024 №45 "
        "о государственных закупках, заказчик обязан разместить "
        "извещение в единой информационной системе.\n\n"
        "Оплатить проезд работнику следует в соответствии со статьёй 168 ТК РФ.",
        encoding="utf-8",
    )
    return p


def test_add_list_remove_cycle(tmp_store, sample_txt):
    emb = HashingEmbedder(dim=256)
    meta = tmp_store.add_document(doc_id="fz-44", file_path=sample_txt, embedder=emb, version="2024-01")
    assert meta.chunks >= 1

    docs = tmp_store.list_documents()
    assert any(d["doc_id"] == "fz-44" for d in docs)
    assert docs[0]["version"] == "2024-01"

    assert tmp_store.remove_document("fz-44") is True
    assert tmp_store.list_documents() == []
    assert tmp_store.remove_document("fz-44") is False


def test_replace_version(tmp_store, sample_txt):
    emb = HashingEmbedder(dim=256)
    tmp_store.add_document(doc_id="fz-44", file_path=sample_txt, embedder=emb, version="2024-01")
    n1 = len(tmp_store.entries)
    tmp_store.add_document(doc_id="fz-44", file_path=sample_txt, embedder=emb, version="2025-03")
    # Размер не растёт экспоненциально — старая версия удалена
    assert len(tmp_store.entries) == n1
    assert tmp_store.docs["fz-44"].version == "2025-03"


def test_search_finds_relevant(tmp_store, sample_txt):
    emb = HashingEmbedder(dim=512)
    tmp_store.add_document(doc_id="fz-44", file_path=sample_txt, embedder=emb)
    hits = tmp_store.search("оплатить проезд работнику", top_k=2, embedder=emb)
    assert hits, "ожидался хотя бы один результат"
    assert hits[0]["doc_id"] == "fz-44"
    assert "платить проезд" in hits[0]["text"].lower()


def test_persistence(tmp_path, sample_txt):
    emb = HashingEmbedder(dim=256)
    s1 = RagStore(tmp_path / "store")
    s1.add_document(doc_id="fz-44", file_path=sample_txt, embedder=emb)
    # Пересоздаём — всё должно подняться
    s2 = RagStore(tmp_path / "store")
    assert "fz-44" in s2.docs
    assert len(s2.entries) == len(s1.entries)
