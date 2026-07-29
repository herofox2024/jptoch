"""Conservative latency-based tuning for translation request pressure."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from statistics import mean
from typing import Deque, Tuple


@dataclass(frozen=True)
class AdaptiveDecision:
    action: str
    workers: int
    batch_size: int
    average_latency_ms: int
    average_request_batch_size: int
    sample_count: int
    reason: str = ""


class AdaptiveRequestController:
    """Suggest small pressure changes after enough comparable successes.

    HTTP errors still belong to the translator's immediate limiter. This
    controller only handles successful main-translation requests so auxiliary
    operations with different latency profiles cannot distort its decisions.
    """

    def __init__(
        self,
        *,
        window_size: int = 24,
        slow_sample_count: int = 8,
        recovery_sample_count: int = 16,
    ) -> None:
        self.window_size = max(8, int(window_size))
        self.slow_sample_count = max(4, int(slow_sample_count))
        self.recovery_sample_count = max(self.slow_sample_count, int(recovery_sample_count))
        self._samples: Deque[Tuple[float, int]] = deque(maxlen=self.window_size)

    def record_failure(self) -> None:
        """Require a new stable window after an immediate error downgrade."""
        self._samples.clear()

    def snapshot(self) -> tuple[int, int, int]:
        samples = len(self._samples)
        average_ms = int(mean(value[0] for value in self._samples) * 1000) if samples else 0
        average_batch = int(round(mean(value[1] for value in self._samples))) if samples else 0
        return samples, average_ms, average_batch

    def observe_success(
        self,
        elapsed_seconds: float,
        *,
        current_workers: int,
        current_batch_size: int,
        max_workers: int,
        max_batch_size: int,
        slow_threshold_seconds: float,
        request_batch_size: int = 1,
    ) -> AdaptiveDecision:
        elapsed = max(0.001, float(elapsed_seconds))
        max_workers = max(1, int(max_workers))
        max_batch_size = max(1, int(max_batch_size))
        workers = max(1, min(int(current_workers), max_workers))
        batch_size = max(1, min(int(current_batch_size), max_batch_size))
        slow_threshold = max(10.0, float(slow_threshold_seconds))
        self._samples.append((elapsed, max(1, int(request_batch_size))))

        samples, average_ms, average_batch = self.snapshot()
        recent_slow = sum(value[0] >= slow_threshold for value in self._samples)
        slow_ratio = recent_slow / samples if samples else 0.0

        if samples >= self.slow_sample_count and (
            average_ms >= int(slow_threshold * 1000) or slow_ratio >= 0.5
        ):
            new_workers = workers
            new_batch = batch_size
            if batch_size > 1:
                new_batch -= 1
            elif workers > 1:
                new_workers -= 1
            if (new_workers, new_batch) != (workers, batch_size):
                self._samples.clear()
                return AdaptiveDecision(
                    "down",
                    new_workers,
                    new_batch,
                    average_ms,
                    average_batch,
                    samples,
                    "rolling latency is above the stable threshold",
                )

        fast_threshold = slow_threshold * 0.6
        stable_fast = (
            samples >= self.recovery_sample_count
            and average_ms <= int(fast_threshold * 1000)
            and recent_slow == 0
        )
        if stable_fast and (workers < max_workers or batch_size < max_batch_size):
            new_workers = workers
            new_batch = batch_size
            if batch_size < max_batch_size:
                new_batch += 1
            elif workers < max_workers:
                new_workers += 1
            self._samples.clear()
            return AdaptiveDecision(
                "up",
                new_workers,
                new_batch,
                average_ms,
                average_batch,
                samples,
                "stable low-latency success window",
            )

        return AdaptiveDecision("none", workers, batch_size, average_ms, average_batch, samples)
