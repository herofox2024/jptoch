# -*- coding: utf-8 -*-
"""QML/V4 application metadata shared by runtime and update checks."""

APP_NAME = "AI日译中（EPUB）"
# 展示版本用于窗口标题和品牌露出，补丁号不必每次显示在主界面。
APP_DISPLAY_VERSION = "4.1"
# 内部版本用于更新检查、GitHub Release、安装包 AppVersion 和 Windows 文件版本。
APP_VERSION = "4.1.1"
APP_VERSION_TAG = f"v{APP_VERSION}"
APP_DISPLAY_NAME = f"{APP_NAME}V{APP_DISPLAY_VERSION}"

GITHUB_REPO = "herofox2024/jptoch"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"
GITHUB_LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
