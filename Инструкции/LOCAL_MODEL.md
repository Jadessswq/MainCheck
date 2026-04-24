# Локальная LLM — подробное руководство

## Рекомендованная модель (2026)

**Qwen3-30B-A3B-Instruct** — MoE-модель (смесь экспертов) от Alibaba:
суммарно 30 млрд параметров, но при каждом токене активны только ≈3 млрд.
На CPU это даёт скорость **14B-модели при качестве 30B-модели** — оптимально
для вашей конфигурации (32 ГБ RAM, 32 ядра, без GPU).

| Модель                | RAM (Q4) | CPU-скорость      | Качество (рус) | Команда                        |
|-----------------------|----------|-------------------|----------------|--------------------------------|
| **qwen3:30b-a3b** ⭐  | ~18 ГБ   | **15–25 tok/s**   | Отличное       | `ollama pull qwen3:30b-a3b`    |
| qwen2.5:32b           | ~22 ГБ   | 3–5 tok/s         | Отличное       | `ollama pull qwen2.5:32b`      |
| qwen3:14b             | ~10 ГБ   | 7–12 tok/s        | Очень хорошее  | `ollama pull qwen3:14b`        |
| qwen2.5:14b           | ~10 ГБ   | 7–12 tok/s        | Хорошее        | `ollama pull qwen2.5:14b`      |
| gemma3:27b            | ~15 ГБ   | 4–7 tok/s         | Хорошее        | `ollama pull gemma3:27b`       |
| mistral-small3.2:24b  | ~14 ГБ   | 5–8 tok/s         | Хорошее        | `ollama pull mistral-small3.2:24b` |

> **Совет.** Если RAM <24 ГБ или процессор слабее 16 ядер — начинайте с `qwen3:14b`,
> это устойчивая рабочая лошадка; потом переходите на `qwen3:30b-a3b`, если RAM позволит.

---

## 1. Установка Ollama

### Windows 10/11

1. Скачать: <https://ollama.com/download/windows>.
2. Установить (без прав администратора для профиля пользователя).
3. Проверить:

   ```cmd
   ollama --version
   ```

### Astra Linux / Ubuntu / Debian

**С правами root:**
```bash
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl enable --now ollama
```

**Без root (в домашнюю папку):**
```bash
mkdir -p ~/.local/bin
curl -L https://ollama.com/download/ollama-linux-amd64 -o ~/.local/bin/ollama
chmod +x ~/.local/bin/ollama
# Добавить в PATH (один раз)
echo 'export PATH=$HOME/.local/bin:$PATH' >> ~/.bashrc
export PATH=$HOME/.local/bin:$PATH
# Запустить в фоне с логом
nohup ~/.local/bin/ollama serve > ~/.local/bin/ollama.log 2>&1 &
```

---

## 2. Скачивание модели

```bash
ollama pull qwen3:30b-a3b
```

Объём загрузки ≈ 18 ГБ. Прогресс виден в консоли. При сбое сети можно повторять команду — Ollama докачивает.

Проверить список установленных моделей:

```bash
ollama list
```

---

## 3. Подключение к AI Suggester

1. Использовать папку `Сервер/local/` из репозитория.
2. Скопировать `.env.example` → `.env`, задать `MODEL_NAME=qwen3:30b-a3b`.
3. Запустить:

   **Linux:** `cd Сервер/local && ./start.sh`
   **Windows:** `cd Сервер\local && start.bat`

4. Проверить <http://localhost:8000/health> — ожидаем `Ollama OK | Модель qwen3:30b-a3b загружена`.
5. Админу: для диагностики — **Сервис → Макросы → Мои макросы → ai_macro → Health → AICheckServer**.

---

## 4. Переключение между локальной и облачной моделью

В модуле `ai_macro.Settings` (Инструменты → Макросы → Мои макросы → ai_macro → Settings → `GetServerList`) указан один или несколько адресов через `|`:

```basic
GetServerList = "http://localhost:8000/suggest|https://ai.example.org/suggest"
```

Макрос перебирает адреса по очереди:

- **Основной — локальный.** Если Ollama недоступен, автоматически используется облачный (OpenRouter).
- **Чтобы перейти на облачный постоянно** — поменять адреса местами или оставить только облачный.
- **Чтобы отключить облачный** — оставить только `http://localhost:8000/suggest`.

После правки сохранить модуль (`Ctrl+S` в Basic IDE) — изменения применяются мгновенно, перезапуск не нужен.

---

## 5. Полное отключение локальной модели

Если локальный сервер временно не нужен (например, работаем только через облако):

```bash
# Остановить FastAPI-сервер AI Suggester
# Ctrl+C в окне start.sh / start.bat
# или, если как systemd-сервис:
sudo systemctl stop ai-suggester

# Остановить Ollama (освободит RAM модели)
#   Windows: правый клик по значку Ollama в трее → Quit
#   Linux с systemd:
sudo systemctl stop ollama
#   Linux без systemd:
pkill -f "ollama serve"
```

Чтобы Ollama не запускалась при входе:

- Windows: Параметры → Приложения → Автозагрузка → выключить **Ollama**.
- Linux: `sudo systemctl disable ollama` (если устанавливали через systemd).

---

## 6. Удаление модели

Модель занимает ≈ 18 ГБ на диске. Чтобы освободить место:

```bash
ollama rm qwen3:30b-a3b
```

Чтобы удалить Ollama целиком:
- Windows: «Параметры → Приложения → Установленные приложения → Ollama → Удалить». Вручную удалить `%userprofile%\.ollama` (там кеш моделей).
- Linux: `sudo systemctl disable --now ollama && sudo rm -f /usr/local/bin/ollama && rm -rf ~/.ollama`.

---

## 7. Настройка под конкретное железо (`.env`)

```env
OLLAMA_URL=http://localhost:11434
MODEL_NAME=qwen3:30b-a3b
NUM_THREADS=28       # ядер; оставьте 3–4 для ОС
```

**Слишком медленно?** Переключиться на меньшую модель:
```env
MODEL_NAME=qwen3:14b
NUM_THREADS=28
```

**Недостаточно RAM?** Рекомендации:
- 16 ГБ → `qwen3:14b` (9 ГБ) или `qwen2.5:7b`
- 24 ГБ → `qwen3:30b-a3b` работает впритык; оставьте запас ≥ 4 ГБ для ОС
- 32 ГБ → любая из рекомендованных

**Параллельные запросы.** По умолчанию Ollama обрабатывает запросы по одному. Если нужно несколько параллельно, запустите несколько инстансов с разными портами (`OLLAMA_HOST=127.0.0.1:11435 ollama serve`) и укажите их в `SERVER_LIST` макроса.

---

## 8. Диагностика

Из LibreOffice: панель инструментов → **AI: Проверить сервер**. Показывает HTTP-код и ответ `/health` для каждого адреса.

Из терминала:
```bash
curl http://localhost:8000/health     # статус сервера AI Suggester
curl http://localhost:11434/api/tags  # список моделей в Ollama
curl http://localhost:8000/metrics    # аудит: запросов за 24 ч, средняя длительность
```

См. также `Инструкции/TROUBLESHOOTING.md`.
