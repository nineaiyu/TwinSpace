"""Tests for Category 4: Architecture, macOS HIG, and GUI Polishing."""

from unittest.mock import MagicMock

from twinspace.core.config import get_config_value, set_config_value
from twinspace.core.state import CloneRecord, StateManager
from twinspace.gui.patch_cocoa import configure_cocoa_window, is_dark_mode


def test_is_dark_mode_does_not_crash():
    """Verify is_dark_mode executes safely on macOS and returns a boolean."""
    mode = is_dark_mode()
    assert isinstance(mode, bool)


def test_configure_cocoa_window_default_normal_level():
    """Verify configure_cocoa_window uses normal window level (0) by default to prevent floating over system apps."""
    mock_window = MagicMock()
    mock_native = MagicMock()
    mock_window._impl.native = mock_native

    # Default call: floating=False
    configure_cocoa_window(mock_window)
    mock_native.setLevel_.assert_called_once_with(0)
    mock_native.makeKeyAndOrderFront_.assert_called_once_with(None)

    # Explicit floating=True
    mock_native.reset_mock()
    configure_cocoa_window(mock_window, floating=True)
    mock_native.setLevel_.assert_called_once_with(3)


def test_settings_base_dir_persistence(tmp_path, monkeypatch):
    """Verify custom base_dir setting is persisted to config."""
    cfg_file = tmp_path / "config.yaml"
    monkeypatch.setattr("twinspace.core.config.DEFAULT_CONFIG_FILE", cfg_file)
    monkeypatch.setattr("twinspace.core.config.DEFAULT_TWINSPACE_DIR", tmp_path)

    custom_dir = str(tmp_path / "CustomWorkspace")
    set_config_value("base_dir", custom_dir)
    assert get_config_value("base_dir") == custom_dir


def test_clone_remove_deletes_keychain_proxy_credentials(tmp_path, monkeypatch):
    """Verify StateManager.remove triggers keychain proxy password cleanup."""
    state_file = tmp_path / "clones.yaml"
    manager = StateManager(state_file=state_file)

    deleted_names = []
    def mock_delete(clone_name):
        deleted_names.append(clone_name)
        return True

    monkeypatch.setattr("twinspace.core.keychain.delete_clone_proxy_password", mock_delete)

    rec = CloneRecord(
        clone_name="test_proxy_clone",
        source_app="App",
        source_path="/Applications/App.app",
        bundle_id="com.example.app",
        strategy="soft_clone",
        dest_path=str(tmp_path / "App.app"),
        data_dir=str(tmp_path / "data"),
        created_at="2026-09-16T12:00:00",
        proxy_enabled=True,
        proxy_summary="http://127.0.0.1:7890",
    )
    manager.add(rec)
    assert len(manager.load()) == 1

    res = manager.remove("test_proxy_clone")
    assert res is True
    assert len(manager.load()) == 0
    assert "test_proxy_clone" in deleted_names
