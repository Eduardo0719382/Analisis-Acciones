"""Logging configuration: rotating file log plus stderr."""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LEVEL_ENV_VAR = "ANALISIS_ACCIONES_LOG_LEVEL"
LOG_FILE_NAME = "analisis_acciones.log"
_FORMAT = "%(asctime)s %(levelname)-8s %(name)s [%(threadName)s] %(message)s"


def configure_logging(log_dir: Path, level: str | None = None) -> Path:
    """Configure the root logger and return the log file path."""
    level_name = (level or os.environ.get(LEVEL_ENV_VAR, "INFO")).upper()
    numeric_level = logging.getLevelNamesMapping().get(level_name, logging.INFO)

    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / LOG_FILE_NAME

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    root.setLevel(numeric_level)

    formatter = logging.Formatter(_FORMAT)
    file_handler = RotatingFileHandler(
        log_file, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # Under pythonw.exe (double-click launch) there is no console: sys.stderr is None.
    if sys.stderr is not None:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    if level_name not in logging.getLevelNamesMapping():
        logging.getLogger(__name__).warning("Unknown log level %r; using INFO", level_name)
    return log_file
