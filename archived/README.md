# Archived User Interfaces

The application mainline is `experimental/qml_v4`. Files under this directory are retained for
fallback testing and source history; they are not part of the default release or installer.

## Qt V3.2.1

- Entry point: `python archived/qt_v3/main_qt.py`
- Status: archived fallback
- Maintenance: security issues, data-loss bugs and startup blockers only
- UI source: `archived/qt_v3/ui/qt_app.py`
- Historical build specs: `archived/qt_v3/packaging/`

## Tk V1

- Entry point: `python archived/tk_v1/app.py`
- Status: frozen historical compatibility version
- Maintenance: no feature development
- `app_backup_20260514153433.py` is a source snapshot, not a supported entry point

## Rules

- New UI features belong in `experimental/qml_v4`.
- Shared translation fixes belong in root core modules and require QML/V4 regression tests.
- GitHub Releases and installers must build only QML/V4.
- Archived entry points may import shared root modules, but current code must not import archived UI modules.
