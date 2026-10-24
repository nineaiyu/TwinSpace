"""Unit tests for twinspace version command and options."""

from click.testing import CliRunner

from twinspace import __version__
from twinspace.cli.main import cli


def test_cli_version_flag_long():
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_cli_version_flag_short():
    runner = CliRunner()
    result = runner.invoke(cli, ["-v"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_cmd_version_detailed():
    runner = CliRunner()
    result = runner.invoke(cli, ["version"])
    assert result.exit_code == 0
    assert "TwinSpace System Information" in result.output
    assert f"v{__version__}" in result.output
    assert "Python Runtime" in result.output
    assert "Platform" in result.output
    assert "State Storage" in result.output
    assert "TwinSpace/clones.yaml" in result.output
    assert "Data Directory" in result.output
    assert "TwinSpace/Data" in result.output


def test_cmd_version_short_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["version", "--short"])
    assert result.exit_code == 0
    assert result.output.strip() == __version__

    result_s = runner.invoke(cli, ["version", "-s"])
    assert result_s.exit_code == 0
    assert result_s.output.strip() == __version__
