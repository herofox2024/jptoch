import unittest

from translation_adaptive import AdaptiveRequestController
from tests.test_translation_pipeline import DummyTranslator


class AdaptiveRequestControllerTests(unittest.TestCase):
    def test_fast_stable_window_recovers_batch_then_workers(self):
        controller = AdaptiveRequestController(recovery_sample_count=8)
        decision = None
        for _ in range(8):
            decision = controller.observe_success(
                2.0,
                current_workers=2,
                current_batch_size=2,
                max_workers=4,
                max_batch_size=4,
                slow_threshold_seconds=15,
                request_batch_size=2,
            )
        self.assertIsNotNone(decision)
        self.assertEqual(decision.action, "up")
        self.assertEqual((decision.workers, decision.batch_size), (2, 3))

    def test_slow_window_reduces_batch_before_workers(self):
        controller = AdaptiveRequestController(slow_sample_count=4, recovery_sample_count=8)
        decision = None
        for _ in range(4):
            decision = controller.observe_success(
                35.0,
                current_workers=4,
                current_batch_size=4,
                max_workers=6,
                max_batch_size=8,
                slow_threshold_seconds=30,
                request_batch_size=4,
            )
        self.assertEqual(decision.action, "down")
        self.assertEqual((decision.workers, decision.batch_size), (4, 3))

    def test_too_few_samples_do_not_change_limits(self):
        controller = AdaptiveRequestController()
        for _ in range(3):
            decision = controller.observe_success(
                60.0,
                current_workers=4,
                current_batch_size=4,
                max_workers=4,
                max_batch_size=4,
                slow_threshold_seconds=30,
                request_batch_size=4,
            )
        self.assertEqual(decision.action, "none")
        self.assertEqual((decision.workers, decision.batch_size), (4, 4))

    def test_failure_discards_previous_recovery_samples(self):
        controller = AdaptiveRequestController(recovery_sample_count=8)
        for _ in range(7):
            controller.observe_success(
                1.0,
                current_workers=2,
                current_batch_size=2,
                max_workers=4,
                max_batch_size=4,
                slow_threshold_seconds=15,
                request_batch_size=2,
            )
        controller.record_failure()
        decision = controller.observe_success(
            1.0,
            current_workers=2,
            current_batch_size=2,
            max_workers=4,
            max_batch_size=4,
            slow_threshold_seconds=15,
            request_batch_size=2,
        )
        self.assertEqual(decision.action, "none")
        self.assertEqual(decision.sample_count, 1)
        self.assertEqual(decision.average_request_batch_size, 2)


class TranslatorAdaptiveIntegrationTests(unittest.TestCase):
    def test_timed_success_updates_adaptive_stats(self):
        translator = DummyTranslator()
        for _ in range(8):
            translator._record_api_success_event(
                40.0,
                batch_size=4,
                context="translate_batch",
            )
        self.assertEqual(translator._current_dynamic_batch_size(), 3)
        self.assertEqual(translator.stats["adaptive_adjust_down"], 1)
        self.assertGreater(translator.stats["adaptive_latency_ms"], 0)
        self.assertEqual(translator.stats["adaptive_request_batch_size"], 4)

    def test_rate_limit_still_reduces_immediately(self):
        translator = DummyTranslator()
        translator.max_workers = 6
        translator.batch_size = 6
        translator._dynamic_max_workers = 6
        translator._dynamic_batch_size = 6
        translator._dynamic_batch_ceiling = 6
        translator._record_dynamic_limit_event("HTTP 429", kind="rate")
        self.assertLess(translator._current_dynamic_workers(), 6)
        self.assertLess(translator._current_dynamic_batch_size(), 6)
        self.assertEqual(translator.stats["rate_limit_events"], 1)

    def test_hymt2_cpu_limits_cannot_expand(self):
        translator = DummyTranslator()
        translator.provider = "hymt2"
        translator.hymt2_runtime_mode = "cpu"
        translator.max_workers = 1
        translator.batch_size = 1
        translator._dynamic_max_workers = 1
        translator._dynamic_batch_size = 1
        translator._dynamic_batch_ceiling = 1
        for _ in range(20):
            translator._record_api_success_event(
                1.0,
                batch_size=1,
                context="translate_single",
            )
        self.assertEqual(translator._current_dynamic_workers(), 1)
        self.assertEqual(translator._current_dynamic_batch_size(), 1)
        self.assertEqual(translator.stats.get("adaptive_adjust_up", 0), 0)


if __name__ == "__main__":
    unittest.main()
