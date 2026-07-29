"""Translation estimates and persisted quality/residue reports."""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any, Dict

from .output_naming import sanitize_filename


def format_duration(seconds: float) -> str:
    total = max(0, int(math.ceil(seconds)))
    if total < 60:
        return "不足 1 分钟" if total < 30 else f"约 {total} 秒"
    minutes = int(math.ceil(total / 60))
    if minutes < 60:
        return f"约 {minutes} 分钟"
    hours, remain_minutes = divmod(minutes, 60)
    if remain_minutes:
        return f"约 {hours} 小时 {remain_minutes} 分钟"
    return f"约 {hours} 小时"


def estimate_translation_duration(total_chars: int, total_texts: int, cfg: Dict[str, Any]) -> float:
    provider = str(cfg.get("provider", "") or "").lower()
    provider_profile = {
        "deepseek": {"batch_seconds": 2.0, "chars_per_second": 120.0},
        "doubao": {"batch_seconds": 2.5, "chars_per_second": 90.0},
        "glm": {"batch_seconds": 4.0, "chars_per_second": 35.0},
        "gemini": {"batch_seconds": 6.0, "chars_per_second": 30.0},
        "wenxin": {"batch_seconds": 4.0, "chars_per_second": 45.0},
        "sakura": {"batch_seconds": 1.5, "chars_per_second": 80.0},
        "hymt2": {"batch_seconds": 4.0, "chars_per_second": 35.0},
        "custom": {"batch_seconds": 3.0, "chars_per_second": 60.0},
    }
    profile = provider_profile.get(provider, provider_profile["custom"])
    batch_size = max(1, int(cfg.get("batch_size") or 1))
    max_workers = max(1, int(cfg.get("max_workers") or 1))
    estimated_batches = max(1, math.ceil(max(1, total_texts) / batch_size))
    active_workers = min(max_workers, estimated_batches)
    effective_workers = 1.0 + max(0, active_workers - 1) * 0.65
    batch_seconds = estimated_batches * profile["batch_seconds"] / effective_workers
    char_seconds = max(1, total_chars) / max(1.0, profile["chars_per_second"] * effective_workers)
    overhead_seconds = max(10.0, total_texts * 0.02)
    return max(batch_seconds, char_seconds) + overhead_seconds


def write_japanese_residue_report(
    *,
    output_path: str,
    policy: str,
    blocked_total: int,
    scan: Any,
) -> str:
    report_dir = Path.home() / ".epub_translator" / "residue_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = sanitize_filename(Path(output_path or "translation").stem) or "translation"
    report_path = report_dir / f"{stamp}-{base}-japanese-residue.json"
    text_report_path = report_dir / f"{stamp}-{base}-japanese-residue.txt"
    payload = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "output_path": output_path,
        "policy": policy,
        "text_report_path": str(text_report_path),
        "blocking_total": int(getattr(scan, "blocking_total", 0)),
        "hard_blocking_total": int(getattr(scan, "hard_blocking_total", 0)),
        "high_risk_total": int(getattr(scan, "high_risk_total", 0)),
        "medium_risk_total": int(getattr(scan, "medium_risk_total", 0)),
        "low_risk_total": int(getattr(scan, "low_risk_total", 0)),
        "weak_total": int(getattr(scan, "weak_total", 0)),
        "blocked_total": int(blocked_total),
        "blocking_samples": list(getattr(scan, "blocking_samples", []) or []),
        "hard_blocking_samples": list(getattr(scan, "hard_blocking_samples", []) or []),
        "high_risk_samples": list(getattr(scan, "high_risk_samples", []) or []),
        "medium_risk_samples": list(getattr(scan, "medium_risk_samples", []) or []),
        "low_risk_samples": list(getattr(scan, "low_risk_samples", []) or []),
        "weak_samples": list(getattr(scan, "weak_samples", []) or []),
        "structured_samples": list(getattr(scan, "structured_samples", []) or []),
        "risk_legend": {
            "high": "likely untranslated Japanese sentence or long kana residue; always blocks except lenient mode",
            "medium": "short mixed residue that still needs translation; blocks in strict/balanced mode",
            "low": "title/name/term-like residue; strict blocks, balanced allows with report",
            "weak": "tiny kana noise; warning only",
        },
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "EPUB Japanese Residue Report",
        f"created_at: {payload['created_at']}",
        f"output_path: {output_path}",
        f"policy: {policy}",
        f"blocked_total: {blocked_total}",
        "",
        "Totals",
        f"- high: {payload['high_risk_total']}",
        f"- medium: {payload['medium_risk_total']}",
        f"- low: {payload['low_risk_total']}",
        f"- weak: {payload['weak_total']}",
        "",
        "Recommended handling",
        "- high: switch model or retranslate failed blocks before saving.",
        "- medium: add a known katakana repair term if it is a term; otherwise retranslate.",
        "- low: balanced mode can save with this report; strict mode blocks it.",
        "- weak: warning only.",
        "",
    ]
    for title, key in (
        ("High risk samples", "high_risk_samples"),
        ("Medium risk samples", "medium_risk_samples"),
        ("Low risk samples", "low_risk_samples"),
        ("Weak samples", "weak_samples"),
    ):
        lines.append(title)
        samples = payload.get(key) or []
        lines.extend((f"- {sample}" for sample in samples) if samples else ["- none"])
        lines.append("")
    text_report_path.write_text("\n".join(lines), encoding="utf-8")
    return str(report_path)


def build_quality_self_check_report(
    translator,
    cfg,
    proofread_style,
    total_texts,
    total_chars,
    elapsed,
    weak_residue_total,
    final_out,
):
    stats = translator.get_stats() if translator else {}
    api_total = int(stats.get("api_requests_total", 0))
    api_failed = int(stats.get("api_requests_failed", 0))
    dynamic_events = int(stats.get("dynamic_limit_events", 0))
    batch_parse_fail = int(stats.get("batch_json_parse_fail", 0))
    batch_lenient = int(stats.get("batch_json_lenient_success", 0))
    proofread_suspicious = int(stats.get("proofread_suspicious", 0))
    proofread_fixed = int(stats.get("proofread_fixed", 0))
    proofread_rejected = int(stats.get("proofread_rejected", 0))
    quality_retranslate = int(stats.get("quality_retranslate", 0))
    tokens_total = int(stats.get("tokens_total", 0))

    warnings = []
    suggestions = []
    if weak_residue_total:
        warnings.append(f"发现 {weak_residue_total} 处弱日文残留，已提示但不阻塞保存。")
        suggestions.append("抽查弱残留样例；只有确认必须保留的片段才加入白名单。")
    if api_failed:
        warnings.append(f"API 失败/异常次数 {api_failed} 次。")
        suggestions.append("免费模型建议降低并发和批量；如果连续触发限流，切换付费模型或稍后恢复续译。")
    if dynamic_events:
        warnings.append(f"动态限流/格式降级触发 {dynamic_events} 次。")
    if batch_parse_fail:
        warnings.append(f"批量 JSON 解析失败 {batch_parse_fail} 次，宽松解析成功 {batch_lenient} 次。")
        suggestions.append("如果 JSON 失败频繁，降低批量大小或对免费模型使用 batch_size=1。")
    if proofread_rejected:
        warnings.append(f"校对结果因疑似错误术语注入被拒绝 {proofread_rejected} 次。")
        suggestions.append("检查术语表中多义词，优先标为“仅供参考”或“上下文命中”。")
    if not bool(cfg.get("enable_proofread", False)):
        warnings.append("译后校对未启用，本次未做日文残留/术语一致性 AI 校对。")
        suggestions.append("正式出书建议启用译后校对，免费模型可使用低并发低批量。")

    status = "通过" if not warnings else "有提醒"
    style_text = getattr(proofread_style, "display_text", "") or "未识别"
    metrics = [
        f"输出文件: {final_out}", f"文本块: {total_texts}", f"总字符: {total_chars}",
        f"耗时: {format_duration(elapsed)}", f"Prompt 风格: {style_text}", f"API 请求: {api_total}",
        f"Token: {tokens_total if tokens_total > 0 else '--'}", f"可疑译文: {proofread_suspicious}",
        f"校对修复: {proofread_fixed}", f"重译次数: {quality_retranslate}",
    ]
    if not suggestions:
        suggestions.append("本次没有发现明显流程风险；如修改 Prompt 或术语策略后需要重译，请先清理当前 EPUB 缓存。")
    summary = (
        f"本次翻译完成，质量自检结果：{status}。"
        f"校对发现 {proofread_suspicious} 条可疑译文，修复 {proofread_fixed} 条。"
    )
    return {
        "status": status,
        "summary": summary,
        "metricsText": "\n".join(metrics),
        "warningsText": "\n".join(f"- {item}" for item in warnings) if warnings else "未发现需要阻塞保存的问题。",
        "suggestionsText": "\n".join(f"- {item}" for item in suggestions),
        "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
