# AI LibreOffice Suggester — Локальный сервер

## Рекомендуемая модель для вашего сервера

**Конфигурация сервера:** 500 GB хранилище · 32 GB RAM · 32 ядра CPU · без GPU

### Выбор модели

| Модель | RAM | Скорость | Качество | Команда загрузки |
|--------|-----|----------|----------|-----------------|
| **qwen2.5:32b** ⭐ рекомендуется | ~22 GB | ~3–5 tok/s | Отличное | `ollama pull qwen2.5:32b` |
| qwen2.5:14b | ~10 GB | ~8–12 tok/s | Хорошее | `ollama pull qwen2.5:14b` |
| mistral-small3.1:22b | ~14 GB | ~6–9 tok/s | Хорошее | `ollama pull mistral-small3.1:22b` |

**Рекомендация: qwen2.5:32b**
- Лучшее понимание русского языка среди open-source моделей
- Квантизация Q4_K_M (используется по умолчанию в Ollama)
- Умещается в 32 GB RAM с запасом (~22 GB модель + ~4 GB система)
- На 28 ядрах даёт 3–5 токенов/сек (короткий текст — 15–30 сек)

---

## Установка (Windows)

### 1. Установить Ollama
Скачать установщик: https://ollama.com/download/windows

Проверить установку:
```
ollama --version
```

### 2. Загрузить модель
```
ollama pull qwen2.5:32b
```
Размер загрузки: ~19 GB. Прогресс отображается в консоли.

### 3. Запустить Ollama (если не запустился автоматически)
```
ollama serve
```

### 4. Установить зависимости Python и запустить сервер
```
pip install -r requirements.txt
start.bat
```

### 5. Проверить работу
Открыть в браузере: http://localhost:8000/health

Ожидаемый ответ:
```
Ollama OK | Модель qwen2.5:32b загружена
```

---

## Установка (Linux / Astra Linux)

### 1. Установить Ollama
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Или без прав root (в домашнюю директорию):
```bash
curl -L https://ollama.com/download/ollama-linux-amd64 -o ~/ollama
chmod +x ~/ollama
~/ollama serve &
```

### 2. Загрузить модель
```bash
ollama pull qwen2.5:32b
```

### 3. Запустить сервер
```bash
pip install -r requirements.txt
./start.sh
```

### 4. Автозапуск через systemd (опционально)
```bash
# Отредактировать ai-suggester.service: заменить YOUR_USERNAME на ваш логин
# и путь /opt/ai-suggester на реальный путь к файлам сервера
sudo cp ai-suggester.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ai-suggester
sudo systemctl start ai-suggester
```

---

## Настройка (.env)

```env
OLLAMA_URL=http://localhost:11434   # URL Ollama
MODEL_NAME=qwen2.5:32b              # Имя модели
NUM_THREADS=28                      # Потоков CPU (оставить 4 для ОС)
```

Чтобы переключиться на более быструю (но менее качественную) модель:
```env
MODEL_NAME=qwen2.5:14b
NUM_THREADS=28
```

---

## Решение проблем

**Ollama не запускается:**
```bash
# Проверить, не занят ли порт
netstat -an | findstr 11434    # Windows
ss -tlnp | grep 11434          # Linux
```

**Модель не найдена:**
```bash
ollama list    # Показать загруженные модели
ollama pull qwen2.5:32b
```

**Мало памяти / сервер зависает:**
Переключитесь на модель меньшего размера в `.env`:
```env
MODEL_NAME=qwen2.5:14b
```

**Медленная генерация:**
Это нормально для CPU-инференса. qwen2.5:32b на 28 ядрах:
- Короткий текст (100–300 слов): 15–40 секунд
- Средний текст (500–1000 слов): 1–3 минуты
