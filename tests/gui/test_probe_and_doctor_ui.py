import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from twinspace.core.app_prober import ProbeResult
from twinspace.core.i18n import t
from twinspace.core.models import AppInfo
from twinspace.gui.services.doctor_service import DoctorService
from twinspace.gui.services.probe_service import ProbeService
from twinspace.gui.services.recipe_service import RecipeService
from twinspace.gui.views.doctor_view import DoctorView
from twinspace.gui.views.probe_view import ProbeView
from twinspace.recipes.models import Recipe


def _doctor_item(key: str, name: str, passed: bool, details: str, hint: str = ""):
    from twinspace.core.doctor import DoctorCheckItem

    return DoctorCheckItem(key=key, name=name, passed=passed, details=details, hint=hint)


def test_doctor_view_render():
    async def _test():
        doctor_service = DoctorService()
        view = DoctorView(doctor_service=doctor_service)
        items = [
            _doctor_item("codesign", "codesign", True, "/usr/bin/codesign"),
            _doctor_item("xcode-select", "xcode-select", True, "/Library/Developer/CommandLineTools"),
            _doctor_item("apps_dir", t("doctor_item_apps_dir"), False, "Read/Write Failed (/Apps)", hint="chmod u+rwx"),
        ]
        with patch.object(doctor_service, "check_environment", new=AsyncMock(return_value=items)):
            await view.run_checks()

        assert len(view.results_box.children) > 0
        assert hasattr(view, "btn_install_xcode")
        # Recheck button re-enabled and indicator stopped after the pass
        assert view.top_bar.btn_action.enabled is True
        # Summary reflects the single failing item
        assert "1" in view.label_summary.text
        # Failed directory check renders its localized repair hint
        rendered = "\n".join(
            getattr(child, "text", "") for child in view.results_box.children
        )
        assert "chmod u+rwx" in rendered

    asyncio.run(_test())


def test_doctor_view_install_button_visibility():
    async def _test():
        doctor_service = DoctorService()
        view = DoctorView(doctor_service=doctor_service)

        # Mock check_environment with missing xcode-select / codesign
        items_missing = [
            _doctor_item("codesign", "codesign", False, "Not found"),
            _doctor_item("xcode-select", "xcode-select", False, "Not found"),
            _doctor_item("plistbuddy", "PlistBuddy", True, "/usr/libexec/PlistBuddy"),
        ]
        with patch.object(doctor_service, "check_environment", new=AsyncMock(return_value=items_missing)):
            await view.run_checks()
            assert view.btn_install_xcode.style.visibility == "visible"

        # Mock check_environment with all passing
        items_passed = [
            _doctor_item("codesign", "codesign", True, "/usr/bin/codesign"),
            _doctor_item("xcode-select", "xcode-select", True, "/Library/Developer/CommandLineTools"),
            _doctor_item("plistbuddy", "PlistBuddy", True, "/usr/libexec/PlistBuddy"),
        ]
        with patch.object(doctor_service, "check_environment", new=AsyncMock(return_value=items_passed)):
            await view.run_checks()
            assert view.btn_install_xcode.style.visibility == "hidden"

    asyncio.run(_test())


def test_doctor_view_status_wording_distinct():
    """Missing tools read as「缺失」; permission-style failures as「未通过」."""
    view = DoctorView(doctor_service=DoctorService())
    missing = _doctor_item("codesign", "codesign", False, "Not found")
    failed = _doctor_item("apps_dir", t("doctor_item_apps_dir"), False, "denied")
    assert view._status_text(missing) == t("doctor_status_missing")
    assert view._status_text(failed) == t("doctor_status_failed")
    assert t("doctor_status_missing") != t("doctor_status_failed")


def test_doctor_view_recheck_guard():
    async def _test():
        doctor_service = DoctorService()
        view = DoctorView(doctor_service=doctor_service)
        release = asyncio.Event()

        async def slow_check():
            await release.wait()
            return [_doctor_item("codesign", "codesign", True, "/usr/bin/codesign")]

        mock_check = AsyncMock(side_effect=slow_check)
        with patch.object(doctor_service, "check_environment", new=mock_check):
            first = asyncio.create_task(view.run_checks())
            await asyncio.sleep(0)
            # While the first pass is running, a second call must be a no-op
            await view.run_checks()
            release.set()
            await first

        assert view._checking is False
        assert mock_check.call_count == 1

    asyncio.run(_test())


def test_doctor_view_action_install_xcode():
    async def _test():
        doctor_service = DoctorService()
        mock_app = MagicMock()
        mock_app.main_window.info_dialog = AsyncMock()

        view = DoctorView(doctor_service=doctor_service, app=mock_app)

        with patch.object(doctor_service, "trigger_xcode_install", new=AsyncMock(return_value=(True, "launched"))) as mock_trigger:
            await view.action_install_xcode()
            assert mock_trigger.called
            assert mock_app.main_window.info_dialog.called

    asyncio.run(_test())


def _probe_result(tmp_path: Path, *, is_ios: bool = False) -> ProbeResult:
    info = AppInfo(
        path=tmp_path / "DemoApp.app",
        bundle_id="com.example.demoapp",
        app_name="DemoApp",
        executable=tmp_path / "DemoApp.app" / "Contents" / "MacOS" / "DemoApp",
        has_sandbox=True,
        is_ios_app=is_ios,
    )
    return ProbeResult(
        app_info=info,
        has_sandbox=True,
        frameworks=[],
        strategy="hard_clone",
        reason_key="probe_reason_ios_wrapper" if is_ios else "probe_reason_native_sandboxed",
        recipe=Recipe(
            bundle_id="com.example.demoapp",
            app_name="DemoApp",
            strategy="hard_clone",
            strip_sandbox=True,
        ),
    )


def test_probe_view_display_result(tmp_path):
    async def _test():
        probe_service = ProbeService()
        recipe_service = RecipeService(custom_recipes_dir=tmp_path / "recipes")
        view = ProbeView(probe_service=probe_service, recipe_service=recipe_service)

        # The GUI validates the path on the real filesystem, so create the bundle.
        real_app = tmp_path / "DemoApp.app"
        real_app.mkdir()

        with patch.object(probe_service, "probe_app", new=AsyncMock(return_value=_probe_result(tmp_path))):
            view.input_path.value = str(real_app)
            await view.do_probe()

            assert "DemoApp" in view.label_app_name.text
            assert "com.example.demoapp" in view.label_bundle_id.text
            assert "Hard Clone" in view.label_strategy.text or "hard_clone" in view.label_strategy.text
            # Localized analysis note (was previously raw English)
            assert "Native macOS application" in view.label_reason.text
            assert view.btn_save_recipe.enabled is True
            assert view.label_ios_warning.style.visibility == "hidden"

            # Test saving probed recipe to custom recipes
            await view.save_probed_recipe()
            assert (tmp_path / "recipes" / "com.example.demoapp.yaml").exists()
            assert view.btn_view_recipes.style.visibility == "visible"

    asyncio.run(_test())


def test_probe_view_ios_app_blocked(tmp_path):
    async def _test():
        probe_service = ProbeService()
        view = ProbeView(probe_service=probe_service, recipe_service=RecipeService(custom_recipes_dir=tmp_path / "recipes"))
        real_app = tmp_path / "DemoApp.app"
        real_app.mkdir()

        with patch.object(probe_service, "probe_app", new=AsyncMock(return_value=_probe_result(tmp_path, is_ios=True))):
            view.input_path.value = str(real_app)
            await view.do_probe()

            assert view.label_ios_warning.style.visibility == "visible"
            assert view.btn_save_recipe.enabled is False

    asyncio.run(_test())


def test_probe_view_invalid_path_localized_error():
    async def _test():
        probe_service = ProbeService()
        view = ProbeView(probe_service=probe_service, recipe_service=RecipeService(custom_recipes_dir=Path("/tmp/x")))
        mock_app = MagicMock()
        mock_app.main_window.error_dialog = AsyncMock()
        view.app_instance = mock_app

        view.input_path.value = "/tmp/definitely_missing.app"
        await view.do_probe()

        assert mock_app.main_window.error_dialog.called
        message = mock_app.main_window.error_dialog.call_args.args[1]
        assert "not a valid macOS .app bundle" in message

    asyncio.run(_test())


def test_probe_view_busy_guard(tmp_path):
    async def _test():
        probe_service = ProbeService()
        view = ProbeView(probe_service=probe_service, recipe_service=RecipeService(custom_recipes_dir=tmp_path / "recipes"))
        release = asyncio.Event()
        real_app = tmp_path / "DemoApp.app"
        real_app.mkdir()

        async def slow_probe(path):
            await release.wait()
            return _probe_result(tmp_path)

        mock_probe = AsyncMock(side_effect=slow_probe)
        with patch.object(probe_service, "probe_app", new=mock_probe):
            view.input_path.value = str(real_app)
            first = asyncio.create_task(view.do_probe())
            await asyncio.sleep(0)
            assert view._probing is True
            assert view.top_bar.btn_action.enabled is False

            # A second concurrent click is a no-op
            await view.do_probe()
            release.set()
            await first

        assert view._probing is False
        assert mock_probe.call_count == 1

    asyncio.run(_test())
