"""
Локальный сервер AI LibreOffice Suggester.

Использует Ollama для запуска модели без интернета.
Рекомендуемая модель (2026): qwen3:30b-a3b — MoE, быстро работает на CPU.
Альтернативы: qwen2.5:32b, qwen2.5:14b, gemma3:27b, mistral-small3.2:24b.

Новое в v1.3:
    • Логи с ротацией и retention (LOG_RETENTION_DAYS)
    • SQLite-аудит запросов (/metrics, /audit)
    • Опциональный RAG по ведомственным документам (RAG_ENABLED=true)
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse

# Подключаем shared/ к sys.path
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from shared.audit import AuditStore, Timer, count_changes  # noqa: E402
from shared.logging_setup import setup_logger  # noqa: E402

load_dotenv()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
MODEL_NAME = os.getenv("MODEL_NAME", "qwen3:30b-a3b")
NUM_THREADS = int(os.getenv("NUM_THREADS", "28"))
# Таймаут одного запроса к Ollama. Должен быть БОЛЬШЕ клиентского (Settings.xba),
# чтобы клиент успевал получить осмысленную 504 вместо «нет ответа».
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "180"))
# Сколько модель остаётся в RAM после ответа. Без этого 30B-модель выгружается
# и каждый следующий запрос ждёт ~30–90 с пока она снова грузится с диска.
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
# Отключает «thinking-режим» qwen3 (Ollama ≥ 0.9). Без этого модель пишет
# многоминутный <think>…</think> перед ответом — для правки текста это лишнее.
OLLAMA_THINK = os.getenv("OLLAMA_THINK", "false").lower() in ("1", "true", "yes", "on")

# RAG
RAG_ENABLED = os.getenv("RAG_ENABLED", "false").lower() in ("1", "true", "yes", "on")
RAG_STORE_DIR = os.getenv("RAG_STORE_DIR", "data/rag_store")
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "4"))
RAG_EMBED_MODEL = os.getenv("RAG_EMBED_MODEL", "nomic-embed-text")

logger = setup_logger("ai_suggester.local")
audit = AuditStore()

_rag_store = None
_rag_embedder = None

if RAG_ENABLED:
    try:
        from shared.rag_store import OllamaEmbedder, RagStore  # noqa: E402

        _rag_store = RagStore(RAG_STORE_DIR)
        _rag_embedder = OllamaEmbedder(model=RAG_EMBED_MODEL, base_url=OLLAMA_URL)
        logger.info(
            "RAG включён: store=%s, embedder=%s, docs=%d",
            RAG_STORE_DIR, RAG_EMBED_MODEL, len(_rag_store.docs),
        )
    except Exception as e:
        logger.warning("RAG не удалось инициализировать: %s", e)
        _rag_store = None


SYSTEM_PROMPT = """Ты — корректор русского языка для официальных документов. Не рассуждай, сразу выдавай ответ в нужном формате.

ИСПРАВЛЯЙ ТОЛЬКО ЯВНЫЕ ОШИБКИ:
• орфография — опечатки, удвоение/пропуск букв, слитное/раздельное написание;
• управление — «согласно приказу» (не «согласно приказа»), «благодаря решению»;
• согласование — однородные члены в одном падеже и числе с главным словом;
• пунктуация — запятые при однородных членах, обособленных оборотах, придаточных.

НЕ ТРОГАЙ:
• аббревиатуры и сокращения (п/п, вх.№, исх.№, ФСБ, МВД);
• ведомственные термины и профессиональные обороты;
• правильно написанный текст («улучшать стиль» нельзя);
• структуру и смысл предложений.

ФОРМАТ ОТВЕТА (строго, без какого-либо текста до или после):
===CORRECTED===
<исправленный текст>
===CHANGES===
1. «было» → «стало» | краткая причина (5–10 слов)
===END===

Если ошибок нет:
===CORRECTED===
<исходный текст без изменений>
===CHANGES===
1. Ошибок не найдено. Текст соответствует нормам.
===END==="""


app = FastAPI(title="AI LibreOffice Suggester — Local", version="1.3.0")


_THINK_BLOCK = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)


def _strip_thinking(text: str) -> str:
    """Срезает <think>…</think> и leading-рассуждения, если модель проигнорировала /no_think.

    Возвращает «чистый» ответ. Если в тексте нет ни тегов <think>, ни маркера
    ===CORRECTED===, не трогаем — пусть верхний слой сам разбирается.
    """
    cleaned = _THINK_BLOCK.sub("", text)
    # Иногда qwen3 без тегов пишет рассуждения, а ===CORRECTED=== всё равно есть ниже.
    idx = cleaned.find("===CORRECTED===")
    if idx > 0:
        cleaned = cleaned[idx:]
    return cleaned.strip()


async def call_ollama(messages: list) -> str:
    # /no_think — soft-switch Qwen3, должен стоять в последнем user-сообщении
    # (не в system-prompt). Работает на любой Ollama, в т.ч. старее 0.9.
    msgs = [dict(m) for m in messages]
    if msgs and msgs[-1].get("role") == "user" and not OLLAMA_THINK:
        msgs[-1]["content"] = msgs[-1]["content"].rstrip() + "\n\n/no_think"

    payload = {
        "model": MODEL_NAME,
        "messages": msgs,
        "stream": False,
        "think": OLLAMA_THINK,  # для Ollama ≥ 0.9; старые игнорируют поле
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {
            "temperature": 0.1,
            "num_ctx": 4096,
            "num_thread": NUM_THREADS,
            "repeat_penalty": 1.1,
        },
    }
    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
        r = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
        r.raise_for_status()
        raw = r.json()["message"]["content"].strip()
        return _strip_thinking(raw)


def _rag_context(text: str) -> str:
    """Возвращает дополнительный блок с фрагментами из RAG-хранилища."""
    if not (_rag_store and _rag_embedder):
        return ""
    try:
        hits = _rag_store.search(text, top_k=RAG_TOP_K, embedder=_rag_embedder)
    except Exception as e:
        logger.warning("RAG поиск провалился: %s", e)
        return ""
    if not hits:
        return ""
    parts = ["ПРИМЕНИМЫЕ НОРМАТИВНЫЕ ФРАГМЕНТЫ (используйте как справку, не цитируйте в CHANGES):"]
    for h in hits:
        parts.append(f"— [{h['doc_id']}] {h['text'][:600]}")
    return "\n".join(parts)


@app.get("/health", response_class=PlainTextResponse)
async def health():
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{OLLAMA_URL}/api/tags")
            models = [m["name"] for m in r.json().get("models", [])]
        status = "Ollama OK"
        if MODEL_NAME in models or any(MODEL_NAME.split(":")[0] in m for m in models):
            status += f" | Модель {MODEL_NAME} загружена"
        else:
            status += f" | ВНИМАНИЕ: модель {MODEL_NAME} не найдена. Загружены: {', '.join(models)}"
        if RAG_ENABLED and _rag_store:
            status += f" | RAG: {len(_rag_store.docs)} документов"
        return status
    except Exception as e:
        return f"ОШИБКА: Ollama недоступна — {e}"


@app.get("/metrics")
async def metrics(hours: int = 24):
    return JSONResponse({
        "server": "local",
        "model": MODEL_NAME,
        "rag_enabled": RAG_ENABLED,
        "rag_documents": len(_rag_store.docs) if _rag_store else 0,
        "audit": audit.stats(hours=hours),
    })


@app.post("/suggest", response_class=PlainTextResponse)
async def suggest(
    request: Request,
    text: UploadFile = File(...),
    context: UploadFile = File(...),
):
    raw_text = (await text.read()).decode("utf-8", errors="replace").strip()
    raw_ctx = (await context.read()).decode("utf-8", errors="replace").strip()
    if not raw_text:
        return "ОШИБКА: Пустой текст"

    extra = _rag_context(raw_text)
    user_msg = f"Контекст:\n{raw_ctx}\n"
    if extra:
        user_msg += f"\n{extra}\n"
    user_msg += f"\n---\nТЕКСТ ДЛЯ ПРОВЕРКИ:\n{raw_text}"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    client_ip = request.client.host if request.client else ""
    user_agent = request.headers.get("user-agent", "")
    timer = Timer()
    ok, error, result = True, "", ""
    with timer:
        try:
            result = await call_ollama(messages)
            if "===CORRECTED===" not in result:
                result = (
                    "===CORRECTED===\n"
                    f"{result}\n"
                    "===CHANGES===\n"
                    "1. Формат ответа не распознан — проверьте вручную.\n"
                    "===END==="
                )
        except Exception as e:
            ok = False
            error = f"{type(e).__name__}: {e}"
            logger.exception("Ошибка запроса к Ollama")
            result = f"ОШИБКА_СЕРВЕРА: {error}"

    audit.record(
        client_ip=client_ip, user_agent=user_agent,
        server="local", model=MODEL_NAME,
        text=raw_text, context=raw_ctx,
        changes_count=count_changes(result),
        duration_ms=timer.ms, ok=ok, error=error,
    )
    logger.info(
        "suggest ip=%s len=%d ctx=%d changes=%d ok=%s dur=%dms",
        client_ip, len(raw_text), len(raw_ctx),
        count_changes(result), ok, timer.ms,
    )
    return result
