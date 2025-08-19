# Используем официальный образ Python как базовый
FROM python:3.11-slim-buster

# Устанавливаем рабочую директорию внутри контейнера
WORKDIR /app

# Копируем файл requirements.txt в рабочую директорию контейнера
COPY requirements.txt .

# Устанавливаем все зависимости, указанные в requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь остальной код вашего бота в рабочую директорию контейнера
COPY . .

# Эти переменные окружения здесь указаны с "dummy" значениями.
# Реальные значения должны быть настроены в Coolify в разделе "Variables" вашего сервиса.
ENV SUPABASE_URL="dummy" \
    SUPABASE_KEY="dummy" \
    DEVICES_CONFIG_PATH="dummy" \
    TARIFF_SETTINGS_PATH="dummy" \
    TUYA_ACCESS_ID="dummy" \
    TUYA_ACCESS_SECRET="dummy" \
    TUYA_API_URL="dummy" \
    TUYA_API_REGION="dummy" \
    TELEGRAM_BOT_TOKEN="dummy" \
    TELEGRAM_ADMIN_ID="dummy" \
    BYBIT_API_KEY="dummy" \
    BYBIT_API_SECRET="dummy" \
    GATE_API_KEY="dummy" \
    GATE_API_SECRET="dummy" \
    OPENROUTER_API_KEY="dummy" \
    CEREBRAS_API_KEY="dummy"

# Команда для запуска приложения при старте контейнера
CMD ["python", "main.py"]