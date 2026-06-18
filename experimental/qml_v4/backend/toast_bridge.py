# -*- coding: utf-8 -*-
"""
Toast 桥接器：提供从 Python 侧向 QML Toast 发送消息的信号。
用法：
    from backend.toast_bridge import ToastBridge
    ToastBridge.info("文件已保存")
    ToastBridge.success("连接成功")
    ToastBridge.warning("请填写 API Key")
    ToastBridge.error("翻译失败")

注意：ToastBridge 必须在 QApplication 创建后只实例化一次（main.py 中完成），
其他模块通过 ToastBridge.info() 等类方法使用。
"""

from PySide6.QtCore import QObject, Signal, Slot


class ToastBridge(QObject):
    """
    通过 Qt 信号驱动 QML Toast 组件显示非阻塞通知。
    外部通过 ToastBridge.info() 等类方法使用（自动路由到全局单例）。

    QML 侧可通过以下方式触发 Toast：
        ToastBridge.showInfo("消息")       // 直接 emit 信号
        ToastBridge.show("消息", "info")   // 调用 Slot
    """

    _instance = None

    showInfo = Signal(str)
    showSuccess = Signal(str)
    showWarning = Signal(str)
    showError = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        ToastBridge._instance = self

    # ---- Python 侧类方法（其他 Python 模块使用）----
    @classmethod
    def info(cls, message: str):
        inst = cls._instance
        if inst:
            inst.showInfo.emit(message)

    @classmethod
    def success(cls, message: str):
        inst = cls._instance
        if inst:
            inst.showSuccess.emit(message)

    @classmethod
    def warning(cls, message: str):
        inst = cls._instance
        if inst:
            inst.showWarning.emit(message)

    @classmethod
    def error(cls, message: str):
        inst = cls._instance
        if inst:
            inst.showError.emit(message)

    # ---- QML 侧可调用的 Slot ----
    @Slot(str)
    def infoSlot(self, message: str):
        """QML 可调用的 info Slot"""
        self.showInfo.emit(message)

    @Slot(str)
    def successSlot(self, message: str):
        """QML 可调用的 success Slot"""
        self.showSuccess.emit(message)

    @Slot(str)
    def warningSlot(self, message: str):
        """QML 可调用的 warning Slot"""
        self.showWarning.emit(message)

    @Slot(str)
    def errorSlot(self, message: str):
        """QML 可调用的 error Slot"""
        self.showError.emit(message)

    @Slot(str, str)
    def show(self, message: str, msg_type: str = "info"):
        """通用 Slot，QML 侧可通过此方法调用。"""
        getattr(type(self), msg_type, type(self).info)(message)
