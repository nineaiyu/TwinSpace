from pathlib import Path


def test_gui_module_exports_main():
    import twinspace.gui
    assert hasattr(twinspace.gui, "main") or hasattr(twinspace.gui, "build_app")


def test_build_gui_script_exists_and_executable():
    script = Path(__file__).resolve().parent.parent.parent / "scripts" / "build_gui.sh"
    assert script.exists()
    assert script.stat().st_mode & 0o111  # executable


def test_codesign_wrapper_exists_and_retryable_logic():
    script = Path(__file__).resolve().parent.parent.parent / "scripts" / "codesign_wrapper.py"
    assert script.exists()
    assert script.stat().st_mode & 0o111

    # Import wrapper helper
    import importlib.util
    spec = importlib.util.spec_from_file_location("codesign_wrapper", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod.is_retryable_error("The timestamp service is not available.")
    assert mod.is_retryable_error("Connection timed out to Apple server")
    assert not mod.is_retryable_error("unsupported format for signature")
    assert mod.BACKOFF_DELAYS == [2, 4, 8, 16, 32, 60]


def test_twinspace_package_main_module_exists():
    root = Path(__file__).resolve().parent.parent.parent
    main_py = root / "src" / "twinspace" / "__main__.py"
    assert main_py.exists(), "src/twinspace/__main__.py must exist for Briefcase and python -m twinspace"
    
    app_py = root / "src" / "twinspace" / "app.py"
    assert app_py.exists(), "src/twinspace/app.py must exist"


def test_twinspace_module_runnable_as_main():
    import runpy
    details = runpy._get_module_details("twinspace")
    assert details[0] == "twinspace.__main__"
    assert details[1].origin.endswith("__main__.py")



