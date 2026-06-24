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
}
