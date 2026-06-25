# -*- coding: utf-8 -*-
"""
软件更新桥接器：检查 GitHub Release，下载 Windows 安装包，并启动安装程序。

第一阶段实现明确的用户确认流程，不做静默安装，避免在用户不知情时覆盖当前程序。
"""

import logging
import re
import subprocess
import threading
from pathlib import Path
from urllib.parse import urlparse

import requests
from PySide6.QtCore import QObject, Property, QCoreApplication, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from backend.app_info import (
    APP_VERSION,
    GITHUB_LATEST_RELEASE_API,
    GITHUB_RELEASES_URL,
    GITHUB_REPO,
)

logger = logging.getLogger(__name__)

_USER_AGENT = f"AI-EPUB-Translator/{APP_VERSION} ({GITHUB_REPO})"
_DOWNLOAD_CHUNK_SIZE = 1024 * 512


def _data_dir() -> Path:
    path = Path.home() / ".epub_translator"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _updates_dir() -> Path:
    path = _data_dir() / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _version_tuple(version: str) -> tuple[int, int, int, int]:
    """Parse v4.1.0 / 4.1.1-rc1 into a comparable numeric tuple."""
    nums = [int(part) for part in re.findall(r"\d+", str(version or ""))]
    nums = nums[:4]
    while len(nums) < 4:
        nums.append(0)
    return tuple(nums)


def _is_newer_version(remote: str, current: str) -> bool:
    return _version_tuple(remote) > _version_tuple(current)


def _safe_file_name(name: str) -> str:
    name = str(name or "").strip()
    if not name:
        name = "AI日译中(EPUB)更新安装程序.exe"
    invalid = '<>:"/\\|?*'
    cleaned = "".join("_" if char in invalid or ord(char) < 32 else char for char in name)
    cleaned = " ".join(cleaned.split()).strip(" ._")
    if not cleaned.lower().endswith(".exe"):
        cleaned += ".exe"
    return cleaned[:180] or "AI日译中(EPUB)更新安装程序.exe"


def _asset_size_text(size_bytes: int) -> str:
    try:
        size = float(size_bytes or 0)
    except Exception:
        size = 0.0
    if size <= 0:
        return "未知大小"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


class UpdateBridge(QObject):
    checkStarted = Signal()
    updateAvailable = Signal("QVariantMap")
    noUpdate = Signal("QVariantMap")
    checkFailed = Signal(str)

    downloadStarted = Signal(str)
    downloadProgress = Signal(int, int, int)  # received, total, percent
    downloadFinished = Signal(str)
    downloadFailed = Signal(str)

    installerLaunched = Signal(str)
    installFailed = Signal(str)

    _checkingChanged = Signal()
    _downloadingChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checking = False
        self._downloading = False
        self._latest_info = {}

    @Property(str, constant=True)
    def currentVersion(self) -> str:
        return APP_VERSION

    @Property(str, constant=True)
    def releasesUrl(self) -> str:
        return GITHUB_RELEASES_URL

    @Property(bool, notify=_checkingChanged)
    def checking(self) -> bool:
        return self._checking

    @Property(bool, notify=_downloadingChanged)
    def downloading(self) -> bool:
        return self._downloading

    def _set_checking(self, value: bool):
        if self._checking == value:
            return
        self._checking = value
        self._checkingChanged.emit()

    def _set_downloading(self, value: bool):
        if self._downloading == value:
            return
        self._downloading = value
        self._downloadingChanged.emit()

    @Slot()
    def checkForUpdates(self):
        if self._checking:
            return
        self._set_checking(True)
        self.checkStarted.emit()
        threading.Thread(target=self._check_worker, name="UpdateCheck", daemon=True).start()

    @Slot(str, str)
    def downloadInstaller(self, download_url: str, file_name: str = ""):
        if self._downloading:
            return
        download_url = str(download_url or "").strip()
        if not download_url:
            self.downloadFailed.emit("没有找到可下载的安装包。")
            return
        if not download_url.lower().startswith("https://"):
            self.downloadFailed.emit("下载地址不是 HTTPS，已阻止。")
            return
        self._set_downloading(True)
        safe_name = _safe_file_name(file_name or Path(urlparse(download_url).path).name)
        self.downloadStarted.emit(safe_name)
        threading.Thread(
            target=self._download_worker,
            args=(download_url, safe_name),
            name="UpdateDownload",
            daemon=True,
        ).start()

    @Slot(str)
    def openReleasePage(self, url: str = ""):
        target = str(url or "").strip() or GITHUB_RELEASES_URL
        QDesktopServices.openUrl(QUrl(target))

    @Slot(str)
    def launchInstaller(self, installer_path: str):
        path = Path(str(installer_path or "")).expanduser()
        if not path.exists():
            self.installFailed.emit("安装包不存在，无法启动。")
            return
        try:
            subprocess.Popen([str(path)], cwd=str(path.parent))
            self.installerLaunched.emit(str(path))
            app = QCoreApplication.instance()
            if app is not None:
                QTimer.singleShot(800, app.quit)
        except Exception as exc:
            logger.exception("启动更新安装程序失败")
            self.installFailed.emit(f"启动安装程序失败: {exc}")

    def _check_worker(self):
        try:
            response = requests.get(
                GITHUB_LATEST_RELEASE_API,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": _USER_AGENT,
                },
                timeout=15,
            )
            if response.status_code == 404:
                raise RuntimeError("GitHub Release 不存在，请先发布一个版本。")
            response.raise_for_status()
            release = response.json()
            info = self._build_update_info(release)
            self._latest_info = info
            if info.get("isNewer"):
                self.updateAvailable.emit(info)
            else:
                self.noUpdate.emit(info)
        except Exception as exc:
            logger.warning("检查更新失败: %s", exc)
            self.checkFailed.emit(str(exc))
        finally:
            self._set_checking(False)

    def _build_update_info(self, release: dict) -> dict:
        tag = str(release.get("tag_name") or "").strip()
        version = tag.lstrip("vV") or tag or "未知版本"
        html_url = str(release.get("html_url") or GITHUB_RELEASES_URL)
        body = str(release.get("body") or "").strip()
        if len(body) > 1200:
            body = body[:1200].rstrip() + "\n..."

        asset = self._select_installer_asset(release.get("assets") or [])
        asset_name = str(asset.get("name") or "") if asset else ""
        asset_url = str(asset.get("browser_download_url") or "") if asset else ""
        asset_size = int(asset.get("size") or 0) if asset else 0

        return {
            "currentVersion": APP_VERSION,
            "latestVersion": version,
            "tagName": tag,
            "isNewer": _is_newer_version(tag or version, APP_VERSION),
            "releaseUrl": html_url,
            "releaseName": str(release.get("name") or tag or version),
            "releaseNotes": body or "该版本没有填写发布说明。",
            "assetName": asset_name,
            "assetUrl": asset_url,
            "assetSize": asset_size,
            "assetSizeText": _asset_size_text(asset_size),
            "publishedAt": str(release.get("published_at") or ""),
        }

    @staticmethod
    def _select_installer_asset(assets: list[dict]) -> dict:
        exe_assets = [
            asset for asset in assets
            if str(asset.get("name") or "").lower().endswith(".exe")
        ]
        if not exe_assets:
            return {}

        def score(asset: dict) -> int:
            name = str(asset.get("name") or "").lower()
            value = 0
            if "安装程序" in name or "installer" in name or "setup" in name:
                value += 10
            if "portable" in name or "便携" in name:
                value -= 5
            return value

        return sorted(exe_assets, key=score, reverse=True)[0]

    def _download_worker(self, download_url: str, safe_name: str):
        dest = _updates_dir() / safe_name
        part = dest.with_name(dest.name + ".part")
        received = 0
        total = 0
        last_percent = -1
        try:
            with requests.get(
                download_url,
                headers={"User-Agent": _USER_AGENT},
                stream=True,
                timeout=(15, 60),
                allow_redirects=True,
            ) as response:
                response.raise_for_status()
                total = int(response.headers.get("Content-Length") or 0)
                with part.open("wb") as f:
                    for chunk in response.iter_content(chunk_size=_DOWNLOAD_CHUNK_SIZE):
                        if not chunk:
                            continue
                        f.write(chunk)
                        received += len(chunk)
                        percent = int(received * 100 / total) if total else 0
                        if percent != last_percent:
                            last_percent = percent
                            self.downloadProgress.emit(received, total, min(percent, 99 if total else 0))

            part.replace(dest)
            self.downloadProgress.emit(received, total, 100)
            self.downloadFinished.emit(str(dest))
        except Exception as exc:
            logger.warning("下载安装包失败: %s", exc)
            try:
                if part.exists():
                    part.unlink()
            except Exception:
                pass
            self.downloadFailed.emit(str(exc))
        finally:
            self._set_downloading(False)

