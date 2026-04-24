# AI LibreOffice Suggester — Module_Libre

Расширение для LibreOffice Writer, которое добавляет в редактор кнопку AI-корректуры
для официальной деловой переписки. Пользователь выделяет фрагмент текста,
нажимает кнопку, получает структурированный diff-диалог с пояснениями каждой правки.
При согласии исправления вносятся в документ **как отслеживаемые изменения**
(Track Changes), что позволяет принимать/отклонять их по одному штатными средствами
LibreOffice.

**Статус:** v1.3 — стабильный прототип.
**Платформы:** Windows 10/11 · Astra Linux (LibreOffice 7.0.4.2 – 7.6).

---

## Что внутри

```
Module_Libre/
├── AI_Suggester/                 # Исходники LibreOffice-расширения
│   ├── ai_macro/
│   │   ├── Main.xba              # Точка входа AISuggestSelection
│   │   ├── Settings.xba          # Пользовательские настройки (SERVER_LIST, Track Changes, таймауты)
│   │   ├── Health.xba            # Кнопка «AI: Проверить сервер»
│   │   ├── script.xlb / dialog.xlb
│   │   └── ...
│   ├── Addons.xcu                # Кнопки на панели инструментов
│   ├── META-INF/manifest.xml
│   └── description.xml
├── AI_Suggester.oxt              # Готовый к установке архив расширения
│
├── fastapi_server(2)/            # Облачный сервер (OpenRouter)
│   ├── main.py                   # /suggest · /health · /test_api · /metrics
│   ├── requirements.txt
│   └── start.sh / start.bat / .env.example
│
├── local_server/                 # Локальный сервер (Ollama, без интернета)
│   ├── main.py                   # + RAG-контекст + аудит + /metrics
│   ├── requirements.txt
│   ├── start.sh / start.bat / .env.example
│   ├── ai-suggester.service      # systemd-юнит
│   └── README.md
│
├── shared/                       # Общий код серверов
│   ├── logging_setup.py          # Логи с ротацией и retention
│   ├── audit.py                  # SQLite-аудит (/metrics)
│   ├── garant_cleanup.py         # Очистка документов Гарант / КонсультантПлюс
│   ├── rag_store.py              # Векторное хранилище + эмбеддеры
│   └── rag_cli.py                # CLI для add/list/remove/search
│
├── tests/                        # 36 pytest-тестов (очистка, RAG, аудит, смоук серверов, валидация .oxt)
├── docs/
│   ├── LOCAL_MODEL.md            # Выбор, установка, отключение локальной модели
│   ├── RAG_GUIDE.md              # Обучение на ведомственных документах
│   ├── LOGGING.md                # Логи, аудит, retention, /metrics
│   └── TROUBLESHOOTING.md        # Диагностика клиента, серверов, RAG
└── README.md (этот файл)
```

---

## Быстрый старт (5 минут)

### 1. Установка расширения

1. Скачать `AI_Suggester.oxt` из этого репозитория.
2. LibreOffice → **Сервис → Управление расширениями → Добавить…** → выбрать `.oxt`.
3. Перезапустить LibreOffice. На панели инструментов появятся кнопки
   **«AI: Улучшить текст»** и **«AI: Проверить сервер»**.

### 2. Выбор сервера

| Вариант           | Требования                        | Описание                                        |
|-------------------|-----------------------------------|-------------------------------------------------|
| **Локальный**     | Ollama + RAM ≥ 24 ГБ              | Без интернета, работает на CPU                  |
| **Облачный**      | API-ключ OpenRouter (бесплатно)   | Быстрее, но требует сеть                        |
| **Гибрид**        | Оба                               | Автоматический fallback при сбое одного из них  |

#### Локальный (рекомендуется)
```bash
# 1. Ollama и модель (см. docs/LOCAL_MODEL.md)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3:30b-a3b

# 2. Сервер AI Suggester
cd local_server
cp .env.example .env
pip install -r requirements.txt
./start.sh
```

Проверить: <http://localhost:8000/health> → `Ollama OK | Модель qwen3:30b-a3b загружена`.

#### Облачный
```bash
cd "fastapi_server(2)"
cp .env.example .env
# отредактировать .env: OPENROUTER_API_KEY=sk-or-v1-...
pip install -r requirements.txt
./start.sh
```

#### Настройка клиента
В LibreOffice: **Сервис → Макросы → Мои макросы → ai_macro → Settings → `GetServerList`**.
Можно указать несколько адресов через `|`, макрос перебирает их по очереди:

```basic
GetServerList = "http://localhost:8000/suggest|https://example.org/suggest"
```

---

## Что нового в v1.3

- **Клиент:**
  - Модуль `Settings` — все настройки в одном месте (без правки основного кода).
  - Проверка HTTP-статуса через `curl -w "%{http_code}"` — больше не полагаемся
    только на наличие файла ответа.
  - Track Changes — исправления применяются как redline-блоки, управляются штатно.
  - Кнопка «AI: Проверить сервер» → ping `/health` для всего `SERVER_LIST`.
- **Серверы:**
  - Логи с ротацией (`TimedRotatingFileHandler`, retention из `.env`).
  - SQLite-аудит: кто/когда/IP/UA/модель/длительность/sha1, настраиваемая retention,
    опциональная редакция текста (`AUDIT_REDACT_TEXT=true`).
  - `/metrics` — сводка за окно времени в JSON.
  - Обновлённая рекомендация локальной модели: **qwen3:30b-a3b** (MoE,
    быстрее qwen2.5:32b на CPU в 3–5 раз при том же качестве).
- **RAG на Гарант / КонсультантПлюс:**
  - Модуль `shared/garant_cleanup.py` — отделяет норматив от служебных шапок/колонтитулов,
    соединяет перенесённые слова, нормализует пробелы, сохраняет `№`.
  - `shared/rag_store.py` — локальное векторное хранилище без тяжёлых зависимостей,
    с поддержкой Ollama-эмбеддеров (`nomic-embed-text` по умолчанию).
  - CLI `python -m shared.rag_cli {add,list,remove,search,ingest-folder}` — простая
    загрузка/замена/удаление документов, замена версии одной командой.
  - См. `docs/RAG_GUIDE.md`.
- **Тесты:** 36 pytest-тестов (cleanup, RAG, аудит, логи, смоук-тесты FastAPI
  с моками Ollama/OpenRouter, валидация XML расширения, ре-сборка .oxt).
- **Безопасность:** добавлен `.gitignore`; `.env`-файлы убраны из git-трекинга.

---

## Документация

- 🧠 [Локальная модель: выбор, установка, отключение](docs/LOCAL_MODEL.md)
- 📚 [RAG: обучение на документах Гарант/КонсультантПлюс](docs/RAG_GUIDE.md)
- 📊 [Логи, аудит и мониторинг](docs/LOGGING.md)
- 🔧 [Траблшутинг](docs/TROUBLESHOOTING.md)

---

## Разработка

```bash
# Установить тестовые зависимости
pip install pytest fastapi httpx python-dotenv python-multipart python-docx

# Запустить все тесты (36 шт.)
pytest tests/

# Пересобрать .oxt из исходников
python - <<'PY'
import zipfile, pathlib
root = pathlib.Path("AI_Suggester")
with zipfile.ZipFile("AI_Suggester.oxt", "w", zipfile.ZIP_DEFLATED) as z:
    for p in root.rglob("*"):
        if p.is_file():
            z.write(p, p.relative_to(root).as_posix())
PY
```

---

## Лицензия и безопасность

- Не коммитьте реальные API-ключи. `fastapi_server(2)/.env` перенесён в `.gitignore`.
- Для production-использования рекомендуется:
  - `AUDIT_REDACT_TEXT=true` — если тексты деловой переписки не должны храниться в открытом виде;
  - запуск серверов от непривилегированного пользователя;
  - ограничение доступа к порту 8000 (iptables/firewall) только из корпоративной сети.
