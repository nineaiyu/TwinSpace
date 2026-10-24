"""Tests for portable environment specs and data backups."""

from pathlib import Path

import pytest

from twinspace.core.environments.backup import create_backup, read_manifest, restore_backup
from twinspace.core.environments.spec import EnvironmentSpec
from twinspace.core.state import CloneRecord


def _record(name: str, bundle_id: str, data_dir: Path) -> CloneRecord:
    return CloneRecord(
        clone_name=name,
        source_app=name,
        source_path=f"/Applications/{name}.app",
        bundle_id=bundle_id,
        strategy="hard_clone",
        dest_path=str(data_dir.parent / f"{name}.app"),
        data_dir=str(data_dir),
        created_at="2026-10-24T00:00:00Z",
        env_group="phone1",
        env_dir=str(data_dir.parent),
    )


def test_environment_spec_roundtrip_and_validation():
    spec = EnvironmentSpec.from_yaml(
        """
version: 1
name: phone1
apps:
  - key: chrome
    clone_name: Chrome-phone1
  - key: zcode
    clone_name: ZCode-phone1
    env_overrides:
      TWINSPACE_BROWSER_APP_PATH: /tmp/Chrome.app
"""
    )
    assert spec.name == "phone1"
    assert [app.key for app in spec.apps] == ["chrome", "zcode"]
    assert spec.apps[1].env_overrides["TWINSPACE_BROWSER_APP_PATH"] == "/tmp/Chrome.app"

    roundtrip = EnvironmentSpec.from_yaml(spec.to_yaml())
    assert roundtrip.to_dict() == spec.to_dict()

    with pytest.raises(ValueError, match="Unsupported"):
        EnvironmentSpec.from_dict({"version": 99, "name": "x", "apps": [{"key": "chrome"}]})
    with pytest.raises(ValueError, match="Unknown app key"):
        EnvironmentSpec.from_dict({"version": 1, "name": "x", "apps": [{"key": "nope"}]})
    with pytest.raises(ValueError, match="Duplicate"):
        EnvironmentSpec.from_dict(
            {
                "version": 1,
                "name": "x",
                "apps": [{"key": "chrome"}, {"key": "chrome"}],
            }
        )


def test_backup_restore_roundtrip(tmp_path):
    zcode_data = tmp_path / "env" / "ZCode-work"
    chrome_data = tmp_path / "env" / "Browser"
    zcode_data.mkdir(parents=True)
    chrome_data.mkdir(parents=True)
    (zcode_data / "auth.json").write_text("original-token", encoding="utf-8")
    (chrome_data / "Cookies").write_text("original-cookie", encoding="utf-8")

    records = [
        _record("ZCode-work", "dev.zcode.app", zcode_data),
        _record("Chrome-work", "com.google.Chrome", chrome_data),
    ]
    archive = create_backup("phone1", records, output_path=tmp_path / "backup.tar.gz")
    assert archive.is_file()

    manifest = read_manifest(archive)
    assert manifest["environment"] == "phone1"
    assert [app["key"] for app in manifest["apps"]] == ["zcode", "chrome"]

    (zcode_data / "auth.json").write_text("broken", encoding="utf-8")
    (zcode_data / "newer.txt").write_text("keep-me", encoding="utf-8")

    restored, errors = restore_backup(archive, records)
    assert restored == ["zcode", "chrome"]
    assert errors == []
    assert (zcode_data / "auth.json").read_text(encoding="utf-8") == "original-token"
    assert (chrome_data / "Cookies").read_text(encoding="utf-8") == "original-cookie"
    assert (zcode_data / "newer.txt").exists()


def test_backup_rejects_unknown_archive(tmp_path):
    archive = tmp_path / "not-a-backup.tar.gz"
    import tarfile

    with tarfile.open(archive, "w:gz") as handle:
        handle.add(tmp_path, arcname="other")
    with pytest.raises(ValueError, match="Not a TwinSpace"):
        read_manifest(archive)


def test_manager_exports_environment(tmp_path):
    from twinspace.core.environments.manager import EnvironmentManager
    from twinspace.core.state import StateManager

    state = StateManager(state_file=tmp_path / "clones.yaml")
    data = tmp_path / "env"
    state.add(_record("Chrome-work", "com.google.Chrome", data / "Browser"))
    state.add(_record("ZCode-work", "dev.zcode.app", data / "ZCode-work"))
    manager = EnvironmentManager(state_manager=state)
    spec = manager.export_environment("phone1")
    assert spec.name == "phone1"
    assert [(app.key, app.clone_name) for app in spec.apps] == [
        ("chrome", "Chrome-work"),
        ("zcode", "ZCode-work"),
    ]
