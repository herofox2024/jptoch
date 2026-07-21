import argparse
import re
import subprocess
from pathlib import Path


def run_git(args):
    try:
        result = subprocess.run(
            ["git", *args],
            check=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def normalize_version(value):
    version = str(value or "").strip()
    return version[1:] if version.lower().startswith("v") else version


def extract_changelog_section(changelog_path, version):
    if not changelog_path.exists():
        return ""

    text = changelog_path.read_text(encoding="utf-8")
    escaped = re.escape(normalize_version(version))
    pattern = re.compile(
        rf"^##\s+\[?v?{escaped}\]?[^\n]*\n(?P<body>.*?)(?=^##\s+|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        return ""
    return match.group("body").strip()


def latest_previous_tag(current_tag):
    current_version = parse_version(normalize_version(current_tag))
    tags = run_git(["tag", "--sort=-creatordate"]).splitlines()
    current_names = {current_tag, current_tag.lower(), normalize_version(current_tag), f"v{normalize_version(current_tag)}"}
    versioned_tags = []
    for tag in tags:
        tag = tag.strip()
        if not tag or tag in current_names:
            continue
        version = parse_version(normalize_version(tag))
        if version and current_version and version < current_version:
            versioned_tags.append((version, tag))
    if versioned_tags:
        return sorted(versioned_tags, reverse=True)[0][1]
    for tag in tags:
        tag = tag.strip()
        if tag and tag not in current_names:
            return tag
    return ""


def parse_version(value):
    match = re.fullmatch(r"(\d+)\.(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(value or "").strip())
    if not match:
        return None
    parts = [int(part or 0) for part in match.groups()]
    return tuple(parts)


def commit_lines(previous_tag, current_ref):
    rev_range = f"{previous_tag}..{current_ref}" if previous_tag else current_ref
    output = run_git(["log", "--pretty=format:%h %s", rev_range])
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines


def build_release_notes(version, previous_tag, out_path):
    normalized = normalize_version(version)
    current_tag = f"v{normalized}"
    previous = previous_tag or latest_previous_tag(current_tag)
    changelog = extract_changelog_section(Path("CHANGELOG.md"), normalized)
    commits = commit_lines(previous, "HEAD")

    parts = [f"# AI日译中(EPUB) V{normalized}", ""]
    if changelog:
        parts.extend(["## 本版本修改内容", "", changelog, ""])
    else:
        parts.extend(
            [
                "## 本版本修改内容",
                "",
                "- 本版本未在 CHANGELOG.md 中填写人工发布说明。",
                "- 如需发布页展示更清晰的修改内容，请在发布前添加 `## v%s` 小节。" % normalized,
                "",
            ]
        )

    parts.extend(["## 构建产物", "", "- Windows 安装包：`dist/installer/*.exe`", "- 便携压缩包：`dist/*.zip`", ""])

    if commits:
        title = "## 提交摘要"
        if previous:
            title += f"（{previous}..{current_tag}）"
        parts.extend([title, ""])
        parts.extend(f"- {line}" for line in commits[:80])
        if len(commits) > 80:
            parts.append(f"- ... 另有 {len(commits) - 80} 条提交")
        parts.append("")

    out_path.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--previous-tag", default="")
    parser.add_argument("--out", default="release_notes.md")
    args = parser.parse_args()
    build_release_notes(args.version, args.previous_tag, Path(args.out))


if __name__ == "__main__":
    main()
