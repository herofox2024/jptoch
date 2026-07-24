# -*- coding: utf-8 -*-
"""QML bridge for viewing the application log in real time."""

import logging
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Property, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

try:
    from backend import request_log
except Exception:  # pragma: no cover - keeps old launch paths compatible
    request_log = None


def _data_dir() -> Path:
    path = Path.home() / ".epub_translator"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _logs_dir() -> Path:
    path = _data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _current_log_path() -> Path:
    return _logs_dir() / f"app-{time.strftime('%Y%m%d')}.log"


class _QtLogHandler(logging.Handler):
    """Forward Python logging records to QML through a Qt signal."""

    def __init__(self, bridge: "LogBridge"):
        super().__init__(level=logging.INFO)
        self._bridge = bridge

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._bridge.enqueueLogLine(self.format(record))
        except Exception:
            # Never let UI log forwarding break the actual logging pipeline.
            pass


class LogBridge(QObject):
    entryAppended = Signal(str)
    currentLogPathChanged = Signal()
    requestLogChanged = Signal()
    _flushRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._buffer_lock = threading.RLock()
        self._pending_lines = []
        self._flush_scheduled = False
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(400)
        self._flush_timer.timeout.connect(self._flushPendingLines)
        self._flushRequested.connect(self._startFlushTimer)
        self._handler = _QtLogHandler(self)
        self._handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        logging.getLogger().addHandler(self._handler)

    def enqueueLogLine(self, line: str) -> None:
        if not line:
            return
        with self._buffer_lock:
            self._pending_lines.append(line)
            if len(self._pending_lines) > 300:
                self._pending_lines = self._pending_lines[-300:]
            if self._flush_scheduled:
                return
            self._flush_scheduled = True
        self._flushRequested.emit()

    @Slot()
    def _startFlushTimer(self) -> None:
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    @Slot()
    def _flushPendingLines(self) -> None:
        with self._buffer_lock:
            lines = self._pending_lines
            self._pending_lines = []
            self._flush_scheduled = False
        if lines:
            self.entryAppended.emit("\n".join(lines))

    @Property(str, notify=currentLogPathChanged)
    def currentLogPath(self) -> str:
        return str(_current_log_path())

    @Property(str, constant=True)
    def logDirectory(self) -> str:
        return str(_logs_dir())

    @Property(str, constant=True)
    def requestLogDirectory(self) -> str:
        if request_log is None:
            return str(_data_dir() / "request_logs")
        return str(request_log.request_log_dir())

    @Slot(int, result=str)
    def readRecent(self, maxLines: int = 800) -> str:
        path = _current_log_path()
        if not path.exists():
            return f"日志文件尚未生成: {path}"

        max_lines = max(50, min(int(maxLines or 800), 5000))
        max_bytes = 1024 * 768
        try:
            size = path.stat().st_size
            with path.open("rb") as file:
                if size > max_bytes:
                    file.seek(-max_bytes, 2)
                    data = file.read()
                    prefix = f"... 仅显示最近 {max_lines} 行日志 ...\n"
                else:
                    data = file.read()
                    prefix = ""
            text = data.decode("utf-8", errors="replace")
            lines = text.splitlines()
            return prefix + "\n".join(lines[-max_lines:])
        except Exception as exc:
            return f"读取日志失败: {exc}"

    @Slot(result=dict)
    def clearCurrentLog(self):
        path = _current_log_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            cleared_file_handler = False
            for handler in logging.getLogger().handlers:
                if not isinstance(handler, logging.FileHandler):
                    continue
                if Path(getattr(handler, "baseFilename", "")).resolve() != path.resolve():
                    continue
                handler.acquire()
                try:
                    if handler.stream:
                        handler.stream.seek(0)
                        handler.stream.truncate(0)
                        handler.stream.flush()
                        cleared_file_handler = True
                finally:
                    handler.release()
            if not cleared_file_handler:
                path.write_text("", encoding="utf-8")
            self.currentLogPathChanged.emit()
            return {"ok": True, "message": "当前运行日志已清空"}
        except Exception as exc:
            return {"ok": False, "message": f"清空运行日志失败: {exc}"}

    @Slot(result=bool)
    def openLogDirectory(self) -> bool:
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(_logs_dir())))

    @Slot(int, str, str, result=list)
    def readRequestLogs(self, limit: int = 300, category: str = "", query: str = ""):
        if request_log is None:
            return []
        return request_log.read_recent(limit=limit, category=category, query=query)

    @Slot(result=bool)
    def openRequestLogDirectory(self) -> bool:
        path = self.requestLogDirectory
        return QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    @Slot(result=dict)
    def clearRequestLogs(self):
        if request_log is None:
            return {"ok": False, "removed": 0, "message": "request log module unavailable"}
        removed = request_log.clear_logs()
        self.requestLogChanged.emit()
        return {"ok": True, "removed": removed, "message": f"cleared {removed} request log files"}
