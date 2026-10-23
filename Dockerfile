# Production Dockerfile for YBA Discord Ranked Bot
FROM python:3.12-slim

# Оптимизация Python для контейнера
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DB_PATH=/app/data/elo_yba.sqlite \
    BACKUP_DIR=/app/data/backups \
    LOG_DIR=/app/logs \
    LOG_LEVEL=INFO

WORKDIR /app

# Установка системных утилит при необходимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Установка Python-зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование исходного кода бота
COPY . .

# Создание директорий для данных и логов, настройка непривилегированного пользователя
RUN mkdir -p /app/data /app/data/backups /app/logs && \
    useradd -m -u 1000 -s /bin/bash botuser && \
    chown -R botuser:botuser /app

USER botuser

# Запуск бота
CMD ["python", "bot.py"]
