# -*- coding: utf-8 -*-
"""Local model service bridge for launching local Hy-MT2 services from QML."""

import logging
import os
import socket
import threading
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import requests
from PySide6.QtCore import QObject, Property, Signal, Slot

from backend.python_llama_service import PythonLlamaService

logger = logging.getLogger(__name__)
DEFAULT_HYMT2_MODEL_URL = (
    "https://huggingface.co/tencent/Hy-MT2-1.8B-1.25bit-GGUF/resolve/main/model.gguf"
)
MIRROR_HYMT2_MODEL_URL = (
    "https://hf-mirror.com/tencent/Hy-MT2-1.8B-1.25bit-GGUF/resolve/main/model.gguf"
)


def _data_dir() -> Path:
    path = Path.home() / ".epub_translator"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _normalize_path(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("file:///"):
        text = text[8:]
    elif text.startswith("file://"):
        text = text[7:]
    return text.replace("/", "\\") if os.name == "nt" and len(text) > 2 and text[1] == ":" else text


class LocalModelBridge(QObject):
    modelPathChanged = Signal()
    serverPathChanged = Signal()
    backendModeChanged = Signal()
    gpuModeChanged = Signal()
    gpuStatusChanged = Signal()
    runningChanged = Signal()
    statusChanged = Signal()
    downloadChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model_path = ""
        self._server_path = ""
        self._backend_mode = "python"
        self._gpu_mode = "auto"
        self._gpu_status = "尚未检测 GPU。自动模式会在启动时检测 NVIDIA 显卡。"
        self._host = "127.0.0.1"
        self._port = 8080
        self._status = "请选择 Hy-MT2 GGUF 模型文件。Python 本地模式无需选择 llama-server。"
        self._process: Optional[subprocess.Popen] = None
        self._python_service: Optional[PythonLlamaService] = None
        self._python_starting = False
        self._python_stop_requested = False
        self._python_start_thread: Optional[threading.Thread] = None
        self._log_file = None
        self._download_progress = 0
        self._downloaded_bytes = 0
        self._download_total_bytes = 0
        self._downloading = False
        self._download_cancel = threading.Event()
        self._download_thread: Optional[threading.Thread] = None

    def _set_status(self, message: str) -> None:
        self._status = message
        self.statusChanged.emit()
        logger.info("本地模型: %s", message)

    def _is_process_alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _is_python_service_alive(self) -> bool:
        return self._python_service is not None and self._python_service.is_running()

    def _set_gpu_status(self, message: str) -> None:
        self._gpu_status = message
        self.gpuStatusChanged.emit()
        logger.info("本地模型 GPU: %s", message)

    @Property(str, notify=modelPathChanged)
    def modelPath(self) -> str:
        return self._model_path

    @Property(str, notify=serverPathChanged)
    def serverPath(self) -> str:
        return self._server_path

    @Property(str, notify=backendModeChanged)
    def backendMode(self) -> str:
        return self._backend_mode

    @Property(str, notify=gpuModeChanged)
    def gpuMode(self) -> str:
        return self._gpu_mode

    @Property(str, notify=gpuStatusChanged)
    def gpuStatus(self) -> str:
        return self._gpu_status

    @Property(str, notify=statusChanged)
    def statusMessage(self) -> str:
        return self._status

    @Property(str, constant=True)
    def defaultModelUrl(self) -> str:
        return DEFAULT_HYMT2_MODEL_URL

    @Property(str, constant=True)
    def mirrorModelUrl(self) -> str:
        return MIRROR_HYMT2_MODEL_URL

    @Property(str, constant=True)
    def defaultModelDir(self) -> str:
        path = _data_dir() / "models" / "hymt2"
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    @Property(bool, notify=downloadChanged)
    def downloading(self) -> bool:
        return self._downloading

    @Property(int, notify=downloadChanged)
    def downloadProgress(self) -> int:
        return int(self._download_progress)

    @Property(str, notify=downloadChanged)
    def downloadBytesText(self) -> str:
        def fmt(value: int) -> str:
            if value <= 0:
                return "0 B"
            units = ["B", "KB", "MB", "GB"]
            amount = float(value)
            index = 0
            while amount >= 1024 and index < len(units) - 1:
                amount /= 1024
                index += 1
            return f"{amount:.1f} {units[index]}"

        if self._download_total_bytes > 0:
            return f"{fmt(self._downloaded_bytes)} / {fmt(self._download_total_bytes)}"
        return fmt(self._downloaded_bytes)

    @Property(bool, notify=runningChanged)
    def running(self) -> bool:
        return self._is_process_alive() or self._is_python_service_alive() or self._python_starting

    @Property(str, constant=True)
    def localApiUrl(self) -> str:
        return f"http://{self._host}:{self._port}/v1/chat/completions"

    @Property(str, notify=modelPathChanged)
    def modelName(self) -> str:
        if not self._model_path:
            return "Hy-MT2-1.8B-1.25bit-GGUF"
        return Path(self._model_path).stem or "Hy-MT2-1.8B-1.25bit-GGUF"

    def _is_port_available(self) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            return sock.connect_ex((self._host, self._port)) != 0

    def _detect_nvidia_gpu(self) -> tuple[bool, str]:
        command = shutil.which("nvidia-smi")
        if not command:
            return False, "未找到 nvidia-smi，按 CPU 模式启动。"
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            result = subprocess.run(
                [command, "-L"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=3,
                creationflags=creationflags,
                check=False,
            )
        except Exception as exc:
            return False, f"GPU 检测失败，按 CPU 模式启动: {exc}"
        output = (result.stdout or result.stderr or "").strip()
        if result.returncode == 0 and ("GPU" in output or "NVIDIA" in output.upper()):
            return True, f"检测到 NVIDIA GPU: {output.splitlines()[0]}"
        return False, "未检测到可用 NVIDIA GPU，按 CPU 模式启动。"

    def _resolve_gpu_layers(self) -> tuple[int, str]:
        mode = self._gpu_mode
        if mode == "cpu":
            return 0, "已选择 CPU 模式。"
        if mode == "cuda":
            return -1, "已选择 CUDA 模式，将尝试 GPU 加速。"

        has_gpu, message = self._detect_nvidia_gpu()
        if has_gpu:
            return -1, message + " 自动启用 CUDA。"
        return 0, message

    def _download_target_for_url(self, url: str) -> Path:
        file_name = (url or "").rstrip("/").split("/")[-1].split("?")[0] or "model.gguf"
        if not file_name.lower().endswith(".gguf"):
            file_name = "model.gguf"
        target_dir = Path(self.defaultModelDir)
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir / file_name

    def _set_download_state(
        self,
        *,
        downloading: Optional[bool] = None,
        progress: Optional[int] = None,
        downloaded: Optional[int] = None,
        total: Optional[int] = None,
    ) -> None:
        if downloading is not None:
            self._downloading = downloading
        if progress is not None:
            self._download_progress = max(0, min(100, int(progress)))
        if downloaded is not None:
            self._downloaded_bytes = max(0, int(downloaded))
        if total is not None:
            self._download_total_bytes = max(0, int(total))
        self.downloadChanged.emit()

    def _candidate_download_urls(self, url: str) -> list[str]:
        candidates = [url]
        if "huggingface.co/" in url:
            candidates.append(url.replace("https://huggingface.co/", "https://hf-mirror.com/"))
        if url == DEFAULT_HYMT2_MODEL_URL and MIRROR_HYMT2_MODEL_URL not in candidates:
            candidates.append(MIRROR_HYMT2_MODEL_URL)
        result = []
        for item in candidates:
            if item and item not in result:
                result.append(item)
        return result

    def _format_download_error(self, error: Exception) -> str:
        if isinstance(error, requests.exceptions.ProxyError):
            return (
                "系统代理连接失败或 TLS 握手超时。已尝试直连和镜像；"
                "如果仍失败，请检查代理设置，或手动下载 GGUF 后在页面选择本地文件。"
            )
        if isinstance(error, requests.exceptions.Timeout):
            return "连接或读取超时。可重试下载，或改用 hf-mirror / 手动下载。"
        if isinstance(error, requests.exceptions.ConnectionError):
            return "网络连接失败。可检查网络、代理或改用镜像下载。"
        return str(error)

    def _download_once(self, url: str, target: Path, temp_path: Path, *, trust_env: bool) -> None:
        existing = temp_path.stat().st_size if temp_path.exists() else 0
        headers = {"User-Agent": "epub-translator-qml-v4"}
        if existing > 0:
            headers["Range"] = f"bytes={existing}-"

        session = requests.Session()
        session.trust_env = trust_env
        with session.get(url, stream=True, timeout=(30, 90), headers=headers) as resp:
            if resp.status_code not in (200, 206):
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            mode = "ab" if resp.status_code == 206 and existing > 0 else "wb"
            if mode == "wb":
                existing = 0
            content_length = int(resp.headers.get("Content-Length") or 0)
            total = existing + content_length if content_length > 0 else 0
            downloaded = existing
            self._set_download_state(downloading=True, downloaded=downloaded, total=total, progress=0)
            with temp_path.open(mode) as fh:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if self._download_cancel.is_set():
                        self._set_status("模型下载已取消，可稍后继续断点下载。")
                        self._set_download_state(downloading=False)
                        return
                    if not chunk:
                        continue
                    fh.write(chunk)
                    downloaded += len(chunk)
                    progress = int(downloaded * 100 / total) if total > 0 else 0
                    self._set_download_state(downloaded=downloaded, total=total, progress=progress)
        temp_path.replace(target)
        self._set_download_state(
            downloading=False,
            progress=100,
            downloaded=target.stat().st_size,
            total=target.stat().st_size,
        )
        self._model_path = str(target)
        self.modelPathChanged.emit()
        self._set_status(f"模型下载完成并已选中: {target}")

    def _download_worker(self, url: str, target: Path) -> None:
        temp_path = target.with_suffix(target.suffix + ".part")
        last_error: Optional[Exception] = None
        try:
            for candidate_url in self._candidate_download_urls(url):
                for trust_env in (True, False):
                    if self._download_cancel.is_set():
                        self._set_status("模型下载已取消，可稍后继续断点下载。")
                        self._set_download_state(downloading=False)
                        return
                    mode_text = "系统代理" if trust_env else "直连"
                    self._set_status(f"正在下载 Hy-MT2 模型（{mode_text}）: {candidate_url}")
                    try:
                        self._download_once(candidate_url, target, temp_path, trust_env=trust_env)
                        return
                    except requests.exceptions.ProxyError as exc:
                        last_error = exc
                        self._set_status("系统代理连接失败，准备尝试直连或镜像。")
                    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                        last_error = exc
                        self._set_status(f"{mode_text}下载连接失败，准备尝试下一个下载方式。")
                    except Exception as exc:
                        last_error = exc
                        logger.warning("下载尝试失败: %s (%s)", candidate_url, exc)
                        break
            if last_error:
                raise last_error
            raise RuntimeError("没有可用的下载地址")
        except Exception as exc:
            logger.exception("下载 Hy-MT2 模型失败")
            self._set_status(f"模型下载失败: {self._format_download_error(exc)}")
            self._set_download_state(downloading=False)

    @Slot(str, result="QVariantMap")
    def setModelPath(self, path: str):
        normalized = _normalize_path(path)
        if not normalized:
            return {"ok": False, "message": "模型路径为空"}
        if not Path(normalized).exists():
            return {"ok": False, "message": f"模型文件不存在: {normalized}"}
        self._model_path = normalized
        self.modelPathChanged.emit()
        self._set_status(f"已选择模型: {normalized}")
        return {"ok": True, "message": "已选择模型文件"}

    @Slot(str, result="QVariantMap")
    def setServerPath(self, path: str):
        normalized = _normalize_path(path)
        if not normalized:
            return {"ok": False, "message": "llama-server 路径为空"}
        if not Path(normalized).exists():
            return {"ok": False, "message": f"llama-server 不存在: {normalized}"}
        self._server_path = normalized
        self.serverPathChanged.emit()
        self._set_status(f"已选择 llama-server: {normalized}")
        return {"ok": True, "message": "已选择 llama-server"}

    @Slot(str, result="QVariantMap")
    def setBackendMode(self, mode: str):
        normalized = str(mode or "").strip().lower()
        if normalized not in {"python", "server"}:
            return {"ok": False, "message": "本地模式只能是 python 或 server"}
        if self.running:
            return {"ok": False, "message": "请先停止本地服务，再切换运行模式"}
        self._backend_mode = normalized
        self.backendModeChanged.emit()
        if normalized == "python":
            self._set_status("已切换到 Python 本地模式：由本软件加载 GGUF 模型。")
        else:
            self._set_status("已切换到 llama-server.exe 模式：由外部程序加载 GGUF 模型。")
        return {"ok": True, "message": "运行模式已切换"}

    @Slot(str, result="QVariantMap")
    def setGpuMode(self, mode: str):
        normalized = str(mode or "").strip().lower()
        if normalized not in {"auto", "cuda", "cpu"}:
            return {"ok": False, "message": "GPU 模式只能是 auto、cuda 或 cpu"}
        if self.running:
            return {"ok": False, "message": "请先停止本地服务，再切换 GPU 模式"}
        self._gpu_mode = normalized
        self.gpuModeChanged.emit()
        if normalized == "auto":
            self._set_gpu_status("已选择自动模式：启动时检测 NVIDIA GPU。")
        elif normalized == "cuda":
            self._set_gpu_status("已选择 CUDA 模式：如果 llama-cpp-python 不支持 CUDA，会自动回退 CPU。")
        else:
            self._set_gpu_status("已选择 CPU 模式：不会启用 CUDA。")
        return {"ok": True, "message": "GPU 模式已切换"}

    @Slot(result="QVariantMap")
    def detectGpuBackend(self):
        has_gpu, message = self._detect_nvidia_gpu()
        self._set_gpu_status(message)
        return {"ok": has_gpu, "message": message}

    @Slot(result="QVariantMap")
    def findLlamaServer(self):
        candidates = [
            "llama-server.exe",
            "llama-server",
        ]
        for name in candidates:
            found = shutil.which(name)
            if found:
                self._server_path = found
                self.serverPathChanged.emit()
                self._set_status(f"已找到 llama-server: {found}")
                return {"ok": True, "message": found}
        return {"ok": False, "message": "未在 PATH 中找到 llama-server，请手动选择。"}

    @Slot(str, result="QVariantMap")
    def startModelDownload(self, url: str):
        download_url = str(url or "").strip() or DEFAULT_HYMT2_MODEL_URL
        if self._downloading:
            return {"ok": False, "message": "模型正在下载中"}
        if not download_url.startswith(("http://", "https://")):
            return {"ok": False, "message": "请输入有效的模型下载 URL"}
        target = self._download_target_for_url(download_url)
        if target.exists() and target.stat().st_size > 0:
            self._model_path = str(target)
            self.modelPathChanged.emit()
            self._set_status(f"模型文件已存在并已选中: {target}")
            return {"ok": True, "message": "模型文件已存在，已直接选中"}
        self._download_cancel.clear()
        self._set_download_state(downloading=True, progress=0, downloaded=0, total=0)
        self._set_status(f"开始下载 Hy-MT2 模型: {download_url}")
        self._download_thread = threading.Thread(
            target=self._download_worker,
            args=(download_url, target),
            daemon=True,
        )
        self._download_thread.start()
        return {"ok": True, "message": f"开始下载到: {target}"}

    @Slot(result="QVariantMap")
    def cancelModelDownload(self):
        if not self._downloading:
            return {"ok": True, "message": "当前没有模型下载任务"}
        self._download_cancel.set()
        return {"ok": True, "message": "正在取消模型下载"}

    @Slot(result="QVariantMap")
    def startServer(self):
        if self.running:
            return {"ok": True, "message": "本地模型服务已在运行"}
        if not self._model_path or not Path(self._model_path).exists():
            return {"ok": False, "message": "请先选择 Hy-MT2 GGUF 模型文件"}
        if self._backend_mode == "python":
            return self._start_python_server()
        return self._start_external_server()

    def _start_python_server(self):
        if not self._is_port_available():
            return {"ok": False, "message": f"端口 {self._port} 已被占用，请先关闭已有本地模型服务。"}

        n_gpu_layers, gpu_message = self._resolve_gpu_layers()
        self._set_gpu_status(gpu_message)
        self._python_starting = True
        self._python_stop_requested = False
        self.runningChanged.emit()
        self._set_status("正在启动 Python 本地模式并加载 GGUF 模型，首次加载可能需要较长时间。")
        self._python_start_thread = threading.Thread(
            target=self._python_start_worker,
            args=(n_gpu_layers,),
            name="python-llama-start",
            daemon=True,
        )
        self._python_start_thread.start()
        return {"ok": True, "message": "Python 本地服务正在启动，请等待状态变为运行中后再测试连接。"}

    def _python_start_worker(self, n_gpu_layers: int) -> None:
        attempted_gpu = n_gpu_layers != 0
        try:
            self._python_service = PythonLlamaService(
                model_path=self._model_path,
                host=self._host,
                port=self._port,
                model_name=self.modelName,
                n_gpu_layers=n_gpu_layers,
                ctx_size=4096,
            )
            self._python_service.start()
            if self._python_stop_requested:
                try:
                    self._python_service.stop()
                except Exception:
                    logger.exception("Python 本地服务停止请求未能即时生效")
                self._python_service = None
                self._set_status("Python 本地服务已取消启动。")
                self._set_gpu_status("Python 本地服务已取消启动。")
                return
            mode_text = "CUDA" if n_gpu_layers != 0 else "CPU"
            self._set_status(f"Python 本地服务已启动（{mode_text}），地址: http://{self._host}:{self._port}/v1")
            self._set_gpu_status(f"当前运行模式: {mode_text}")
        except Exception as exc:
            if attempted_gpu:
                logger.warning("CUDA 模式加载失败，准备回退 CPU: %s", exc)
                self._set_gpu_status(f"CUDA 加载失败，自动回退 CPU: {exc}")
                try:
                    self._python_service = PythonLlamaService(
                        model_path=self._model_path,
                        host=self._host,
                        port=self._port,
                        model_name=self.modelName,
                        n_gpu_layers=0,
                        ctx_size=4096,
                    )
                    self._python_service.start()
                    self._set_status(f"Python 本地服务已启动（CPU 回退），地址: http://{self._host}:{self._port}/v1")
                    self._set_gpu_status("当前运行模式: CPU（CUDA 不可用，已回退）")
                except Exception as fallback_exc:
                    logger.exception("Python 本地服务 CPU 回退也启动失败")
                    self._python_service = None
                    self._set_status(f"Python 本地服务启动失败: {fallback_exc}")
            else:
                logger.exception("Python 本地服务启动失败")
                self._python_service = None
                self._set_status(f"Python 本地服务启动失败: {exc}")
        finally:
            self._python_starting = False
            self.runningChanged.emit()

    def _start_external_server(self):
        if not self._server_path:
            self.findLlamaServer()
        if not self._server_path or not Path(self._server_path).exists():
            return {"ok": False, "message": "请先选择 llama-server 程序"}

        log_dir = _data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "llama-server.log"
        log_file = log_path.open("a", encoding="utf-8")
        args = [
            self._server_path,
            "-m",
            self._model_path,
            "--host",
            self._host,
            "--port",
            str(self._port),
            "--ctx-size",
            "4096",
        ]
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            self._process = subprocess.Popen(
                args,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
            )
            self._log_file = log_file
        except Exception as exc:
            log_file.close()
            logger.exception("启动 llama-server 失败")
            return {"ok": False, "message": f"启动失败: {exc}"}

        self.runningChanged.emit()
        self._set_status(f"llama-server 已启动，日志: {log_path}")
        return {"ok": True, "message": f"服务已启动: http://{self._host}:{self._port}/v1"}

    @Slot(result="QVariantMap")
    def stopServer(self):
        stopped = False
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            stopped = True
        self._process = None
        if self._log_file is not None:
            try:
                self._log_file.close()
            except Exception:
                pass
            self._log_file = None
        if self._python_service is not None:
            try:
                self._python_service.stop()
                stopped = True
            except Exception:
                logger.exception("停止 Python 本地服务失败")
            self._python_service = None
        if self._python_starting:
            self._python_stop_requested = True
            stopped = True
            self._set_status("Python 本地服务正在加载模型，已请求停止；加载完成前可能无法立即中断。")
        else:
            self._set_status("本地模型服务已停止" if stopped else "本地模型服务未运行")
        self.runningChanged.emit()
        return {"ok": True, "message": "本地模型服务已停止" if stopped else "本地模型服务未运行"}
