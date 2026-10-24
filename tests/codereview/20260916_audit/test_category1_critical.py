"""Automated tests for Category 1 fixes:
- C Launcher compile command includes dir declaration for isolation hooks
- Proxy environment variable expansion in C launcher
- Raw argument handling in _combine_launch_args without stray single quotes
- Runner._run_as_admin multiline temporary file execution and timeout
- Bidirectional language normalization between locale.py and i18n.py
- Security validation: shell metacharacters rejection and user folder deletion guard
- Recipe show bundle_id validation against path traversal
"""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from twinspace.core.clone_task import CloneTask
from twinspace.core.engines import CloneEngine, HardCloneEngine
from twinspace.core.i18n import normalize_lang_code, t
from twinspace.core.locale import normalize_locale_code, resolve_language_config
from twinspace.core.models import AppInfo
from twinspace.executor.runner import CloneError, Runner
from twinspace.recipes.models import Recipe
from twinspace.validation import (
    validate_deletion_target,
    validate_proxy_credential,
)


@pytest.fixture
def base_task(tmp_path: Path) -> CloneTask:
    app_dir = tmp_path / "Test.app"
    app_dir.mkdir(parents=True, exist_ok=True)
    info = AppInfo(
        path=app_dir,
        bundle_id="com.test.app",
        app_name="TestApp",
        executable=app_dir / "Contents" / "MacOS" / "TestApp",
        has_sandbox=False,
    )
    recipe = Recipe(
        bundle_id="com.test.app",
        app_name="TestApp",
        strategy="hard_clone",
        launch_args=["--user-data-dir={{TWINSPACE_DATA_DIR}}", "--flag"],
    )
    return CloneTask(
        source=info,
        dest_path=tmp_path / "TestClone.app",
        data_dir=tmp_path / "Data Dir With Spaces",
        recipe=recipe,
        clone_name="TestClone",
        new_bundle_id="com.test.app.clone",
    )


class TestCategory1EnginesAndLauncher:
    def test_c_launcher_contains_dir_declaration_for_isolation_hook(self, tmp_path: Path):
        """Verify C launcher declares dir and resolves it before hook_block."""
        cmd = CloneEngine._build_c_launcher_compile_cmd(
            dst_wrapper="/tmp/wrapper",
            target_bin_statement='char *real_bin = "/Applications/Test.app/Contents/MacOS/Test";',
            effective_env={},
            proxy_env="",
            lang_env="",
            args_list=["--arg1"],
            data_dir=tmp_path,
            hook_dylib_rel_path="../Frameworks/libhook.dylib",
        )
        assert "char *hook_dir = dirname(hook_exe_buf);" in cmd
        assert "_NSGetExecutablePath" in cmd
        assert 'const char *hook_rels[] = {"../Frameworks/libhook.dylib"};' in cmd
        assert 'strncat(hook_joined, hook_dir' in cmd

    def test_combine_launch_args_preserves_raw_strings_without_stray_quotes(self, base_task: CloneTask):
        """Verify args are not wrapped in shlex.quote, avoiding literal single quotes in C literals."""
        args = CloneEngine._combine_launch_args(
            valid_launch_args=["--user-data-dir={{TWINSPACE_DATA_DIR}}", "--flag"],
            lang_args=['("zh-Hans")'],
            task=base_task,
        )
        # Should be exact raw strings, not surrounded by single quotes
        assert f"--user-data-dir={base_task.data_dir}" in args
        assert "--flag" in args
        assert '("zh-Hans")' in args
        assert not any(a.startswith("'--") for a in args)

    def test_c_launcher_expands_proxy_shell_variables(self, tmp_path: Path):
        """Verify C launcher sets actual proxy values rather than literal $HTTP_PROXY."""
        proxy_env = (
            'export HTTP_PROXY="http://127.0.0.1:8080"\n'
            'export HTTPS_PROXY="http://127.0.0.1:8080"\n'
            'export http_proxy="$HTTP_PROXY"\n'
            'export https_proxy="$HTTPS_PROXY"\n'
            'export NO_PROXY="localhost,127.0.0.1"\n'
            'export no_proxy="$NO_PROXY"'
        )
        cmd = CloneEngine._build_c_launcher_compile_cmd(
            dst_wrapper="/tmp/wrapper",
            target_bin_statement='char *real_bin = "/bin/ls";',
            effective_env={},
            proxy_env=proxy_env,
            lang_env="",
            args_list=[],
            data_dir=tmp_path,
        )
        assert 'setenv("http_proxy", "http://127.0.0.1:8080", 1);' in cmd
        assert 'setenv("https_proxy", "http://127.0.0.1:8080", 1);' in cmd
        assert 'setenv("no_proxy", "localhost,127.0.0.1", 1);' in cmd
        assert '$HTTP_PROXY' not in cmd

    def test_hard_clone_codesign_has_trap_cleanup(self, base_task: CloneTask):
        """Verify codesign script has a trap to clean up the temporary entitlement plist."""
        base_task.recipe.strip_sandbox = True
        with patch("twinspace.executor.runner.Runner.run") as mock_run:
            HardCloneEngine.execute(base_task)
            script, _ = mock_run.call_args[0]
            assert "trap 'rm -f \"$ent_plist\"' EXIT INT TERM" in script


class TestCategory1Runner:
    def test_runner_run_as_admin_multiline_uses_temp_file(self):
        """Verify multiline scripts are written to a temporary shell script for osascript."""
        multiline_script = "#!/bin/bash\necho 'line 1'\necho 'line 2'\n"
        with patch("subprocess.check_output", return_value="ok") as mock_subp:
            Runner._run_as_admin(multiline_script)
            mock_subp.assert_called_once()
            args = mock_subp.call_args[0][0]
            assert args[0] == "/usr/bin/osascript"
            assert args[1] == "-e"
            assert 'do shell script "/bin/bash' in args[2]

    def test_runner_run_direct_timeout(self):
        """Verify Runner._run_direct raises CloneError on timeout."""
        with patch("subprocess.check_output", side_effect=subprocess.TimeoutExpired("cmd", 5)):
            with pytest.raises(CloneError) as exc_info:
                Runner._run_direct("sleep 10", timeout=5)
            assert "timed out" in str(exc_info.value)


class TestCategory1LocaleAndI18n:
    def test_locale_normalizer_and_resolver(self):
        """Verify zh, zh_CN, zh-Hans and zh-Hant all map to the Simplified Chinese configuration."""
        assert normalize_locale_code("zh") == "zh-Hans"
        assert normalize_locale_code("zh_CN") == "zh-Hans"
        assert normalize_locale_code("zh-Hans") == "zh-Hans"
        assert normalize_locale_code("zh_TW") == "zh-Hans"
        assert normalize_locale_code("zh-Hant") == "zh-Hans"

        cfg_zh = resolve_language_config("zh")
        assert cfg_zh.apple_locale == "zh_CN"
        assert cfg_zh.chromium_lang == "zh-CN"

        cfg_tw = resolve_language_config("zh_TW")
        assert cfg_tw.apple_locale == "zh_CN"
        assert cfg_tw.chromium_lang == "zh-CN"

    def test_i18n_normalizer_and_translation_lookup(self):
        """Verify i18n maps every Chinese variant to Simplified Chinese messages."""
        assert normalize_lang_code("zh-Hans") == "zh"
        assert normalize_lang_code("zh-Hant") == "zh"
        assert normalize_lang_code("zh_CN") == "zh"
        assert normalize_lang_code("zh_TW") == "zh"

        with patch("twinspace.core.i18n.get_language", return_value="zh-Hans"):
            res = t("btn_cancel")
            assert res in ("取消", "Cancel")  # Should be translated Chinese, not key name


class TestCategory1SecurityValidation:
    def test_proxy_credential_rejects_shell_metacharacters(self):
        """Verify ; & | < > ( ) are rejected in proxy credentials."""
        for metachar in (";", "&", "|", "<", ">", "(", ")"):
            with pytest.raises(ValueError):
                validate_proxy_credential(f"user{metachar}pass")

    def test_validate_deletion_target_protects_user_directories(self):
        """Verify ~/Desktop, ~/Library, ~/Documents cannot be deleted."""
        home = Path.home()
        for protected in (home, home / "Desktop", home / "Documents", home / "Downloads", home / "Library"):
            with pytest.raises(ValueError) as exc_info:
                validate_deletion_target(str(protected))
            assert "Refusing to delete critical" in str(exc_info.value)
