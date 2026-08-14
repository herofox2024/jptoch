pragma Singleton

import QtQuick

QtObject {
    function normalizeFileUrl(value) {
        var path = value ? value.toString() : ""
        if (path.startsWith("file:///")) {
            path = path.substring(8)
        } else if (path.startsWith("file://")) {
            path = path.substring(7)
        }
        return decodeURIComponent(path)
    }

    function fileName(path) {
        if (!path || path === "") return "未选择"
        var normalized = String(path).replace(/\\/g, "/")
        var slash = normalized.lastIndexOf("/")
        return slash >= 0 ? normalized.substring(slash + 1) : normalized
    }

    function pathDisplay(path) {
        if (!path || path === "") return "未选择"
        return String(path).replace(/\\/g, "/")
    }

    function defaultOutputPath(path) {
        var normalized = String(path || "").replace(/\\/g, "/")
        var slash = normalized.lastIndexOf("/")
        var dir = slash >= 0 ? normalized.substring(0, slash + 1) : ""
        var base = slash >= 0 ? normalized.substring(slash + 1) : normalized
        base = base.replace(/\.epub$/i, "")
        return dir + base + "_zh.epub"
    }
}
