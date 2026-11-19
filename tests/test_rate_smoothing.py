"""限流平滑发送测试。

背景（实测《黄金色的祈祷》3455 段）：
  总耗时 532 秒，其中 284 秒（53.5%）在限流等待；
  请求速率利用率只有 92%，配额并没满，只是「并发同时到期」导致集中撞墙。
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from translator import JaZhTranslator


def _make_translator(rpm=36, tpm=120000):
    """Create a minimal translator with only the rate-limit state initialised."""
    t = JaZhTranslator.__new__(JaZhTranslator)
    t.provider = "deepseek"
    t._provider_rpm_limit = rpm
    t._provider_tpm_limit = tpm
    t._provider_rate_lock = threading.RLock()
    from collections import deque

    t._provider_rate_requests = deque()
    t._provider_rate_tokens = deque()
    t._provider_last_send_ts = 0.0
    t._rate_wait_until = 0.0
    t._rate_wait_seconds = 0.0
    t._rate_wait_context = ""
    t.cancel_event = threading.Event()
    return t


# ---------- 平滑发送 ----------


def test_first_request_is_not_delayed():
    """第一个请求应立即放行，不能因为初始状态就等待。"""
    t = _make_translator()
    start = time.time()
    t._wait_provider_rate_budget(estimated_tokens=100, context="test")
    assert time.time() - start < 0.15, "首个请求不应等待"


def test_consecutive_requests_are_spaced():
    """连续请求之间要按 60/rpm 的间隔铺开，而不是一起放行。"""
    # rpm=60 → 每秒一个请求；检测间隔是否接近 1 秒
    t = _make_translator(rpm=60)
    t._wait_provider_rate_budget(estimated_tokens=100, context="a")
    started = time.time()
    t._wait_provider_rate_budget(estimated_tokens=100, context="b")
    elapsed = time.time() - started
    assert 0.8 <= elapsed <= 1.4, f"应间隔约 1 秒，实际 {elapsed:.2f}s"


def test_spacing_prevents_window_overflow():
    """平滑发送后，一整轮 rpm 次请求不应触发长时间等待。

    这是核心回归点：旧实现下并发线程同时到期，会在窗口末尾一起撞墙，
    单次等待可达 40 秒以上。
    """
    rpm = 30
    t = _make_translator(rpm=rpm)
    t.RATE_WINDOW_SECONDS = 2.0  # 缩短窗口，让测试快一些

    started = time.time()
    waits = []
    for _ in range(rpm):
        before = time.time()
        t._wait_provider_rate_budget(estimated_tokens=10, context="loop")
        waits.append(time.time() - before)
    total = time.time() - started

    # 30 个请求按 2/30 秒间隔铺开 → 约 2 秒
    assert total < 4.0, f"30 个请求耗时过长: {total:.2f}s"
    # 不能出现单次几十秒的集中等待
    assert max(waits) < 1.0, f"出现异常长等待: {max(waits):.2f}s"


def test_tokens_still_counted():
    """平滑发送不能绕过 token 统计。"""
    t = _make_translator(rpm=600, tpm=120000)
    t._wait_provider_rate_budget(estimated_tokens=500, context="x")
    assert sum(tokens for _, tokens in t._provider_rate_tokens) == 500


# ---------- 等待状态上报 ----------


def test_rate_wait_info_is_idle_by_default():
    t = _make_translator()
    info = t.get_rate_wait_info()
    assert info["waiting"] is False
    assert info["remaining"] == 0.0


def test_rate_wait_status_is_recorded():
    """限流等待时要记录状态，供界面显示「正在等配额」。"""
    t = _make_translator()
    t._set_rate_wait_status(5.0, "批量JSON翻译")
    info = t.get_rate_wait_info()
    assert info["waiting"] is True
    assert 4.0 <= info["remaining"] <= 5.1
    assert info["context"] == "批量JSON翻译"


def test_rate_wait_status_expires():
    """等待结束后状态要自动失效，不能一直显示「等待中」。"""
    t = _make_translator()
    t._set_rate_wait_status(0.2, "短等待")
    time.sleep(0.35)
    info = t.get_rate_wait_info()
    assert info["waiting"] is False


# ---------- 无配额时不干预 ----------


def test_no_limit_means_no_delay():
    """没有配置 rpm/tpm 的 provider 不应被节流。"""
    t = _make_translator(rpm=0, tpm=0)
    started = time.time()
    for _ in range(10):
        t._wait_provider_rate_budget(estimated_tokens=100, context="x")
    assert time.time() - started < 0.2, "无配额时不应有任何等待"


# ---------- 并发配置 ----------


def test_deepseek_concurrency_reduced():
    """并发从 6 降到 4：batch_size 已由大书模式提到 12，6 并发属于过剩。"""
    from provider_registry import PROVIDER_DEFAULTS

    deepseek = PROVIDER_DEFAULTS["deepseek"]
    assert deepseek.max_workers <= 4, (
        f"deepseek 并发偏高（{deepseek.max_workers}），会持续撞 rpm 上限"
    )
    assert deepseek.rpm == 36
