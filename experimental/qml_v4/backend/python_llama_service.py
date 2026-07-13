# -*- coding: utf-8 -*-
"""Embedded OpenAI-compatible llama.cpp service for local GGUF models."""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class PythonLlamaService:
    """Small local HTTP server backed by llama-cpp-python.

    The rest of the app already talks to local models through an OpenAI
    compatible /v1/chat/completions endpoint. Keeping that boundary avoids
    special cases in translator.py and lets external llama-server remain a
    drop-in fallback.
    """

    def __init__(
        self,
        *,
        model_path: str,
        host: str = "127.0.0.1",
        port: int = 8080,
        model_name: str = "Hy-MT2-1.8B-Q4_K_M",
        n_gpu_layers: int = 0,
        ctx_size: int = 4096,
        n_threads: int | None = None,
    ) -> None:
        self.model_path = str(model_path)
        self.host = host
        self.port = int(port)
        self.model_name = model_name
        self.n_gpu_layers = int(n_gpu_layers)
        self.ctx_size = int(ctx_size)
        self.n_threads = n_threads
        self._llm: Any = None
        self._server: ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._inference_lock = threading.Lock()

    def start(self) -> None:
        model = Path(self.model_path)
        if not model.exists():
            raise FileNotFoundError(f"模型文件不存在: {self.model_path}")

        try:
            from llama_cpp import Llama
        except ImportError as exc:
            raise RuntimeError(
                "未安装 llama-cpp-python，无法使用 Python 本地模式。"
                "请先安装 CPU 或 CUDA 版本 llama-cpp-python，或改用 llama-server.exe 模式。"
            ) from exc

        kwargs: dict[str, Any] = {
            "model_path": self.model_path,
            "n_ctx": self.ctx_size,
            "n_gpu_layers": self.n_gpu_layers,
            "verbose": False,
        }
        if self.n_threads:
            kwargs["n_threads"] = self.n_threads

        logger.info(
            "加载 Python llama 模型: %s, n_gpu_layers=%s, ctx=%s",
            self.model_path,
            self.n_gpu_layers,
            self.ctx_size,
        )
        try:
            self._llm = Llama(**kwargs)
        except ValueError as exc:
            message = str(exc)
            lower_path = self.model_path.lower()
            if "failed to load model" in message.lower() and "hy-mt2" in lower_path:
                raise RuntimeError(
                    "当前 llama-cpp-python 不能加载这个 Hy-MT2 GGUF。"
                    "1.25bit/2bit GGUF 当前 llama 不支持，"
                    "请改用 Hy-MT2-1.8B-Q4_K_M.gguf。"
                ) from exc
            raise

        handler = self._make_handler()
        self._server = ThreadingHTTPServer((self.host, self.port), handler)
        self._server_thread = threading.Thread(
            target=self._server.serve_forever,
            name="python-llama-service",
            daemon=True,
        )
        self._server_thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._server_thread is not None:
            self._server_thread.join(timeout=3)
            self._server_thread = None
        self._llm = None

    def is_running(self) -> bool:
        return self._server is not None and self._server_thread is not None and self._server_thread.is_alive()

    def _make_handler(self):
        service = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt: str, *args: Any) -> None:
                logger.debug("Python llama HTTP: " + fmt, *args)

            def do_GET(self) -> None:  # noqa: N802
                if self.path.rstrip("/") == "/health":
                    self._write_json({"ok": True, "model": service.model_name})
                    return
                if self.path.rstrip("/") == "/v1/models":
                    self._write_json(
                        {
                            "object": "list",
                            "data": [
                                {
                                    "id": service.model_name,
                                    "object": "model",
                                    "created": int(time.time()),
                                    "owned_by": "local",
                                }
                            ],
                        }
                    )
                    return
                self._write_json({"error": {"message": "not found"}}, status=404)

            def do_POST(self) -> None:  # noqa: N802
                if self.path.rstrip("/") != "/v1/chat/completions":
                    self._write_json({"error": {"message": "not found"}}, status=404)
                    return

                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
                    response = service._chat_completion(payload)
                    self._write_json(response)
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, socket.timeout) as exc:
                    logger.warning("Python llama client disconnected before response was sent: %s", exc)
                except Exception as exc:  # pragma: no cover - defensive HTTP boundary
                    logger.exception("Python llama completion failed")
                    try:
                        self._write_json({"error": {"message": str(exc), "type": "server_error"}}, status=500)
                    except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, socket.timeout) as write_exc:
                        logger.warning("Python llama client disconnected while sending error response: %s", write_exc)

            def _write_json(self, payload: dict[str, Any], status: int = 200) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler

    def _chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._llm is None:
            raise RuntimeError("模型尚未加载完成")

        messages = payload.get("messages") or []
        temperature = float(payload.get("temperature", 0.7))
        top_p = float(payload.get("top_p", 0.6))
        top_k = int(payload.get("top_k") or 40)
        repeat_penalty = float(payload.get("repeat_penalty") or payload.get("repetition_penalty") or 1.0)
        max_tokens = int(payload.get("max_tokens") or payload.get("max_completion_tokens") or 1024)

        with self._inference_lock:
            try:
                result = self._llm.create_chat_completion(
                    messages=messages,
                    temperature=temperature,
                    top_p=top_p,
                    top_k=top_k,
                    repeat_penalty=repeat_penalty,
                    max_tokens=max_tokens,
                )
                if isinstance(result, dict) and result.get("choices"):
                    return result
            except Exception:
                logger.debug("create_chat_completion failed, falling back to plain completion", exc_info=True)

            prompt = self._messages_to_prompt(messages)
            result = self._llm(
                prompt,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                repeat_penalty=repeat_penalty,
                max_tokens=max_tokens,
                stop=["</s>", "<|endoftext|>"],
            )
            content = self._extract_plain_text(result)

        return {
            "id": "chatcmpl-local",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": self.model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    @staticmethod
    def _messages_to_prompt(messages: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        for message in messages:
            role = str(message.get("role") or "user")
            content = str(message.get("content") or "")
            if not content:
                continue
            if role == "system":
                parts.append(f"系统指令:\n{content}")
            elif role == "assistant":
                parts.append(f"助手:\n{content}")
            else:
                parts.append(f"用户:\n{content}")
        parts.append("助手:")
        return "\n\n".join(parts)

    @staticmethod
    def _extract_plain_text(result: Any) -> str:
        if isinstance(result, dict):
            choices = result.get("choices") or []
            if choices:
                first = choices[0]
                if isinstance(first, dict):
                    if "text" in first:
                        return str(first.get("text") or "").strip()
                    message = first.get("message")
                    if isinstance(message, dict):
                        return str(message.get("content") or "").strip()
        return str(result or "").strip()
