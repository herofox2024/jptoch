import json
import logging
import os
import random
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
SAKURA_API_URL = "http://127.0.0.1:8080/v1/chat/completions"
SAKURA_MODEL = "sakura-v1.0"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
GEMINI_MODEL = "gemini-2.5-pro"
DEFAULT_TEXT_SEPARATOR = "\n---SPLIT---\n"


def get_data_dir() -> Path:
    """获取用户数据目录，用于存储缓存和配置"""
    data_dir = Path.home() / ".epub_translator"
    data_dir.mkdir(exist_ok=True)
    return data_dir


class JaZhTranslator:
    def __init__(
        self,
        api_key: Optional[str] = None,
        provider: str = "deepseek",
        api_url: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        frequency_penalty: Optional[float] = None,
        glossary_path: Optional[str] = None,
        cache_path: Optional[str] = None,
        max_workers: int = 5,
        cancel_event: Optional[threading.Event] = None,
        extract_glossary: bool = False,
    ):
        self.provider = (provider or "deepseek").strip().lower()
        if self.provider not in {"deepseek", "sakura", "gemini", "custom"}:
            raise ValueError(f"不支持的提供方: {provider}")

        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        if self.provider == "deepseek" and not self.api_key:
            raise ValueError("未找到 DeepSeek API Key，请在界面输入或设置环境变量 DEEPSEEK_API_KEY")
        if self.provider == "gemini" and not self.api_key:
            raise ValueError("未找到 Gemini API Key，请在界面输入")
        if self.provider == "sakura" and not self.api_key:
            # Sakura 本地服务通常可无鉴权，默认给一个占位 key，兼容部分网关。
            self.api_key = "sk-local"
        if self.provider == "custom" and not self.api_key:
            raise ValueError("未找到自定义 API Key，请在界面输入")

        default_url = DEEPSEEK_API_URL
        default_model = DEEPSEEK_MODEL
        if self.provider == "sakura":
            default_url = SAKURA_API_URL
            default_model = SAKURA_MODEL
        elif self.provider == "gemini":
            default_url = GEMINI_API_URL
            default_model = GEMINI_MODEL

        raw_api_url = (api_url or default_url).strip()
        self.api_url = self._normalize_api_url(raw_api_url)
        self.model = (model or default_model).strip()
        self.temperature = temperature if temperature is not None else (0.1 if self.provider == "sakura" else 0.3)
        self.top_p = top_p if top_p is not None else (0.3 if self.provider == "sakura" else None)
        self.frequency_penalty = (
            frequency_penalty if frequency_penalty is not None else (0.1 if self.provider == "sakura" else None)
        )

        data_dir = get_data_dir()
        self.glossary_path = glossary_path or str(data_dir / "glossary.json")
        self.cache_path = cache_path or str(data_dir / "cache.json")

        self.glossary = self._load_json(self.glossary_path, {})
        self.cache = self._load_json(self.cache_path, {})
        self._cache_dirty = False
        self._save_counter = 0
        self._cache_lock = threading.RLock()
        self._stats_lock = threading.Lock()
        self.max_workers = max_workers
        self.cancel_event = cancel_event or threading.Event()
        self.session = requests.Session()
        self.extract_glossary = bool(extract_glossary)
        self.stats = {
            "api_requests_total": 0,
            "batch_total": 0,
            "batch_json_success": 0,
            "batch_delimiter_success": 0,
            "batch_fallback": 0,
            "batch_split_mismatch": 0,
            "batch_json_parse_fail": 0,
            "glossary_new_terms_added": 0,
        }
        logger.info(
            f"翻译器初始化完成: provider={self.provider}, model={self.model}, api_url={self.api_url}, 并发数: {max_workers}"
        )

    @staticmethod
    def _normalize_api_url(url: str) -> str:
        """兼容填写根地址或 /v1 的场景，自动补全到 chat completions 端点。"""
        u = (url or "").strip()
        if not u:
            return u
        u = u.rstrip("/")
        lower = u.lower()
        if lower.endswith("/chat/completions"):
            return u
        if lower.endswith("/v1"):
            return u + "/chat/completions"
        if lower.endswith("/v1/chat"):
            return u + "/completions"
        return u + "/chat/completions"

    @staticmethod
    def _extract_json_object(raw: str) -> Optional[dict]:
        """从模型返回中提取 JSON 对象，兼容 ```json 代码块与前后文本。"""
        if not raw:
            return None
        text = raw.strip()
        try:
            obj = json.loads(text)
            return obj if isinstance(obj, dict) else None
        except Exception:
            pass

        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
        if m:
            try:
                obj = json.loads(m.group(1).strip())
                return obj if isinstance(obj, dict) else None
            except Exception:
                pass

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                obj = json.loads(text[start:end + 1].strip())
                return obj if isinstance(obj, dict) else None
            except Exception:
                return None
        return None

    def _inc_stat(self, key: str, delta: int = 1):
        with self._stats_lock:
            self.stats[key] = self.stats.get(key, 0) + delta

    def get_stats(self) -> Dict[str, int]:
        with self._stats_lock:
            return dict(self.stats)

    @staticmethod
    def _load_json(path: str, default) -> dict:
        """加载 JSON 文件，不存在则返回默认值"""
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError as e:
                logging.warning(f"JSON 文件解析失败 {path}: {e}")
                return default
        return default

    def _save_cache(self, force: bool = False):
        """保存缓存到文件，使用延迟写入策略"""
        with self._cache_lock:
            self._cache_dirty = True
            self._save_counter += 1

            if force or self._save_counter >= 20:
                try:
                    with open(self.cache_path, "w", encoding="utf-8") as f:
                        json.dump(self.cache, f, ensure_ascii=False, indent=2)
                    self._cache_dirty = False
                    self._save_counter = 0
                except IOError as e:
                    logger.error(f"缓存保存失败: {e}")

    def flush_cache(self):
        """强制保存缓存（程序退出或翻译完成时调用）"""
        if self._cache_dirty:
            self._save_cache(force=True)

    def _build_glossary_text(self) -> str:
        """构建术语表文本"""
        if not self.glossary:
            return "无术语表。"
        lines = []
        for k, v in self.glossary.items():
            if isinstance(v, dict):
                dst = str(v.get("dst", "")).strip()
                info = str(v.get("info", "")).strip()
                if dst and info:
                    lines.append(f"{k}->{dst} #{info}")
                elif dst:
                    lines.append(f"{k}->{dst}")
                else:
                    lines.append(f"{k} => {json.dumps(v, ensure_ascii=False)}")
            else:
                lines.append(f"{k} => {v}")
        return "\n".join(lines)

    def _call_deepseek(
        self,
        text: str,
        max_retries: int = 3,
        text_separator: Optional[str] = None,
    ) -> str:
        """调用模型 API，支持重试机制"""
        sep = text_separator or DEFAULT_TEXT_SEPARATOR
        is_batch = sep in text

        deepseek_prompt = """你是资深日文文学翻译专家，精通日中双语，擅长文学翻译。
【翻译原则】信、雅、达：
- 信：准确传达原文含义，不随意增删改，保持原作风格和情感基调
- 雅：译文文笔优美，符合中文表达习惯，避免生硬直译或翻译腔
- 达：语言流畅自然，通顺易懂，让读者沉浸在故事中
【日文特有表达处理】：
1. 敬语体系：将敬语转换为符合中文语境的表达，不必过度保留敬称
2. 姐さん/兄さん等称谓：根据角色关系，译为“姐姐/哥哥”或保留昵称风格
3. 委婉表达：日文的含蓄委婉可适当转化为更直接的中文表达，但要保留情感色彩
4. 语气词：よ、ね、さ等语气词不必逐字翻译，用自然的中文语气表达即可
5. 内心独白：保持第一人称叙述的连贯性，内心想法用括号或直接叙述

【文体风格】：
1. 小说对话：保持角色性格和语气，对话生动自然
2. 叙述描写：文笔优美，有文学质感，避免大白话
3. 专业术语：按术语表翻译，保持一致
4. 成语典故：可用恰当中文成语替代，但要自然不生硬
【输出要求】：
1. 输出仅为译文，不要解释或添加原文
2. 保持原文段落结构，不合并或拆分段落
3. 保留专有名词一致性（人名、地名、作品名等）
4. 标点符号使用中文规范"""

        sakura_prompt = """你是一个轻小说翻译模型，可以流畅通顺地使用给定术语表以指定格式从日文翻译到简体中文，并联系上下文正确使用人称代词，不擅自添加原文中没有的人名。
你必须按照以下规则执行：
1. 理解并严格遵循术语表格式与备注。
2. 仅输出译文，不输出说明。
3. 不改变段落数量与顺序。"""

        system_prompt = sakura_prompt if self.provider == "sakura" else deepseek_prompt
        if is_batch:
            system_prompt += f"""

【重要！多段落分隔规则】原文由多个独立段落组成，段落之间用'{sep.strip()}'分隔。
你必须在译文中保留相同数量的段落，且每个段落之间也必须用'{sep.strip()}'分隔。
绝对不能将多个段落合并为一个段落！
输出格式：译文1{sep.strip()}译文2{sep.strip()}译文3..."""

        user_prompt = (
            f"【术语表】\n{self._build_glossary_text()}\n\n"
            f"请将以下日文翻译为优美流畅的中文：\n{text}"
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
        }
        if self.top_p is not None:
            payload["top_p"] = self.top_p
        if self.frequency_penalty is not None:
            payload["frequency_penalty"] = self.frequency_penalty

        last_error = None
        for attempt in range(max_retries):
            if self.cancel_event.is_set():
                raise RuntimeError("翻译已取消")

            try:
                self._inc_stat("api_requests_total")
                resp = self.session.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                    timeout=120,
                )

                if resp.status_code == 429:
                    wait_time = 2 ** attempt + random.uniform(0, 1)
                    logger.warning(f"API 限流，等待 {wait_time:.1f} 秒后重试...")
                    if self.cancel_event.wait(wait_time):
                        raise RuntimeError("翻译已取消")
                    continue
                if resp.status_code == 502:
                    raise RuntimeError("翻译失败: HTTP 502 Bad Gateway（已按配置直接中断）")

                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()

            except requests.exceptions.Timeout:
                last_error = "请求超时"
                logger.warning(f"API 请求超时 (尝试 {attempt + 1}/{max_retries})")
            except requests.exceptions.ConnectionError:
                last_error = "网络连接失败"
                logger.warning(f"网络连接失败 (尝试 {attempt + 1}/{max_retries})")
            except requests.exceptions.HTTPError as e:
                last_error = f"HTTP 错误: {e}"
                logger.warning(f"HTTP 错误 (尝试 {attempt + 1}/{max_retries}): {e}")
            except (KeyError, IndexError) as e:
                last_error = f"API 响应格式错误: {e}"
                logger.error(f"API 响应格式错误: {e}")
                break
            except Exception as e:
                last_error = f"未知错误: {e}"
                logger.error(f"未知错误: {e}")

            if attempt < max_retries - 1:
                wait_time = 2 ** attempt + random.uniform(0, 1)
                if self.cancel_event.wait(wait_time):
                    raise RuntimeError("翻译已取消")

        raise RuntimeError(f"翻译失败: {last_error}")

    def _call_deepseek_batch_json(self, texts: List[str], max_retries: int = 2) -> Optional[Dict[str, object]]:
        """批量翻译：结构化返回 translations + new_terms。失败时返回 None。"""
        if not texts:
            return {"translations": [], "new_terms": []}

        numbered = [{"idx": i, "text": t} for i, t in enumerate(texts)]
        system_prompt = """你是日文到中文翻译助手。
请严格输出 JSON 对象，不要输出任何额外文字。
JSON 顶层字段：
1) "translations": 数组，长度必须与输入一致，索引顺序一致，元素格式 {"idx": 整数, "zh": "译文"}。
2) "new_terms": 数组，元素格式 {"src": "原词", "dst": "译词"}，没有则返回空数组。"""
        if not self.extract_glossary:
            system_prompt += '\n当未启用术语抽取时，必须返回 "new_terms": []。'
        else:
            system_prompt += """
术语抽取规则：
- 仅提取专有名词或固定术语（人名/地名/组织/招式/装备等）
- 不提取通用词、语气词、普通动词形容词
- 每批最多返回 5 条，宁缺毋滥"""
        user_prompt = (
            f"【术语表】\n{self._build_glossary_text()}\n\n"
            f"请翻译以下 JSON 数组中的 text 字段并返回 JSON：\n{json.dumps(numbered, ensure_ascii=False)}"
        )
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1 if self.provider == "deepseek" else self.temperature,
        }
        if self.top_p is not None:
            payload["top_p"] = self.top_p
        if self.frequency_penalty is not None:
            payload["frequency_penalty"] = self.frequency_penalty
        if self.provider == "deepseek":
            payload["response_format"] = {"type": "json_object"}

        for attempt in range(max_retries):
            if self.cancel_event.is_set():
                raise RuntimeError("翻译已取消")
            try:
                self._inc_stat("api_requests_total")
                resp = self.session.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                    timeout=120,
                )
                if resp.status_code == 429:
                    wait_time = 2 ** attempt + random.uniform(0, 1)
                    if self.cancel_event.wait(wait_time):
                        raise RuntimeError("翻译已取消")
                    continue
                if resp.status_code == 502:
                    raise RuntimeError("翻译失败: HTTP 502 Bad Gateway（已按配置直接中断）")
                resp.raise_for_status()
                data = resp.json()
                raw = data["choices"][0]["message"]["content"].strip()
                obj = self._extract_json_object(raw)
                if not isinstance(obj, dict):
                    self._inc_stat("batch_json_parse_fail")
                    return None
                arr = obj.get("translations") or obj.get("items")
                if not isinstance(arr, list) or len(arr) != len(texts):
                    self._inc_stat("batch_json_parse_fail")
                    return None

                out = [None] * len(texts)
                for item in arr:
                    if not isinstance(item, dict):
                        self._inc_stat("batch_json_parse_fail")
                        return None
                    idx = item.get("idx")
                    zh = item.get("zh")
                    if not isinstance(idx, int) or idx < 0 or idx >= len(texts) or not isinstance(zh, str):
                        self._inc_stat("batch_json_parse_fail")
                        return None
                    out[idx] = zh.strip()
                if any(v is None for v in out):
                    self._inc_stat("batch_json_parse_fail")
                    return None
                raw_terms = obj.get("new_terms", [])
                if not isinstance(raw_terms, list):
                    raw_terms = []
                return {"translations": out, "new_terms": raw_terms}
            except Exception:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt + random.uniform(0, 1)
                    if self.cancel_event.wait(wait_time):
                        raise RuntimeError("翻译已取消")
                    continue
                return None

        return None

    @staticmethod
    def _clean_new_terms(raw_terms: List[dict]) -> List[Tuple[str, str]]:
        """清洗术语：最短长度、排除通用词、去重。"""
        if not raw_terms:
            return []
        stop_words = {
            "我们", "你们", "他们", "这个", "那个", "这里", "那里", "然后", "但是", "因为", "所以",
            "可以", "不会", "已经", "正在", "没有", "非常", "真的", "老师", "学校", "城市", "国家",
            "魔法", "剑", "勇者", "魔王",
        }
        cleaned: List[Tuple[str, str]] = []
        seen = set()
        for item in raw_terms:
            if not isinstance(item, dict):
                continue
            src = str(item.get("src", "")).strip()
            dst = str(item.get("dst", "")).strip()
            if not src or not dst:
                continue
            if len(src) < 2 or len(dst) < 2:
                continue
            if src in stop_words or dst in stop_words:
                continue
            key = (src, dst)
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(key)
        return cleaned

    def _merge_new_terms_into_glossary(self, terms: List[Tuple[str, str]]) -> int:
        """增量写入 glossary.json（仅新增，不覆盖）。"""
        if not terms:
            return 0
        added = 0
        with self._cache_lock:
            for src, dst in terms:
                if src in self.glossary:
                    continue
                self.glossary[src] = dst
                added += 1
            if added > 0:
                try:
                    with open(self.glossary_path, "w", encoding="utf-8") as f:
                        json.dump(self.glossary, f, ensure_ascii=False, indent=2)
                except Exception as e:
                    logger.warning(f"术语表写入失败: {e}")
                    added = 0
        if added > 0:
            self._inc_stat("glossary_new_terms_added", added)
        return added

    def _translate_chunk(self, text: str) -> str:
        """翻译单个文本块（带缓存）"""
        text = text.strip()
        if not text:
            return text

        if self.cancel_event.is_set():
            raise RuntimeError("翻译已取消")

        with self._cache_lock:
            if text in self.cache:
                return self.cache[text]

        zh = self._call_deepseek(text)

        with self._cache_lock:
            self.cache[text] = zh

        self._save_cache()
        return zh

    @staticmethod
    def _smart_split_text(text: str, chunk_size: int) -> List[str]:
        """按段落+句子优先切分，尽量避免生硬按字符截断。"""
        text = text.strip()
        if not text:
            return []
        if len(text) <= chunk_size:
            return [text]

        paragraphs = [p for p in text.split("\n") if p]
        chunks: List[str] = []
        current = ""

        def flush_current():
            nonlocal current
            if current:
                chunks.append(current)
                current = ""

        for para in paragraphs:
            if len(para) > chunk_size:
                sentences = re.split(r"(?<=[。！？!?…])", para)
                for sentence in sentences:
                    sentence = sentence.strip()
                    if not sentence:
                        continue

                    if len(sentence) > chunk_size:
                        flush_current()
                        for i in range(0, len(sentence), chunk_size):
                            chunks.append(sentence[i:i + chunk_size])
                        continue

                    if not current:
                        current = sentence
                    elif len(current) + 1 + len(sentence) <= chunk_size:
                        current += "\n" + sentence
                    else:
                        flush_current()
                        current = sentence
                continue

            if not current:
                current = para
            elif len(current) + 1 + len(para) <= chunk_size:
                current += "\n" + para
            else:
                flush_current()
                current = para

        flush_current()
        return chunks

    def translate(self, text: str, chunk_size: int = 1200) -> str:
        """翻译文本，支持缓存和长文本分块"""
        text = text.strip()
        if not text:
            return text

        with self._cache_lock:
            if text in self.cache:
                return self.cache[text]

        if len(text) <= chunk_size:
            zh = self._call_deepseek(text)
        else:
            chunks = self._smart_split_text(text, chunk_size)
            with ThreadPoolExecutor(max_workers=min(self.max_workers, len(chunks))) as executor:
                futures = {executor.submit(self._translate_chunk, c): i for i, c in enumerate(chunks)}
                results = [None] * len(chunks)
                for future in as_completed(futures):
                    idx = futures[future]
                    results[idx] = future.result()

            zh = "\n".join(results).strip()

        with self._cache_lock:
            self.cache[text] = zh
        self._save_cache()
        return zh

    def translate_batch(
        self,
        texts: List[str],
        progress_callback: Optional[Callable[[int, int], None]] = None,
        batch_size: int = 4,
    ) -> Dict[str, str]:
        """并发批量翻译多个文本"""
        results: Dict[str, str] = {}
        total = len(texts)
        completed = 0

        uncached_unique: List[str] = []
        seen_uncached = set()

        with self._cache_lock:
            for text in texts:
                if text in self.cache:
                    results[text] = self.cache[text]
                    completed += 1
                elif text not in seen_uncached:
                    uncached_unique.append(text)
                    seen_uncached.add(text)

        logger.info(f"批量翻译: {total} 条，缓存命中 {completed} 条，待翻译去重后 {len(uncached_unique)} 条")

        if progress_callback:
            progress_callback(completed, total)

        if not uncached_unique:
            return results

        batches = []
        current_batch = []
        current_length = 0
        max_batch_length = 800

        for text in uncached_unique:
            if len(text) <= 200 and current_length + len(text) < max_batch_length and len(current_batch) < batch_size:
                current_batch.append(text)
                current_length += len(text)
            else:
                if current_batch:
                    batches.append(current_batch)
                if len(text) <= 200:
                    current_batch = [text]
                    current_length = len(text)
                else:
                    batches.append([text])
                    current_batch = []
                    current_length = 0

        if current_batch:
            batches.append(current_batch)

        logger.info(f"合并为 {len(batches)} 个批次进行并发翻译")
        mismatch_count = 0

        def translate_one_batch(batch: List[str]) -> List[Tuple[str, str]]:
            nonlocal mismatch_count
            if self.cancel_event.is_set():
                raise RuntimeError("翻译已取消")

            if len(batch) == 1:
                text = batch[0]
                zh = self._translate_chunk(text)
                return [(text, zh)]

            self._inc_stat("batch_total")
            # 优先使用结构化 JSON 返回，减少分割符丢失导致的拆分失败。
            payload = self._call_deepseek_batch_json(batch)
            if payload and isinstance(payload, dict):
                json_parts = payload.get("translations", [])
                if isinstance(json_parts, list) and len(json_parts) == len(batch):
                    if self.extract_glossary:
                        raw_terms = payload.get("new_terms", [])
                        cleaned_terms = self._clean_new_terms(raw_terms if isinstance(raw_terms, list) else [])
                        self._merge_new_terms_into_glossary(cleaned_terms)
                    self._inc_stat("batch_json_success")
                    return list(zip(batch, json_parts))

            if payload and not isinstance(payload, dict):
                json_parts = payload
            else:
                json_parts = None
            if json_parts and len(json_parts) == len(batch):
                self._inc_stat("batch_json_success")
                return list(zip(batch, json_parts))

            separator = f"\n---SPLIT-{uuid.uuid4().hex}---\n"
            combined = separator.join(batch)
            combined_zh = self._call_deepseek(combined, text_separator=separator)
            parts = combined_zh.split(separator)

            if len(parts) != len(batch):
                with self._cache_lock:
                    mismatch_count += 1
                self._inc_stat("batch_fallback")
                self._inc_stat("batch_split_mismatch")
                return [(t, self._translate_chunk(t)) for t in batch]

            self._inc_stat("batch_delimiter_success")
            return list(zip(batch, parts))

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(translate_one_batch, batch): batch for batch in batches}

            for future in as_completed(futures):
                if self.cancel_event.is_set():
                    for f in futures:
                        f.cancel()
                    raise RuntimeError("翻译已取消")

                try:
                    batch_results = future.result()
                    for original, translated in batch_results:
                        results[original] = translated
                        completed += 1
                        if progress_callback:
                            progress_callback(completed, total)
                except Exception as e:
                    logger.error(f"批次翻译失败: {e}")
                    if "502" in str(e):
                        raise
                    batch = futures[future]
                    for text in batch:
                        if self.cancel_event.is_set():
                            raise RuntimeError("翻译已取消")
                        try:
                            zh = self._translate_chunk(text)
                            results[text] = zh
                        except Exception as e2:
                            logger.error(f"翻译失败: {e2}")
                            results[text] = text
                        completed += 1
                        if progress_callback:
                            progress_callback(completed, total)

        self._save_cache(force=True)
        if mismatch_count:
            logger.warning(f"批量拆分回退 {mismatch_count} 次（模型输出与批次数不一致，已自动逐条翻译）")

        for text in texts:
            if text not in results:
                with self._cache_lock:
                    cached = self.cache.get(text)
                if cached is not None:
                    results[text] = cached

        return results

    def __del__(self):
        """析构时保存缓存"""
        try:
            self.flush_cache()
            self.session.close()
        except Exception:
            pass
