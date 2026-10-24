from unittest.mock import patch

from click.testing import CliRunner

from twinspace.cli.cmd_doctor import doctor
from twinspace.cli.cmd_remove import remove
from twinspace.core.logger import read_logs, setup_logging
from twinspace.core.state import CloneRecord, StateManager

runner = CliRunner()


def test_cli_doctor_logging(tmp_path):
    log_file = tmp_path / "twinspace.log"
    setup_logging(log_file=log_file)

    with patch("subprocess.check_output", return_value="/usr/bin/codesign"):
        result = runner.invoke(doctor)
        assert result.exit_code == 0

    content = read_logs(log_file=log_file)
    assert "[INFO]" in content
    assert "doctor" in content.lower() or "check" in content.lower()


def test_cli_remove_logging(tmp_path):
    log_file = tmp_path / "twinspace.log"
    setup_logging(log_file=log_file)

    state_file = tmp_path / "clones.yaml"
    sm = StateManager(state_file=state_file)
    record = CloneRecord(
        clone_name="TestApp2",
        source_app="TestApp",
        source_path="/Applications/TestApp.app",
        bundle_id="com.test.app",
        strategy="soft_clone",
        dest_path=str(tmp_path / "TestApp2.app"),
        data_dir=str(tmp_path / "Data"),
        created_at="2026-08-20T00:00:00Z",
    )
    sm.add(record)

    with patch("twinspace.core.cloning.manager.StateManager", return_value=sm), \
         patch("twinspace.core.cloning.manager.Runner.run"):
        result = runner.invoke(remove, ["TestApp2", "--no-with-data"])
        assert result.exit_code == 0

    content = read_logs(log_file=log_file)
    assert "TestApp2" in content
    assert "remove" in content.lower() or "removed" in content.lower()
