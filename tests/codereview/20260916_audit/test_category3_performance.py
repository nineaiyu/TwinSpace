"""Tests for Category 3: Performance & Scalability Optimizations."""


from twinspace.core.argument_prober import BinaryArgumentProber
from twinspace.core.clone_inspector import CloneInspector
from twinspace.core.clone_task import CloneTask
from twinspace.core.engines import HardCloneEngine, SoftCloneEngine
from twinspace.core.models import AppInfo
from twinspace.core.state import CloneRecord
from twinspace.recipes.models import Recipe


def test_extract_binary_strings_fast(tmp_path):
    """Verify extract_binary_strings extracts printable strings accurately."""
    bin_file = tmp_path / "test_bin"
    content = b"\x00\x01\x02Hello_World\x00\xff--user-data-dir\x00SomeRandomString\x00"
    bin_file.write_bytes(content)

    strings = BinaryArgumentProber.extract_binary_strings(bin_file, min_len=4)
    assert "Hello_World" in strings
    assert "--user-data-dir" in strings
    assert "SomeRandomString" in strings


def test_probe_data_dir_argument_fast(tmp_path):
    """Verify probe_data_dir_argument detects data flag with SIMD pre-filter."""
    bin_file = tmp_path / "chrome_mock"
    content = b"\x00" * 100 + b"--user-data-dir=/tmp/foo" + b"\x00" * 100
    bin_file.write_bytes(content)

    res = BinaryArgumentProber.probe_data_dir_argument(bin_file)
    assert res.flag is not None
    assert res.flag == "--user-data-dir"

    # Non-matching binary
    bin_no_match = tmp_path / "empty_mock"
    bin_no_match.write_bytes(b"\x00" * 500 + b"just some standard strings here" + b"\x00" * 500)
    res_no = BinaryArgumentProber.probe_data_dir_argument(bin_no_match)
    assert res_no.flag is None


def test_clone_inspector_skips_macho_binary(tmp_path):
    """Verify clone_inspector skips reading Mach-O binary files as text."""
    app_dir = tmp_path / "Test.app"
    macos_dir = app_dir / "Contents" / "MacOS"
    macos_dir.mkdir(parents=True)

    # 1. Mach-O executable
    macho_bin = macos_dir / "Test"
    macho_bin.write_bytes(b"\xcf\xfa\xed\xfe" + b"\x00" * 1000)

    # 2. Wrapper script
    wrapper = macos_dir / "Test_wrapper"
    wrapper.write_text('#!/bin/bash\nexport DATA_DIR="/tmp/test"\nexec "/Applications/Test.app/Contents/MacOS/Test" --data "/tmp/test"\n')

    rec = CloneRecord(
        clone_name="test_clone",
        source_app="Test",
        source_path="/Applications/Test.app",
        bundle_id="com.example.test",
        strategy="soft_clone",
        dest_path=str(app_dir),
        data_dir="/tmp/test",
        created_at="2026-09-16T12:00:00",
    )

    details = CloneInspector.inspect(rec)
    assert details.exec_command != ""
    assert "--data" in details.launch_args or "DATA_DIR" in details.env_vars


def test_apfs_copy_command_in_scripts(tmp_path):
    """Verify that both SoftCloneEngine and HardCloneEngine generate cp -Rc with fallback."""
    src_app = tmp_path / "Source.app"
    src_app.mkdir(parents=True)
    (src_app / "Contents").mkdir()
    (src_app / "Contents" / "Info.plist").write_bytes(b"dummy plist")

    app_info = AppInfo(
        path=src_app,
        bundle_id="com.example.source",
        app_name="Source",
        executable=src_app / "Contents" / "MacOS" / "Source",
        has_sandbox=False,
    )
    recipe = Recipe(
        app_name="Source",
        bundle_id="com.example.source",
        strategy="soft_clone",
    )
    task = CloneTask(
        source=app_info,
        dest_path=tmp_path / "Dest.app",
        data_dir=tmp_path / "Data",
        recipe=recipe,
        clone_name="Source_Clone",
        new_bundle_id="com.example.source.clone1",
    )

    # In SoftCloneEngine, check copy command
    captured_scripts = []
    def mock_run(script, needs_admin=False):
        captured_scripts.append(script)

    import twinspace.executor.runner as runner_mod
    orig_run = runner_mod.Runner.run
    runner_mod.Runner.run = mock_run
    try:
        SoftCloneEngine.execute(task)
        assert len(captured_scripts) == 1
        assert "cp -Rc" in captured_scripts[0]
        assert "2>/dev/null || (rm -rf" in captured_scripts[0]
        assert "cp -R" in captured_scripts[0]

        # In HardCloneEngine
        task.recipe.strategy = "hard_clone"
        HardCloneEngine.execute(task)
        assert len(captured_scripts) == 2
        assert "cp -Rc" in captured_scripts[1]
        assert "2>/dev/null || (rm -rf" in captured_scripts[1]
        assert "cp -R" in captured_scripts[1]
    finally:
        runner_mod.Runner.run = orig_run
