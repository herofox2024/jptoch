<div align="center">

<img src="assets/logo.png" width="180" alt="AI Japanese-to-Chinese EPUB Translator">

# AI Japanese-to-Chinese EPUB Translator

An LLM-powered desktop tool for translating Japanese EPUB books into Simplified Chinese. It is designed for light novels, mystery novels, sci-fi novels, and other Japanese e-book workflows, with glossary management, resumable translation, post-translation proofreading, and Windows installers.

![Version](https://img.shields.io/badge/version-V4.1-2f6f5f)
![UI](https://img.shields.io/badge/UI-PySide6%20%2B%20QML-203a43)
![Platform](https://img.shields.io/badge/platform-Windows-c47f2c)
![Status](https://img.shields.io/badge/status-stable-brightgreen)

**Language:** [简体中文](README.md) | [English](README_EN.md)

**Current mainline:** QML/V4.1  
**Stable fallback:** Qt V3.2.1

</div>

---

## Contents

| Section | Description |
|---|---|
| [Version Strategy](#version-strategy) | Mainline, fallback, and legacy maintenance status |
| [Features](#features) | EPUB translation, glossary, cache resume, proofreading |
| [Quick Start](#quick-start) | Installer and source-based startup |
| [Workflow](#workflow) | From selecting an EPUB to generating a translated EPUB |
| [API Configuration](#api-configuration) | Supported model providers and free-tier recommendations |
| [Translation Settings](#translation-settings) | Performance, style prompts, proofreading, glossary |
| [Cache And Resume](#cache-and-resume) | Pause, resume, stop, and re-translate behavior |
| [Project Structure](#project-structure) | Major directories and entry points |
| [Packaging](#packaging) | PyInstaller and Inno Setup packaging |
| [GitHub Auto Release](#github-auto-release) | Build and publish installers through GitHub Actions |
| [FAQ](#faq) | Rate limits, cache, TOC translation, startup speed |
| [Release Notes](#release-notes) | V4.1 and historical summary |

---

## Version Strategy

| Version | Entry Point | Status | Notes |
|---|---|---|---|
| QML/V4.1 | `experimental/qml_v4/main.py` | Current mainline | Main desktop version with architecture and performance upgrades |
| Qt V3.2.1 | `main_qt.py` | Stable fallback | Maintenance mode, only P0/P1 issues are expected to be fixed |
| Tk legacy | `app.py` | Frozen compatibility | Kept for compatibility tests and blocking fixes only |

`experimental/qml_v4/` is a historical directory name. It is still used in V4.1 to avoid breaking existing packaging scripts, installer paths, and user workflows.

---

## Features

- **Japanese-to-Chinese EPUB translation**: translates body text, headings, links, lists, quotes, and common HTML content while preserving EPUB structure.
- **TOC and link translation**: translates NCX/nav titles and short in-book TOC link text while preserving `href` navigation.
- **Multiple LLM providers**: supports DeepSeek, Doubao, Sakura, Gemini, Zhipu GLM, Wenxin/Qianfan, and custom OpenAI-compatible endpoints.
- **Resumable cache**: translated text is cached, so interrupted jobs can resume without re-translating completed content.
- **Cross-model cache reuse option**: switching providers can reuse verified translations when enabled, or re-translate after clearing the EPUB cache.
- **Glossary management**: enable/disable glossary, import JSON, incremental import, duplicate filtering, direct editing, source display, and automatic term extraction.
- **Glossary policies**: supports default policy, force, reference-only, context-only, preserve-source, and ignore-proofread modes.
- **Post-translation proofreading**: detects Japanese residue, suspicious translations, and glossary mismatches. The UI shows source text, draft, revised text, and trigger reason.
- **Novel style prompts**: configurable genre and narrative tone affect both first-pass translation and proofreading prompts.
- **Prompt preview and custom instructions**: preview the active prompt locally and add project-specific instructions without calling an API.
- **Few-shot style guidance**: optional short examples for genre and tone guidance with limited prompt overhead.
- **Context-aware short-text cache**: short Japanese fragments are cached with nearby context to reduce wrong reuse across different scenes.
- **Status monitoring**: shows progress, translated characters, total characters, estimated remaining time, speed, API requests, token usage, and failures.
- **Quality self-check report**: generates a final local report after completion, without extra API calls.
- **EPUB compatibility improvements**: handles `body/br` layouts, short TOC pages, Ruby annotations, and image placeholder text.
- **Windows installers**: supports slim onedir packaging and Inno Setup installers.
- **In-app updates**: checks the latest GitHub Release and can download and launch the installer.

---

## Quick Start

### Option 1: Use the Windows installer

Packaged installers are expected under:

```text
dist/installer/AI日译中(EPUB)V4.1 安装程序.exe
```

Install it, then launch the app from the Start Menu or desktop shortcut.

### Option 2: Run QML/V4.1 from source

```powershell
pip install -r experimental/qml_v4/requirements.txt
python experimental/qml_v4/main.py
```

### Option 3: Run the stable Qt V3.2.1 fallback

```powershell
pip install -r requirements.txt
python main_qt.py
```

### Option 4: Run the frozen Tk legacy entry

```powershell
python app.py
```

The Tk entry is frozen and is not recommended for daily use.

---

## Workflow

1. Open the app and go to the **Task** page.
2. Drag in or select a Japanese EPUB file.
3. Confirm the output EPUB path.
4. Go to the **API** page, choose a provider, and enter API Key, Base URL, and model name.
5. Go to **Settings**, choose performance parameters, novel style, and proofreading options.
6. If fixed terminology is required, go to **Glossary**, enable the glossary, then import or edit terms.
7. Return to **Task** and start translation.
8. Monitor progress, remaining time, speed, API usage, and proofreading details on the **Status** page.
9. After completion, inspect the output EPUB with an EPUB reader, especially the TOC, chapter links, and early pages.

---

## API Configuration

| Provider | Typical Use | Notes |
|---|---|---|
| DeepSeek | Recommended primary provider | Fast and stable for long EPUBs |
| Doubao | General translation | Requires Volcengine API Key |
| Sakura | Local/self-hosted service | OpenAI-compatible local endpoint |
| Gemini | Free or paid API | Free tier is rate-limited and does not support some thinking parameters |
| Zhipu GLM | Free or paid API | Free tier requires very conservative settings |
| Wenxin/Qianfan | Compatible provider | Requires a valid API Key, Base URL, and model name |
| Custom | Custom OpenAI-compatible endpoint | Useful for proxy gateways or other compatible services |

### Free-tier recommendations

Free APIs are usable, but concurrency and batch size must be conservative.

| Scenario | Workers | Batch Size | Max Single Text | Max Batch Text | Timeout |
|---|---:|---:|---:|---:|---:|
| Zhipu GLM free tier | `1` | `2-3` | around `200` chars | around `200` chars | `300` sec |
| Gemini free tier | `1` | `2-3` | around `200` chars | around `200` chars | `300` sec |
| DeepSeek paid tier | can be higher | can be higher | can be higher | can be higher | adjust by network |

Gemini free tier may still trigger rate limits even with GLM-like conservative settings. For long EPUBs, a paid model is strongly recommended.

---

## Translation Settings

### Performance

V4.1 uses Slider + SpinBox controls and provides model-specific presets.

| Parameter | Purpose | Recommendation |
|---|---|---|
| Workers | Number of concurrent API requests | Use `1` for free models; increase only within paid quota |
| Batch size | Number of text blocks per API request | `2-3` for free models; higher for stable paid models |
| Max single text | Split threshold for long text blocks | Increase for long narrative passages if stable |
| Max batch text | Total characters per batch request | Keep low for free models |
| API timeout | Wait time for a single request | Use `300` seconds for slow/free providers |

### Novel style prompts

The app supports:

- **Genre**: auto-detect, general novel, mystery, historical mystery, sci-fi, fantasy.
- **Tone**: auto-detect, neutral, light-novel tone, literary tone.

Style settings affect both first-pass translation and post-translation proofreading. Auto detection is local and uses title, TOC, and sample text; it does not consume API tokens.

### Prompt preview and custom instructions

The Settings page can generate a local prompt preview. It does not call any model. You can add custom instructions, for example:

```text
For historical mystery novels, keep period-specific titles and avoid modern internet slang.
```

Custom instructions are appended with hard safety constraints: do not add plot, do not delete information, keep paragraph structure, and do not output explanations.

### Post-translation proofreading

Proofreading focuses on repairs, not unrestricted rewriting:

- Japanese residue.
- Glossary mismatch.
- Obvious missing translation or abnormal output.
- Whether the revised text preserves the original meaning.

Using a free model for proofreading increases both token usage and total translation time, and may trigger more rate limits.

### Glossary

Default glossary path:

```text
~/.epub_translator/glossary.json
```

Simple example:

```json
{
  "能面島": "能面岛",
  "女学生探偵シリーズ": "女学生侦探系列",
  "魔王": "魔王"
}
```

The Glossary page supports:

- Enable or disable glossary.
- Import glossary JSON.
- Incremental import with duplicate filtering.
- Direct term editing.
- Source display: auto-extracted, manually imported, or unknown source.
- Policy selection: default, force, reference-only, context-only, preserve-source, ignore proofreading.

Policy meanings:

- `Default`: automatic behavior based on category and source.
- `Force`: proofreading checks whether a standalone source match uses the required translation.
- `Reference-only`: only used as a prompt hint; proofreading will not force replacement.
- `Context-only`: shown to the model but should only be used when context matches.
- `Preserve-source`: keep the original source term in the Chinese output.
- `Ignore proofreading`: excluded from prompts and proofreading checks.

---

## Cache And Resume

Default cache path:

```text
~/.epub_translator/cache.json
```

Behavior:

- **Pause** keeps completed translations and allows resume.
- **Stop** ends the current task and clears the current UI runtime state.
- Cached text is reused on the next run and does not call the API again.
- To re-translate with a different model, clear the current EPUB cache or disable cross-model cache reuse.
- After a 429 rate-limit event, lower workers/batch size and resume; completed content should hit the cache.

Log path:

```text
~/.epub_translator/logs/app-YYYYMMDD.log
```

---

## Project Structure

```text
.
├─ experimental/qml_v4/        # QML/V4.1 current mainline
│  ├─ main.py                  # V4 entry point (PySide6 + QML)
│  ├─ qml/                     # QML pages, themes, components
│  ├─ backend/                 # Python-QML bridge layer
│  ├─ assets/                  # V4 icon assets
│  └─ EPUBTranslator*.spec     # PyInstaller specs
├─ ui/qt_app.py                # Qt V3.2.1 fallback UI
├─ main_qt.py                  # Qt V3.2.1 entry point
├─ app.py                      # Frozen Tk legacy entry
├─ translator.py               # Core translation engine
├─ epub_io.py                  # EPUB reading, writing, TOC and layout handling
├─ style_detector.py           # Local novel genre/tone detection
├─ glossary_store.py           # Glossary loading, merging, filtering, indexing
├─ cache_store.py              # Cache helpers and atomic JSON writes
├─ text_utils.py               # Translatable-text detection
├─ installer/                  # Inno Setup scripts
└─ tests/                      # Regression tests
```

Core flow:

```text
QML UI -> TranslateBridge -> QThread Worker -> epub_io -> JaZhTranslator
       -> cache lookup -> batching -> LLM API -> quality repair/proofread
       -> write translated text back to EPUB -> save output EPUB
```

---

## Packaging

### PyInstaller slim onedir build

```powershell
python -m PyInstaller experimental\qml_v4\EPUBTranslator_onedir_slim.spec --noconfirm
```

Output:

```text
dist/AI日译中(EPUB)V4.1_slim/
```

### Inno Setup installer

Compile `installer/EPUB日译中V4.0_slim.iss` with Inno Setup 6.

Common local path:

```powershell
& "C:\Users\HUAWEI\AppData\Local\Programs\Inno Setup 6\ISCC.exe" "installer\EPUB日译中V4.0_slim.iss"
```

Expected installer:

```text
dist/installer/AI日译中(EPUB)V4.1 安装程序.exe
```

---

## GitHub Auto Release

The project includes a GitHub Actions workflow:

```text
.github/workflows/release-qml-v4.yml
```

Behavior:

- Pushing a `v*` tag builds QML/V4.1 on a Windows runner.
- It creates a slim onedir portable package and an Inno Setup installer.
- It creates a GitHub Release and uploads `.exe` and `.zip` assets.
- Manual `workflow_dispatch` uploads Actions artifacts but does not automatically publish a Release.

Example:

```powershell
git tag v4.1.0
git push origin v4.1.0
```

In-app update depends on public GitHub Release assets. For private repositories, users must log in to GitHub or use a custom update source.

---

## FAQ

### Why is startup slower than a native installer app?

QML/PySide6, Python runtime initialization, configuration loading, and deferred module imports add startup cost. V4 has already added a splash screen, lazy-loaded pages, delayed glossary loading, and lazy heavy-module imports.

### Why do free models often return 429 or timeout?

Free APIs usually limit request frequency, concurrency, tokens, or daily quota. Use workers `1`, batch size `2-3`, around `200` characters per item/batch, and a `300` second timeout.

### Why does output stay the same after switching models?

The cache is likely being reused. Clear the current EPUB cache or disable cross-model cache reuse if you want a full re-translation.

### Why does a TOC page still contain Japanese?

Some EPUBs store TOC-like pages as regular short in-book links rather than standard NCX/nav entries. V4 translates many of these, but unusual layouts may still need manual inspection.

### Why is the estimated character count too small?

Some EPUBs use `body/br` or non-standard HTML layouts instead of paragraphs. V4 includes fallback extraction logic for these cases.

### Why does proofreading sometimes barely change the draft?

Proofreading is designed to fix residue, glossary mismatch, missing translation, and obvious issues. It is not a default free-polishing pass.

### What does "API response missing choices" mean?

The provider response is not an OpenAI-compatible `chat/completions` payload. Common causes are wrong Base URL, unavailable model name, authentication failure, insufficient balance, or a provider error page.

---

## Regression Checklist

Before release, test at least:

- A normal chapter-based EPUB.
- A `body/br` or non-standard layout EPUB.
- A large-glossary EPUB.

Check:

- Output EPUB opens correctly.
- TOC and chapter links work.
- Early pages do not contain obvious Japanese residue.
- Glossary terms are consistent.
- Pause, resume, and stop behave as expected.
- Logs do not show continuous API errors.

---

## Release Notes

### V4.1

- QML/V4 is promoted to the V4.1 mainline.
- Adds architecture improvements: Toast notifications, translation pipeline, service container, theme registry, smart batching, context window, pre-translation rules, text cache, proofreading tiers, dual-model pipeline, and streaming-oriented processing.
- Adds iOS26 glass theme, dark theme fixes, navigation and status-page visual improvements.
- Adds splash screen, lazy-loaded pages, delayed glossary loading, and lazy heavy-module imports.
- Adds stop button, resumable pause, estimated duration, and estimated remaining time.
- Adds Wenxin/Qianfan provider.
- Adds novel style settings and local style detection for translation and proofreading prompts.
- Adds prompt preview, custom instructions, few-shot style guidance, and final quality self-check report.
- Improves `body/br` EPUB extraction and short in-book TOC link translation.
- Provides slim onedir and Inno Setup packaging.

### Qt V3.2.1

- Kept as the stable fallback.
- Maintenance mode: only severe P0/P1 issues are expected to be fixed.
- Retains mature API configuration, glossary, cache, pause/resume, and monitoring features.

### Historical Summary

- V3.2: Qt UI mainline with glossary, cache resume, proofreading details, performance settings, and installers.
- V3.1: Introduced Qt version and gradually replaced Tk UI.
- V2.x: Multi-page desktop UI, status monitoring, and basic packaging.
- V1.x: EPUB translation, API calls, cache, glossary, and basic GUI.

---

## License

This project is intended for personal learning and local EPUB translation workflows. Respect book copyrights, API provider terms, and applicable laws. Do not distribute unauthorized translated EPUBs.
