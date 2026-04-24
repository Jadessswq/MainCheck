"""
Локальный сервер AI LibreOffice Suggester
Использует Ollama для запуска модели без интернета
"""
import os, httpx
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv

load_dotenv()

OLLAMA_URL  = os.getenv("OLLAMA_URL",  "http://localhost:11434")
MODEL_NAME  = os.getenv("MODEL_NAME",  "qwen2.5:32b")
NUM_THREADS = int(os.getenv("NUM_THREADS", "28"))   # 28 из 32 ядер, оставить 4 ОС

SYSTEM_PROMPT = """Вы — опытный корректор русского языка. Исправляйте ТОЛЬКО реальные языковые ошибки.

━━━ ШАГ 1: МЫСЛЕННЫЙ АНАЛИЗ (не выводить) ━━━
Перед правкой последовательно проверьте:

А) СОГЛАСОВАНИЕ ПРИ ОДНОРОДНЫХ ЧЛЕНАХ
   — Если несколько определений относятся к одному существительному в конце перечисления,
     все они должны стоять в том же падеже и числе, что и это существительное.
   — Пример ошибки:  «в Уральском, Сибирском и Приволжском округе» (три округа → «округах»)
   — Пример ошибки:  «Уральском на 300%, Сибирском на 100% и Приволжском на 43% округах»
     → «Уральском», «Сибирском», «Приволжском» — ед.ч., но «округах» — мн.ч. Несоответствие.

Б) УПРАВЛЕНИЕ ГЛАГОЛОВ И ПРЕДЛОГОВ
   — «согласно приказу» (не «согласно приказа»)
   — «благодаря решению» (не «благодаря решения»)

В) ОРФОГРАФИЯ — опечатки, удвоение/пропуск букв

Г) ПУНКТУАЦИЯ — однородные члены, обособленные обороты, придаточные

━━━ ЧТО НЕЛЬЗЯ ТРОГАТЬ ━━━
• Аббревиатуры и сокращения (п/п, вх.№, исх.№, ФСБ, МВД и др.) — оставить как есть
• Ведомственные термины и профессиональные обороты — не переформулировать
• Правильно написанный текст — не «улучшать»

━━━ ПРИМЕРЫ ━━━
ВХОД: «согласно распоряжения №45»
CHANGES: 1. «согласно распоряжения» → «согласно распоряжению» | предлог требует дательного падежа

ВХОД: «Во исполнение приказа директора»
CHANGES: 1. Ошибок не найдено.

━━━ ФОРМАТ ОТВЕТА (строго) ━━━
===CORRECTED===
<исправленный текст>
===CHANGES===
№. «было» → «стало» | причина (5–10 слов)
===END===
Если ошибок нет: 1. Ошибок не найдено. Текст соответствует нормам."""

app = FastAPI(title="AI LibreOffice Suggester — Local")


async def call_ollama(messages: list) -> str:
    async with httpx.AsyncClient(timeout=300.0) as client:
        r = await client.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": MODEL_NAME,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_ctx": 4096,
                    "num_thread": NUM_THREADS,
                    "repeat_penalty": 1.1,
                },
            },
        )
        r.raise_for_status()
        return r.json()["message"]["content"].strip()


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
        return status
    except Exception as e:
        return f"ОШИБКА: Ollama недоступна — {e}"


@app.post("/suggest", response_class=PlainTextResponse)
async def suggest(text: UploadFile = File(...), context: UploadFile = File(...)):
    raw_text = (await text.read()).decode("utf-8").strip()
    raw_ctx  = (await context.read()).decode("utf-8").strip()
    if not raw_text: return "ОШИБКА: Пустой текст"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": (
            f"Контекст:\n{raw_ctx}\n\n---\nТЕКСТ ДЛЯ ПРОВЕРКИ:\n{raw_text}"
        )},
    ]
    try:
        result = await call_ollama(messages)
        if "===CORRECTED===" in result:
            return result
        return f"===CORRECTED===\n{result}\n===CHANGES===\n1. Формат ответа не распознан.\n===END==="
    except Exception as e:
        return f"ОШИБКА_СЕРВЕРА: {str(e)}"
