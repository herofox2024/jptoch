from __future__ import annotations

import unittest

import requests

import translation_models
from translation_async_http import HttpxResponseAdapter
from translation_batching import smart_batch_task_keys, smart_batch_texts, smart_split_text
from translation_json_parser import extract_json_object, extract_lenient_indexed_items
from translator import (
    BatchJsonResult,
    ContentModerationError,
    FastFailError,
    JaZhTranslator,
    SingleChunkResult,
    TranslationIncompleteError,
)
from experimental.qml_v4.backend.recovery_agent import RecoveryAgent
from experimental.qml_v4.backend.recovery_classifier import classify_failed_detail, classify_recovery_issue
from experimental.qml_v4.backend.recovery_executor import RecoveryExecutor
from translation_models import RecoveryAction, RecoveryDecision, RecoveryExecutionResult, RecoveryIssue, RecoveryIssueType


class TranslationArchitectureTests(unittest.TestCase):
    def test_translator_keeps_public_result_and_error_exports(self):
        self.assertIs(SingleChunkResult, translation_models.SingleChunkResult)
        self.assertIs(BatchJsonResult, translation_models.BatchJsonResult)
        self.assertIs(FastFailError, translation_models.FastFailError)
        self.assertIs(ContentModerationError, translation_models.ContentModerationError)
        self.assertIs(TranslationIncompleteError, translation_models.TranslationIncompleteError)

    def test_recovery_issue_has_stable_model_selected_fields(self):
        issue = classify_recovery_issue(
            original="她は笑った。",
            translation="她笑了でも。",
            provider="deepseek",
            model="deepseek-v4-flash",
            attempts=2,
            context_before="上一段",
            context_after="下一段",
        )

        assert isinstance(issue, RecoveryIssue)
        assert issue.issue_type == RecoveryIssueType.JAPANESE_RESIDUE_MEDIUM.value
        assert issue.to_dict()["provider"] == "deepseek"
        assert issue.to_dict()["model"] == "deepseek-v4-flash"
        assert issue.to_dict()["attempts"] == 2
        assert RecoveryIssue.from_dict(issue.to_dict()) == issue

    def test_recovery_classifier_prioritizes_transport_and_format_errors(self):
        moderation = classify_recovery_issue(
            original="敏感原文",
            reason="security_audit_fail",
            provider="longcat",
            model="LongCat-2.0",
        )
        timeout = classify_recovery_issue(original="原文", reason="read timed out")
        parse_error = classify_recovery_issue(original="原文", error=ValueError("invalid JSON"))
        glossary = classify_recovery_issue(original="原文", reason="术语不一致")

        assert moderation.issue_type == RecoveryIssueType.CONTENT_MODERATION.value
        assert timeout.issue_type == RecoveryIssueType.TIMEOUT.value
        assert parse_error.issue_type == RecoveryIssueType.JSON_PARSE_ERROR.value
        assert glossary.issue_type == RecoveryIssueType.GLOSSARY_CONFLICT.value

    def test_recovery_classifier_converts_residue_detail(self):
        issue = classify_failed_detail(
            {
                "original": "她笑了。",
                "translated": "她笑了でも。",
                "fragments": ["でも"],
                "reason": "译文疑似仍有日文残留",
            },
            provider="longcat",
            model="LongCat-2.0",
        )

        assert issue.issue_type == RecoveryIssueType.JAPANESE_RESIDUE_MEDIUM.value
        assert issue.fragments == ["でも"]

    def test_recovery_agent_routes_to_issue_model_and_contains_no_api_key(self):
        issue = RecoveryIssue(
            issue_type=RecoveryIssueType.JAPANESE_RESIDUE_MEDIUM.value,
            original="原文",
            translation="译文でも",
            provider="deepseek",
            model="deepseek-v4-flash",
        )
        request = RecoveryAgent().build_request(issue)

        assert request["provider"] == "deepseek"
        assert request["model"] == "deepseek-v4-flash"
        assert "api_key" not in request
        assert "deepseek-v4-flash" not in request["messages"][0]["content"]
        assert "原文" in request["messages"][1]["content"]

    def test_recovery_agent_rejects_invalid_or_unsafe_decisions(self):
        issue = RecoveryIssue(
            issue_type=RecoveryIssueType.JAPANESE_RESIDUE_HIGH.value,
            provider="longcat",
            model="LongCat-2.0",
        )
        agent = RecoveryAgent(enabled=True, min_confidence=0.85)

        invalid = agent.parse_response('{"action":"run_code","confidence":1}', issue)
        low_confidence = agent.parse_response(
            '{"action":"RETRANSLATE","confidence":0.2,"provider":"longcat","model":"LongCat-2.0"}',
            issue,
        )

        assert invalid.action == RecoveryAction.REQUIRE_USER_REVIEW.value
        assert low_confidence.action == RecoveryAction.REQUIRE_USER_REVIEW.value

    def test_recovery_agent_only_allows_configured_fallback_model(self):
        issue = RecoveryIssue(
            issue_type=RecoveryIssueType.JAPANESE_RESIDUE_MEDIUM.value,
            provider="longcat",
            model="LongCat-2.0",
        )
        agent = RecoveryAgent(
            enabled=True,
            fallback_provider="deepseek",
            fallback_model="deepseek-v4-flash",
        )
        unsafe = agent.parse_response(
            '{"action":"USE_FALLBACK_PROVIDER","confidence":0.95,"provider":"glm","model":"glm-4-flash"}',
            issue,
        )
        safe = agent.parse_response(
            '{"action":"USE_FALLBACK_PROVIDER","confidence":0.95,"provider":"deepseek","model":"deepseek-v4-flash"}',
            issue,
        )

        assert unsafe.action == RecoveryAction.REQUIRE_USER_REVIEW.value
        assert safe.action == RecoveryAction.USE_FALLBACK_PROVIDER.value

    def test_recovery_agent_calls_executor_once_and_blocks_moderation_retry(self):
        calls = []

        def executor(request):
            calls.append(request)
            return {
                "action": "RETRANSLATE",
                "reason": "retry",
                "confidence": 0.99,
                "provider": "longcat",
                "model": "LongCat-2.0",
            }

        issue = RecoveryIssue(
            issue_type=RecoveryIssueType.CONTENT_MODERATION.value,
            original="原文",
            provider="longcat",
            model="LongCat-2.0",
        )
        decision = RecoveryAgent(enabled=True, request_executor=executor).decide(issue)

        assert len(calls) == 1
        assert decision.action == RecoveryAction.REQUIRE_USER_REVIEW.value
        assert "内容审核" in decision.reason

    def test_disabled_recovery_agent_never_calls_executor(self):
        calls = []
        issue = RecoveryIssue(issue_type=RecoveryIssueType.EMPTY_RESPONSE.value)
        decision = RecoveryAgent(
            enabled=False,
            request_executor=lambda request: calls.append(request),
        ).decide(issue)

        assert calls == []
        assert isinstance(decision, RecoveryDecision)
        assert decision.action == RecoveryAction.REQUIRE_USER_REVIEW.value

    def test_recovery_executor_retranslates_one_block_and_limits_attempts(self):
        class FakeTranslator:
            def __init__(self):
                self.calls = []

            def translate_batch(self, texts, **kwargs):
                self.calls.append((list(texts), kwargs))
                return {texts[0]: "安全译文"}

            @staticmethod
            def _is_incomplete_translation(_source, translation):
                return not bool(translation)

        issue = RecoveryIssue(
            issue_type=RecoveryIssueType.EMPTY_RESPONSE.value,
            original="原文",
            attempts=0,
        )
        decision = RecoveryDecision(
            action=RecoveryAction.RETRANSLATE.value,
            confidence=0.95,
            provider="deepseek",
            model="deepseek-v4-flash",
        )
        translator = FakeTranslator()
        result = RecoveryExecutor(max_attempts=2).execute(issue, decision, translator)
        blocked = RecoveryExecutor(max_attempts=2).execute(
            RecoveryIssue(**{**issue.__dict__, "attempts": 2}), decision, translator
        )

        assert isinstance(result, RecoveryExecutionResult)
        assert result.status == "success"
        assert result.translation == "安全译文"
        assert translator.calls == [(["原文"], {"batch_size": 1})]
        assert blocked.status == "needs_review"
        assert "最大恢复次数" in blocked.reason

    def test_recovery_executor_applies_deterministic_repair_without_api(self):
        class FakeTranslator:
            @staticmethod
            def _is_incomplete_translation(_source, translation):
                return "でも" in translation

        issue = RecoveryIssue(
            issue_type=RecoveryIssueType.JAPANESE_RESIDUE_MEDIUM.value,
            original="原文",
            translation="为了阿清，我でも想回到江户。",
        )
        decision = RecoveryDecision(
            action=RecoveryAction.APPLY_TERM_REPAIR.value,
            confidence=0.95,
        )

        result = RecoveryExecutor().execute(issue, decision, FakeTranslator())

        assert result.status == "success"
        assert "でも" not in result.translation

    def test_json_parser_handles_fenced_object_and_translation_array(self):
        fenced = '说明\n```json\n{"translations":[{"idx":0,"zh":"她笑了。"}]}\n```'
        self.assertEqual(
            extract_json_object(fenced),
            {"translations": [{"idx": 0, "zh": "她笑了。"}]},
        )
        self.assertEqual(
            extract_json_object('["第一条", "第二条"]'),
            {"translations": ["第一条", "第二条"], "new_terms": []},
        )

    def test_json_parser_distinguishes_glossary_array(self):
        raw = '[{"original":"黒猫","translation":"黑猫","category":"其他"}]'
        self.assertEqual(
            extract_json_object(raw, prefer_new_terms=True),
            {
                "new_terms": [
                    {"original": "黒猫", "translation": "黑猫", "category": "其他"}
                ]
            },
        )

    def test_lenient_parser_recovers_unescaped_quotes(self):
        raw = (
            '{"items":['
            '{"idx":0,"zh":"她说"你好"。"},'
            '{"idx":1,"zh":"结束。"}'
            ']}'
        )
        self.assertEqual(
            extract_lenient_indexed_items(raw),
            [
                {"idx": 0, "zh": '她说"你好"。'},
                {"idx": 1, "zh": "结束。"},
            ],
        )

    def test_translator_json_methods_are_compatibility_wrappers(self):
        raw = '{"items":[{"idx":0,"revised":"已修正"}]}'
        self.assertEqual(JaZhTranslator._extract_json_object(raw), extract_json_object(raw))
        self.assertEqual(
            JaZhTranslator._extract_lenient_indexed_items(raw, value_keys=["revised"]),
            extract_lenient_indexed_items(raw, value_keys=["revised"]),
        )

    def test_httpx_response_adapter_matches_requests_contract(self):
        response = HttpxResponseAdapter(
            429,
            '{"error":"rate limited"}',
            "https://example.invalid/v1/chat/completions",
            headers={"Retry-After": "8"},
        )
        self.assertEqual(response.json(), {"error": "rate limited"})
        self.assertEqual(response.headers["Retry-After"], "8")
        with self.assertRaises(requests.exceptions.HTTPError) as raised:
            response.raise_for_status()
        self.assertIs(raised.exception.response, response)

    def test_incomplete_error_keeps_structured_diagnostics(self):
        error = TranslationIncompleteError(
            failed_texts=["原文一"],
            residue_texts=["原文二"],
            residue_details=[
                {
                    "original": "原文二",
                    "translated": "译文でも残留",
                    "fragments": ["でも"],
                }
            ],
        )
        diagnostics = error.format_diagnostics()
        self.assertIn("未成功翻译 1 条", diagnostics)
        self.assertIn("残留片段: でも", diagnostics)

    def test_batching_module_keeps_order_and_length_tiers(self):
        short = "短句"
        medium = "中" * 40
        long = "长" * 220
        self.assertEqual(
            smart_batch_texts(
                [short, medium, long],
                4,
                short_threshold=30,
                long_threshold=200,
                max_batch_length=500,
            ),
            [[short], [medium], [long]],
        )
        self.assertEqual(smart_split_text("第一句。第二句。", 4), ["第一句。", "第二句。"])

    def test_fast_task_batching_uses_source_lengths_not_keys(self):
        task_texts = {"short-key": "短", "long-key": "长" * 240}
        batches = smart_batch_task_keys(
            ["short-key", "long-key"],
            task_texts,
            4,
            short_threshold=30,
            long_threshold=200,
            max_batch_length=500,
            fast_mode=False,
            fast_max_items=8,
            fast_max_chars=2400,
            provider="deepseek",
        )
        self.assertEqual(batches, [["short-key"], ["long-key"]])


if __name__ == "__main__":
    unittest.main()
