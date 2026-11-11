# QML/V4 Architecture

## Runtime Flow

1. QML pages call the PySide bridge layer in `experimental/qml_v4/backend`.
2. `TranslateBridge` creates a worker thread and runs the staged EPUB pipeline.
3. `JaZhTranslator` coordinates cache lookup, provider requests, quality checks and persistence.
4. The pipeline writes translated text back to EPUB content and performs save-time validation.

## Translation Engine Boundaries

`translator.py` remains the compatibility facade. Existing entry points can continue importing
`JaZhTranslator`, `BatchJsonResult` and translation exceptions from that module.

The implementation is split by responsibility:

| Module | Responsibility |
| --- | --- |
| `translation_models.py` | Shared result objects and public error contracts |
| `translation_json_parser.py` | Strict, repaired and lenient model JSON parsing |
| `translation_async_http.py` | Optional reusable `httpx` async connection pool |
| `translation_http.py` | Retry classification, exponential delay and `Retry-After` parsing |
| `translation_batching.py` | Text splitting and length-aware batch grouping |
| `translation_adaptive.py` | Rolling-latency batch/concurrency pressure controller |
| `provider_registry.py` | Provider defaults and endpoint normalization |
| `provider_client.py` | Provider payload and HTTP response helpers |
| `translation_cache_db.py` | Indexed SQLite model, text and manual caches |
| `translation_quality.py` / `quality_rules.py` | Japanese residue and translation quality rules |

The facade keeps thin methods with the old names where QML/V4 or tests rely on them. This permits
incremental extraction without changing UI/backend call sites or invalidating persisted tasks.

## QML Bridge Boundaries

`TranslateBridge` owns QML signals, worker-thread lifetime and persistent task state. Business
helpers that do not depend on QML state are separated:

| Module | Responsibility |
| --- | --- |
| `experimental/qml_v4/backend/output_naming.py` | EPUB filename and translated TOC title normalization |
| `experimental/qml_v4/backend/translation_reports.py` | Duration estimates, residue reports and quality reports |
| `experimental/qml_v4/backend/bridge_workers.py` | Character estimate, cache cleanup and connection-test workers |
| `experimental/qml_v4/backend/config_schema.py` | Typed, bounded validation for disk, preset and QML settings |

Compatibility wrappers remain in `translate_bridge.py` for maintained imports. The primary
translation worker still lives beside the bridge because it currently updates task history through
bridge callbacks; it should move only after those callbacks become an explicit protocol.

## Threading

- EPUB translation runs in a QML worker `QThread`.
- Batch requests use a bounded `ThreadPoolExecutor`.
- New work is submitted incrementally, so latency/error-based runtime limits apply to later batches
  without recreating the executor. Error downgrades are immediate; successful requests need a stable
  rolling window before limits recover.
- Providers eligible for fast batch mode can use one reusable `httpx.AsyncClient` hosted by a
  dedicated event-loop thread.
- SQLite uses WAL mode and buffered writes; explicit checkpoints run at task boundaries.

## Compatibility Rules

- Do not import QML types into core translation modules.
- Keep provider-specific routing data in `provider_registry.py`.
- Keep response parsing independent from network clients.
- Preserve exports from `translator.py` until all maintained entry points use the new modules.
- Add direct module tests before replacing a compatibility wrapper.
- Validate persisted and imported settings before they reach bridge fields or translator constructors.

## Shared Root Modules

Modules needed by both the core engine and the QML bridges must live at the project root,
not under `experimental/qml_v4/backend`:

| Module | Responsibility |
| --- | --- |
| `request_log.py` | Structured diagnostic request logs, secret redaction and retention |

`request_log.py` has no Qt dependency. `translator.py` and the QML log/translate bridges
both import it as a top-level module. Do not move it back under the backend package: the
core engine must not import the QML package.

## Static Checks

`pyproject.toml` configures ruff for the whole repository. The enabled rule set is
deliberately narrow so the baseline stays green and every finding is a real defect:

| Rule | Purpose |
| --- | --- |
| `F` (Pyflakes) | Unused imports/variables, redefinitions, duplicate dict keys |
| `E9` | Syntax-level hard errors |

Formatting-only rules such as `E501` (line length) and `E702` (statement separators) are
intentionally disabled: enabling them today would add over a thousand findings and hide
real defects in noise. `archived/`, `dist/`, `build/` and the QML directory are excluded.

`ruff check .` runs in the release workflow before packaging and blocks it on failure.

## Interpreter Version

The project pins a single Python minor version in three places, and they must agree:

| Location | Purpose |
| --- | --- |
| `.python-version` | Local development and editor auto-detection |
| `.github/workflows/release-qml-v4.yml` | Release build and CI test interpreter |
| `pyproject.toml` → `tool.ruff.target-version` | Static analysis target |

Python 3.12 is the standard. `tests/test_python_version_alignment.py` enforces the
agreement and rejects prerelease (beta/rc) interpreters, because tests passing on a
prerelease do not guarantee identical behaviour in the stable release build.

## Version Ownership

- `experimental/qml_v4` is the only active desktop UI and the only release target.
- `archived/qt_v3` is a manual fallback for critical compatibility checks.
- `archived/tk_v1` is frozen source history.
- Current modules must not import archived UI code.
- Release workflows, installers and current tests target QML/V4 unless a test explicitly validates the archive layout.

## QML Design Tokens

Visual constants have exactly one owner each:

| Concern | Owner | Notes |
| --- | --- | --- |
| Colors / theme | `qml/AppPalette.qml` | Fill colors (`accentColor`, `successColor`…) vs. text-safe variants (`accentText`, `successText`…). Text-safe variants must meet WCAG AA (4.5:1). |
| Spacing, type, radii, breakpoints | `qml/AppStyle.qml` | Radii live only here. `AppPalette.radiusLarge/Medium/Small` are aliases pointing at `AppStyle`; do not add a second set. |
| User-facing copy | `qml/Strings.qml` | Page titles, nav items, primary actions, state words. Convert to `qsTr()` here when localization starts. |

Rules enforced by `tests/test_qml_design_tokens.py`:

- No raw numeric `radius:` for appearance; use an `AppStyle.radius*` token.
  (Dot/pill geometry such as `width / 2` and the decorative glow circles in
  `main.qml` are exempt.)
- Small-size status text must use the `*Text` color variants, never the vivid
  fill colors.
- Card shadows are gated by `AppStyle.shadowsEnabled` — never unconditional
  `layer.enabled: true`.
- Page `Loader`s must not combine `anchors.fill` with `x:`, and must not put a
  `Behavior on opacity` on the transition `opacity` binding: both silently break
  the binding, leaving page switching non-functional.

## Page Transition Model

Pages are `Loader`s inside `pageStack`, always alive once `markPageLoaded()` has
run. Visibility is driven by two bindings per loader:

```qml
opacity: appWindow.currentPageIndex === N ? 1 : 0
x: appWindow.pageX(N)
```

Both are plain bindings. Do not attach a `Behavior` to `opacity`, and do not add
`anchors.fill` to these loaders — either change disables the binding and the page
stops switching.

## Screenshot Regeneration

`tools/capture_readme_screenshots.py` regenerates `docs/screenshots/`. It boots
the real `main.qml` with real bridges, sets `QQuickStyle` to Material, disables
window-geometry restore, and grabs each page after it becomes visible. Re-run it
whenever the theme, layout, or page composition changes.

