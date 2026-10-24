"""Unit tests for the `remove` CLI command."""

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from twinspace.cli.main import cli
from twinspace.core.state import CloneRecord
from twinspace.executor.runner import CloneError


@pytest.fixture
def mock_record_user_dir() -> CloneRecord:
    return CloneRecord(
        clone_name="WeChat2",
        source_app="WeChat",
        source_path="/Applications/WeChat.app",
        bundle_id="com.tencent.xinWeChat",
        strategy="hard_clone",
        dest_path=str(Path.home() / "Applications" / "WeChat2.app"),
        data_dir=str(Path.home() / "TwinSpace" / "Data" / "WeChat2"),
        created_at="2026-08-18T20:00:00",
        proxy_enabled=False,
        proxy_summary="",
    )


@pytest.fixture
def mock_record_admin_dir() -> CloneRecord:
    return CloneRecord(
        clone_name="WeChat2",
        source_app="WeChat",
        source_path="/Applications/WeChat.app",
        bundle_id="com.tencent.xinWeChat",
        strategy="hard_clone",
        dest_path="/Applications/WeChat2.app",
        data_dir=str(Path.home() / "TwinSpace" / "Data" / "WeChat2"),
        created_at="2026-08-18T20:00:00",
        proxy_enabled=False,
        proxy_summary="",
    )


def test_remove_refuses_running_clone(mock_record_user_dir: CloneRecord, monkeypatch):
    monkeypatch.setattr("twinspace.core.cloning.manager.is_clone_running", lambda path: True)
    runner = CliRunner()
    with patch("twinspace.core.cloning.manager.StateManager.get", return_value=mock_record_user_dir):
        result = runner.invoke(cli, ["remove", "WeChat2", "--with-data"])
    assert result.exit_code == 1
    assert "quit" in result.output.lower()


def test_remove_not_found():
    runner = CliRunner()
    with patch("twinspace.core.cloning.manager.StateManager.get", return_value=None):
        result = runner.invoke(cli, ["remove", "WeChat2"])
        assert result.exit_code == 1
        assert "Error:" in result.output
        assert "Clone 'WeChat2' not found." in result.output


def test_remove_interactive_confirm_yes(mock_record_user_dir: CloneRecord):
    runner = CliRunner()
    with patch("twinspace.core.cloning.manager.StateManager.get", return_value=mock_record_user_dir), \
         patch("twinspace.core.cloning.manager.Runner.run") as mock_runner, \
         patch("twinspace.core.cloning.manager.StateManager.remove") as mock_remove:

        result = runner.invoke(cli, ["remove", "WeChat2"], input="y\n")
        assert result.exit_code == 0
        assert f"Also delete data directory {mock_record_user_dir.data_dir}?" in result.output
        assert "Success! Removed clone 'WeChat2'" in result.output

        mock_runner.assert_called_once()
        script, needs_admin = mock_runner.call_args[0]
        assert needs_admin is False
        assert f"rm -rf {mock_record_user_dir.dest_path}" in script
        assert f"rm -rf {mock_record_user_dir.data_dir}" in script

        mock_remove.assert_called_once_with("WeChat2")


def test_remove_interactive_confirm_no(mock_record_user_dir: CloneRecord):
    runner = CliRunner()
    with patch("twinspace.core.cloning.manager.StateManager.get", return_value=mock_record_user_dir), \
         patch("twinspace.core.cloning.manager.Runner.run") as mock_runner, \
         patch("twinspace.core.cloning.manager.StateManager.remove") as mock_remove:

        result = runner.invoke(cli, ["remove", "WeChat2"], input="n\n")
        assert result.exit_code == 0
        assert f"Also delete data directory {mock_record_user_dir.data_dir}?" in result.output
        assert "Success! Removed clone 'WeChat2'" in result.output

        mock_runner.assert_called_once()
        script, needs_admin = mock_runner.call_args[0]
        assert needs_admin is False
        assert f"rm -rf {mock_record_user_dir.dest_path}" in script
        assert mock_record_user_dir.data_dir not in script

        mock_remove.assert_called_once_with("WeChat2")


def test_remove_explicit_with_data(mock_record_user_dir: CloneRecord):
    runner = CliRunner()
    with patch("twinspace.core.cloning.manager.StateManager.get", return_value=mock_record_user_dir), \
         patch("twinspace.core.cloning.manager.Runner.run") as mock_runner, \
         patch("twinspace.core.cloning.manager.StateManager.remove") as mock_remove:

        result = runner.invoke(cli, ["remove", "WeChat2", "--with-data"])
        assert result.exit_code == 0
        assert "Also delete data directory" not in result.output
        assert "Success! Removed clone 'WeChat2'" in result.output

        mock_runner.assert_called_once()
        script, needs_admin = mock_runner.call_args[0]
        assert needs_admin is False
        assert f"rm -rf {mock_record_user_dir.dest_path}" in script
        assert f"rm -rf {mock_record_user_dir.data_dir}" in script

        mock_remove.assert_called_once_with("WeChat2")


def test_remove_explicit_keep_data(mock_record_user_dir: CloneRecord):
    runner = CliRunner()
    with patch("twinspace.core.cloning.manager.StateManager.get", return_value=mock_record_user_dir), \
         patch("twinspace.core.cloning.manager.Runner.run") as mock_runner, \
         patch("twinspace.core.cloning.manager.StateManager.remove") as mock_remove:

        result = runner.invoke(cli, ["remove", "WeChat2", "--keep-data"])
        assert result.exit_code == 0
        assert "Also delete data directory" not in result.output
        assert "Success! Removed clone 'WeChat2'" in result.output

        mock_runner.assert_called_once()
        script, needs_admin = mock_runner.call_args[0]
        assert needs_admin is False
        assert f"rm -rf {mock_record_user_dir.dest_path}" in script
        assert mock_record_user_dir.data_dir not in script

        mock_remove.assert_called_once_with("WeChat2")


def test_remove_explicit_no_with_data(mock_record_user_dir: CloneRecord):
    runner = CliRunner()
    with patch("twinspace.core.cloning.manager.StateManager.get", return_value=mock_record_user_dir), \
         patch("twinspace.core.cloning.manager.Runner.run") as mock_runner, \
         patch("twinspace.core.cloning.manager.StateManager.remove") as mock_remove:

        result = runner.invoke(cli, ["remove", "WeChat2", "--no-with-data"])
        assert result.exit_code == 0
        assert "Also delete data directory" not in result.output

        mock_runner.assert_called_once()
        script, needs_admin = mock_runner.call_args[0]
        assert f"rm -rf {mock_record_user_dir.dest_path}" in script
        assert mock_record_user_dir.data_dir not in script

        mock_remove.assert_called_once_with("WeChat2")


def test_remove_runner_error(mock_record_user_dir: CloneRecord):
    runner = CliRunner()
    with patch("twinspace.core.cloning.manager.StateManager.get", return_value=mock_record_user_dir), \
         patch("twinspace.core.cloning.manager.Runner.run", side_effect=CloneError("Permission denied")), \
         patch("twinspace.core.cloning.manager.StateManager.remove") as mock_remove:

        result = runner.invoke(cli, ["remove", "WeChat2", "--keep-data"])
        assert result.exit_code == 1
        assert "Error:" in result.output
        assert "Permission denied" in result.output

        mock_remove.assert_not_called()


def test_remove_admin_elevation_due_to_dest(mock_record_admin_dir: CloneRecord):
    runner = CliRunner()
    with patch("twinspace.core.cloning.manager.StateManager.get", return_value=mock_record_admin_dir), \
         patch("twinspace.core.cloning.manager.Runner.run") as mock_runner, \
         patch("twinspace.core.cloning.manager.StateManager.remove") as mock_remove:

        result = runner.invoke(cli, ["remove", "WeChat2", "--keep-data"])
        assert result.exit_code == 0
        assert "Success! Removed clone 'WeChat2'" in result.output

        mock_runner.assert_called_once()
        script, needs_admin = mock_runner.call_args[0]
        assert needs_admin is True
        assert f"rm -rf {mock_record_admin_dir.dest_path}" in script

        mock_remove.assert_called_once_with("WeChat2")


def test_remove_admin_elevation_due_to_data_dir():
    record = CloneRecord(
        clone_name="WeChat2",
        source_app="WeChat",
        source_path="/Applications/WeChat.app",
        bundle_id="com.tencent.xinWeChat",
        strategy="hard_clone",
        dest_path=str(Path.home() / "Applications" / "WeChat2.app"),
        data_dir="/Users/Shared/TwinSpace/Data/WeChat2",
        created_at="2026-08-18T20:00:00",
        proxy_enabled=False,
        proxy_summary="",
    )
    runner = CliRunner()
    with patch("twinspace.core.cloning.manager.StateManager.get", return_value=record), \
         patch("twinspace.core.cloning.manager.Runner.run") as mock_runner, \
         patch("twinspace.core.cloning.manager.StateManager.remove"):

        result = runner.invoke(cli, ["remove", "WeChat2", "--with-data"])
        assert result.exit_code == 0
        script, needs_admin = mock_runner.call_args[0]
        assert needs_admin is True
        assert f"rm -rf {record.dest_path}" in script
        import shlex
        assert f"rm -rf {shlex.quote(record.data_dir)}" in script



def test_remove_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["remove", "--help"])
    assert result.exit_code == 0
    assert "CLONE_NAME" in result.output
    assert "--with-data" in result.output
    assert "--keep-data" in result.output
