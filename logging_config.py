import logging
import time

from translator import get_data_dir


def setup_logging() -> None:
    """Configure console and daily file logging for application entrypoints."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

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
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    logging.getLogger(__name__).info("日志文件: %s", log_path)
