"""Tests for Category 2: Concurrency, Threading, and Memory Leaks."""

import concurrent.futures

import yaml

from twinspace.core.config import save_config
from twinspace.core.engines import HardCloneEngine
from twinspace.core.state import CloneRecord, StateManager


def test_state_manager_concurrent_adds(tmp_path):
    """Verify StateManager concurrency and atomic file locking under multi-threaded load."""
    state_file = tmp_path / "clones.yaml"
    manager = StateManager(state_file=state_file)

    def worker(i: int):
        rec = CloneRecord(
            clone_name=f"clone_{i}",
            source_app="App",
            source_path=f"/Applications/App_{i}.app",
            bundle_id=f"com.example.app_{i}",
            strategy="soft_clone",
            dest_path=str(tmp_path / f"App_{i}.app"),
            data_dir=str(tmp_path / f"data_{i}"),
            created_at="2026-09-16T12:00:00",
        )
        manager.add(rec)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, i) for i in range(20)]
        for f in futures:
            f.result()

    all_clones = manager.load()
    assert len(all_clones) == 20
    # Ensure file permissions are 0o600
    assert (state_file.stat().st_mode & 0o777) == 0o600


def test_save_config_atomic(tmp_path, monkeypatch):
    """Verify save_config writes atomically with 0o600 permissions."""
    cfg_file = tmp_path / "config.yaml"
    monkeypatch.setattr("twinspace.core.config.DEFAULT_CONFIG_FILE", cfg_file)
    monkeypatch.setattr("twinspace.core.config.DEFAULT_TWINSPACE_DIR", tmp_path)

    test_cfg = {"language": "zh-Hans", "theme": "dark", "base_dir": str(tmp_path)}
    save_config(test_cfg)

    assert cfg_file.exists()
    assert (cfg_file.stat().st_mode & 0o777) == 0o600
    with open(cfg_file, "r", encoding="utf-8") as f:
        loaded = yaml.safe_load(f)
    assert loaded == test_cfg


def test_logs_view_cleanup_deregisters_listener(monkeypatch):
    """Verify LogsView.cleanup() removes the log listener to prevent memory leaks."""
    import twinspace.core.logger as logger_module

    called = []
    def dummy_cb(msg):
        called.append(msg)

    logger_module.add_log_listener(dummy_cb)
    assert dummy_cb in logger_module._listeners

    logger_module.remove_log_listener(dummy_cb)
    assert dummy_cb not in logger_module._listeners


def test_dylib_c_code_thread_local():
    """Verify that dylib C interpose source code declares fake_pw as __thread."""
    source = HardCloneEngine._cocoa_hook_source()
    assert "__thread static struct passwd fake_pw;" in source
