# AI LibreOffice Suggester

Расширение для LibreOffice Writer, которое добавляет в редактор одну кнопку
AI-корректуры для официальной деловой переписки. Сотрудник выделяет фрагмент,
нажимает кнопку, получает структурированный список правок и применяет их
**как отслеживаемые изменения** (Track Changes): каждую правку можно принять
или отклонить штатными средствами LibreOffice.

**Статус:** v1.3 — стабильный прототип.
**Платформы:** Windows 10/11 · Astra Linux (LibreOffice 7.0.4.2 – 7.6).

---

## Две роли

Расширение разработано по модели **«админ ↔ сотрудник»**:

| Роль          | Что делает                                                                                                     |
|---------------|---------------------------------------------------------------------------------------------------------------|
| **Админ**     | Поднимает сервер (Ollama или OpenRouter), правит один файл `Settings.xba` с адресом, пересобирает `.oxt`, рассылает сотрудникам по почте. |
| **Сотрудник** | Получает `.oxt` по почте → устанавливает в LibreOffice → нажимает одну кнопку в панели инструментов. Больше ничего делать не надо. |

Подробные гайды:
- Сотруднику — [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) (одна страница).
- Админу — [`docs/ADMIN_GUIDE.md`](docs/ADMIN_GUIDE.md) (развёртывание сервера + сборка .oxt + рассылка).

---

## Что внутри

```
Module_Libre/
├── AI_Suggester/                 # Исходники LibreOffice-расширения
│   ├── ai_macro/
│   │   ├── Main.xba              # Точка входа AISuggestSelection (единственная кнопка сотрудника)
│   │   ├── Settings.xba          # Админский compile-time конфиг (URL, таймауты, Track Changes)
│   │   ├── Health.xba            # Диагностика для админа (из Сервис → Макросы)
│   │   └── script.xlb / dialog.xlb
│   ├── Addons.xcu                # Одна кнопка на панели
│   ├── META-INF/manifest.xml
│   └── description.xml
├── AI_Suggester.oxt              # Готовый архив для раздачи
│
├── fastapi_server(2)/            # Облачный сервер (OpenRouter)
├── local_server/                 # Локальный сервер (Ollama, без интернета, + RAG + аудит)
├── shared/                       # Общий код серверов
│   ├── logging_setup.py          # Логи с ротацией и retention
│   ├── audit.py                  # SQLite-аудит + /metrics
│   ├── garant_cleanup.py         # Очистка документов Гарант / КонсультантПлюс
│   ├── rag_store.py              # Локальное векторное хранилище + эмбеддеры
│   └── rag_cli.py                # CLI add/list/remove/search
│
├── tests/                        # 36 pytest (очистка, RAG, аудит, смоук серверов, валидация .oxt)
└── docs/
    ├── ADMIN_GUIDE.md            # Админ: развёртывание сервера, сборка .oxt, рассылка
    ├── USER_GUIDE.md             # Сотрудник: установить .oxt и пользоваться
    ├── LOCAL_MODEL.md            # Выбор, установка, отключение локальной модели
    ├── RAG_GUIDE.md              # Обучение на ведомственных документах
    ├── LOGGING.md                # Логи, аудит, retention, /metrics
    └── TROUBLESHOOTING.md        # Диагностика клиента, серверов, RAG
```

---

## Быстрый старт для админа

1. Поднять сервер (подробно — [`ADMIN_GUIDE.md`](docs/ADMIN_GUIDE.md)):

   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ollama pull qwen3:30b-a3b          # рекомендуемая модель
   cd local_server && cp .env.example .env && pip install -r requirements.txt && ./start.sh
   # → http://localhost:8000/health
   ```

2. В `AI_Suggester/ai_macro/Settings.xba` заменить URL:

   ```vbnet
   Public Function GetServerList() As String
       GetServerList = "http://ai-gw.corp.local:8000/suggest"
   End Function
   ```

3. Пересобрать `.oxt` (одна команда, в `ADMIN_GUIDE.md`) и разослать сотрудникам
   вместе с текстом из [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md).

---

## Быстрый старт для сотрудника

1. Сохранить полученный `AI_Suggester.oxt`.
2. **Сервис → Управление расширениями → Добавить → выбрать .oxt → Перезапустить LibreOffice.**
3. Выделить текст → нажать **«AI: Улучшить текст»** → принять/отклонить правки
   через **Правка → Отслеживать изменения → Управление**.

Всё.

---

## Что нового в v1.3

- **Клиент (`AI_Suggester/`)**
  - На панели сотрудника — ровно одна кнопка. Никаких настроечных диалогов.
  - Модуль `Settings.xba` — весь конфиг админа в одном файле, меняется один раз перед сборкой.
  - Проверка HTTP-статуса через `curl -w "%{http_code}"` — больше не полагаемся только на наличие файла.
  - Track Changes — исправления применяются как redline-блоки, управляются штатно.
  - Диагностический `Health.AICheckServer` для админа (через Сервис → Макросы).

- **Серверы**
  - Логи с ротацией (`TimedRotatingFileHandler`, retention из `.env`).
  - SQLite-аудит: кто/когда/IP/UA/модель/длительность/sha1, настраиваемая retention,
    опциональная редакция текста (`AUDIT_REDACT_TEXT=true`).
  - `/metrics` — JSON-сводка за окно времени.
  - Обновлённая рекомендация локальной модели: **qwen3:30b-a3b** (MoE, ≈15–25 tok/s на 32 ядрах CPU).

- **RAG**
  - Поддержка ведомственных документов из Гарант/КонсультантПлюс:
    автоматическая очистка служебных элементов, чанкинг, локальные эмбеддинги
    через Ollama (`nomic-embed-text`), простое CLI для add/list/remove/update.

- **Качество**
  - 36 pytest-тестов (cleanup, RAG, audit, logging, FastAPI smoke, XML-валидация и пересборка `.oxt`).

- **Безопасность**
  - `.gitignore`, `.env` убран из git-трекинга, подробный `.env.example`.

---

## Лицензия

MIT.
