from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release-qml-v4.yml"


def _workflow_python_version() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r'python-version:\s*"([^"]+)"', text)
    assert match, "release workflow does not pin a python-version"
    return match.group(1)


def _python_version_file() -> str:
    path = ROOT / ".python-version"
    assert path.is_file(), ".python-version is missing"
    return path.read_text(encoding="utf-8").strip()


def _ruff_target_version() -> str:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    target = config["tool"]["ruff"]["target-version"]
    assert target, "pyproject.toml does not set tool.ruff.target-version"
    return target


def test_python_version_is_consistent_across_environments():
    """CI, local development and ruff must agree on the same Python minor version.

    A mismatch means local tests can pass while the release build fails, which is
    only discovered at release time.
    """
    workflow = _workflow_python_version()
    local = _python_version_file()
    ruff_target = _ruff_target_version()

    # .python-version may pin a full version (3.12.13); compare minor versions only.
    local_minor = ".".join(local.split(".")[:2])
    workflow_minor = ".".join(workflow.split(".")[:2])
    ruff_minor = ruff_target.removeprefix("py")
    ruff_minor = f"{ruff_minor[0]}.{ruff_minor[1:]}"

    assert workflow_minor == local_minor, (
        f"CI runs Python {workflow_minor} but .python-version pins {local_minor}"
    )
    assert ruff_minor == local_minor, (
        f"ruff targets Python {ruff_minor} but .python-version pins {local_minor}"
    )


def test_workflow_python_version_is_supported():
    """Guard against silently pinning an unsupported or prerelease interpreter."""
    workflow = _workflow_python_version()
    major, minor = (int(part) for part in workflow.split(".")[:2])
    assert (major, minor) >= (3, 11), "project requires Python 3.11 or newer"
    assert major == 3, "unexpected major version"


def test_local_interpreter_is_not_a_prerelease():
    """Local development should not run on a beta/rc interpreter.

    Tests on a prerelease can pass while the release build on a stable interpreter
    behaves differently.
    """
    version = sys.version_info
    assert version.releaselevel == "final", (
        f"local interpreter is a prerelease: {sys.version}"
    )
