"""Exclusive local socket and safe execution log; never log environment or exceptions."""

from __future__ import annotations

import logging
import socket
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path


class PortInUseError(Exception):
    pass


def reserve_socket(host: str, port: int) -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            # Cloud development: allow restart after TIME_WAIT; no SO_REUSEPORT/shared listener.
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, port))
        listener.listen(128)
        return listener
    except OSError as exc:
        listener.close()
        raise PortInUseError(
            "지정 포트를 사용할 수 없습니다. 기존 실행을 종료하거나 명시적으로 포트를 설정하세요."
        ) from exc


def runtime_logger(data_dir: Path) -> logging.Logger:
    logger = logging.getLogger("newsflow.runtime")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    handler = RotatingFileHandler(
        data_dir / "logs" / "execution.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    formatter = logging.Formatter("%(asctime)sZ %(levelname)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
    formatter.converter = time.gmtime
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


def windows_server_loop():
    """Use Selector only for the local HTTP server, without a global loop policy.

    CPython 3.14 Proactor transport cleanup can raise WinError 10054 before
    detaching a reset socket from its Server, leaving wait_closed pending.
    The app uses synchronous worker subprocesses, not asyncio pipe transports.
    """
    import asyncio

    return asyncio.SelectorEventLoop()
