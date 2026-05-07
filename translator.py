import json
import logging
import os
import threading
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, List, Dict, Tuple

import requests

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

# 分隔符，用于合并多个短文本
TEXT_SEPARATOR = "\n---SPLIT---\n"


def get_data_dir() -> Path:
    """获取用户数据目录，用于存储缓存和配置"""
    data_dir = Path.home() / ".epub_translator"
    data_dir.mkdir(exist_ok=True)
    return data_dir


class JaZhTranslator:
    def __init__(
        self,
        api_key: Optional[str] = None,
        glossary_path: Optional[str] = None,
        cache_path: Optional[str] = None,
        max_workers: int = 5,
    ):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError("未找到 DeepSeek API Key，请在界面输入或设置环境变量 DEEPSEEK_API_KEY")

        # 使用用户数据目录存储缓存
        data_dir = get_data_dir()
        self.glossary_path = glossary_path or str(data_dir / "glossary.json")
        self.cache_path = cache_path or str(data_dir / "cache.json")

        self.glossary = self._load_json(self.glossary_path, {})
        self.cache = self._load_json(self.cache_path, {})
        self._cache_dirty = False
        self._save_counter = 0
        self._cache_lock = threading.Lock()  # 缓存线程锁

        self.max_workers = max_workers  # 并发线程数

        logger.info(f"翻译器初始化完成，并发数: {max_workers}")

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
        with self._cache_lock:
            if self._cache_dirty:
                self._save_cache(force=True)

    def _build_glossary_text(self) -> str:
        """构建术语表文本"""
        if not self.glossary:
            return "无术语表。"
        lines = [f"{k} => {v}" for k, v in self.glossary.items()]
        return "\n".join(lines)

    def _call_deepseek(self, text: str, max_retries: int = 3) -> str:
        """调用 DeepSeek API，支持重试机制"""
        # 检查是否是合并文本
        is_batch = TEXT_SEPARATOR in text

        system_prompt = """你是资深日文文学翻译专家，精通日中双语，擅长文学翻译。

【翻译原则】信、雅、达：
- 信：准确传达原文含义，不随意增删改，保持原作风格和情感基调
- 雅：译文文笔优美，符合中文表达习惯，避免生硬直译或翻译腔
- 达：语言流畅自然，通顺易懂，让读者沉浸在故事中

【日文特有表达处理】：
1. 敬语体系：将敬语转换为符合中文语境的表达，不必过度保留敬称
2. 姉ちゃん/兄ちゃん等称呼：根据角色关系，译为"姐姐/哥哥"或保留昵称风格
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

        if is_batch:
            system_prompt += f"""

【重要！多段落分隔规则】
原文由多个独立段落组成，段落之间用'{TEXT_SEPARATOR.strip()}'分隔。
你必须在译文中保留相同数量的段落，且每个段落之间也必须用'{TEXT_SEPARATOR.strip()}'分隔。
绝对不能将多个段落合并为一个段落！
输出格式：译文1{TEXT_SEPARATOR.strip()}译文2{TEXT_SEPARATOR.strip()}译文3..."""

        user_prompt = (
            f"【术语表】\n{self._build_glossary_text()}\n\n"
            f"请将以下日文翻译为优美流畅的中文：\n{text}"
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
        }

        last_error = None
        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    DEEPSEEK_API_URL,
                    headers=headers,
                    json=payload,
                    timeout=120
                )

                # 处理速率限制
                if resp.status_code == 429:
                    wait_time = 2 ** attempt + random.uniform(0, 1)
                    logger.warning(f"API 限流，等待 {wait_time:.1f} 秒后重试...")
                    time.sleep(wait_time)
                    continue

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
                time.sleep(wait_time)

        raise RuntimeError(f"翻译失败: {last_error}")

    def _translate_chunk(self, text: str) -> str:
        """翻译单个文本块（带缓存）"""
        text = text.strip()
        if not text:
            return text

        # 检查缓存
        with self._cache_lock:
            if text in self.cache:
                return self.cache[text]

        zh = self._call_deepseek(text)

        # 存入缓存
        with self._cache_lock:
            self.cache[text] = zh

        self._save_cache()
        return zh

    def translate(self, text: str, chunk_size: int = 1200) -> str:
        """翻译文本，支持缓存和长文本分块"""
        text = text.strip()
        if not text:
            return text

        # 检查缓存
        with self._cache_lock:
            if text in self.cache:
                return self.cache[text]

        # 分块处理长文本
        if len(text) <= chunk_size:
            zh = self._call_deepseek(text)
        else:
            paragraphs = text.split('\n')
            chunks = []
            current_chunk = ""

            for para in paragraphs:
                if len(current_chunk) + len(para) + 1 <= chunk_size:
                    current_chunk += ('\n' if current_chunk else '') + para
                else:
                    if current_chunk:
                        chunks.append(current_chunk)
                    if len(para) > chunk_size:
                        for i in range(0, len(para), chunk_size):
                            chunks.append(para[i:i + chunk_size])
                    else:
                        current_chunk = para

            if current_chunk:
                chunks.append(current_chunk)

            # 并发翻译长文本的各个分块
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
        progress_callback=None,
        batch_size: int = 4
    ) -> Dict[str, str]:
        """
        并发批量翻译多个文本

        Args:
            texts: 待翻译文本列表
            progress_callback: 进度回调函数 (completed, total)
            batch_size: 单次 API 合并的文本数量（短文本合并）

        Returns:
            {原文: 译文} 字典
        """
        results = {}
        total = len(texts)
        completed = 0

        # 分离已缓存和未缓存的文本
        uncached = []
        with self._cache_lock:
            for text in texts:
                if text in self.cache:
                    results[text] = self.cache[text]
                    completed += 1
                else:
                    uncached.append(text)

        logger.info(f"批量翻译: {total} 条，缓存命中 {completed} 条，待翻译 {len(uncached)} 条")

        if progress_callback:
            progress_callback(completed, total)

        if not uncached:
            return results

        # 将短文本合并成批次，减少 API 调用次数
        batches = []
        current_batch = []
        current_length = 0
        max_batch_length = 800  # 合并后最大长度

        for text in uncached:
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
                    # 长文本单独处理
                    batches.append([text])
                    current_batch = []
                    current_length = 0

        if current_batch:
            batches.append(current_batch)

        logger.info(f"合并为 {len(batches)} 个批次进行并发翻译")

        # 并发翻译各批次
        def translate_batch(batch: List[str]) -> List[Tuple[str, str]]:
            """翻译一个批次"""
            if len(batch) == 1:
                text = batch[0]
                zh = self._translate_chunk(text)
                return [(text, zh)]
            else:
                # 合并多个短文本
                combined = TEXT_SEPARATOR.join(batch)
                combined_zh = self._translate_chunk(combined)
                parts = combined_zh.split(TEXT_SEPARATOR)

                # 确保分割数量匹配
                if len(parts) != len(batch):
                    logger.warning(f"分割数量不匹配: {len(parts)} vs {len(batch)}，回退逐条翻译")
                    return [(t, self._translate_chunk(t)) for t in batch]

                return list(zip(batch, parts))

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(translate_batch, batch): batch for batch in batches}

            for future in as_completed(futures):
                try:
                    batch_results = future.result()
                    for original, translated in batch_results:
                        results[original] = translated
                        completed += 1
                        if progress_callback:
                            progress_callback(completed, total)
                except Exception as e:
                    logger.error(f"批次翻译失败: {e}")
                    # 回退：逐条翻译失败的批次
                    batch = futures[future]
                    for text in batch:
                        try:
                            zh = self._translate_chunk(text)
                            results[text] = zh
                        except Exception as e2:
                            logger.error(f"翻译失败: {e2}")
                            results[text] = text  # 保留原文
                        completed += 1
                        if progress_callback:
                            progress_callback(completed, total)

        self._save_cache(force=True)
        return results

    def __del__(self):
        """析构时保存缓存"""
        try:
            self.flush_cache()
        except Exception:
            pass
