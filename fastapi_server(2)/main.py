import os, httpx
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv

load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

MODELS = [
    "openrouter/free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-3-27b-it:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
    "nvidia/llama-3.1-nemotron-nano-8b-v1:free",
]

# ══════════════════════════════════════════════════════════════
#  СИСТЕМНЫЙ ПРОМТ  (Chain-of-Thought + Few-Shot + строгие правила)
# ══════════════════════════════════════════════════════════════
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

app = FastAPI(title="AI LibreOffice Suggester")


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
    """Реальная проверка: ключ задан + хотя бы одна модель отвечает."""
    if not OPENROUTER_API_KEY or "ваш_ключ" in OPENROUTER_API_KEY:
        return "ОШИБКА: OPENROUTER_API_KEY не задан в .env"
    probe = [{"role": "user", "content": "Ответь одним словом: OK"}]
    for model in MODELS:
        try:
            ans = await call_model(probe, model)
            return f"OK | Работает: {model} | Ответ: {ans[:40]}"
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                continue          # rate limit — пробуем следующую
            return f"ОШИБКА HTTP {e.response.status_code} на {model}: {e.response.text[:200]}"
        except Exception as e:
            return f"ОШИБКА на {model}: {str(e)[:200]}"
    return "ОШИБКА: Все модели вернули 429 (rate limit). Попробуйте позже."


@app.get("/test_api", response_class=PlainTextResponse)
async def test_api():
    if not OPENROUTER_API_KEY or "ваш_ключ" in OPENROUTER_API_KEY:
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


@app.post("/suggest", response_class=PlainTextResponse)
async def suggest(text: UploadFile = File(...), context: UploadFile = File(...)):
    if not OPENROUTER_API_KEY or "ваш_ключ" in OPENROUTER_API_KEY:
        return "ОШИБКА: OPENROUTER_API_KEY не задан в .env"

    raw_text = (await text.read()).decode("utf-8").strip()
    raw_ctx  = (await context.read()).decode("utf-8").strip()
    if not raw_text: return "ОШИБКА: Пустой текст"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Контекст (предшествующий текст, только для понимания стиля):\n{raw_ctx}\n\n"
            f"---\nТЕКСТ ДЛЯ ПРОВЕРКИ:\n{raw_text}"
        )},
    ]

    last_err = "нет ответа"
    for model in MODELS:
        try:
            result = await call_model(messages, model)
            if "===CORRECTED===" in result:
                return result
            return f"===CORRECTED===\n{result}\n===CHANGES===\n1. Формат ответа не распознан.\n===END==="
        except httpx.HTTPStatusError as e:
            last_err = f"[{model}] HTTP {e.response.status_code}"
            if e.response.status_code in (429, 502, 503): continue
            return f"ОШИБКА_СЕРВЕРА: {last_err}"
        except Exception as e:
            last_err = f"[{model}] {str(e)[:200]}"
            continue

    return f"ОШИБКА_СЕРВЕРА: Все модели недоступны. {last_err}"
