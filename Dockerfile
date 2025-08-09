# Используем официальный образ Python как базовый
FROM python:3.11-slim-bookworm

# Устанавливаем системные зависимости, которые могут понадобиться
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем рабочую директорию внутри контейнера
WORKDIR /app

# Создаем пользователя для безопасности (не запускаем от root)
RUN useradd --create-home --shell /bin/bash app && \
    chown -R app:app /app
USER app

# Копируем файл requirements.txt в рабочую директорию контейнера
COPY --chown=app:app requirements.txt .

# Устанавливаем все зависимости, указанные в requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Копируем весь остальной код вашего бота в рабочую директорию контейнера
COPY --chown=app:app . .

# Создаем директорию для логов с правильными правами
RUN mkdir -p logs && \
    chown -R app:app logs

# Эти переменные окружения здесь указаны с "dummy" значениями.
# Реальные значения должны быть настроены в Coolify в разделе "Variables" вашего сервиса.
ENV TUYA_ACCESS_ID="dummy" \
    TUYA_ACCESS_SECRET="dummy" \
    TUYA_API_REGION="eu" \
    SUPABASE_URL="dummy" \
    SUPABASE_KEY="dummy" \
    DEVICES_CONFIG_PATH="devices.json" \
    TARIFF_SETTINGS_PATH="tariff_settings.json" \
    TELEGRAM_BOT_TOKEN="dummy" \
    TELEGRAM_ADMIN_ID="dummy" \
    PYTHONUNBUFFERED=1 \
    LOG_LEVEL="INFO"

# Открываем порт (если понадобится для health check или других целей)
EXPOSE 8080

# Health check для проверки состояния приложения
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8080/health')" || exit 1

# Команда для запуска приложения при старте контейнера
CMD ["python", "main.py"]