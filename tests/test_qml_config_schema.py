from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from experimental.qml_v4.backend import config_bridge
from experimental.qml_v4.backend.config_bridge import ConfigBridge
from experimental.qml_v4.backend.config_schema import validate_config
from experimental.qml_v4.backend.service_container import ServiceContainer


_APP = QCoreApplication.instance() or QCoreApplication([])


def test_schema_coerces_types_and_bounds_without_exposing_values():
    result = validate_config({
        "max_workers": "999",
        "batch_size": 0,
        "api_timeout": "bad",
        "enable_proofread": "false",
        "selected_glossary_profile_ids": [" book-a ", "book-a", "book-b"],
        "api_key": {"secret": "must-not-appear"},
    })

    assert result.values["max_workers"] == 64
    assert result.values["batch_size"] == 1
    assert result.values["api_timeout"] == 120
    assert result.values["enable_proofread"] is False
    assert result.values["selected_glossary_profile_ids"] == ["book-a", "book-b"]
    assert result.values["api_key"] == ""
    assert all("must-not-appear" not in issue.message for issue in result.issues)


def test_schema_rejects_unknown_enum_and_non_http_url():
    result = validate_config({
        "provider": "not-a-provider",
        "api_url": "file:///tmp/model",
        "japanese_residue_policy": "unsafe",
        "future_setting": True,
    })

    assert result.values["provider"] == "deepseek"
    assert result.values["api_url"] == ""
    assert result.values["japanese_residue_policy"] == "balanced"
    assert result.unknown_keys == ("future_setting",)


def test_config_bridge_repairs_corrupt_persisted_values(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(config_bridge, "_data_dir", lambda: tmp_path)
    (tmp_path / config_bridge.CONFIG_FILE_NAME).write_text(
        json.dumps({
            "provider": "deepseek",
            "max_workers": -4,
            "batch_size": "6",
            "api_timeout": None,
            "theme": "unknown",
            "hymt2_runtime_mode": "cuda",
        }),
        encoding="utf-8",
    )

    cfg = ConfigBridge()

    assert cfg.maxWorkers == 1
    assert cfg.batchSize == 6
    assert cfg.apiTimeout == 120
    assert cfg.theme == "light"
    assert cfg.hymt2RuntimeMode == "cpu"


def test_config_bridge_setters_clamp_runtime_numeric_values(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(config_bridge, "_data_dir", lambda: tmp_path)
    cfg = ConfigBridge()

    cfg.maxWorkers = 10_000
    cfg.batchSize = 0
    cfg.apiTimeout = 2

    assert cfg.maxWorkers == 64
    assert cfg.batchSize == 1
    assert cfg.apiTimeout == 10


def test_service_container_uses_the_same_validation_rules():
    container = ServiceContainer()
    container.config = {
        "max_workers": "12",
        "batch_size": -3,
        "enable_proofread": "true",
        "api_url": "javascript:invalid",
    }

    assert container.config["max_workers"] == 12
    assert container.config["batch_size"] == 1
    assert container.config["enable_proofread"] is True
    assert container.config["api_url"] == ""
