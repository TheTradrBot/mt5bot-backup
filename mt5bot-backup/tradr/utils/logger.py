"""
Logging utilities with rotating file handler.
"""

import logging
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


_loggers = {}


def setup_logger(
    name: str = "tradr",
    log_file: Optional[str] = None,
    level: int = logging.INFO,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> logging.Logger:
    """
    Set up a logger with console and optional file output.
    
    Args:
        name: Logger name
        log_file: Path to log file (optional)
        level: Logging level
        max_bytes: Max size per log file before rotation
        backup_count: Number of backup files to keep
        
    Returns:
        Configured logger
    """
    if name in _loggers:
        return _loggers[name]
    
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False
    
    if logger.handlers:
        logger.handlers.clear()
    
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    _loggers[name] = logger
    return logger


def get_logger(name: str = "tradr") -> logging.Logger:
    """Get or create a logger by name."""
    if name in _loggers:
        return _loggers[name]
    return setup_logger(name)
