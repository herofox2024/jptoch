"""Small QThread workers used by the QML translation bridge."""

from __future__ import annotations

from typing import Any, Dict, List

import requests
from PySide6.QtCore import QObject, Signal


def collect_translatable_texts(epub_path: str) -> List[str]:
    from epub_io import extract_toc_titles, extract_visible_text, iter_text_nodes, load_book
    from text_utils import is_translatable

    book = load_book(epub_path)
    texts: List[str] = []
    for _, _, tags in iter_text_nodes(book):
        for tag in tags:
            anchors = tag.find_all("a")
            if len(anchors) > 1:
                for node in tag.find_all(string=True):
                    raw = str(node).strip()
                    if is_translatable(raw):
                        texts.append(raw)
                continue
            text = extract_visible_text(tag)
            if is_translatable(text):
                texts.append(text)
    texts.extend(extract_toc_titles(book))
    return texts


class EstimateWorker(QObject):
    finished = Signal(str, int)
    failed = Signal(str, str)

    def __init__(self, path: str):
        super().__init__()
        self._path = path

    def run(self) -> None:
        try:
            from epub_io import extract_toc_titles, extract_visible_text, iter_text_nodes, load_book

            book = load_book(self._path)
            all_texts = []
            for _, _, tags in iter_text_nodes(book):
                for tag in tags:
                    text = extract_visible_text(tag)
                    if text:
                        all_texts.append(text)
            all_texts.extend(extract_toc_titles(book))
            self.finished.emit(self._path, sum(len(text) for text in all_texts))
        except Exception as exc:
            self.failed.emit(self._path, str(exc))


class ClearBookCacheWorker(QObject):
    finished = Signal(int, int)
    failed = Signal(str)

    def __init__(self, config: Dict[str, Any]):
        super().__init__()
        self._config = dict(config or {})

    def run(self) -> None:
        try:
            from translator import JaZhTranslator

            cfg = self._config
            texts = collect_translatable_texts(cfg["inp"])
            translator = JaZhTranslator(
                api_key=cfg.get("api_key") or "cache-clear",
                provider=cfg.get("provider") or "deepseek",
                api_url=cfg.get("api_url") or None,
                model=cfg.get("model") or None,
                max_workers=1,
                batch_size=1,
                max_batch_length=cfg.get("max_batch_length", 800),
                max_text_size_for_batch=cfg.get("max_text_size_for_batch", 200),
                api_timeout=cfg.get("api_timeout", 120),
                enable_glossary=False,
                hymt2_generation_mode=cfg.get("hymt2_generation_mode", "stable"),
                hymt2_prompt_mode=cfg.get("hymt2_prompt_mode", "official"),
                hymt2_runtime_mode=cfg.get("hymt2_runtime_mode", "cpu"),
            )
            removed = translator.clear_cache_for_texts(texts, include_text_cache=True, all_models=True)
            unique_total = len({str(text or "").strip() for text in texts if str(text or "").strip()})
            self.finished.emit(removed, unique_total)
        except Exception as exc:
            self.failed.emit(str(exc))


class TestConnectionWorker(QObject):
    result = Signal(str)

    def __init__(self, api_key, api_url, model, timeout):
        super().__init__()
        self._api_key = api_key
        self._api_url = api_url
        self._model = model
        self._timeout = timeout

    def run(self) -> None:
        try:
            headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
            payload = {
                "model": self._model,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 10,
                "temperature": 0.1,
            }
            response = requests.post(
                self._api_url,
                headers=headers,
                json=payload,
                timeout=int(self._timeout) if self._timeout else 15,
            )
            if response.status_code == 200:
                self.result.emit(f"连接成功 ({response.status_code}) — 模型: {self._model}")
            else:
                self.result.emit(f"失败: HTTP {response.status_code} — {response.text[:200]}")
        except requests.exceptions.Timeout:
            self.result.emit(f"失败: 连接超时 ({self._timeout}秒)")
        except requests.exceptions.ConnectionError as exc:
            message = str(exc)
            if "10061" in message or "Connection refused" in message or "actively refused" in message:
                self.result.emit(
                    "失败: 本地服务未启动或端口未监听。"
                    "请在下方 Hy-MT2 本地模型区域选择 llama-server 后点击“启动本地服务”，"
                    "或确认外部 llama-server 正在监听当前 API URL。"
                )
            else:
                self.result.emit(f"失败: 网络连接失败 — {message[:240]}")
        except Exception as exc:
            self.result.emit(f"失败: {exc}")
