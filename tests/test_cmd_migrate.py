"""Tests for legacy ATBClone data migration."""

from pathlib import Path

import yaml
from click.testing import CliRunner

from twinspace.cli.main import cli


def _write_legacy(root: Path) -> None:
    root.mkdir(parents=True)
    record = {
        "clone_name": "ZCode-work",
        "source_app": "ZCode",
        "source_path": "/Applications/ZCode.app",
        "bundle_id": "dev.zcode.app",
        "strategy": "hard_clone",
        "dest_path": str(root / "Apps" / "ZCode-work.app"),
        "data_dir": str(root / "Data" / "Environments" / "phone1" / "ZCode-work"),
        "created_at": "2026-10-24T00:00:00Z",
        "env_group": "phone1",
        "env_dir": str(root / "Data" / "Environments" / "phone1"),
    }
    (root / "clones.yaml").write_text(
        yaml.safe_dump([record], allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (root / "config.yaml").write_text(
        yaml.safe_dump({"base_dir": str(root), "language": "zh"}, allow_unicode=True),
        encoding="utf-8",
    )


def test_migrate_creates_compatibility_symlink(tmp_path):
    source = tmp_path / "ATBClone"
    target = tmp_path / "TwinSpace"
    _write_legacy(source)

    result = CliRunner().invoke(
        cli, ["migrate", "--from", str(source), "--to", str(target), "--yes"]
    )
    assert result.exit_code == 0, result.output
    assert target.is_symlink()
    assert target.resolve() == source.resolve()
    assert (target / "clones.yaml").is_file()


def test_migrate_move_rewrites_state_and_config(tmp_path):
    source = tmp_path / "ATBClone"
    target = tmp_path / "TwinSpace"
    _write_legacy(source)

    result = CliRunner().invoke(
        cli,
        ["migrate", "--from", str(source), "--to", str(target), "--move", "--yes"],
    )
    assert result.exit_code == 0, result.output
    assert target.is_dir()
    assert not source.exists()

    records = yaml.safe_load((target / "clones.yaml").read_text(encoding="utf-8"))
    assert records[0]["dest_path"].startswith(str(target))
    assert records[0]["data_dir"].startswith(str(target))
    assert records[0]["env_dir"].startswith(str(target))
    assert (target / "clones.yaml.pre-twinspace.bak").is_file()

    config = yaml.safe_load((target / "config.yaml").read_text(encoding="utf-8"))
    assert config["base_dir"] == str(target)


def test_migrate_refuses_existing_target(tmp_path):
    source = tmp_path / "ATBClone"
    target = tmp_path / "TwinSpace"
    _write_legacy(source)
    target.mkdir()

    result = CliRunner().invoke(
        cli, ["migrate", "--from", str(source), "--to", str(target), "--yes"]
    )
    assert result.exit_code == 1
    assert "already exists" in result.output
