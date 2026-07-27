import logging
import os
import tempfile
import time
from pathlib import Path

from translator import get_data_dir


def setup_logging() -> None:
    """Configure console and daily file logging for application entrypoints."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    # Keep the main app log focused on translator events. httpx/httpcore log one
    # INFO line for every successful 200 OK request, which floods large-book runs.
    for noisy_logger in (
        "httpx",
        "httpcore",
        "httpcore.connection",
        "httpcore.http11",
        "urllib3",
        "urllib3.connectionpool",
    ):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    logs_dir = get_data_dir() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"app-{time.strftime('%Y%m%d')}.log"
    log_file = str(log_path)

    if not any(
        isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", "") == log_file
        for h in root.handlers
    ):
        file_handler = None
        log_candidates = [
            log_path,
            logs_dir / f"app-{time.strftime('%Y%m%d')}-{os.getpid()}.log",
            Path(tempfile.gettempdir()) / f"epub-translator-{time.strftime('%Y%m%d')}-{os.getpid()}.log",
        ]
        for candidate in log_candidates:
            try:
                candidate.parent.mkdir(parents=True, exist_ok=True)
                file_handler = logging.FileHandler(candidate, encoding="utf-8")
                log_path = candidate
                break
            except OSError:
                continue
        if file_handler is not None:
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)

    logging.getLogger(__name__).info("日志文件: %s", log_path)
