"""
Локальный сервер AI LibreOffice Suggester.

Использует Ollama для запуска модели без интернета.
Рекомендуемая модель (v1.5, апрель 2026): t-tech/T-lite-it-2.1:q4_K_M —
русскоязычный instruct-tune от T-Bank на базе Qwen3-8B. На CPU Broadwell
даёт warm-ответ за 30–50 с, что в 2× быстрее qwen2.5:14b при идентичном
качестве исправлений падежного управления официально-делового стиля.
Альтернативы (для нестандартного железа/требований): qwen2.5:14b,
qwen2.5:32b, forzer/GigaChat3-10B-A1.8B, qwen3:30b-a3b-instruct-2507.

Новое в v1.3:
    • Логи с ротацией и retention (LOG_RETENTION_DAYS)
    • SQLite-аудит запросов (/metrics, /audit)
    • Опциональный RAG по ведомственным документам (RAG_ENABLED=true)
Новое в v1.5:
    • Переход по умолчанию на T-lite-it-2.1 (в 2× быстрее)
    • Пост-процессор ===CHANGES===: фильтрует идемпотентные пункты «X → X»
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
MODEL_NAME = os.getenv("MODEL_NAME", "t-tech/T-lite-it-2.1:q4_K_M")
NUM_THREADS = int(os.getenv("NUM_THREADS", "28"))
# Размер окна контекста (input + output в токенах). 4096 — стандарт qwen2.5,
# но если у вас короткие тексты (<2 КБ), 2048 даёт ~2× прирост скорости
# на CPU без потери качества (модель меньше тратит на init контекста).
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "2048"))
# Жёсткий лимит на длину ответа в токенах. Без лимита Ollama иногда
# дописывает «развёрнутые комментарии» — режем заранее. 1024 токена
# (~3000 символов) с запасом покрывают типовой исправленный фрагмент
# плюс блок ===CHANGES===.
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "1024"))
# Таймаут одного запроса к Ollama. Должен быть БОЛЬШЕ клиентского (Settings.xba),
# чтобы клиент успевал получить осмысленную 504 вместо «нет ответа».
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "300"))
# Прогревать модель при старте сервера (загрузить веса в RAM, чтобы первый
# запрос пользователя не ждал 30–90 с). Отключите, если стартуете много
# инстансов на одной машине и хотите экономить RAM.
OLLAMA_WARMUP = os.getenv("OLLAMA_WARMUP", "true").lower() in ("1", "true", "yes", "on")
OLLAMA_WARMUP_TIMEOUT = float(os.getenv("OLLAMA_WARMUP_TIMEOUT", "180"))
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


app = FastAPI(title="AI LibreOffice Suggester — Local", version="1.5.0")


@app.on_event("startup")
async def _warmup_ollama():
    """Грузим модель в RAM при старте сервера, чтобы первый запрос
    пользователя не ждал 30–90 с на загрузку весов 30B-модели.

    Делает один минимальный chat-запрос с keep_alive — Ollama после
    этого держит модель загруженной OLLAMA_KEEP_ALIVE минут.
    """
    if not OLLAMA_WARMUP:
        return
    logger.info("Прогрев модели %s через Ollama (timeout=%.0fs)…",
                MODEL_NAME, OLLAMA_WARMUP_TIMEOUT)
    try:
        async with httpx.AsyncClient(timeout=OLLAMA_WARMUP_TIMEOUT) as c:
            r = await c.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": MODEL_NAME,
                    "messages": [{"role": "user", "content": "ok\n\n/no_think"}],
                    "stream": False,
                    "think": False,
                    "keep_alive": OLLAMA_KEEP_ALIVE,
                    "options": {"num_ctx": 512, "num_thread": NUM_THREADS},
                },
            )
            r.raise_for_status()
        logger.info("Прогрев OK: модель загружена в RAM, keep_alive=%s",
                    OLLAMA_KEEP_ALIVE)
    except Exception as e:
        logger.warning("Прогрев модели не удался (%s) — первый запрос будет медленнее", e)


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


# Угловые/типографские кавычки, встречающиеся в ===CHANGES===. Одиночные
# ' и ` не включаем — они ложно срабатывают на апостроф/транслитерацию.
_QUOTE_CHARS = "«»\"“”‘’‚‛„"
# Разделитель между «было» и «стало». Допускаем стрелки (→, ->), тире
# (—, –, -) и текстовые связки, включая обороты «заменено/исправлено на».
# В сепараторе разрешаем любые символы, кроме кавычек — так захватываются
# варианты вроде «X» — исправлено на «X» или «X» заменено на «X».
_CHANGE_PAIR_RE = re.compile(
    rf"[{_QUOTE_CHARS}]([^{_QUOTE_CHARS}]+)[{_QUOTE_CHARS}]"
    rf"[^{_QUOTE_CHARS}]*?"
    rf"[{_QUOTE_CHARS}]([^{_QUOTE_CHARS}]+)[{_QUOTE_CHARS}]",
    re.IGNORECASE,
)


def _drop_idempotent_changes(text: str) -> str:
    """Удаляет из блока ===CHANGES=== пункты вида «X → X».

    Некоторые модели (в частности T-lite-it-2.1) на задаче корректуры иногда
    перечисляют в changelog правила из системного промпта, выдавая пустые
    пункты типа «согласно распоряжению → согласно распоряжению» или
    «отдел подготовил отчётность → отдел подготовил отчётность» там, где
    исправлений не было. Такие пункты бесполезны для пользователя и
    засоряют Track Changes. Удаляем их.

    Если после фильтрации в ===CHANGES=== не осталось ни одного пункта —
    подставляем заглушку «Ошибок не найдено».
    """
    if "===CHANGES===" not in text or "===END===" not in text:
        return text
    try:
        before, rest = text.split("===CHANGES===", 1)
        changes_block, tail = rest.split("===END===", 1)
    except ValueError:
        return text

    kept: list[str] = []
    for raw_line in changes_block.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            kept.append(line)
            continue
        m = _CHANGE_PAIR_RE.search(line)
        # Сравниваем БЕЗ .lower(): «Приказа» → «приказа» — это валидная
        # орфографическая правка регистра (имя собственное vs нарицательное),
        # такие пункты сохраняем. Идемпотентный пункт — это когда до и после
        # совпадают побуквенно.
        if m and m.group(1).strip() == m.group(2).strip():
            logger.debug("Фильтрую идемпотентный пункт: %s", line.strip())
            continue
        kept.append(line)

    # Есть ли хотя бы один пронумерованный пункт с текстом?
    non_empty = [ln for ln in kept if re.search(r"\w", ln)]
    has_real_item = any(re.match(r"\s*\d+\.\s*\S", ln) for ln in non_empty)
    if not has_real_item:
        kept = ["", "1. Ошибок не найдено. Текст соответствует нормам.", ""]

    new_changes = "\n".join(kept).rstrip() + "\n"
    return f"{before}===CHANGES===\n{new_changes.lstrip()}===END==={tail}"


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
            "num_ctx": OLLAMA_NUM_CTX,
            "num_predict": OLLAMA_NUM_PREDICT,
            "num_thread": NUM_THREADS,
            "repeat_penalty": 1.1,
        },
    }
    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
        r = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
        r.raise_for_status()
        raw = r.json()["message"]["content"].strip()
        return _drop_idempotent_changes(_strip_thinking(raw))


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
