"""Test project dependencies declarations."""

import tomllib
from pathlib import Path


def test_requests_dependency_declared():
    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    gui_deps = data.get("project", {}).get("optional-dependencies", {}).get("gui", [])
    assert any("requests" in dep for dep in gui_deps), "requests must be in project.optional-dependencies.gui"

    briefcase_reqs = data.get("tool", {}).get("briefcase", {}).get("app", {}).get("twinspace", {}).get("requires", [])
    assert any("requests" in req for req in briefcase_reqs), "requests must be in tool.briefcase.app.twinspace.requires"
