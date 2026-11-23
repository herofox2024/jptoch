"""更新桥接器的纯逻辑单元测试。

为什么补这些测试：
  `update_bridge.py` 此前没有任何测试导入（全仓零覆盖），但它掌握两件高风险判断：

  1. `_is_newer_version` 决定「要不要提示用户升级」。判错的后果是静默不更新，
     或者对旧版本反复提示升级。
  2. `_safe_file_name` 决定下载后的安装包**写到磁盘上的文件名**。清理不当会导致
     路径穿越（`../`）或非法字符，在 Windows 上写入失败或落到预期目录之外。

  这两者都是纯函数，不需要网络、不需要启动 Qt，因此可以直接断言。
"""

from __future__ import annotations

import sys
from pathlib import Path

QML_ROOT = Path(__file__).resolve().parents[1] / "experimental" / "qml_v4"
if str(QML_ROOT) not in sys.path:
    sys.path.insert(0, str(QML_ROOT))

from backend.update_bridge import (
    _asset_size_text,
    _is_newer_version,
    _safe_file_name,
    _version_tuple,
)


# --- 版本比较 -------------------------------------------------------------


def test_version_tuple_pads_missing_segments():
    """`v4.1` 与 `4.1.0.0` 必须等价，否则短版本号永远被判成更旧。"""
    assert _version_tuple("v4.1") == (4, 1, 0, 0)
    assert _version_tuple("4.1.0.0") == (4, 1, 0, 0)
    assert _version_tuple("v4.1.0") == _version_tuple("4.1")


def test_version_tuple_ignores_non_numeric_noise():
    """带前缀/后缀的版本号仍应正确解析。"""
    assert _version_tuple("V4.2.3") == (4, 2, 3, 0)
    assert _version_tuple("4.2.3-rc1") == (4, 2, 3, 1)
    assert _version_tuple("") == (0, 0, 0, 0)


def test_is_newer_version_detects_upgrade():
    assert _is_newer_version("4.2.4", "4.2.3")
    assert _is_newer_version("v4.3.0", "4.2.9")
    assert _is_newer_version("5.0", "4.99.99")


def test_is_newer_version_rejects_same_and_older():
    """相同或更旧的版本不能触发升级提示。"""
    assert not _is_newer_version("4.2.3", "4.2.3")
    assert not _is_newer_version("v4.2.3", "4.2.3")
    assert not _is_newer_version("4.2.2", "4.2.3")
    assert not _is_newer_version("", "4.2.3")


# --- 安装包文件名 ---------------------------------------------------------


def test_safe_file_name_strips_path_separators():
    """文件名不得保留路径分隔符，否则安装包会被写到预期目录之外。"""
    for raw in (
        "../../evil.exe",
        "sub/dir/setup.exe",
        "sub\\dir\\setup.exe",
        "C:\\Windows\\setup.exe",
    ):
        cleaned = _safe_file_name(raw)
        assert "/" not in cleaned, cleaned
        assert "\\" not in cleaned, cleaned
        assert ".." not in cleaned, cleaned
        assert not cleaned.startswith("."), cleaned


def test_safe_file_name_removes_windows_invalid_chars():
    """Windows 非法字符必须被替换，否则写文件直接失败。"""
    cleaned = _safe_file_name('setup<>:"|?*.exe')
    for char in '<>:"|?*':
        assert char not in cleaned, (char, cleaned)
    assert cleaned.endswith(".exe")


def test_safe_file_name_appends_exe_suffix():
    cleaned = _safe_file_name("MyUpdater")
    assert cleaned == "MyUpdater.exe"


def test_safe_file_name_keeps_exe_case_insensitively():
    """已经是 .EXE 的不应被追加成 .EXE.exe。"""
    assert _safe_file_name("Setup.EXE").lower().endswith(".exe")
    assert not _safe_file_name("Setup.EXE").lower().endswith(".exe.exe")


def test_safe_file_name_falls_back_when_empty():
    """空名或全是非法字符时必须回退到默认名。

    回归点：清洗 `"///"` 会得到 `".exe"`——非空，但主文件名是空的，
    在 Windows 上是无效文件名，写盘会失败或落到意料之外的路径。
    曾经的实现只在「完全空串」时回退，挡不住这种情况。
    """
    default = "AI日译中(EPUB)更新安装程序.exe"
    for raw in ("", "   ", "///", "<>:", "..."):
        cleaned = _safe_file_name(raw)
        assert cleaned, f"空文件名会覆盖默认路径: {raw!r}"
        assert cleaned.endswith(".exe")
        # 主文件名不能为空：不能只剩下 ".exe"
        assert cleaned.lower() != ".exe", f"只剩扩展名的无效文件名: {raw!r} -> {cleaned!r}"
        assert len(cleaned.lower().removesuffix(".exe").strip(" ._")) > 0, (
            f"主文件名为空: {raw!r} -> {cleaned!r}"
        )
    assert _safe_file_name("///") == default


def test_safe_file_name_caps_length():
    """过长文件名会超出 Windows 路径限制，必须截断。"""
    cleaned = _safe_file_name("a" * 500 + ".exe")
    assert len(cleaned) <= 180, len(cleaned)


# --- 体积展示 -------------------------------------------------------------


def test_asset_size_text_handles_unparsable_values():
    """GitHub 的 size 字段可能是 None 或字符串，不能抛异常。"""
    assert _asset_size_text(None) == "未知大小"
    assert _asset_size_text(0) == "未知大小"
    assert _asset_size_text(-5) == "未知大小"
    assert _asset_size_text("not-a-number") == "未知大小"


def test_asset_size_text_formats_units():
    assert _asset_size_text(512) == "512 B"
    assert _asset_size_text(2048) == "2.0 KB"
    assert _asset_size_text(5 * 1024 * 1024) == "5.0 MB"
    assert _asset_size_text(3 * 1024 ** 3) == "3.0 GB"
