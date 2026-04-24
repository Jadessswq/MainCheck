"""
Облачный сервер AI LibreOffice Suggester (OpenRouter free tier).

Новое в v1.3:
    • Логи с ротацией и retention
    • SQLite-аудит запросов (/metrics)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from shared.audit import AuditStore, Timer, count_changes  # noqa: E402
from shared.logging_setup import setup_logger  # noqa: E402

load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

MODELS = [
    "openrouter/free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-3-27b-it:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
    "nvidia/llama-3.1-nemotron-nano-8b-v1:free",
]

logger = setup_logger("ai_suggester.cloud")
audit = AuditStore()

SYSTEM_PROMPT = """Вы — опытный корректор русского языка. Исправляйте ТОЛЬКО реальные языковые ошибки.

━━━ ШАГ 1: МЫСЛЕННЫЙ АНАЛИЗ (не выводить) ━━━
Перед правкой последовательно проверьте:

А) СОГЛАСОВАНИЕ ПРИ ОДНОРОДНЫХ ЧЛЕНАХ
   — Если несколько определений относятся к одному существительному в конце перечисления,
     все они должны стоять в том же падеже и числе, что и это существительное.
   — Пример ошибки:  «в Уральском, Сибирском и Приволжском округе» (три округа → «округах»)
   — Пример ошибки:  «Уральском на 300%, Сибирском на 100% и Приволжском на 43% округах»
     → здесь «Уральском», «Сибирском», «Приволжском» — предложный пад. ед.ч., но «округах» — мн.ч.
     → надо: «Уральском, Сибирском и Приволжском округах» (с числами вынести отдельно)
     ИЛИ перестроить: «в Уральском (300%), Сибирском (100%) и Приволжском (43%) округах»

Б) УПРАВЛЕНИЕ ГЛАГОЛОВ И ПРЕДЛОГОВ
   — «оплатить проезд» (не «оплатить за проезд»)
   — «согласно приказу» (не «согласно приказа»)
   — «благодаря решению» (не «благодаря решения»)

В) ОРФОГРАФИЯ — опечатки, удвоение/пропуск букв, слитное/раздельное написание

Г) ПУНКТУАЦИЯ — запятые при однородных членах, обособленных оборотах, придаточных

━━━ ЧТО НЕЛЬЗЯ ТРОГАТЬ ━━━
• Аббревиатуры и сокращения (п/п, вх.№, исх.№, ФСБ, МВД и др.) — оставить как есть
• Ведомственные термины и профессиональные обороты — не переформулировать
• Правильно написанный текст — не «улучшать»
• Структуру и смысл — не менять

━━━ ПРИМЕРЫ (few-shot) ━━━
ВХОД: «повысился в Уральском на 300%, Сибирском на 100% и Приволжском на 43% округах»
ВЫХОД (CHANGES): 1. «Уральском на 300%, Сибирском на 100% и Приволжском на 43% округах» → «Уральском (300%), Сибирском (100%) и Приволжском (43%) округах» | несогласованная вставка числовых данных внутри однородного ряда прилагательных

ВХОД: «Во исполнение приказа директора об организации работы сотрудников отдела»
ВЫХОД (CHANGES): 1. Ошибок не найдено.

ВХОД: «согласно распоряжения №45 от 01.01.2024»
ВЫХОД (CHANGES): 1. «согласно распоряжения» → «согласно распоряжению» | предлог «согласно» требует дательного падежа

━━━ ФОРМАТ ОТВЕТА (строго обязательный) ━━━

===CORRECTED===
<исправленный текст — только текст>
===CHANGES===
<каждая правка с новой строки: №. «было» → «стало» | причина (5–10 слов)>
===END===

Правила блока CHANGES:
- Нумеровать: 1. 2. 3. ...
- Цитировать точно в «»: «исходный фрагмент» → «исправленный фрагмент»
- Максимум 20 пунктов; однотипные объединять
- Если ошибок нет: 1. Ошибок не найдено. Текст соответствует нормам.
- Никакого текста вне блоков ==="""

app = FastAPI(title="AI LibreOffice Suggester — Cloud", version="1.3.0")


def _key_missing() -> bool:
    return not OPENROUTER_API_KEY or "ваш_ключ" in OPENROUTER_API_KEY.lower()


async def call_model(messages: list, model: str) -> str:
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": "LibreOffice AI Suggester",
    }
    async with httpx.AsyncClient(timeout=90.0) as client:
        r = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json={"model": model, "messages": messages, "temperature": 0.1, "max_tokens": 3000},
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()


@app.get("/health", response_class=PlainTextResponse)
async def health():
    if _key_missing():
        return "ОШИБКА: OPENROUTER_API_KEY не задан в .env"
    probe = [{"role": "user", "content": "Ответь одним словом: OK"}]
    for model in MODELS:
        try:
            ans = await call_model(probe, model)
            return f"OK | Работает: {model} | Ответ: {ans[:40]}"
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                continue
            return f"ОШИБКА HTTP {e.response.status_code} на {model}: {e.response.text[:200]}"
        except Exception as e:
            return f"ОШИБКА на {model}: {str(e)[:200]}"
    return "ОШИБКА: Все модели вернули 429 (rate limit). Попробуйте позже."


@app.get("/test_api", response_class=PlainTextResponse)
async def test_api():
    if _key_missing():
        return "ОШИБКА: OPENROUTER_API_KEY не задан в .env"
    lines = [f"Ключ: {OPENROUTER_API_KEY[:12]}...{OPENROUTER_API_KEY[-4:]}\n"]
    for model in MODELS:
        try:
            ans = await call_model([{"role": "user", "content": "Ответь одним словом: OK"}], model)
            lines.append(f"[OK]   {model}\n       → {ans[:80]}")
        except Exception as e:
            lines.append(f"[FAIL] {model}\n       {str(e)[:120]}")
        lines.append("")
    return "\n".join(lines)


@app.get("/metrics")
async def metrics(hours: int = 24):
    return JSONResponse({
        "server": "cloud",
        "models": MODELS,
        "audit": audit.stats(hours=hours),
    })


@app.post("/suggest", response_class=PlainTextResponse)
async def suggest(
    request: Request,
    text: UploadFile = File(...),
    context: UploadFile = File(...),
):
    if _key_missing():
        return "ОШИБКА: OPENROUTER_API_KEY не задан в .env"

    raw_text = (await text.read()).decode("utf-8", errors="replace").strip()
    raw_ctx = (await context.read()).decode("utf-8", errors="replace").strip()
    if not raw_text:
        return "ОШИБКА: Пустой текст"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Контекст (предшествующий текст, только для понимания стиля):\n{raw_ctx}\n\n"
            f"---\nТЕКСТ ДЛЯ ПРОВЕРКИ:\n{raw_text}"
        )},
    ]

    client_ip = request.client.host if request.client else ""
    user_agent = request.headers.get("user-agent", "")

    last_err = "нет ответа"
    used_model = ""
    ok, error, result = False, "", ""
    timer = Timer()
    with timer:
        for model in MODELS:
            try:
                result = await call_model(messages, model)
                used_model = model
                if "===CORRECTED===" not in result:
                    result = (
                        "===CORRECTED===\n"
                        f"{result}\n"
                        "===CHANGES===\n"
                        "1. Формат ответа не распознан — проверьте вручную.\n"
                        "===END==="
                    )
                ok = True
                break
            except httpx.HTTPStatusError as e:
                last_err = f"[{model}] HTTP {e.response.status_code}"
                if e.response.status_code in (429, 502, 503):
                    continue
                error = last_err
                result = f"ОШИБКА_СЕРВЕРА: {last_err}"
                break
            except Exception as e:
                last_err = f"[{model}] {str(e)[:200]}"
                continue
        if not ok and not result:
            error = last_err
            result = f"ОШИБКА_СЕРВЕРА: Все модели недоступны. {last_err}"

    audit.record(
        client_ip=client_ip, user_agent=user_agent,
        server="cloud", model=used_model or "(none)",
        text=raw_text, context=raw_ctx,
        changes_count=count_changes(result),
        duration_ms=timer.ms, ok=ok, error=error,
    )
    logger.info(
        "suggest ip=%s model=%s len=%d changes=%d ok=%s dur=%dms",
        client_ip, used_model, len(raw_text),
        count_changes(result), ok, timer.ms,
    )
    return result
