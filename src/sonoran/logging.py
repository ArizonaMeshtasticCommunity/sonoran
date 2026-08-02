"""Logging setup.

This module configures structured logging for all processes.
Use get_logger in every other module.
"""

import logging
import sys

_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger.

    Call this once at process start.
    """
    logging.basicConfig(
        level=level.upper(),
        format=_FORMAT,
        stream=sys.stdout,
        force=True,
    )


def get_logger(name: str) -> logging.Logger:
    """Return a logger for the given module name."""
    return logging.getLogger(name)
