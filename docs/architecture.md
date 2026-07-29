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

Compatibility wrappers remain in `translate_bridge.py` for maintained imports. The primary
translation worker still lives beside the bridge because it currently updates task history through
bridge callbacks; it should move only after those callbacks become an explicit protocol.

## Threading

- EPUB translation runs in a QML worker `QThread`.
- Batch requests use a bounded `ThreadPoolExecutor`.
- Providers eligible for fast batch mode can use one reusable `httpx.AsyncClient` hosted by a
  dedicated event-loop thread.
- SQLite uses WAL mode and buffered writes; explicit checkpoints run at task boundaries.

## Compatibility Rules

- Do not import QML types into core translation modules.
- Keep provider-specific routing data in `provider_registry.py`.
- Keep response parsing independent from network clients.
- Preserve exports from `translator.py` until all maintained entry points use the new modules.
- Add direct module tests before replacing a compatibility wrapper.

## Version Ownership

- `experimental/qml_v4` is the only active desktop UI and the only release target.
- `archived/qt_v3` is a manual fallback for critical compatibility checks.
- `archived/tk_v1` is frozen source history.
- Current modules must not import archived UI code.
- Release workflows, installers and current tests target QML/V4 unless a test explicitly validates the archive layout.
