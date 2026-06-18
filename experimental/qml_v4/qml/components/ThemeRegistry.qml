pragma Singleton
import QtQuick

/* ============================================================
   ThemeRegistry — 主题预设注册表

   提供主题名称→标签的映射，以及索引转换工具函数。
   实际主题切换由 main.qml 通过 cfg.theme + Binding 驱动 AppPalette。

   用法（在 OptionsPage 中）:
     ComboBox { model: ThemeRegistry.labels() }
     ThemeRegistry.nameFromIndex(index)  // 获取主题名
     ThemeRegistry.labelFor("dark")      // 获取标签
   ============================================================ */

QtObject {
    // 主题预设定义（名称→标签）
    readonly property var presets: ({
        "light": "浅色纸感",
        "dark":  "深色墨色",
        "glass": "iOS26 玻璃",
    })

    // 获取所有主题标签
    function labels() {
        var result = []
        for (var key in presets) {
            result.push(presets[key])
        }
        return result
    }

    // 获取所有主题名称（保持与 presets 一致的顺序）
    function keys() {
        return Object.keys(presets)
    }

    // 通过名称获取标签
    function labelFor(name) {
        return presets[name] || name
    }

    // 通过索引获取名称
    function nameFromIndex(index) {
        var k = keys()
        return (index >= 0 && index < k.length) ? k[index] : "light"
    }

    // 通过名称获取索引
    function indexFromName(name) {
        return keys().indexOf(name)
    }
}
