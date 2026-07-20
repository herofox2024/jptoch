from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from experimental.qml_v4.backend import config_bridge
from experimental.qml_v4.backend.config_bridge import ConfigBridge


_APP = QCoreApplication.instance() or QCoreApplication([])


def _make_bridge(monkeypatch, tmp_path: Path) -> ConfigBridge:
    monkeypatch.setattr(config_bridge, "_data_dir", lambda: tmp_path)
    return ConfigBridge()


def test_builtin_model_prompt_presets_cover_stage5_categories(monkeypatch, tmp_path: Path):
    cfg = _make_bridge(monkeypatch, tmp_path)

    presets = cfg.getModelPromptPresets()
    keys = {item["key"] for item in presets}
    categories = {item["category"] for item in presets}

    assert {"model", "prompt", "workflow"}.issubset(categories)
    assert "deepseek_fast" in keys
    assert "deepseek_stable" in keys
    assert "longcat_stable" in keys
    assert "longcat_balanced" in keys
    assert "hymt2_cpu_stable" in keys
    assert "hymt2_gpu_stable" in keys
    assert "custom_openai" in keys
    assert "prompt_literary_default" in keys
    assert "prompt_hymt2_official_short" in keys
    assert "prompt_safe_conservative" in keys
    assert "prompt_failed_block_repair" in keys
    assert "prompt_proofread_retranslate" in keys


def test_save_current_preset_excludes_api_keys(monkeypatch, tmp_path: Path):
    cfg = _make_bridge(monkeypatch, tmp_path)
    cfg.apiKey = "sk-real-secret"
    cfg.proofreadApiKey = "proofread-secret"
    cfg.promptExtraInstruction = "请以简体中文输出。"

    result = cfg.saveCurrentModelPromptPreset("我的稳定配置", "test hint")

    assert result["ok"] is True
    path = tmp_path / config_bridge.MODEL_PROMPT_PRESETS_FILE_NAME
    payload_text = path.read_text(encoding="utf-8")
    assert "sk-real-secret" not in payload_text
    assert "proofread-secret" not in payload_text
    payload = json.loads(payload_text)
    values = payload["presets"][0]["values"]
    assert "api_key" not in values
    assert "proofread_api_key" not in values
    assert values["prompt_extra_instruction"] == "请以简体中文输出。"


def test_import_preset_strips_secrets_and_apply_hymt2_sets_local_key(monkeypatch, tmp_path: Path):
    cfg = _make_bridge(monkeypatch, tmp_path)
    source = tmp_path / "import_presets.json"
    source.write_text(
        json.dumps(
            {
                "presets": [
                    {
                        "key": "hymt2_imported",
                        "label": "Hy-MT2 导入",
                        "category": "model",
                        "values": {
                            "provider": "hymt2",
                            "api_key": "should-not-persist",
                            "proofread_api_key": "also-secret",
                            "api_url": "http://127.0.0.1:8080/v1/chat/completions",
                            "model": "Hy-MT2-1.8B-Q4_K_M",
                            "max_workers": 4,
                            "batch_size": 4,
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = cfg.importModelPromptPresets(str(source))

    assert result["ok"] is True
    stored_text = (tmp_path / config_bridge.MODEL_PROMPT_PRESETS_FILE_NAME).read_text(encoding="utf-8")
    assert "should-not-persist" not in stored_text
    assert "also-secret" not in stored_text
    apply_result = cfg.applyModelPromptPreset("user_hymt2_imported")
    assert apply_result["ok"] is True
    assert cfg.provider == "hymt2"
    assert cfg.apiKey == "sk-local"
    assert cfg.maxWorkers == 4
    assert cfg.batchSize == 4


def test_export_current_preset_excludes_api_keys(monkeypatch, tmp_path: Path):
    cfg = _make_bridge(monkeypatch, tmp_path)
    cfg.apiKey = "sk-export-secret"
    cfg.proofreadApiKey = "proofread-export-secret"
    cfg.model = "deepseek-v4-flash"
    export_path = tmp_path / "current_preset.json"

    result = cfg.exportCurrentModelPromptPreset(str(export_path), "当前配置")

    assert result["ok"] is True
    payload_text = export_path.read_text(encoding="utf-8")
    assert "sk-export-secret" not in payload_text
    assert "proofread-export-secret" not in payload_text
    payload = json.loads(payload_text)
    assert payload["type"] == "qml_v4_model_prompt_presets"
    assert payload["secrets_excluded"] is True
    values = payload["presets"][0]["values"]
    assert "api_key" not in values
    assert "proofread_api_key" not in values
    assert values["model"] == "deepseek-v4-flash"


def test_delete_only_user_model_prompt_preset(monkeypatch, tmp_path: Path):
    cfg = _make_bridge(monkeypatch, tmp_path)
    saved = cfg.saveCurrentModelPromptPreset("delete me", "")

    builtin_delete = cfg.deleteUserModelPromptPreset("deepseek_stable")
    user_delete = cfg.deleteUserModelPromptPreset(saved["key"])

    assert builtin_delete["ok"] is False
    assert user_delete["ok"] is True
    assert all(item["key"] != saved["key"] for item in cfg.getModelPromptPresets())
