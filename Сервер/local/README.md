# AI LibreOffice Suggester — Локальный сервер

Работает без интернета на Ollama. Рекомендуемая модель 2026 года — **qwen3:30b-a3b**
(MoE, 15–25 tok/s на 32 ядрах).

Полное руководство: [`../Инструкции/LOCAL_MODEL.md`](../Инструкции/LOCAL_MODEL.md).

## TL;DR

```bash
# Ollama + модель
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3:30b-a3b
ollama pull nomic-embed-text   # для RAG

# Сервер
cp .env.example .env           # при необходимости правим
pip install -r requirements.txt
./start.sh                     # Linux
# или start.bat                # Windows
```

Проверка:
```bash
curl http://localhost:8000/health
curl http://localhost:8000/metrics
```

## Переменные окружения

Все параметры — в `.env.example`. Основные:

- `MODEL_NAME` — имя модели Ollama (`qwen3:30b-a3b`, `qwen2.5:32b`, `gemma3:27b`, …)
- `NUM_THREADS` — потоков CPU (на 32 ядрах ставим 28, оставляем 4 ядра ОС)
- `RAG_ENABLED` — `true/false`, включить обогащение промта выдержками из ведомственных документов
- `LOG_LEVEL`, `LOG_RETENTION_DAYS`, `AUDIT_ENABLED` — см. `../Инструкции/LOGGING.md`

## Автозапуск (Linux, systemd)

```bash
# Отредактировать ai-suggester.service: заменить YOUR_USERNAME и путь
sudo cp ai-suggester.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ai-suggester
systemctl status ai-suggester
```

## RAG (обучение на Гарант / КонсультантПлюс)

Полное руководство: [`../Инструкции/RAG_GUIDE.md`](../Инструкции/RAG_GUIDE.md).

Краткая шпаргалка:
```bash
# Из корня репозитория
PYTHONPATH=Сервер python -m shared.rag_cli add  ./data/docs/fz_44.docx --doc-id fz-44 --version 2025-03
PYTHONPATH=Сервер python -m shared.rag_cli list
PYTHONPATH=Сервер python -m shared.rag_cli remove fz-44
PYTHONPATH=Сервер python -m shared.rag_cli search "согласно распоряжения"
PYTHONPATH=Сервер python -m shared.rag_cli ingest-folder ./data/docs
```

## Траблшутинг

См. [`../Инструкции/TROUBLESHOOTING.md`](../Инструкции/TROUBLESHOOTING.md).
