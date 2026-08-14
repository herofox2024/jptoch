pragma Singleton

import QtQuick

QtObject {
    function selectedGlossaryProfileIds(cfg) {
        if (!cfg) return []
        var raw = cfg.selectedGlossaryProfileIds || []
        var ids = []
        for (var i = 0; i < raw.length; i++) {
            var value = String(raw[i] || "").trim()
            if (value !== "" && ids.indexOf(value) < 0) ids.push(value)
        }
        return ids
    }

    function selectedGlossaryProfileCount(cfg) {
        return selectedGlossaryProfileIds(cfg).length
    }

    function setSelectedGlossaryProfileIds(cfg, ids) {
        if (!cfg) return
        var cleaned = []
        for (var i = 0; i < (ids || []).length; i++) {
            var value = String(ids[i] || "").trim()
            if (value !== "" && cleaned.indexOf(value) < 0) cleaned.push(value)
        }
        cfg.selectedGlossaryProfileIds = cleaned
        if (cleaned.length > 0) {
            cfg.enableGlossary = true
            cfg.enableLayeredGlossary = true
        }
    }

    function clearSelectedGlossaryProfiles(cfg) {
        setSelectedGlossaryProfileIds(cfg, [])
    }

    function isGlossaryProfileSelected(cfg, profileId) {
        var value = String(profileId || "").trim()
        if (value === "") return false
        return selectedGlossaryProfileIds(cfg).indexOf(value) >= 0
    }

    function toggleGlossaryProfile(cfg, profileId, checked) {
        var value = String(profileId || "").trim()
        if (value === "" || !cfg) return
        var ids = selectedGlossaryProfileIds(cfg)
        var index = ids.indexOf(value)
        if (checked && index < 0) ids.push(value)
        if (!checked && index >= 0) ids.splice(index, 1)
        setSelectedGlossaryProfileIds(cfg, ids)
    }

    function addSelectedGlossaryProfileIds(cfg, ids) {
        if (!ids || ids.length === 0) return
        var merged = selectedGlossaryProfileIds(cfg)
        for (var i = 0; i < ids.length; i++) {
            var value = String(ids[i] || "").trim()
            if (value !== "" && merged.indexOf(value) < 0) merged.push(value)
        }
        setSelectedGlossaryProfileIds(cfg, merged)
    }
}
