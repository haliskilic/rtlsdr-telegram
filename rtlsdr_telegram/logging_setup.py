"""Rotating file + console logging."""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path


def setup_logging(log_dir: Path, level: str = "INFO") -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("rtlsdr")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.handlers.RotatingFileHandler(log_dir / "rtlsdr-telegram.log", maxBytes=5_000_000,
                                              backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    # errors in a separate file
    eh = logging.handlers.RotatingFileHandler(log_dir / "errors.log", maxBytes=2_000_000,
                                              backupCount=3, encoding="utf-8")
    eh.setFormatter(fmt)
    eh.setLevel(logging.WARNING)
    logger.addHandler(eh)
    logger.propagate = False
    return logger
