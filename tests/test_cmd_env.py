"""CLI tests for environment management commands."""

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from twinspace.cli.main import cli
from twinspace.core.environments import apps as apps_module
from twinspace.core.environments.apps import EnvironmentApp
from twinspace.core.environments.spec import EnvironmentAppSpec, EnvironmentSpec


class FakeManager:
    def __init__(self, apps=None, environments=None, exported=None):
        self.apps = apps or []
        self.environments = environments or []
        self.exported = exported
        self.created = None

    def available_apps(self):
        return list(self.apps)

    def list_environments(self):
        return list(self.environments)

    def environment(self, name):
        for item in self.environments:
            if item.name == name:
                return item
        return None

    def export_environment(self, name):
        if self.exported is None:
            raise ValueError(f"Environment {name!r} not found.")
        return self.exported

    async def create_environment(self, name, app_keys, on_progress=None, clone_names=None, env_overrides=None):
        self.created = {
            "name": name,
            "apps": list(app_keys),
            "clone_names": clone_names or {},
        }
        return []

    async def import_environment(self, spec, target_name=None, on_progress=None):
        self.created = {"name": target_name or spec.name, "apps": [a.key for a in spec.apps]}
        return []

    def backup_environment(self, name, output_path=None):
        return Path("/tmp/fake-backup.tar.gz")

    def open_environment(self, name, app_keys=None):
        return []


def _app(tmp_path: Path, key: str, label: str) -> EnvironmentApp:
    app_dir = tmp_path / f"{label}.app"
    app_dir.mkdir()
    return EnvironmentApp(key, label, (f"com.example.{key}",), app_dir, label)


def test_env_templates_lists_builtin_templates():
    result = CliRunner().invoke(cli, ["env", "templates"])
    assert result.exit_code == 0
    assert "phone" in result.output
    assert "dev" in result.output
    assert "all" in result.output


def test_env_list_empty():
    fake = FakeManager()
    with patch("twinspace.cli.cmd_env._manager", return_value=fake):
        result = CliRunner().invoke(cli, ["env", "list"])
    assert result.exit_code == 0
    assert "No environments yet" in result.output


def test_env_export_to_stdout():
    spec = EnvironmentSpec(
        name="phone1",
        apps=[EnvironmentAppSpec(key="chrome", clone_name="Chrome-phone1")],
    )
    fake = FakeManager(exported=spec)
    with patch("twinspace.cli.cmd_env._manager", return_value=fake):
        result = CliRunner().invoke(cli, ["env", "export", "phone1"])
    assert result.exit_code == 0
    assert "version: 1" in result.output
    assert "clone_name: Chrome-phone1" in result.output


def test_env_create_dry_run(tmp_path):
    apps = [_app(tmp_path, "chrome", "Chrome"), _app(tmp_path, "zcode", "ZCode")]
    fake = FakeManager(apps=apps)
    with patch("twinspace.cli.cmd_env._manager", return_value=fake), patch.object(
        apps_module, "KNOWN_APPS", tuple(apps)
    ):
        result = CliRunner().invoke(
            cli,
            [
                "env",
                "create",
                "phone1",
                "--apps",
                "chrome,zcode",
                "--clone-name",
                "zcode=ZCode-custom",
                "--dry-run",
            ],
        )
    assert result.exit_code == 0
    assert "Chrome-phone1" in result.output
    assert "ZCode-custom" in result.output
    assert fake.created is None


def test_env_create_defaults_skip_opt_in_apps(tmp_path):
    chrome = _app(tmp_path, "chrome", "Chrome")
    intl_dir = tmp_path / "CodeBuddyAI.app"
    intl_dir.mkdir()
    intl = EnvironmentApp(
        "codebuddy_ai",
        "CodeBuddy AI",
        ("com.tencent.codebuddy",),
        intl_dir,
        "CodeBuddyAI",
        default_selected=False,
    )
    fake = FakeManager(apps=[chrome, intl])
    with patch("twinspace.cli.cmd_env._manager", return_value=fake), patch.object(
        apps_module, "KNOWN_APPS", (chrome, intl)
    ):
        result = CliRunner().invoke(cli, ["env", "create", "phone1", "--dry-run"])
    assert result.exit_code == 0
    assert "Chrome (chrome)" in result.output
    assert "CodeBuddy AI" not in result.output


def test_env_import_dry_run(tmp_path):
    spec_file = tmp_path / "phone.yaml"
    spec_file.write_text(
        "version: 1\nname: phone1\napps:\n  - key: chrome\n    clone_name: Chrome-phone1\n",
        encoding="utf-8",
    )
    fake = FakeManager()
    with patch("twinspace.cli.cmd_env._manager", return_value=fake):
        result = CliRunner().invoke(cli, ["env", "import", str(spec_file), "--dry-run"])
    assert result.exit_code == 0
    assert "chrome" in result.output
    assert "new" in result.output
    assert fake.created is None


def test_env_backup_command():
    fake = FakeManager()
    with patch("twinspace.cli.cmd_env._manager", return_value=fake):
        result = CliRunner().invoke(cli, ["env", "backup", "phone1"])
    assert result.exit_code == 0
    assert "/tmp/fake-backup.tar.gz" in result.output
