import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from typing import Optional

def setup_logger(
    name: str = "yba_bot",
    log_dir: Optional[str] = None,
    log_level: str = "INFO",
    max_bytes: int = 10 * 1024 * 1024, # 10 MB
    backup_count: int = 5
) -> logging.Logger:
    """
    Настраивает и возвращает потокобезопасный регистратор (logger)
    с одновременным выводом в консоль и ротацией в файл bot.log.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Предотвращаем дублирование обработчиков при повторном вызове
    if logger.handlers:
        return logger

    # Форматирование логов
    file_format = logging.Formatter(
        "[%(asctime)s] [%(levelname)-8s] [%(name)s.%(module)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_format = logging.Formatter(
        "[%(asctime)s] [%(levelname)s]: %(message)s",
        datefmt="%H:%M:%S"
    )

    # Обработчик консоли (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

    # Обработчик файла с ротацией
    target_log_dir = log_dir or os.getenv("LOG_DIR", "logs")
    try:
        os.makedirs(target_log_dir, exist_ok=True)
        log_file_path = os.path.join(target_log_dir, "bot.log")
        file_handler = RotatingFileHandler(
            log_file_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8"
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)
    except Exception as e:
        logger.warning(f"Не удалось инициализировать файловый логгер: {e}")

    return logger

log = setup_logger()
